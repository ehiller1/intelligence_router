"""
The governance-policy store interface and an in-memory implementation.

The interface is what ir_controlplane.service depends on -- a real
Postgres-backed implementation (using ir_controlplane/migrations/003) is a
straight swap that doesn't touch promotion logic, because atomicity is
enforced here, at the store boundary, not by the caller retrying.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional


class VersionAlreadyExists(Exception):
    pass


class VersionNotFound(Exception):
    pass


@dataclass(frozen=True)
class GovernancePolicyVersion:
    """Mirrors ir_controlplane/migrations/003_governance_policy_versions.sql."""
    version_id: str
    domain_id: str
    classes: dict
    pool_membership: dict
    tiering: dict
    tightening_map: dict
    attestation_rules: dict
    bands: dict
    ledger_sampling_rate: float
    verification_trust_bundle: dict
    signature: str
    is_active: bool = False
    created_at: datetime = None
    promoted_at: Optional[datetime] = None
    promoted_by: Optional[str] = None

    def signable_payload(self) -> dict:
        """Everything except `signature` and mutable promotion state -- this
        is what gets signed and what a signature is verified against."""
        return {
            "version_id": self.version_id,
            "domain_id": self.domain_id,
            "classes": self.classes,
            "pool_membership": self.pool_membership,
            "tiering": self.tiering,
            "tightening_map": self.tightening_map,
            "attestation_rules": self.attestation_rules,
            "bands": self.bands,
            "ledger_sampling_rate": self.ledger_sampling_rate,
            "verification_trust_bundle": self.verification_trust_bundle,
        }


class PolicyStore(ABC):
    @abstractmethod
    def create_draft(self, policy: GovernancePolicyVersion) -> None: ...

    @abstractmethod
    def get(self, version_id: str) -> GovernancePolicyVersion: ...

    @abstractmethod
    def get_active(self, domain_id: str) -> Optional[GovernancePolicyVersion]: ...

    @abstractmethod
    def promote(self, version_id: str, domain_id: str, approver: str) -> GovernancePolicyVersion:
        """
        Atomically: mark `version_id` active and any previously-active
        version for `domain_id` inactive. Must never leave two versions
        active for the same domain, even under concurrent calls -- this is
        the MVP-0 exit criterion (Implementation Guide: "Atomic promotion
        test passes (concurrent writers, only one sees the flip)").
        """
        ...


class InMemoryPolicyStore(PolicyStore):
    """
    Thread-safe, single-process implementation for tests and local
    development. Atomicity is via one lock per domain (not a single global
    lock) so promotions in different domains never contend -- matching
    FR-IRG-CTL-03's "policy authority scoped to a single trust domain".

    Design note (found by ir_controlplane/tests/test_concurrency.py, which
    is worth keeping even though the bug it caught is fixed): an earlier
    version of this class stored `is_active` as an independent boolean field
    on each version and flipped it in two separate dict writes -- deactivate
    the old version's flag, then activate the new one's. Both writes were
    correctly serialized by the domain lock, so the store's WRITES were
    never wrong. But a reader that is not holding that lock (any reader --
    concurrent reads are never expected to take the write lock) could scan
    several versions' flags across that two-write window and see a stale
    "true" left over from before the deactivation alongside a fresh "true"
    from after the activation: two flags reading true at once, even though
    at no true instant did the store's actual state have two active
    versions. The fix is to stop storing `is_active` as independent,
    duplicated state at all -- `_active_by_domain[domain_id]` is the single
    source of truth, and `is_active` is now DERIVED from it, read fresh, on
    every `get()`. A derived fact updated by one atomic pointer swap cannot
    be torn the way two independent writes can.

    The equivalent lesson for the real Postgres-backed implementation:
    promote() must be `UPDATE ir_governance_policy_versions SET is_active =
    (version_id = $1) WHERE domain_id = $2` -- ONE statement covering every
    row for the domain, inside one transaction -- never two separate
    UPDATE statements, even inside the same transaction, if anything might
    ever read at an isolation level or through a path that can observe
    between them.
    """

    def __init__(self):
        self._versions: dict[str, GovernancePolicyVersion] = {}
        self._active_by_domain: dict[str, str] = {}
        self._domain_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, domain_id: str) -> threading.Lock:
        with self._locks_guard:
            if domain_id not in self._domain_locks:
                self._domain_locks[domain_id] = threading.Lock()
            return self._domain_locks[domain_id]

    def _with_derived_is_active(self, version: GovernancePolicyVersion) -> GovernancePolicyVersion:
        is_active = self._active_by_domain.get(version.domain_id) == version.version_id
        if version.is_active == is_active:
            return version
        return replace(version, is_active=is_active)

    def create_draft(self, policy: GovernancePolicyVersion) -> None:
        with self._locks_guard:
            if policy.version_id in self._versions:
                raise VersionAlreadyExists(policy.version_id)
            self._versions[policy.version_id] = policy

    def get(self, version_id: str) -> GovernancePolicyVersion:
        try:
            stored = self._versions[version_id]
        except KeyError:
            raise VersionNotFound(version_id) from None
        return self._with_derived_is_active(stored)

    def get_active(self, domain_id: str) -> Optional[GovernancePolicyVersion]:
        version_id = self._active_by_domain.get(domain_id)
        if version_id is None or version_id not in self._versions:
            return None
        return self.get(version_id)

    def promote(self, version_id: str, domain_id: str, approver: str) -> GovernancePolicyVersion:
        lock = self._lock_for(domain_id)
        with lock:
            candidate = self.get(version_id)
            if candidate.domain_id != domain_id:
                raise ValueError(
                    f"Version {version_id} belongs to domain {candidate.domain_id}, not {domain_id}"
                )

            promoted_at = datetime.now(timezone.utc)
            self._versions[version_id] = replace(
                self._versions[version_id],
                promoted_at=promoted_at,
                promoted_by=approver,
            )
            # Single atomic pointer swap -- see the class docstring. This is
            # the only write that changes which version is active; no
            # per-version boolean is separately flipped on or off.
            self._active_by_domain[domain_id] = version_id

            return self.get(version_id)
