"""
HTTP-level tests for the control plane API. These deliberately duplicate a
couple of the service-level scenarios (happy path, forged signature) to
confirm the FastAPI marshalling layer doesn't lose or mistranslate the
underlying guarantees -- a HardStop must surface as 409 with its code
intact, never as an unhandled 500.
"""
import pytest
from fastapi.testclient import TestClient

from ir_controlplane.app import create_app
from ir_controlplane.signing import KeyPair


@pytest.fixture()
def client():
    return TestClient(create_app())


def _draft_payload(key: KeyPair, version_id="gov-v1", domain_id="diocese-a"):
    return {
        "version_id": version_id,
        "domain_id": domain_id,
        "classes": {"commodity_extraction": {}},
        "pool_membership": {"commodity_extraction": ["m1"]},
        "tiering": {"commodity_extraction": "commodity"},
        "tightening_map": {},
        "attestation_rules": {},
        "bands": {},
        "ledger_sampling_rate": 1.0,
        "verification_trust_bundle": {"steward_key": key.public_key_b64()},
        "signing_private_key_pem": key.private_key_pem(),
    }


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_submit_draft_then_promote_then_active(client):
    key = KeyPair.generate()

    resp = client.post("/governance-policy/draft", json=_draft_payload(key))
    assert resp.status_code == 201
    assert resp.json()["is_active"] is False

    resp = client.post(
        "/governance-policy/gov-v1/promote",
        params={"domain_id": "diocese-a"},
        json={"approver": "domain-authority-1", "approver_public_key_pem": key.public_key_pem()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "gov-v1"
    assert body["approver"] == "domain-authority-1"

    resp = client.get("/governance-policy/active", params={"domain_id": "diocese-a"})
    assert resp.status_code == 200
    assert resp.json()["version_id"] == "gov-v1"
    assert resp.json()["is_active"] is True


def test_submit_duplicate_version_is_409(client):
    key = KeyPair.generate()
    client.post("/governance-policy/draft", json=_draft_payload(key))
    resp = client.post("/governance-policy/draft", json=_draft_payload(key))
    assert resp.status_code == 409


def test_promote_with_wrong_key_is_409_hard_stop_not_500(client):
    key = KeyPair.generate()
    attacker_key = KeyPair.generate()
    client.post("/governance-policy/draft", json=_draft_payload(key))

    resp = client.post(
        "/governance-policy/gov-v1/promote",
        params={"domain_id": "diocese-a"},
        json={"approver": "domain-authority-1", "approver_public_key_pem": attacker_key.public_key_pem()},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "governance_policy_signature_invalid"


def test_promote_unknown_version_is_404(client):
    key = KeyPair.generate()
    resp = client.post(
        "/governance-policy/does-not-exist/promote",
        params={"domain_id": "diocese-a"},
        json={"approver": "x", "approver_public_key_pem": key.public_key_pem()},
    )
    assert resp.status_code == 404


def test_active_policy_for_unknown_domain_is_none(client):
    resp = client.get("/governance-policy/active", params={"domain_id": "nonexistent-domain"})
    assert resp.status_code == 200
    assert resp.json() is None


def test_malformed_public_key_is_400_not_500(client):
    key = KeyPair.generate()
    client.post("/governance-policy/draft", json=_draft_payload(key))
    resp = client.post(
        "/governance-policy/gov-v1/promote",
        params={"domain_id": "diocese-a"},
        json={"approver": "x", "approver_public_key_pem": "not a real pem key"},
    )
    assert resp.status_code == 400
