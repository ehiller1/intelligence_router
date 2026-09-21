"""
Control plane HTTP API (FR-IRG-CTL-01/02): a thin FastAPI wrapper over
ir_controlplane.service.GovernanceControlPlane. All atomicity, signature
verification, and hard-stop logic lives in service.py/store.py and is
tested there without HTTP in the loop -- this module only does request/
response marshalling.

Stateless by design (FR-IRG-CTL-02: "replicated, stateless instances with
failover"): the in-memory store here is a single-process placeholder. A
real deployment injects a Postgres-backed PolicyStore (implementing the
same interface) via `create_app(store=...)`, and any number of replicas can
run behind a load balancer because none of them hold state the others don't
also see through the shared database.
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ir_core.exceptions import HardStop
from ir_controlplane.service import GovernanceControlPlane
from ir_controlplane.store import (
    InMemoryPolicyStore,
    PolicyStore,
    VersionAlreadyExists,
    VersionNotFound,
)


class SubmitDraftRequest(BaseModel):
    version_id: str
    domain_id: str
    classes: dict = Field(default_factory=dict)
    pool_membership: dict = Field(default_factory=dict)
    tiering: dict = Field(default_factory=dict)
    tightening_map: dict = Field(default_factory=dict)
    attestation_rules: dict = Field(default_factory=dict)
    bands: dict = Field(default_factory=dict)
    ledger_sampling_rate: float = 1.0
    verification_trust_bundle: dict = Field(default_factory=dict)
    signing_private_key_pem: str
    """
    PEM-encoded Ed25519 private key. Present for MVP-0 testing convenience
    ONLY -- a real deployment signs in the Domain Authority's own tooling
    (or an HSM) and submits an already-signed payload; the control plane
    should never see a private key over the wire in production (Trust
    Architecture §9). Tracked as a TODO for the real Postgres-backed phase.
    """


class PromoteRequest(BaseModel):
    approver: str
    approver_public_key_pem: str
    evidence_refs: list[str] = Field(default_factory=list)


class PolicyVersionResponse(BaseModel):
    version_id: str
    domain_id: str
    is_active: bool
    promoted_at: Optional[str] = None
    promoted_by: Optional[str] = None


def _to_response(policy) -> PolicyVersionResponse:
    return PolicyVersionResponse(
        version_id=policy.version_id,
        domain_id=policy.domain_id,
        is_active=policy.is_active,
        promoted_at=policy.promoted_at.isoformat() if policy.promoted_at else None,
        promoted_by=policy.promoted_by,
    )


def create_app(store: Optional[PolicyStore] = None) -> FastAPI:
    from cryptography.hazmat.primitives import serialization

    plane = GovernanceControlPlane(store or InMemoryPolicyStore())
    app = FastAPI(title="Intelligence Router Control Plane", version="0.1.0")

    @app.post("/governance-policy/draft", response_model=PolicyVersionResponse, status_code=201)
    def submit_draft(req: SubmitDraftRequest):
        try:
            private_key = serialization.load_pem_private_key(
                req.signing_private_key_pem.encode(), password=None
            )
            draft = plane.submit_draft(
                version_id=req.version_id,
                domain_id=req.domain_id,
                classes=req.classes,
                pool_membership=req.pool_membership,
                tiering=req.tiering,
                tightening_map=req.tightening_map,
                attestation_rules=req.attestation_rules,
                bands=req.bands,
                ledger_sampling_rate=req.ledger_sampling_rate,
                verification_trust_bundle=req.verification_trust_bundle,
                signing_private_key=private_key,
            )
        except VersionAlreadyExists as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _to_response(draft)

    @app.post("/governance-policy/{version_id}/promote")
    def promote(version_id: str, domain_id: str, req: PromoteRequest):
        from cryptography.hazmat.primitives import serialization
        import base64

        try:
            public_key = serialization.load_pem_public_key(req.approver_public_key_pem.encode())
            public_key_b64 = base64.b64encode(public_key.public_bytes_raw()).decode("ascii")
        except Exception as exc:  # noqa: BLE001 -- malformed key is a client error, not a 500
            raise HTTPException(status_code=400, detail=f"Malformed public key: {exc}") from exc

        try:
            event = plane.promote(
                version_id=version_id,
                domain_id=domain_id,
                approver=req.approver,
                approver_public_key_b64=public_key_b64,
                evidence_refs=req.evidence_refs,
            )
        except VersionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HardStop as exc:
            # A HardStop is always a 409 (refused, not a server error) with
            # the stable code surfaced so callers/tests can key off it --
            # never silently swallowed, never a 500.
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
        return event

    @app.get("/governance-policy/active", response_model=Optional[PolicyVersionResponse])
    def active_policy(domain_id: str):
        policy = plane.active_policy(domain_id)
        return _to_response(policy) if policy else None

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
