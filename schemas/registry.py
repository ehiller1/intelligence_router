"""
Maps a CloudEvents `type` to its data-payload schema file. This is the
single lookup table both the mesh consumers and the test suite use, so
adding an event type means editing exactly one place.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMAS_DIR = Path(__file__).parent
EVENTS_DIR = SCHEMAS_DIR / "events"

EVENT_TYPE_TO_SCHEMA_FILE = {
    "ir.routing.requested": "routing_requested.schema.json",
    "ir.routing.bound": "routing_bound.schema.json",
    "ir.routing.tier.tightened": "routing_tier_tightened.schema.json",
    "ir.routing.outcome.observed": "routing_outcome_observed.schema.json",
    "ir.guider.hold": "guider_hold.schema.json",
    "ir.attestation.failed": "attestation_failed.schema.json",
    "ir.classifier.drift": "classifier_drift.schema.json",
    "ir.governance.policy.promoted": "governance_policy_promoted.schema.json",
    "ir.partition.entered": "partition.schema.json",
    "ir.partition.cleared": "partition.schema.json",
    "ir.posture.changed": "posture_changed.schema.json",
    # All 14 ir.integrity.* signal types share one payload schema, keyed by
    # signal_type inside the payload (Trust Architecture §6.1).
    "ir.integrity.stamp_missing": "integrity_signal.schema.json",
    "ir.integrity.stamp_invalid": "integrity_signal.schema.json",
    "ir.integrity.verdict_replay": "integrity_signal.schema.json",
    "ir.integrity.ingress_egress_divergence": "integrity_signal.schema.json",
    "ir.integrity.fragmentation_suspected": "integrity_signal.schema.json",
    "ir.integrity.class_content_mismatch": "integrity_signal.schema.json",
    "ir.integrity.probe_suspected": "integrity_signal.schema.json",
    "ir.integrity.resubmit_after_hold": "integrity_signal.schema.json",
    "ir.integrity.perturbation_mislabel": "integrity_signal.schema.json",
    "ir.integrity.override_refused": "integrity_signal.schema.json",
    "ir.integrity.manifest_violation": "integrity_signal.schema.json",
    "ir.integrity.direct_endpoint_attempt": "integrity_signal.schema.json",
    "ir.integrity.mesh_acl_denied": "integrity_signal.schema.json",
    "ir.integrity.guider_injection_suspected": "integrity_signal.schema.json",
}


def load_envelope_schema() -> dict:
    return json.loads((SCHEMAS_DIR / "envelope.schema.json").read_text())


def load_data_schema(event_type: str) -> dict:
    filename = EVENT_TYPE_TO_SCHEMA_FILE.get(event_type)
    if filename is None:
        raise KeyError(f"No schema registered for event type '{event_type}'")
    return json.loads((EVENTS_DIR / filename).read_text())


def all_schema_files() -> "list[Path]":
    return [SCHEMAS_DIR / "envelope.schema.json"] + sorted(EVENTS_DIR.glob("*.schema.json"))
