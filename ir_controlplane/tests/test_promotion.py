import json

import pytest
from jsonschema import Draft202012Validator

from ir_core.exceptions import HardStop
from ir_controlplane.service import GovernanceControlPlane
from ir_controlplane.signing import KeyPair
from ir_controlplane.store import InMemoryPolicyStore, VersionAlreadyExists, VersionNotFound
from schemas.registry import load_data_schema


def _plane_and_key():
    return GovernanceControlPlane(InMemoryPolicyStore()), KeyPair.generate()


def _submit(plane, key, version_id="gov-v1", domain_id="diocese-a"):
    return plane.submit_draft(
        version_id=version_id,
        domain_id=domain_id,
        classes={"commodity_extraction": {}},
        pool_membership={"commodity_extraction": ["m1", "m2"]},
        tiering={"commodity_extraction": "commodity"},
        tightening_map={},
        attestation_rules={},
        bands={"ttl_base": 300, "ttl_floor": 5, "h": 10},
        ledger_sampling_rate=1.0,
        verification_trust_bundle={"steward_key": key.public_key_b64()},
        signing_private_key=key.private_key,
    )


def test_submit_and_promote_happy_path():
    plane, key = _plane_and_key()
    draft = _submit(plane, key)
    assert draft.is_active is False

    event = plane.promote(
        version_id="gov-v1", domain_id="diocese-a", approver="domain-authority-1",
        approver_public_key_b64=key.public_key_b64(),
    )
    active = plane.active_policy("diocese-a")
    assert active.version_id == "gov-v1"
    assert active.is_active is True
    assert active.promoted_by == "domain-authority-1"
    assert event["version"] == "gov-v1"
    assert event["approver"] == "domain-authority-1"


def test_promote_emits_event_matching_governance_policy_promoted_schema():
    """The control plane's output must stay in lockstep with the event
    schema (schemas/events/governance_policy_promoted.schema.json) -- if
    either drifts, this test catches it before a consumer does."""
    plane, key = _plane_and_key()
    _submit(plane, key)
    event = plane.promote(
        version_id="gov-v1", domain_id="diocese-a", approver="domain-authority-1",
        approver_public_key_b64=key.public_key_b64(), evidence_refs=["review-1"],
    )
    schema = load_data_schema("ir.governance.policy.promoted")
    Draft202012Validator(schema).validate(event)  # raises on mismatch


def test_promote_refuses_forged_signature():
    """
    Hard stop: an unsigned or forged governance policy must never become
    active, regardless of who calls promote(). Simulates an attacker who
    tampers with the stored draft's content after signing (or forges a
    version_id -> content pair whose signature doesn't match).
    """
    plane, key = _plane_and_key()
    draft = _submit(plane, key)

    # Attacker verifies against a DIFFERENT key -- this is what "the
    # signature doesn't check out" looks like from the promotion caller's
    # side (e.g. a stale or wrong trust-bundle key was configured).
    attacker_key = KeyPair.generate()
    with pytest.raises(HardStop) as exc:
        plane.promote(
            version_id="gov-v1", domain_id="diocese-a", approver="domain-authority-1",
            approver_public_key_b64=attacker_key.public_key_b64(),
        )
    assert exc.value.code == "governance_policy_signature_invalid"
    assert plane.active_policy("diocese-a") is None  # never promoted


def test_promote_unknown_version_raises():
    plane, key = _plane_and_key()
    with pytest.raises(VersionNotFound):
        plane.promote(
            version_id="does-not-exist", domain_id="diocese-a", approver="x",
            approver_public_key_b64=key.public_key_b64(),
        )


def test_duplicate_version_id_rejected():
    plane, key = _plane_and_key()
    _submit(plane, key)
    with pytest.raises(VersionAlreadyExists):
        _submit(plane, key)  # same version_id again


def test_promoting_new_version_deactivates_previous_one():
    plane, key = _plane_and_key()
    _submit(plane, key, version_id="gov-v1")
    plane.promote("gov-v1", "diocese-a", "authority-1", key.public_key_b64())

    _submit(plane, key, version_id="gov-v2")
    plane.promote("gov-v2", "diocese-a", "authority-1", key.public_key_b64())

    active = plane.active_policy("diocese-a")
    assert active.version_id == "gov-v2"
    v1 = plane._store.get("gov-v1")
    assert v1.is_active is False  # exactly one active version per domain


def test_domains_are_independent():
    plane, key = _plane_and_key()
    _submit(plane, key, version_id="gov-a", domain_id="diocese-a")
    _submit(plane, key, version_id="gov-b", domain_id="diocese-b")
    plane.promote("gov-a", "diocese-a", "authority-1", key.public_key_b64())
    plane.promote("gov-b", "diocese-b", "authority-1", key.public_key_b64())

    assert plane.active_policy("diocese-a").version_id == "gov-a"
    assert plane.active_policy("diocese-b").version_id == "gov-b"
