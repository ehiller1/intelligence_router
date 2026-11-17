"""
Property tests for the lattice types. These run on every commit forever
(README: "zero regressions in these tests from this moment forward").
"""
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, strategies as st

from ir_core.types import (
    GovernanceTier,
    Posture,
    PrivacyClass,
    LineageSet,
    PostureThresholds,
    posture_from_score,
    tighten,
    tighten_posture,
    may_receive,
    ttl_eff,
)

tiers = st.sampled_from(list(GovernanceTier))
postures = st.sampled_from(list(Posture))
privacy_classes = st.sampled_from(list(PrivacyClass))


# ---------------------------------------------------------------------------
# D1: tighten() is monotonic and idempotent -- the core safety invariant.
# ---------------------------------------------------------------------------

@given(st.lists(tiers, min_size=1, max_size=10))
def test_tighten_never_below_any_input(ts):
    result = tighten(*ts)
    assert all(result >= t for t in ts)


@given(tiers)
def test_tighten_idempotent(t):
    assert tighten(t) == t
    assert tighten(t, t) == t


@given(tiers, tiers)
def test_tighten_commutative(a, b):
    assert tighten(a, b) == tighten(b, a)


@given(st.lists(postures, min_size=1, max_size=10))
def test_tighten_posture_never_below_any_input(ps):
    result = tighten_posture(*ps)
    assert all(result >= p for p in ps)


def test_tighten_empty_raises():
    with pytest.raises(ValueError):
        tighten()
    with pytest.raises(ValueError):
        tighten_posture()


# ---------------------------------------------------------------------------
# R1a: may_receive() asserts P0 = most sensitive, and is the ONLY comparison.
# ---------------------------------------------------------------------------

def test_privacy_ordering_matches_decision_r1a():
    """P0 is MOST sensitive, P3 is least (decision R1a, 2026-11-17; R1 had the
    reverse). Written out label by label so a silent flip fails here."""
    assert PrivacyClass.P3 < PrivacyClass.P2 < PrivacyClass.P1 < PrivacyClass.P0
    assert [PrivacyClass[n].value for n in ("P0", "P1", "P2", "P3")] == [3, 2, 1, 0]
    # the apps' own labels: restricted, confidential, internal, public
    assert not may_receive(PrivacyClass.P3, PrivacyClass.P0)   # public-only model, restricted data
    assert not may_receive(PrivacyClass.P2, PrivacyClass.P1)   # internal-cleared, confidential data
    assert may_receive(PrivacyClass.P1, PrivacyClass.P2)       # confidential-cleared, internal data
    assert may_receive(PrivacyClass.P0, PrivacyClass.P0)


@given(privacy_classes, privacy_classes)
def test_may_receive_reflexive_and_ordered(ceiling, data):
    """A model may receive data at or below its ceiling, and nothing above it."""
    assert may_receive(ceiling, data) == (ceiling >= data)


def test_most_sensitive_data_never_reaches_the_lowest_ceiling():
    """The MVP FRD's central rule, in R1a labels: P0 (most sensitive) data
    never reaches a model whose ceiling is P3 (e.g. an unrestricted frontier
    API)."""
    assert may_receive(PrivacyClass.P3, PrivacyClass.P0) is False


def test_the_highest_ceiling_accepts_everything():
    for data in PrivacyClass:
        assert may_receive(PrivacyClass.P0, data) is True


# ---------------------------------------------------------------------------
# D6: lineage sets are transitive and disjointness is symmetric.
# ---------------------------------------------------------------------------

def test_lineage_teacher_propagates():
    teacher = LineageSet.for_base_model("frontier-a")
    worker_base = LineageSet.for_base_model("oss-13b")
    distilled = worker_base.derive(teacher_lineages=(teacher,))
    assert "frontier-a" in distilled.members
    assert "oss-13b" in distilled.members


def test_lineage_disjoint_after_distillation_from_guider_teacher():
    """
    The exact failure mode decision D6 exists to catch: if a worker is
    distilled from the SAME lineage as its guider, disjointness must fail
    even though their model_ids differ.
    """
    guider_lineage = LineageSet.for_base_model("frontier-a")
    worker_base = LineageSet.for_base_model("oss-13b")
    worker_distilled_from_guiders_family = worker_base.derive(teacher_lineages=(guider_lineage,))
    assert not worker_distilled_from_guiders_family.disjoint_from(guider_lineage)


def test_lineage_disjoint_true_for_unrelated_families():
    a = LineageSet.for_base_model("frontier-a")
    b = LineageSet.for_base_model("frontier-b")
    assert a.disjoint_from(b)
    assert b.disjoint_from(a)  # symmetric


@given(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=20))
def test_lineage_disjoint_is_symmetric(fam_a, fam_b):
    a = LineageSet.for_base_model(fam_a)
    b = LineageSet.for_base_model(fam_b)
    assert a.disjoint_from(b) == b.disjoint_from(a)


# ---------------------------------------------------------------------------
# D10 / RTR-06: TTL is emergent, tighten-only, and bounded.
# ---------------------------------------------------------------------------

@given(
    st.floats(min_value=1, max_value=3600),
    st.floats(min_value=0, max_value=60),
    st.floats(min_value=0, max_value=100),
    st.floats(min_value=0.1, max_value=100),
)
def test_ttl_eff_always_within_bounds(base, floor, score, half_life):
    if floor > base:
        return  # invalid combination, ttl_eff itself rejects it
    result = ttl_eff(base, floor, score, half_life)
    assert floor <= result <= base


def test_ttl_eff_decreases_monotonically_with_score():
    base, floor, h = 300.0, 5.0, 10.0
    scores = [0, 5, 10, 20, 50, 100]
    values = [ttl_eff(base, floor, s, h) for s in scores]
    assert values == sorted(values, reverse=True)


def test_ttl_eff_at_zero_score_equals_base():
    assert ttl_eff(300.0, 5.0, 0.0, 10.0) == 300.0


def test_ttl_eff_rejects_invalid_bounds():
    with pytest.raises(ValueError):
        ttl_eff(ttl_base=100, ttl_floor=200, suspicion_score=0, half_life_h=10)


# ---------------------------------------------------------------------------
# INT-05: posture thresholds must be non-decreasing (governance-policy bound).
# ---------------------------------------------------------------------------

def test_posture_thresholds_reject_out_of_order():
    with pytest.raises(ValueError):
        PostureThresholds(watch_at=10, restricted_at=5, quarantined_at=20)


def test_posture_from_score_boundaries():
    th = PostureThresholds(watch_at=10, restricted_at=25, quarantined_at=50)
    assert posture_from_score(0, th) == Posture.NORMAL
    assert posture_from_score(9.99, th) == Posture.NORMAL
    assert posture_from_score(10, th) == Posture.WATCH
    assert posture_from_score(25, th) == Posture.RESTRICTED
    assert posture_from_score(50, th) == Posture.QUARANTINED
    assert posture_from_score(1000, th) == Posture.QUARANTINED
