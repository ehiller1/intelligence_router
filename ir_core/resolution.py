"""
Eligibility resolution: reasoning class -> eligible model set.

This module implements the precedence order fixed by decision R5 and the
patched Adaptive FRD FND-03:

    governance eligibility (tier, privacy ceiling, attestation, lineage)
        -> override, IF the named model is inside that eligible set
        -> learned selection policy               [Adaptive track, not here]
        -> static default (lowest cost)            [MVP selector]

Nothing here ever *removes* a governance constraint to satisfy a caller
preference. An override is a filter applied to the already-computed
eligible set, never a way around it (decision R5).
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import FrozenSet, Optional
from urllib.parse import urlparse

from ir_core.exceptions import HardStop, ValidationError
from ir_core.types import (
    EligibilityBinding,
    EligibilityBindingKey,
    BindingProvenance,
    GovernanceTier,
    LineageSet,
    PrivacyClass,
    may_receive,
)


#: The only wire protocol dispatch speaks today: an OpenAI-compatible
#: ``/v1/chat/completions`` (vLLM serves this for a base model and every
#: LoRA adapter loaded on it).
ENDPOINT_API_OPENAI_CHAT = "openai-chat"


@dataclass(frozen=True)
class ServingEndpoint:
    """
    Where a model answers (FND-02 ``deployment_endpoint``). Data only: ir_core
    does no I/O, ir_dispatch makes the call.

    ``served_model_name`` is what goes in the request's ``model`` field. For a
    distilled student it is the LoRA adapter's name on the vLLM server, which
    is how many experts share one base-model deployment.

    No credential is held here. ir_dispatch is the sole holder of model
    credentials and looks them up by model_id.
    """
    base_url: str
    served_model_name: str
    api: str = ENDPOINT_API_OPENAI_CHAT

    def __post_init__(self) -> None:
        u = urlparse(self.base_url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValidationError(f"endpoint base_url must be an http(s) URL: {self.base_url!r}")
        if u.path not in ("", "/") or u.query or u.fragment:
            raise ValidationError("endpoint base_url is the server root; dispatch adds the path")
        if u.scheme == "http" and not _is_private_host(u.hostname):
            raise ValidationError(
                f"plain http is allowed only to a private host, not {u.hostname!r}")
        if not self.served_model_name:
            raise ValidationError("endpoint needs a served_model_name")
        if self.api != ENDPOINT_API_OPENAI_CHAT:
            raise ValidationError(f"unsupported endpoint api {self.api!r}")


def _is_private_host(host: str) -> bool:
    """A private IP, localhost, or a cluster-internal name. Mirrors RLDE's rule."""
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return host == "localhost" or host.endswith((".internal", ".svc"))


@dataclass(frozen=True)
class ModelRecord:
    """Minimal registry entry (MVP FRD FND-02) needed for eligibility.

    ``endpoint`` plays no part in eligibility. A model with no endpoint can
    still be eligible (registered but not deployed); dispatch refuses to call
    it rather than resolution hiding it.
    """
    model_id: str
    privacy_ceiling: PrivacyClass
    lineage: LineageSet
    cost_per_1k_tokens: float
    is_attested: bool
    attestation_valid_until: Optional[datetime]
    supported_classes: FrozenSet[str]
    endpoint: Optional[ServingEndpoint] = None

    def attestation_ok(self, now: Optional[datetime] = None) -> bool:
        if not self.is_attested:
            return False
        if self.attestation_valid_until is None:
            return False
        now = now or datetime.now(timezone.utc)
        return now < self.attestation_valid_until


@dataclass(frozen=True)
class ReasoningClassRecord:
    """MVP FRD FND-01/03: class -> default tier + eligible model pool."""
    name: str
    default_governance_tier: GovernanceTier
    eligible_model_ids: FrozenSet[str]
    structural_input: bool = False  # decision D2: may skip the model classifier


def resolve_eligible_set(
    reasoning_class: ReasoningClassRecord,
    all_models: dict,  # model_id -> ModelRecord
    effective_governance_tier: GovernanceTier,
    privacy_class: PrivacyClass,
    now: Optional[datetime] = None,
) -> FrozenSet[str]:
    """
    Governance eligibility ONLY (no override, no selection). This is the
    function whose output is cached as an EligibilityBinding (decision D2)
    and whose output is exactly the arm set the Adaptive FRD's bandit may
    choose from (decision: "Governance precedes optimization").

    A model is eligible iff:
      1. it is in the reasoning class's configured pool, AND
      2. its privacy ceiling covers the task's privacy class (may_receive), AND
      3. if the EFFECTIVE tier is normative or guider, it carries a valid,
         unexpired attestation (FR-IRG-ATT-01).

    This function never raises on an empty result -- callers decide whether
    an empty set is a hard stop (see EligibilityBinding.require_nonempty).
    """
    eligible = set()
    for model_id in reasoning_class.eligible_model_ids:
        model = all_models.get(model_id)
        if model is None:
            continue
        if not may_receive(model.privacy_ceiling, privacy_class):
            continue
        if effective_governance_tier >= GovernanceTier.NORMATIVE:
            if not model.attestation_ok(now):
                continue
        eligible.add(model_id)
    return frozenset(eligible)


def select_lowest_cost(eligible_model_ids: FrozenSet[str], all_models: dict) -> str:
    """
    MVP selector (FR-IRG-RTR-02): lowest cost within the eligible set.
    This is the seam the Adaptive FRD's Thompson-sampling selector plugs
    into later -- same signature, different body, same eligible set as input.
    Deterministic tie-break on model_id keeps bindings reproducible.
    """
    if not eligible_model_ids:
        raise HardStop("no_eligible_model", "select_lowest_cost called with an empty eligible set")
    return min(eligible_model_ids, key=lambda mid: (all_models[mid].cost_per_1k_tokens, mid))


@dataclass(frozen=True)
class OverrideResult:
    selected_model_id: str
    override_honored: bool
    override_refused_reason: Optional[str] = None


PERMITTED_OVERRIDE_SOURCES = frozenset({"admin", "template"})


def apply_override(
    eligible_model_ids: FrozenSet[str],
    all_models: dict,
    override_model_id: Optional[str],
    override_source: Optional[str],
    effective_governance_tier: GovernanceTier,
) -> OverrideResult:
    """
    Decision R5: an override is a preference within the eligible set, never
    a way around it. Guider-tier work accepts no overrides from any source
    (mirrors FR-IRG-GDR-01: guider routing is pinned and excluded from the
    selector entirely).
    """
    if override_model_id is None:
        selected = select_lowest_cost(eligible_model_ids, all_models)
        return OverrideResult(selected_model_id=selected, override_honored=False)

    if override_source not in PERMITTED_OVERRIDE_SOURCES:
        raise HardStop(
            "override_source_not_permitted",
            f"Override source '{override_source}' is not in {sorted(PERMITTED_OVERRIDE_SOURCES)}; "
            "runtime agents must reference reasoning classes only (FR-IRG-FND-04).",
        )

    if effective_governance_tier == GovernanceTier.GUIDER:
        selected = select_lowest_cost(eligible_model_ids, all_models)
        return OverrideResult(
            selected_model_id=selected,
            override_honored=False,
            override_refused_reason="guider_tier_accepts_no_overrides",
        )

    if override_model_id in eligible_model_ids:
        return OverrideResult(selected_model_id=override_model_id, override_honored=True)

    # Pin not eligible for the effective tier: drop it, route normally, ledger
    # the refusal (decision R5) -- never fail the whole task over a stale pin.
    selected = select_lowest_cost(eligible_model_ids, all_models)
    return OverrideResult(
        selected_model_id=selected,
        override_honored=False,
        override_refused_reason="pin_not_eligible_for_effective_tier",
    )


def assert_guider_lineage_disjoint(guider: ModelRecord, overseen: ModelRecord) -> None:
    """
    FR-IRG-GDR-02: reject any configuration where a guider shares lineage
    with the model it oversees. Called at governance-policy promotion time
    and at registry-change time (decision D6); raises HardStop rather than
    returning a bool, because this must never be silently skipped.
    """
    if not guider.lineage.disjoint_from(overseen.lineage):
        raise HardStop(
            "guider_lineage_not_disjoint",
            f"Guider model '{guider.model_id}' shares lineage with overseen "
            f"model '{overseen.model_id}': shared members = "
            f"{sorted(guider.lineage.members & overseen.lineage.members)}",
        )


def build_binding(
    reasoning_class: ReasoningClassRecord,
    all_models: dict,
    effective_governance_tier: GovernanceTier,
    privacy_class,
    posture,
    governance_policy_version: str,
    ttl_seconds: float,
    now: Optional[datetime] = None,
) -> EligibilityBinding:
    """Compose resolution into a cacheable EligibilityBinding (decision D2)."""
    now = now or datetime.now(timezone.utc)
    eligible = resolve_eligible_set(
        reasoning_class, all_models, effective_governance_tier, privacy_class, now
    )
    key = EligibilityBindingKey(
        reasoning_class=reasoning_class.name,
        effective_governance_tier=effective_governance_tier,
        privacy_class=privacy_class,
        posture=posture,
        governance_policy_version=governance_policy_version,
    )
    provenance = BindingProvenance(
        governance_policy_version=governance_policy_version,
        selection_policy_version=None,
        calibration_state_version=None,
    )
    return EligibilityBinding(
        key=key,
        eligible_model_ids=eligible,
        provenance=provenance,
        issued_at=now,
        ttl_seconds=ttl_seconds,
    ).require_nonempty()
