-- Two Adaptive-track tables, created in MVP-0 (empty) for schema
-- compatibility (decision D7) so the Adaptive track needs no migration when
-- it lands. Every ir_routing_decisions row references both by version id
-- (nullable until AD-4 / MVP-2's calibration state respectively).

-- FR-IR-LRN-08: the learned selection policy. Distinct from governance
-- policy (decision R3). Not written to until AD-4.
CREATE TABLE ir_selection_policy_versions (
    version_id                  TEXT PRIMARY KEY,
    routing_key                 TEXT NOT NULL,
    governance_policy_version   TEXT NOT NULL REFERENCES ir_governance_policy_versions (version_id),
        -- decision R3: every selection policy records the governance
        -- policy it was learned under. A governance promotion that removes
        -- a champion from the eligible set invalidates the affected
        -- selection policy (application-enforced, not a DB constraint).
    posteriors                  JSONB NOT NULL,
    lambda_value                NUMERIC(6, 4),
    exploration_budget          NUMERIC(5, 4),
    origin                      TEXT NOT NULL DEFAULT 'production'
        CHECK (origin IN ('production', 'sim')),
    sim_run_id                  TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active                   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX ix_ir_selection_policy_routing_key ON ir_selection_policy_versions (routing_key, created_at);

-- FR-IRG-CLS-08: tighten-only calibration state (classifier thresholds),
-- inside the band set by the active governance policy. Not written to
-- until MVP-2.
CREATE TABLE ir_calibration_state_versions (
    version_id                  TEXT PRIMARY KEY,
    domain_id                   TEXT NOT NULL,
    reasoning_class             TEXT NOT NULL REFERENCES ir_reasoning_classes (name),
    governance_policy_version   TEXT NOT NULL REFERENCES ir_governance_policy_versions (version_id),
    thresholds                  JSONB NOT NULL,
    triggering_evidence_refs    JSONB NOT NULL DEFAULT '[]'::JSONB,
    direction                   TEXT NOT NULL CHECK (direction IN ('tighten', 'loosen')),
    approved_by                 TEXT,
        -- NULL for an automated tighten; required for a loosen
        -- (decision: the ratchet, Trust Architecture §1/§6.4).
    signature                   TEXT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active                   BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT ck_calibration_loosen_requires_approval
        CHECK (direction = 'tighten' OR approved_by IS NOT NULL)
);

CREATE INDEX ix_ir_calibration_state_class ON ir_calibration_state_versions (domain_id, reasoning_class, created_at);
