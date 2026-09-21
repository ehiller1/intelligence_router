"""
Distillation privacy gating (decision R1, patched Adaptive FRD §3.4 / §5.10).

Two hard stops live here:
  1. P3 content is excluded from distillation candidates absolutely; P2
     requires explicit consent and a Redactor pass; P0/P1 are unrestricted.
  2. A dataset carries the HIGHEST privacy class of any row in it, and may
     only be exported to a training destination whose privacy ceiling covers
     that class (the export-ceiling rule -- an addition beyond both FRDs,
     because "the fine-tuning pipeline is out of scope" left a gap: nothing
     stopped an exported dataset from reaching a vendor destination the
     router would have refused as a live request).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional

from ir_core.exceptions import HardStop
from ir_core.types import PrivacyClass, may_receive


@dataclass(frozen=True)
class DistillationCandidate:
    candidate_id: str
    privacy_class: PrivacyClass
    has_consent: bool = False
    redactor_passed: bool = False


def candidate_is_eligible(candidate: DistillationCandidate) -> bool:
    """
    FR-IR-DST-01 gating, privacy direction per decision R1:
      P0, P1            -> eligible unconditionally
      P2                 -> eligible only with explicit consent AND a Redactor pass
      P3                 -> never eligible (hard stop)
    """
    if candidate.privacy_class == PrivacyClass.P3:
        return False
    if candidate.privacy_class == PrivacyClass.P2:
        return candidate.has_consent and candidate.redactor_passed
    return True  # P0, P1


def dataset_privacy_class(candidates: "list[DistillationCandidate]") -> PrivacyClass:
    """A dataset's class is the maximum class of any row in it."""
    if not candidates:
        raise ValueError("dataset_privacy_class: candidates must be non-empty")
    return max(c.privacy_class for c in candidates)


def build_dataset(
    candidates: "list[DistillationCandidate]",
    destination_privacy_ceiling: PrivacyClass,
) -> FrozenSet[str]:
    """
    Filters to eligible candidates, computes the resulting dataset's privacy
    class, and enforces the export-ceiling hard stop before returning the
    set of candidate ids that may be exported together.

    Raises HardStop if the destination's ceiling does not cover the dataset's
    resulting privacy class -- this must be checked at export time, not just
    per-candidate, because a dataset's class is the max over all its rows.
    """
    eligible = [c for c in candidates if candidate_is_eligible(c)]
    if not eligible:
        return frozenset()

    resulting_class = dataset_privacy_class(eligible)
    if not may_receive(destination_privacy_ceiling, resulting_class):
        raise HardStop(
            "distillation_export_exceeds_destination_ceiling",
            f"Dataset privacy class {resulting_class.name} exceeds destination "
            f"ceiling {destination_privacy_ceiling.name}; export refused.",
        )
    return frozenset(c.candidate_id for c in eligible)
