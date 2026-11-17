"""
One test per hard stop in the autonomy ladder (MVP FRD §5.13 + patched
Adaptive FRD §5.10). Every hard stop raises ir_core.exceptions.HardStop with
a stable `code`. This file is the executable checklist referenced by the
Implementation Guide's "MVP-0 exit criterion": all hard stops covered.

    1.  no_eligible_model
    2.  governance tier cannot be downgraded (structural, via tighten())
    3.  unattested model excluded from governed tiers
    4.  privacy ceiling: data above a model's ceiling is never routed to it
    5.  guider tier accepts no overrides, from any source
    6.  override source not in the permitted set (agents cannot pin models)
    7.  guider lineage must be disjoint from the model it oversees
    8.  distillation candidate: P0 (most sensitive) content excluded absolutely
    9.  distillation candidate: P1 without consent+Redactor excluded
    10. distillation export: dataset class must not exceed destination ceiling
    11. no automatic relaxation path exists for governance-tier or posture
"""
from datetime import datetime, timedelta, timezone

import pytest

from ir_core.exceptions import HardStop
from ir_core.types import GovernanceTier, LineageSet, Posture, PrivacyClass, tighten
from ir_core.resolution import (
    ModelRecord,
    ReasoningClassRecord,
    apply_override,
    assert_guider_lineage_disjoint,
    build_binding,
    resolve_eligible_set,
)
from ir_core.distillation import DistillationCandidate, build_dataset

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=30)
PAST = NOW - timedelta(days=1)


def _model(model_id, ceiling=PrivacyClass.P0, lineage="fam-a", cost=1.0,
           attested=True, valid_until=FUTURE):
    return ModelRecord(
        model_id=model_id,
        privacy_ceiling=ceiling,
        lineage=LineageSet.for_base_model(lineage),
        cost_per_1k_tokens=cost,
        is_attested=attested,
        attestation_valid_until=valid_until,
        supported_classes=frozenset({"commodity_extraction"}),
    )


# ---------------------------------------------------------------------------
# 1. No eligible model -> ledgered refusal, never a silent downgrade.
# ---------------------------------------------------------------------------

def test_hard_stop_no_eligible_model():
    rc = ReasoningClassRecord(
        name="pastoral_drafting",
        default_governance_tier=GovernanceTier.NORMATIVE,
        eligible_model_ids=frozenset({"model-a"}),
    )
    # model-a's ceiling (P2) cannot receive P1 data -> eligible set is empty
    models = {"model-a": _model("model-a", ceiling=PrivacyClass.P2)}
    with pytest.raises(HardStop) as exc:
        build_binding(
            rc, models, GovernanceTier.NORMATIVE, PrivacyClass.P0,
            Posture.NORMAL, "gov-v1", ttl_seconds=60, now=NOW,
        )
    assert exc.value.code == "no_eligible_model"


# ---------------------------------------------------------------------------
# 2. Governance tier is structurally non-decreasing (D1).
# ---------------------------------------------------------------------------

def test_hard_stop_tier_cannot_be_downgraded():
    """
    A task's function-default tier is COMMODITY; content classification
    raised it to NORMATIVE. There is no code path back down -- tighten()
    is the only combinator and it is a max().
    """
    function_default = GovernanceTier.COMMODITY
    classifier_signal = GovernanceTier.NORMATIVE
    effective = tighten(function_default, classifier_signal)
    assert effective == GovernanceTier.NORMATIVE
    # Applying tighten again with the original (lower) default cannot undo it.
    assert tighten(effective, function_default) == GovernanceTier.NORMATIVE


# ---------------------------------------------------------------------------
# 3. Unattested model excluded from normative/guider tiers.
# ---------------------------------------------------------------------------

def test_hard_stop_unattested_model_excluded_from_governed_tier():
    rc = ReasoningClassRecord(
        name="doctrinal_review",
        default_governance_tier=GovernanceTier.NORMATIVE,
        eligible_model_ids=frozenset({"unattested", "attested"}),
    )
    models = {
        "unattested": _model("unattested", attested=False, valid_until=None),
        "attested": _model("attested", attested=True, valid_until=FUTURE),
    }
    eligible = resolve_eligible_set(rc, models, GovernanceTier.NORMATIVE, PrivacyClass.P1, now=NOW)
    assert eligible == frozenset({"attested"})


def test_hard_stop_expired_attestation_excluded_from_governed_tier():
    rc = ReasoningClassRecord(
        name="doctrinal_review",
        default_governance_tier=GovernanceTier.NORMATIVE,
        eligible_model_ids=frozenset({"expired"}),
    )
    models = {"expired": _model("expired", attested=True, valid_until=PAST)}
    eligible = resolve_eligible_set(rc, models, GovernanceTier.NORMATIVE, PrivacyClass.P2, now=NOW)
    assert eligible == frozenset()


def test_attestation_not_required_for_commodity_tier():
    """Commodity work does not require attestation (only normative/guider do)."""
    rc = ReasoningClassRecord(
        name="commodity_extraction",
        default_governance_tier=GovernanceTier.COMMODITY,
        eligible_model_ids=frozenset({"unattested"}),
    )
    models = {"unattested": _model("unattested", attested=False, valid_until=None)}
    eligible = resolve_eligible_set(rc, models, GovernanceTier.COMMODITY, PrivacyClass.P3, now=NOW)
    assert eligible == frozenset({"unattested"})


# ---------------------------------------------------------------------------
# 4. Privacy ceiling: P0 (most sensitive) content never reaches a lower-ceiling model.
# ---------------------------------------------------------------------------

def test_hard_stop_p0_data_never_reaches_low_ceiling_model():
    rc = ReasoningClassRecord(
        name="commodity_extraction",
        default_governance_tier=GovernanceTier.COMMODITY,
        eligible_model_ids=frozenset({"vendor-frontier"}),
    )
    models = {"vendor-frontier": _model("vendor-frontier", ceiling=PrivacyClass.P3)}
    eligible = resolve_eligible_set(rc, models, GovernanceTier.COMMODITY, PrivacyClass.P0, now=NOW)
    assert eligible == frozenset()


# ---------------------------------------------------------------------------
# 5. Guider tier accepts no overrides, from any source (FR-IRG-GDR-01).
# ---------------------------------------------------------------------------

def test_hard_stop_guider_tier_rejects_override_even_from_admin():
    models = {"cheap": _model("cheap", cost=1.0), "guider-model": _model("guider-model", cost=99.0)}
    eligible = frozenset({"cheap", "guider-model"})
    result = apply_override(
        eligible, models,
        override_model_id="cheap",
        override_source="admin",
        effective_governance_tier=GovernanceTier.GUIDER,
    )
    assert result.override_honored is False
    assert result.override_refused_reason == "guider_tier_accepts_no_overrides"
    # Selection still proceeds normally within the eligible set.
    assert result.selected_model_id == "cheap"  # lowest cost, not the "override"


# ---------------------------------------------------------------------------
# 6. Runtime agents cannot pin a model outside the permitted source list
#    (FR-IRG-FND-04: agents reference classes, never models).
# ---------------------------------------------------------------------------

def test_hard_stop_override_source_not_permitted():
    models = {"m1": _model("m1")}
    with pytest.raises(HardStop) as exc:
        apply_override(
            frozenset({"m1"}), models,
            override_model_id="m1",
            override_source="agent_runtime",  # not in {admin, template}
            effective_governance_tier=GovernanceTier.COMMODITY,
        )
    assert exc.value.code == "override_source_not_permitted"


def test_ineligible_pin_is_dropped_not_fatal():
    """
    Decision R5: an ineligible pin does not fail the task. It is dropped,
    the task routes normally, and the refusal reason is surfaced for the
    ledger -- this is NOT one of the 11 hard stops (it degrades gracefully).
    """
    models = {"eligible-cheap": _model("eligible-cheap", cost=1.0)}
    result = apply_override(
        frozenset({"eligible-cheap"}), models,
        override_model_id="stale-pinned-model",  # not in the eligible set
        override_source="template",
        effective_governance_tier=GovernanceTier.NORMATIVE,
    )
    assert result.override_honored is False
    assert result.override_refused_reason == "pin_not_eligible_for_effective_tier"
    assert result.selected_model_id == "eligible-cheap"


# ---------------------------------------------------------------------------
# 7. Guider lineage must be disjoint from the model it oversees (D6).
# ---------------------------------------------------------------------------

def test_hard_stop_guider_shares_lineage_with_overseen_model():
    guider = _model("guider-1", lineage="frontier-a")
    overseen = _model("worker-1", lineage="frontier-a")  # same family!
    with pytest.raises(HardStop) as exc:
        assert_guider_lineage_disjoint(guider, overseen)
    assert exc.value.code == "guider_lineage_not_disjoint"


def test_lineage_disjoint_guider_passes():
    guider = _model("guider-1", lineage="frontier-a")
    overseen = _model("worker-1", lineage="oss-13b")
    assert_guider_lineage_disjoint(guider, overseen)  # does not raise


def test_hard_stop_distilled_worker_inherits_teachers_lineage():
    """
    The exact scenario D6 exists for: a worker distilled from the guider's
    own family must still fail disjointness, even with a fresh model_id.
    """
    guider_lineage = LineageSet.for_base_model("frontier-a")
    guider = ModelRecord(
        model_id="guider-1", privacy_ceiling=PrivacyClass.P0, lineage=guider_lineage,
        cost_per_1k_tokens=99.0, is_attested=True, attestation_valid_until=FUTURE,
        supported_classes=frozenset(),
    )
    distilled_lineage = LineageSet.for_base_model("oss-13b").derive(teacher_lineages=(guider_lineage,))
    distilled_worker = ModelRecord(
        model_id="worker-distilled", privacy_ceiling=PrivacyClass.P0, lineage=distilled_lineage,
        cost_per_1k_tokens=0.1, is_attested=True, attestation_valid_until=FUTURE,
        supported_classes=frozenset(),
    )
    with pytest.raises(HardStop):
        assert_guider_lineage_disjoint(guider, distilled_worker)


# ---------------------------------------------------------------------------
# 8 & 9. Distillation privacy gating (decision R1, patched Adaptive DST-01).
# ---------------------------------------------------------------------------

def test_hard_stop_p3_excluded_from_distillation_absolutely():
    candidates = [
        DistillationCandidate("c1", PrivacyClass.P0, has_consent=True, redactor_passed=True),
    ]
    dataset = build_dataset(candidates, destination_privacy_ceiling=PrivacyClass.P0)
    assert dataset == frozenset()  # excluded regardless of consent


def test_hard_stop_p2_without_consent_excluded_from_distillation():
    candidates = [
        DistillationCandidate("c1", PrivacyClass.P1, has_consent=False, redactor_passed=True),
        DistillationCandidate("c2", PrivacyClass.P1, has_consent=True, redactor_passed=False),
    ]
    dataset = build_dataset(candidates, destination_privacy_ceiling=PrivacyClass.P0)
    assert dataset == frozenset()


def test_p2_with_consent_and_redactor_pass_is_included():
    candidates = [
        DistillationCandidate("c1", PrivacyClass.P1, has_consent=True, redactor_passed=True),
        DistillationCandidate("c2", PrivacyClass.P3),
    ]
    dataset = build_dataset(candidates, destination_privacy_ceiling=PrivacyClass.P0)
    assert dataset == frozenset({"c1", "c2"})


# ---------------------------------------------------------------------------
# 10. Distillation export: dataset class must not exceed destination ceiling.
# ---------------------------------------------------------------------------

def test_hard_stop_distillation_export_exceeds_destination_ceiling():
    """
    Even fully-eligible, fully-consented candidates cannot be exported to a
    training destination whose ceiling is below the dataset's resulting
    class. This is the gap the FRDs left open: 'fine-tuning pipeline is out
    of scope' did not say anything blocks a P1 dataset reaching a vendor's
    fine-tuning API.
    """
    candidates = [
        DistillationCandidate("c1", PrivacyClass.P1, has_consent=True, redactor_passed=True),
    ]
    with pytest.raises(HardStop) as exc:
        build_dataset(candidates, destination_privacy_ceiling=PrivacyClass.P2)  # too low
    assert exc.value.code == "distillation_export_exceeds_destination_ceiling"


def test_distillation_export_succeeds_when_ceiling_covers_dataset():
    candidates = [
        DistillationCandidate("c1", PrivacyClass.P2, has_consent=True, redactor_passed=True),
    ]
    dataset = build_dataset(candidates, destination_privacy_ceiling=PrivacyClass.P1)
    assert dataset == frozenset({"c1"})


# ---------------------------------------------------------------------------
# 11. The ratchet: no automatic-relaxation function exists in ir_core.
# ---------------------------------------------------------------------------

def test_no_automatic_relaxation_symbol_exists_in_core_types():
    """
    Guardrail test, not a runtime check: fails loudly if anyone adds a
    function that could lower GovernanceTier or Posture automatically.
    Loosening is a human act (Trust Architecture §6.4) and belongs in a
    separately reviewed, approval-gated module -- never in ir_core.
    """
    import ir_core.types as types_mod
    forbidden_substrings = ("loosen", "relax", "lower_tier", "downgrade", "decrease_posture")
    public_names = [n for n in dir(types_mod) if not n.startswith("_")]
    offending = [n for n in public_names if any(f in n.lower() for f in forbidden_substrings)]
    assert offending == [], f"Found relaxation-shaped symbols in ir_core.types: {offending}"


def test_tighten_is_the_only_governance_tier_combinator():
    """There is exactly one way to combine GovernanceTier values: tighten()."""
    import ir_core.types as types_mod
    import inspect
    tier_combinators = [
        name for name, obj in vars(types_mod).items()
        if inspect.isfunction(obj)
        and "GovernanceTier" in inspect.signature(obj).__str__()
    ]
    assert tier_combinators == ["tighten"]
