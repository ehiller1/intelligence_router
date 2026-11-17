-- FR-IRG-FND-02: single source of truth the resolution engine, Redactor,
-- and attestation verifier all read. lineage_set and teacher_model_ids are
-- JSONB arrays of strings (decision D6: lineage is a transitive SET, not an
-- id -- see ir_core.types.LineageSet).

CREATE TABLE ir_model_registry (
    model_id                    TEXT PRIMARY KEY,
    family                      TEXT NOT NULL,
    model_version                TEXT NOT NULL,
    deployment_endpoint         TEXT NOT NULL,
    capability_tier             TEXT NOT NULL
        CHECK (capability_tier IN ('lightweight', 'mid_tier', 'heavyweight', 'specialized')),
    context_window              INTEGER,
    cost_per_1k_input_tokens    NUMERIC(12, 6) NOT NULL,
    cost_per_1k_output_tokens   NUMERIC(12, 6) NOT NULL,
    p50_latency_ms              INTEGER,
    p95_latency_ms              INTEGER,
    supported_classes           JSONB NOT NULL DEFAULT '[]'::JSONB,
    privacy_ceiling             TEXT NOT NULL
        CHECK (privacy_ceiling IN ('P0', 'P1', 'P2', 'P3')),
        -- decision R1a: P0 MOST sensitive .. P3 least sensitive (R1 had the reverse). This column
        -- must only ever be compared through the application-layer
        -- may_receive() equivalent -- never `privacy_ceiling <= 'P2'` in raw
        -- SQL: lexical order is the REVERSE of sensitivity here.
    lineage_base_family         TEXT NOT NULL,
    lineage_set                 JSONB NOT NULL DEFAULT '[]'::JSONB,
    teacher_model_ids           JSONB NOT NULL DEFAULT '[]'::JSONB,
    lifecycle_state             TEXT NOT NULL DEFAULT 'candidate'
        CHECK (lifecycle_state IN ('candidate', 'sim_qualified', 'shadow', 'active', 'deprecated', 'retired')),
        -- Adaptive FRD §3.2. MVP-0 only ever writes 'candidate' / 'active';
        -- the intermediate states are Adaptive-track (AD-2/AD-5).
    is_attested                 BOOLEAN NOT NULL DEFAULT FALSE,
    attestation_id              TEXT,  -- FK added in 008_attestations.sql
    training_dataset_version    TEXT,
    qualifying_sim_run_id       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by                  TEXT NOT NULL,
    version                     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX ix_ir_model_registry_lifecycle_state ON ir_model_registry (lifecycle_state);
CREATE INDEX ix_ir_model_registry_privacy_ceiling ON ir_model_registry (privacy_ceiling);

COMMENT ON COLUMN ir_model_registry.lineage_set IS
    'Transitive lineage (decision D6): base family + every teacher at any depth + any model this model was trained on the outputs of. Populated by the application from ir_core.types.LineageSet, never edited directly.';
