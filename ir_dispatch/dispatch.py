"""
Minimal dispatch: an eligibility binding in, one model call out.

    binding (governance output: WHICH models are allowed)
      -> drop eligible models that have no endpoint (registered, not deployed)
      -> selection over what is left (override if permitted, else lowest cost)
      -> POST {base_url}/v1/chat/completions with model=<served_model_name>

Selection runs over a SUBSET of the binding's eligible set, so nothing here can
add a model governance did not allow ("governance precedes optimization").
Removing undeployed models only narrows the set.

For a distilled student, ``served_model_name`` is its LoRA adapter's name on a
shared vLLM server. One deployment of the base model serves every expert
loaded on it; the router picks the expert, the name picks the adapter.

What this deliberately does not do yet (see docs/IMPLEMENTATION_PLAN.md):
  * sign the output stamp (FR-IRG-INT-01): the result carries ``output_hash``
    so the stamp can be built from it, but nothing is signed here;
  * emit ``ir.routing.bound``: ``DispatchResult.routing_bound_fields()``
    returns the fields; the caller adds decision_id and the stamp;
  * retry, fall back to the next eligible model, or escalate. A failed call is
    a DispatchError. Escalation to a baseline belongs to the caller (RLDE's
    ``serving.live.serve`` does it for students).
  * streaming.

Credentials: this module is the only place a model credential is used
(README: ir_dispatch is the sole holder). They are looked up by model_id from
an injected provider and never stored on the registry record.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ir_core.exceptions import HardStop, RouterError
from ir_core.resolution import ModelRecord, apply_override
from ir_core.types import EligibilityBinding

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

#: Request parameters a caller may set. Anything else is refused, so a caller
#: cannot smuggle a different ``model`` past selection.
ALLOWED_PARAMS = frozenset({"max_tokens", "temperature", "top_p", "stop", "seed"})

#: (url, json body, headers, timeout) -> (status, parsed json body)
Post = Callable[[str, dict, dict, float], "tuple[int, dict]"]


class DispatchError(RouterError):
    """An operational failure: nothing servable, a bad request, or the endpoint failed.
    Distinct from HardStop, which is a policy refusal."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


@dataclass(frozen=True)
class DispatchResult:
    model_id: str
    served_model_name: str
    endpoint_base_url: str
    output: str
    finish_reason: Optional[str]
    usage: Mapping[str, Any]
    latency_ms: float
    output_hash: str
    binding: EligibilityBinding
    servable_model_ids: frozenset
    override_source: Optional[str] = None
    override_honored: bool = False
    override_refused_reason: Optional[str] = None

    def routing_bound_fields(self) -> dict:
        """The ``ir.routing.bound`` payload minus ``decision_id`` and ``stamp``,
        which belong to the caller and the (not yet built) stamp signer."""
        k, p = self.binding.key, self.binding.provenance
        return {
            "reasoning_class": k.reasoning_class,
            "eligible_model_ids": sorted(self.binding.eligible_model_ids),
            "selected_model_id": self.model_id,
            "governance_tier": k.effective_governance_tier.name.lower(),
            "privacy_class": k.privacy_class.name,
            "posture": k.posture.name.lower(),
            "governance_policy_version": p.governance_policy_version,
            "selection_policy_version": p.selection_policy_version,
            "calibration_state_version": p.calibration_state_version,
            "override_source": self.override_source if self.override_honored else None,
            "override_refused_reason": self.override_refused_reason,
            "signals": list(p.signals),
        }


def _http_post(url: str, body: dict, headers: dict, timeout: float) -> "tuple[int, dict]":
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (scheme checked)
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read() or b""
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": raw.decode(errors="replace")[:500]}


@dataclass
class Dispatcher:
    """
    ``registry`` maps model_id -> ModelRecord (the same records resolution read).
    ``credentials`` maps model_id -> bearer token or None (in-VPC vLLM needs none).
    """
    registry: Mapping[str, ModelRecord]
    credentials: Callable[[str], Optional[str]] = field(default=lambda _model_id: None)
    post: Post = field(default=_http_post)
    timeout_s: float = 60.0
    clock: Callable[[], float] = field(default=time.monotonic)

    def servable(self, binding: EligibilityBinding) -> frozenset:
        """Eligible models that have an endpoint. A subset of the binding, never more."""
        return frozenset(
            m for m in binding.eligible_model_ids
            if m in self.registry and self.registry[m].endpoint is not None
        )

    def dispatch(
        self,
        binding: EligibilityBinding,
        messages: Sequence[Mapping[str, Any]],
        *,
        override_model_id: Optional[str] = None,
        override_source: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> DispatchResult:
        if binding.is_expired(now):
            raise HardStop("binding_expired",
                           "the eligibility binding's TTL has passed; resolve again")
        if not messages:
            raise DispatchError("bad_request", "no messages to send")
        params = dict(params or {})
        extra = set(params) - ALLOWED_PARAMS
        if extra:
            raise DispatchError("bad_request",
                                f"parameters {sorted(extra)} are not allowed; the model is chosen "
                                "by the router, not the caller")

        servable = self.servable(binding)
        if not servable:
            raise DispatchError(
                "no_servable_model",
                f"none of {sorted(binding.eligible_model_ids)} has a serving endpoint "
                f"(class={binding.key.reasoning_class})")

        choice = apply_override(servable, self.registry, override_model_id, override_source,
                                binding.key.effective_governance_tier)
        record = self.registry[choice.selected_model_id]
        ep = record.endpoint
        assert ep is not None  # servable() guarantees it

        headers = {}
        token = self.credentials(record.model_id)
        if token:
            if not ep.base_url.startswith("https://"):
                raise DispatchError("insecure_endpoint",
                                    f"{record.model_id}: a credential is never sent over http")
            headers["authorization"] = f"Bearer {token}"

        body = {"model": ep.served_model_name, "messages": [dict(m) for m in messages], **params}
        url = ep.base_url.rstrip("/") + CHAT_COMPLETIONS_PATH
        start = self.clock()
        try:
            status, resp = self.post(url, body, headers, self.timeout_s)
        except (OSError, ValueError) as exc:  # URLError and timeouts are OSError
            raise DispatchError("endpoint_unreachable",
                                f"{record.model_id} at {ep.base_url}: {exc}") from exc
        latency_ms = (self.clock() - start) * 1000.0
        if status != 200:
            raise DispatchError("endpoint_error",
                                f"{record.model_id} at {ep.base_url}: HTTP {status} {resp}")
        try:
            first = resp["choices"][0]
            output = first["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise DispatchError("bad_response",
                                f"{record.model_id}: no choices[0].message.content") from exc

        return DispatchResult(
            model_id=record.model_id,
            served_model_name=ep.served_model_name,
            endpoint_base_url=ep.base_url,
            output=output,
            finish_reason=first.get("finish_reason"),
            usage=resp.get("usage") or {},
            latency_ms=latency_ms,
            output_hash="sha256:" + hashlib.sha256(output.encode()).hexdigest(),
            binding=binding,
            servable_model_ids=servable,
            override_source=override_source,
            override_honored=choice.override_honored,
            override_refused_reason=choice.override_refused_reason,
        )
