"""
Ed25519 signing for governance policy versions (FR-IRG-KEY-01, decision D8).

This module is deliberately narrow: it signs and verifies a canonical byte
representation of a policy's content. It has no opinion on WHERE the private
key lives -- that's the HSM/KMS integration (Trust Architecture §9,
still-open item in the Implementation Plan §8), and production code must
never hold a raw Ed25519 private key in process memory the way the test
fixtures below do. This module exists so the promotion logic (atomicity,
"is this signature valid") can be built and tested now, and the signer
swapped for an HSM-backed one later without touching ir_controlplane.service.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonical_bytes(payload: dict) -> bytes:
    """
    Deterministic serialization for signing: sorted keys, no whitespace
    ambiguity. The `signature` field itself must never be included -- callers
    are responsible for signing the payload BEFORE attaching a signature.
    """
    if "signature" in payload:
        raise ValueError("canonical_bytes: payload must not already contain a 'signature' field")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class KeyPair:
    """Test/dev convenience only -- see module docstring."""
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @staticmethod
    def generate() -> "KeyPair":
        priv = Ed25519PrivateKey.generate()
        return KeyPair(private_key=priv, public_key=priv.public_key())

    def public_key_b64(self) -> str:
        raw = self.public_key.public_bytes_raw()
        return base64.b64encode(raw).decode("ascii")

    def private_key_pem(self) -> str:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")

    def public_key_pem(self) -> str:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")


def sign(private_key: Ed25519PrivateKey, payload: dict) -> str:
    """Returns a base64-encoded signature over the canonical payload bytes."""
    signature = private_key.sign(canonical_bytes(payload))
    return base64.b64encode(signature).decode("ascii")


def verify(public_key_b64: str, payload: dict, signature_b64: str) -> bool:
    """
    True iff `signature_b64` is a valid Ed25519 signature over `payload`
    under the given base64-encoded public key. Never raises -- a malformed
    signature or key is simply an invalid one (callers should treat that as
    a HardStop, not an exception to handle specially).
    """
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        public_key.verify(base64.b64decode(signature_b64), canonical_bytes(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
