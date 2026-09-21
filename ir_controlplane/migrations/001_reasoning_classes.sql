-- FR-IRG-FND-01, decision R7: shared registry with the Adaptive FRD's task
-- class taxonomy. A reasoning class = a task class + governance attributes.
-- Governance attributes attach here, at class level, ONLY -- never at a
-- finer routing key (decision R7).

CREATE TABLE ir_reasoning_classes (
    name                        TEXT PRIMARY KEY,
    default_governance_tier     TEXT NOT NULL
        CHECK (default_governance_tier IN ('commodity', 'normative', 'guider')),
    default_capability_tier     TEXT
        CHECK (default_capability_tier IN ('lightweight', 'mid_tier', 'heavyweight', 'specialized')),
    eligible_model_ids          JSONB NOT NULL DEFAULT '[]'::JSONB,
    structural_input            BOOLEAN NOT NULL DEFAULT FALSE,
        -- decision D2/D3: may skip the model-based classifier and use the
        -- deterministic rules floor only. Set by signed governance policy,
        -- never by engineering default.
    cascade_eligible            BOOLEAN NOT NULL DEFAULT FALSE,
        -- Adaptive FR-IR-FND-04: latency-critical classes route directly.
    latency_target_ms           INTEGER,
    attestation_required        BOOLEAN NOT NULL DEFAULT TRUE,
        -- FR-IRG-ATT-01: false only for commodity-only classes.
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by                  TEXT NOT NULL,
    version                     INTEGER NOT NULL DEFAULT 1
);

COMMENT ON TABLE ir_reasoning_classes IS
    'Shared class registry (MVP FRD FR-IRG-FND-01 / Adaptive FRD FR-IR-FND-01, decision R7). Governance attributes attach here only.';
