"""
Dispatch: binding -> selection over servable models -> one OpenAI-compatible call.

The fake in most tests is the injected ``post``. ``test_real_http_*`` runs a
local HTTP server shaped like vLLM with two LoRA experts on one base, so the
urllib path and the expertise routing are exercised end to end.
"""
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ir_core.exceptions import HardStop, ValidationError
from ir_core.resolution import (
    ModelRecord,
    ReasoningClassRecord,
    ServingEndpoint,
    build_binding,
)
from ir_core.types import GovernanceTier, LineageSet, Posture, PrivacyClass
from ir_dispatch import DispatchError, Dispatcher

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)
VLLM = "http://10.0.0.5:8000"


def model(model_id, *, cost=1.0, classes=("contract_review",), endpoint=None):
    return ModelRecord(
        model_id=model_id, privacy_ceiling=PrivacyClass.P0,
        lineage=LineageSet.for_base_model("qwen"), cost_per_1k_tokens=cost,
        is_attested=True, attestation_valid_until=NOW + timedelta(days=30),
        supported_classes=frozenset(classes), endpoint=endpoint)


def binding(registry, cls="contract_review", tier=GovernanceTier.COMMODITY, ttl=300.0):
    pool = frozenset(m for m, r in registry.items() if cls in r.supported_classes)
    rc = ReasoningClassRecord(name=cls, default_governance_tier=tier, eligible_model_ids=pool)
    return build_binding(rc, registry, tier, PrivacyClass.P1, Posture.NORMAL, "gov-v1", ttl,
                         now=NOW)


class FakePost:
    def __init__(self, status=200, content="ok", raise_exc=None):
        self.calls, self.status, self.content, self.raise_exc = [], status, content, raise_exc

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, headers))
        if self.raise_exc:
            raise self.raise_exc
        if self.status != 200:
            return self.status, {"error": "boom"}
        return 200, {"choices": [{"message": {"content": self.content},
                                  "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 3, "completion_tokens": 1}}


MSG = [{"role": "user", "content": "review this clause"}]


def test_calls_the_selected_model_by_its_served_name():
    reg = {"student/contracts": model("student/contracts", cost=0.1,
                                      endpoint=ServingEndpoint(VLLM, "contracts-v3")),
           "frontier": model("frontier", cost=5.0,
                             endpoint=ServingEndpoint("https://api.example.com", "big-1"))}
    post = FakePost(content="looks fine")
    r = Dispatcher(reg, post=post).dispatch(binding(reg), MSG, params={"max_tokens": 50},
                                           now=NOW)
    url, body, headers = post.calls[0]
    assert url == VLLM + "/v1/chat/completions"
    assert body == {"model": "contracts-v3", "messages": MSG, "max_tokens": 50}
    assert headers == {}
    assert r.model_id == "student/contracts" and r.output == "looks fine"
    assert r.output_hash.startswith("sha256:") and r.finish_reason == "stop"
    assert r.usage["completion_tokens"] == 1


def test_an_eligible_model_with_no_endpoint_is_skipped_not_called():
    reg = {"cheap-undeployed": model("cheap-undeployed", cost=0.01),
           "deployed": model("deployed", cost=1.0, endpoint=ServingEndpoint(VLLM, "d"))}
    b = binding(reg)
    assert b.eligible_model_ids == {"cheap-undeployed", "deployed"}
    r = Dispatcher(reg, post=FakePost()).dispatch(b, MSG, now=NOW)
    assert r.model_id == "deployed" and r.servable_model_ids == {"deployed"}


def test_nothing_deployed_is_a_dispatch_error_not_a_widening():
    reg = {"a": model("a")}
    with pytest.raises(DispatchError) as e:
        Dispatcher(reg, post=FakePost()).dispatch(binding(reg), MSG, now=NOW)
    assert e.value.code == "no_servable_model"


def test_dispatch_never_reaches_outside_the_binding():
    """A deployed model in the registry but not in the binding is never called,
    even when it is cheaper and even when an admin pins it."""
    reg = {"in": model("in", cost=1.0, endpoint=ServingEndpoint(VLLM, "in")),
           "out": model("out", cost=0.0, classes=("other",),
                        endpoint=ServingEndpoint(VLLM, "out"))}
    b = binding(reg)
    assert b.eligible_model_ids == {"in"}
    post = FakePost()
    r = Dispatcher(reg, post=post).dispatch(b, MSG, override_model_id="out",
                                           override_source="admin", now=NOW)
    assert r.model_id == "in" and not r.override_honored
    assert r.override_refused_reason == "pin_not_eligible_for_effective_tier"
    assert post.calls[0][1]["model"] == "in"


def test_a_permitted_override_inside_the_set_is_honoured():
    reg = {"a": model("a", cost=0.1, endpoint=ServingEndpoint(VLLM, "a")),
           "b": model("b", cost=9.0, endpoint=ServingEndpoint(VLLM, "b"))}
    r = Dispatcher(reg, post=FakePost()).dispatch(binding(reg), MSG, override_model_id="b",
                                                 override_source="template", now=NOW)
    assert r.model_id == "b" and r.override_honored
    assert r.routing_bound_fields()["override_source"] == "template"


def test_an_agent_cannot_pin_a_model():
    reg = {"a": model("a", endpoint=ServingEndpoint(VLLM, "a"))}
    with pytest.raises(HardStop) as e:
        Dispatcher(reg, post=FakePost()).dispatch(binding(reg), MSG, override_model_id="a",
                                                 override_source="agent", now=NOW)
    assert e.value.code == "override_source_not_permitted"


def test_a_caller_cannot_smuggle_a_model_through_params():
    reg = {"a": model("a", endpoint=ServingEndpoint(VLLM, "a"))}
    with pytest.raises(DispatchError, match="not allowed"):
        Dispatcher(reg, post=FakePost()).dispatch(binding(reg), MSG, params={"model": "x"},
                                                 now=NOW)


def test_an_expired_binding_is_refused():
    reg = {"a": model("a", endpoint=ServingEndpoint(VLLM, "a"))}
    b = binding(reg, ttl=60)
    with pytest.raises(HardStop) as e:
        Dispatcher(reg, post=FakePost()).dispatch(b, MSG, now=NOW + timedelta(seconds=61))
    assert e.value.code == "binding_expired"


def test_credentials_are_looked_up_by_model_and_only_sent_over_https():
    reg = {"f": model("f", endpoint=ServingEndpoint("https://api.example.com", "big-1"))}
    post = FakePost()
    Dispatcher(reg, post=post, credentials=lambda m: "tok" if m == "f" else None).dispatch(
        binding(reg), MSG, now=NOW)
    assert post.calls[0][2] == {"authorization": "Bearer tok"}

    reg = {"s": model("s", endpoint=ServingEndpoint(VLLM, "s"))}
    with pytest.raises(DispatchError) as e:
        Dispatcher(reg, post=FakePost(), credentials=lambda m: "tok").dispatch(
            binding(reg), MSG, now=NOW)
    assert e.value.code == "insecure_endpoint"


@pytest.mark.parametrize("post,code", [
    (FakePost(status=500), "endpoint_error"),
    (FakePost(raise_exc=OSError("connection refused")), "endpoint_unreachable"),
    (lambda *a: (200, {"choices": []}), "bad_response"),
])
def test_endpoint_failures_are_dispatch_errors(post, code):
    reg = {"a": model("a", endpoint=ServingEndpoint(VLLM, "a"))}
    with pytest.raises(DispatchError) as e:
        Dispatcher(reg, post=post).dispatch(binding(reg), MSG, now=NOW)
    assert e.value.code == code


def test_routing_bound_fields_validate_against_the_event_schema_once_completed():
    """The caller adds decision_id and the signed stamp; everything else comes
    from the result, and the whole payload must satisfy ir.routing.bound."""
    from jsonschema import Draft202012Validator

    from schemas.registry import load_data_schema

    reg = {"a": model("a", endpoint=ServingEndpoint(VLLM, "a"))}
    r = Dispatcher(reg, post=FakePost()).dispatch(binding(reg), MSG, now=NOW)
    fields = r.routing_bound_fields()
    payload = {**fields, "decision_id": "d-1",
               "stamp": {"decision_id": "d-1", "output_hash": r.output_hash,
                         "governance_tier": fields["governance_tier"],
                         "privacy_class": fields["privacy_class"], "verdict_id": None,
                         "signature": "unsigned-test"}}
    Draft202012Validator(load_data_schema("ir.routing.bound")).validate(payload)


@pytest.mark.parametrize("url,name", [
    ("http://api.example.com", "m"),       # plain http to a public host
    ("ftp://10.0.0.5", "m"),
    ("http://10.0.0.5:8000/v1", "m"),      # dispatch adds the path
    ("http://10.0.0.5:8000", ""),
])
def test_serving_endpoint_validation(url, name):
    with pytest.raises(ValidationError):
        ServingEndpoint(url, name)


# ---------------------------------------------------------------------------
# End to end over real HTTP: one "vLLM" base serving two LoRA experts.
# ---------------------------------------------------------------------------

class _FakeVllm(BaseHTTPRequestHandler):
    adapters = {"contracts-v3": "contract answer", "tax-v1": "tax answer"}
    seen = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).seen.append((self.path, body["model"]))
        if self.path != "/v1/chat/completions" or body["model"] not in self.adapters:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "unknown model"}')
            return
        out = json.dumps({"choices": [{"message": {"content": self.adapters[body["model"]]},
                                       "finish_reason": "stop"}], "usage": {}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def vllm():
    srv = HTTPServer(("127.0.0.1", 0), _FakeVllm)
    _FakeVllm.seen = []
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_real_http_routes_each_class_to_its_expert_adapter_on_one_server(vllm):
    reg = {
        "student/contracts": model("student/contracts", cost=0.1, classes=("contract_review",),
                                   endpoint=ServingEndpoint(vllm, "contracts-v3")),
        "student/tax": model("student/tax", cost=0.1, classes=("tax_question",),
                             endpoint=ServingEndpoint(vllm, "tax-v1")),
    }
    d = Dispatcher(reg)
    a = d.dispatch(binding(reg, "contract_review"), MSG, now=NOW)
    b = d.dispatch(binding(reg, "tax_question"), MSG, now=NOW)
    assert (a.model_id, a.output) == ("student/contracts", "contract answer")
    assert (b.model_id, b.output) == ("student/tax", "tax answer")
    assert _FakeVllm.seen == [("/v1/chat/completions", "contracts-v3"),
                              ("/v1/chat/completions", "tax-v1")]


def test_real_http_an_unloaded_adapter_is_an_endpoint_error(vllm):
    reg = {"s": model("s", endpoint=ServingEndpoint(vllm, "not-loaded"))}
    with pytest.raises(DispatchError) as e:
        Dispatcher(reg).dispatch(binding(reg), MSG, now=NOW)
    assert e.value.code == "endpoint_error" and "404" in str(e.value)
