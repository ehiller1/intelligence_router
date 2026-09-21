"""
Validates every schema file is well-formed JSON Schema (Draft 2020-12), and
that the envelope + per-event schemas accept a realistic valid payload and
reject the specific invalid variants the FRDs call out by name:

  - an event missing `env` (decision R9 / FR-IR-TRN-02: "consumers reject
    events missing env rather than defaulting")
  - a sim-env event missing `run_id`
  - an integrity signal with an unregistered signal_type
  - a posture loosening from restricted/quarantined with no approver
  - a routing.bound event with an empty eligible_model_ids array (the
    no_eligible_model hard stop must never be represented as a "bound" event)
"""
import json
from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator, ValidationError

from schemas.registry import (
    EVENT_TYPE_TO_SCHEMA_FILE,
    all_schema_files,
    load_data_schema,
    load_envelope_schema,
)


# ---------------------------------------------------------------------------
# Every schema file must be self-consistent Draft 2020-12 JSON Schema.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", all_schema_files(), ids=lambda p: p.name)
def test_schema_is_well_formed(path):
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)


def test_every_registered_event_type_has_a_schema_file():
    for event_type, filename in EVENT_TYPE_TO_SCHEMA_FILE.items():
        schema = load_data_schema(event_type)
        assert schema["title"] or True  # loads without raising is the assertion


# ---------------------------------------------------------------------------
# Envelope: mandatory env, sim requires run_id (decision R9).
# ---------------------------------------------------------------------------

def _envelope(env="prod", **overrides):
    base = {
        "specversion": "1.0",
        "id": "evt-1",
        "source": "urn:ir:dispatch-plane",
        "type": "ir.routing.bound",
        "time": datetime.now(timezone.utc).isoformat(),
        "env": env,
        "data": {},
    }
    base.update(overrides)
    return base


def test_envelope_accepts_valid_prod_event():
    Draft202012Validator(load_envelope_schema()).validate(_envelope())


def test_envelope_rejects_missing_env():
    envelope = _envelope()
    del envelope["env"]
    with pytest.raises(ValidationError):
        Draft202012Validator(load_envelope_schema()).validate(envelope)


def test_envelope_rejects_sim_without_run_id():
    with pytest.raises(ValidationError):
        Draft202012Validator(load_envelope_schema()).validate(_envelope(env="sim"))


def test_envelope_accepts_sim_with_run_id():
    Draft202012Validator(load_envelope_schema()).validate(_envelope(env="sim", run_id="run-42"))


def test_envelope_rejects_unknown_env_value():
    with pytest.raises(ValidationError):
        Draft202012Validator(load_envelope_schema()).validate(_envelope(env="staging"))


# ---------------------------------------------------------------------------
# ir.routing.requested: the narrow, non-under-declarable contract.
# ---------------------------------------------------------------------------

def test_routing_requested_rejects_a_model_field():
    """
    The contract has no `model` field at all. A caller (or a compromised
    SDK) trying to smuggle one in must be rejected outright, not silently
    ignored -- additionalProperties: false enforces this (FR-IRG-FND-05).
    """
    schema = load_data_schema("ir.routing.requested")
    payload = {
        "reasoning_class": "commodity_extraction",
        "task_ref": "task-1",
        "idempotency_key": "idem-1",
        "model": "gpt-whatever",  # not part of the contract
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_routing_requested_accepts_minimal_valid_payload():
    schema = load_data_schema("ir.routing.requested")
    payload = {"reasoning_class": "commodity_extraction", "task_ref": "task-1", "idempotency_key": "idem-1"}
    Draft202012Validator(schema).validate(payload)


def test_routing_requested_override_source_restricted_to_permitted_set():
    schema = load_data_schema("ir.routing.requested")
    payload = {
        "reasoning_class": "commodity_extraction", "task_ref": "task-1", "idempotency_key": "idem-1",
        "override": {"model_id": "m1", "source": "agent_runtime"},  # not admin|template
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


# ---------------------------------------------------------------------------
# ir.routing.bound: never emitted with an empty eligible set.
# ---------------------------------------------------------------------------

def _valid_stamp():
    return {
        "decision_id": "d-1", "output_hash": "sha256:abc", "governance_tier": "commodity",
        "privacy_class": "P0", "verdict_id": None,
        "expires_at": datetime.now(timezone.utc).isoformat(), "signature": "sig",
    }


def test_routing_bound_accepts_valid_payload():
    schema = load_data_schema("ir.routing.bound")
    payload = {
        "decision_id": "d-1", "reasoning_class": "commodity_extraction",
        "eligible_model_ids": ["m1", "m2"], "selected_model_id": "m1",
        "governance_tier": "commodity", "privacy_class": "P0",
        "governance_policy_version": "gov-v1", "stamp": _valid_stamp(),
    }
    Draft202012Validator(schema).validate(payload)


def test_routing_bound_rejects_empty_eligible_set():
    schema = load_data_schema("ir.routing.bound")
    payload = {
        "decision_id": "d-1", "reasoning_class": "commodity_extraction",
        "eligible_model_ids": [], "selected_model_id": "m1",
        "governance_tier": "commodity", "privacy_class": "P0",
        "governance_policy_version": "gov-v1", "stamp": _valid_stamp(),
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


# ---------------------------------------------------------------------------
# ir.integrity.*: signal_type must be one of the 14 registered signals.
# ---------------------------------------------------------------------------

def test_integrity_signal_rejects_unregistered_signal_type():
    schema = load_data_schema("ir.integrity.stamp_missing")
    payload = {"signal_type": "made_up_signal", "principal": "urn:ir:agent:x", "decision_id": "d-1"}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_integrity_signal_accepts_all_fourteen_registered_types():
    schema = load_data_schema("ir.integrity.stamp_missing")
    all_types = schema["properties"]["signal_type"]["enum"]
    assert len(all_types) == 14
    for signal_type in all_types:
        Draft202012Validator(schema).validate(
            {"signal_type": signal_type, "principal": "urn:ir:agent:x", "decision_id": "d-1"}
        )


# ---------------------------------------------------------------------------
# ir.posture.changed: loosening from restricted/quarantined needs a human.
# ---------------------------------------------------------------------------

def test_posture_changed_rejects_unapproved_loosen_from_restricted():
    schema = load_data_schema("ir.posture.changed")
    payload = {
        "principal": "urn:ir:agent:x", "from_posture": "restricted", "to_posture": "watch",
        "direction": "loosen", "score": 5.0,
        # no approved_by
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_posture_changed_accepts_approved_loosen_from_restricted():
    schema = load_data_schema("ir.posture.changed")
    payload = {
        "principal": "urn:ir:agent:x", "from_posture": "restricted", "to_posture": "watch",
        "direction": "loosen", "score": 5.0, "approved_by": "steward-1",
    }
    Draft202012Validator(schema).validate(payload)


def test_posture_changed_accepts_automated_tighten_with_no_approver():
    schema = load_data_schema("ir.posture.changed")
    payload = {
        "principal": "urn:ir:agent:x", "from_posture": "normal", "to_posture": "watch",
        "direction": "tighten", "score": 12.0,
    }
    Draft202012Validator(schema).validate(payload)


def test_posture_changed_accepts_automatic_watch_to_normal_decay_with_no_approver():
    """The one bounded ratchet exception: watch decays to normal automatically (Trust Architecture §6.4)."""
    schema = load_data_schema("ir.posture.changed")
    payload = {
        "principal": "urn:ir:agent:x", "from_posture": "watch", "to_posture": "normal",
        "direction": "loosen", "score": 0.0,
    }
    Draft202012Validator(schema).validate(payload)
