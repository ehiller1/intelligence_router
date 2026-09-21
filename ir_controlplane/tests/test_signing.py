from ir_controlplane.signing import KeyPair, sign, verify


def _payload():
    return {"domain_id": "test-domain", "classes": {"a": 1}, "tiering": {"x": "normative"}}


def test_sign_and_verify_round_trip():
    kp = KeyPair.generate()
    signature = sign(kp.private_key, _payload())
    assert verify(kp.public_key_b64(), _payload(), signature) is True


def test_verify_fails_on_tampered_payload():
    kp = KeyPair.generate()
    signature = sign(kp.private_key, _payload())
    tampered = {**_payload(), "tiering": {"x": "commodity"}}  # attacker downgrades the tier
    assert verify(kp.public_key_b64(), tampered, signature) is False


def test_verify_fails_with_wrong_key():
    kp_a = KeyPair.generate()
    kp_b = KeyPair.generate()
    signature = sign(kp_a.private_key, _payload())
    assert verify(kp_b.public_key_b64(), _payload(), signature) is False


def test_verify_fails_on_malformed_inputs_without_raising():
    assert verify("not-valid-base64!!!", _payload(), "also-not-valid") is False


def test_canonical_bytes_deterministic_regardless_of_key_order():
    from ir_controlplane.signing import canonical_bytes
    a = canonical_bytes({"x": 1, "y": 2})
    b = canonical_bytes({"y": 2, "x": 1})
    assert a == b
