"""
Core lattice types for the Intelligence Router.

These types encode the safety invariants as *types*, not as checks scattered
through the codebase. See docs/DECISIONS.md (D1) and the Trust Architecture
(the ratchet, §1) for the reasoning.

Ground rules enforced by construction here, not by convention elsewhere:
  - GovernanceTier, Posture and PrivacyClass are TOTAL ORDERS with a single
    `tighten` combinator; there is no operation that lowers a value.
  - PrivacyClass follows the platform-confirmed direction: P0 = least
    sensitive, P3 = most sensitive (decision R1). Comparisons must go through
    `may_receive()` — never compare `.value` directly in calling code.
  - LineageSet is a set-valued type with a symmetric disjointness test used
    for guider/classifier independence (decision D6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import FrozenSet, Optional

from ir_core.exceptions import HardStop


# ---------------------------------------------------------------------------
# Ordered lattice types
# ---------------------------------------------------------------------------

class GovernanceTier(IntEnum):
    """Cost-of-being-wrong tiers. Ordered; only ever raised via `tighten()`."""
    COMMODITY = 0
    NORMATIVE = 1
    GUIDER = 2


class PrivacyClass(IntEnum):
    """
    Data sensitivity, P0 (least sensitive) .. P3 (most sensitive).

    Decision R1 (2026-09-20): P3 = most sensitive. This is the MVP FRD's
    original direction; the Adaptive FRD was patched to match (v1.1).
    Do not compare .value directly outside this module — use may_receive().
    """
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3


class AuthorityTier(IntEnum):
    """Human-approval tiers, T0 (autonomous) .. T3 (dual approval)."""
    T0 = 0
    T1 = 1
    T2 = 2
    T3 = 3


class Posture(IntEnum):
    """
    A principal's standing, derived from integrity signals (Trust
    Architecture §6). Ordered; automated transitions may only *raise*
    posture (the ratchet, decision D-ratchet / INT-06). Lowering posture is a
    human act — see ir_posture.engine.
    """
    NORMAL = 0
    WATCH = 1
    RESTRICTED = 2
    QUARANTINED = 3


class CapabilityTier(IntEnum):
    """Model capability class. Distinct from GovernanceTier (decision R4)."""
    LIGHTWEIGHT = 0
    MID_TIER = 1
    HEAVYWEIGHT = 2
    SPECIALIZED = 3


def tighten(*tiers: GovernanceTier) -> GovernanceTier:
    """The only combinator over GovernanceTier: always the maximum (never lowers)."""
    if not tiers:
        raise ValueError("tighten() requires at least one tier")
    return max(tiers)


def tighten_posture(*postures: Posture) -> Posture:
    """The only automated combinator over Posture: always the maximum."""
    if not postures:
        raise ValueError("tighten_posture() requires at least one posture")
    return max(postures)


def may_receive(model_ceiling: PrivacyClass, data_class: PrivacyClass) -> bool:
    """
    The single comparison point for privacy enforcement (decision R1).

    A model may receive data only if its privacy ceiling is at or above the
    data's class. No other code in this codebase should compare PrivacyClass
    values directly -- route every such check through this function so the
    ordering direction is asserted in exactly one place.
    """
    return model_ceiling >= data_class


# ---------------------------------------------------------------------------
# Lineage (decision D6): a transitive SET, not an id.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LineageSet:
    """
    lineage(model) = lineage(base) ∪ (∪ lineage(teacher) for teacher in teachers)
                      ∪ {models whose outputs this model was trained on}

    The client framework corpus (doctrine, polity, policy) is deliberately
    EXEMPT from this set -- a guider and the model it oversees must both be
    grounded in it. Only base-family/provider, teacher lineages (at any
    depth) and cross-training count toward shared blind spots.
    """
    base_family: str
    members: FrozenSet[str] = field(default_factory=frozenset)  # includes base_family

    @staticmethod
    def for_base_model(base_family: str) -> "LineageSet":
        return LineageSet(base_family=base_family, members=frozenset({base_family}))

    def derive(self, teacher_lineages: "tuple[LineageSet, ...]" = (),
               trained_on_outputs_of: "tuple[LineageSet, ...]" = ()) -> "LineageSet":
        """Compute the lineage set of a model trained from this one plus teachers."""
        members = set(self.members)
        for t in teacher_lineages:
            members |= t.members
        for o in trained_on_outputs_of:
            members |= o.members
        return LineageSet(base_family=self.base_family, members=frozenset(members))

    def disjoint_from(self, other: "LineageSet") -> bool:
        """True iff no shared base family, teacher, or training-output source."""
        return self.members.isdisjoint(other.members)


# ---------------------------------------------------------------------------
# Eligibility binding (decision D2): caches the ELIGIBLE SET, never a single
# model. Selection over the set runs fresh on every request (the seam the
# Adaptive FRD's bandit later plugs into).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EligibilityBindingKey:
    """
    Cache key per decision D2. Includes posture (Trust Architecture §6.3) so
    a posture change invalidates cached eligibility for that principal.
    """
    reasoning_class: str
    effective_governance_tier: GovernanceTier
    privacy_class: PrivacyClass
    posture: Posture
    governance_policy_version: str

    def as_tuple(self):
        return (
            self.reasoning_class,
            int(self.effective_governance_tier),
            int(self.privacy_class),
            int(self.posture),
            self.governance_policy_version,
        )


@dataclass(frozen=True)
class EligibilityBinding:
    """The cached, revocable object: WHICH MODELS ARE ALLOWED, not which one to use."""
    key: EligibilityBindingKey
    eligible_model_ids: FrozenSet[str]
    provenance: "BindingProvenance"
    issued_at: datetime
    ttl_seconds: float

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        age = (now - self.issued_at).total_seconds()
        return age > self.ttl_seconds

    def require_nonempty(self) -> "EligibilityBinding":
        """Hard stop: no eligible model under the given constraints (FR-IRG-APV-02)."""
        if not self.eligible_model_ids:
            raise HardStop(
                "no_eligible_model",
                f"No model eligible for class={self.key.reasoning_class} "
                f"tier={self.key.effective_governance_tier.name} "
                f"privacy={self.key.privacy_class.name}",
            )
        return self


@dataclass(frozen=True)
class BindingProvenance:
    governance_policy_version: str
    selection_policy_version: Optional[str]
    calibration_state_version: Optional[str]
    signals: tuple = ()


# ---------------------------------------------------------------------------
# TTL formula (decision D10 / RTR-06): emergent, tighten-only via posture.
# ---------------------------------------------------------------------------

def ttl_eff(
    ttl_base: float,
    ttl_floor: float,
    suspicion_score: float,
    half_life_h: float,
) -> float:
    """
    TTL_eff = clamp(TTL_base * 2^(-S/h), TTL_floor, TTL_base)

    Each workaround attempt raises the principal's suspicion score S, halving
    the effective TTL every `h` points. Bounds (ttl_base, ttl_floor, h) are
    set in signed governance policy; the operating value is emergent.
    """
    if ttl_base <= 0 or ttl_floor < 0 or half_life_h <= 0:
        raise ValueError("ttl_eff: ttl_base and half_life_h must be positive; ttl_floor >= 0")
    if ttl_floor > ttl_base:
        raise ValueError("ttl_eff: ttl_floor must not exceed ttl_base")
    raw = ttl_base * (2.0 ** (-suspicion_score / half_life_h))
    return max(ttl_floor, min(ttl_base, raw))


def posture_from_score(score: float, thresholds: "PostureThresholds") -> Posture:
    """Map a decaying suspicion score to a posture via signed-policy thresholds."""
    if score >= thresholds.quarantined_at:
        return Posture.QUARANTINED
    if score >= thresholds.restricted_at:
        return Posture.RESTRICTED
    if score >= thresholds.watch_at:
        return Posture.WATCH
    return Posture.NORMAL


@dataclass(frozen=True)
class PostureThresholds:
    """Bounds from signed governance policy (INT-05)."""
    watch_at: float
    restricted_at: float
    quarantined_at: float

    def __post_init__(self):
        if not (0 <= self.watch_at <= self.restricted_at <= self.quarantined_at):
            raise ValueError(
                "PostureThresholds must be non-decreasing: "
                "0 <= watch_at <= restricted_at <= quarantined_at"
            )
