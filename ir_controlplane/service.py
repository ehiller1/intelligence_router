"""
Governance-policy promotion service (FR-IRG-CTL-01/04).

Composes ir_controlplane.store (atomicity) with ir_controlplane.signing
(trust) and ir_core.exceptions.HardStop (refusal semantics), and emits the
ir.governance.policy.promoted event payload -- validated in tests against
schemas/events/governance_policy_promoted.schema.json so the control plane
and the event schema cannot silently drift apart.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ir_core.exceptions import HardStop
from ir_controlplane.signing import sign, verify
from ir_controlplane.store import GovernancePolicyVersion, PolicyStore


class GovernanceControlPlane:
    def __init__(self, store: PolicyStore):
        self._store = store

    def submit_draft(
        self,
        version_id: str,
        domain_id: str,
        classes: dict,
        pool_membership: dict,
        tiering: dict,
        tightening_map: dict,
        attestation_rules: dict,
        bands: dict,
        ledger_sampling_rate: float,
        verification_trust_bundle: dict,
        signing_private_key,
    ) -> GovernancePolicyVersion:
        """
        Constructs a draft, signs it, and stores it (not yet active). The
        signature covers everything except `signature`, `is_active`,
        `promoted_at`, `promoted_by` -- i.e. exactly the content a Domain
        Authority is attesting to (FR-IRG-KEY-01).
        """
        draft = GovernancePolicyVersion(
            version_id=version_id,
            domain_id=domain_id,
            classes=classes,
            pool_membership=pool_membership,
            tiering=tiering,
            tightening_map=tightening_map,
            attestation_rules=attestation_rules,
            bands=bands,
            ledger_sampling_rate=ledger_sampling_rate,
            verification_trust_bundle=verification_trust_bundle,
            signature="",  # placeholder; replaced below
            created_at=datetime.now(timezone.utc),
        )
        signature = sign(signing_private_key, draft.signable_payload())
        signed_draft = GovernancePolicyVersion(**{**draft.__dict__, "signature": signature})
        self._store.create_draft(signed_draft)
        return signed_draft

    def promote(
        self,
        version_id: str,
        domain_id: str,
        approver: str,
        approver_public_key_b64: str,
        evidence_refs: Optional[list] = None,
    ) -> dict:
        """
        FR-IRG-CTL-04: atomic promotion with a new version id, sidecars
        converge. Verifies the signature BEFORE promoting -- an unsigned or
        forged policy must never become active, hard stop.

        Returns the ir.governance.policy.promoted event payload (decision
        R9), ready to publish on the mesh.
        """
        draft = self._store.get(version_id)

        if not verify(approver_public_key_b64, draft.signable_payload(), draft.signature):
            raise HardStop(
                "governance_policy_signature_invalid",
                f"Signature verification failed for policy version {version_id}; "
                "refusing promotion. An unsigned or forged governance policy "
                "must never become active.",
            )

        promoted = self._store.promote(version_id, domain_id, approver)

        return {
            "version": promoted.version_id,
            "domain_id": promoted.domain_id,
            "approver": approver,
            "evidence_refs": evidence_refs or [],
            "signature": promoted.signature,
        }

    def active_policy(self, domain_id: str) -> Optional[GovernancePolicyVersion]:
        return self._store.get_active(domain_id)
