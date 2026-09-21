-- FR-IRG-CTL-01, decision R3: the SIGNED, human-promoted governance policy.
-- Distinct from ir_selection_policy_versions (004) -- the learned selector's
-- policy. Exactly one row per domain has is_active = TRUE at any time;
-- enforced by the partial unique index below, not by application code alone.

CREATE TABLE ir_governance_policy_versions (
    version_id                  TEXT PRIMARY KEY,
    domain_id                   TEXT NOT NULL,
    classes                     JSONB NOT NULL,
    pool_membership             JSONB NOT NULL,
    tiering                     JSONB NOT NULL,
    tightening_map              JSONB NOT NULL,
        -- FR-IRG-CLS-03, renamed from "escalation map" per decision R4.
    attestation_rules           JSONB NOT NULL,
    bands                       JSONB NOT NULL,
        -- Trust Architecture §6/§7: TTL_base, TTL_floor, h, posture
        -- thresholds, initial signal weights, governance-lease interval,
        -- audit-sample floor. Bounds only -- operating values are emergent
        -- and live in ir_calibration_state_versions / the posture engine.
    ledger_sampling_rate        NUMERIC(5, 4) NOT NULL DEFAULT 1.0000
        CHECK (ledger_sampling_rate >= 0 AND ledger_sampling_rate <= 1),
        -- decision R6: applies to untightened commodity decisions only.
        -- 1.0 throughout the MVP; may be lowered from the Adaptive track.
    verification_trust_bundle   JSONB NOT NULL,
        -- Public keys for offline signature verification (Trust
        -- Architecture §4.4: "gates verify signatures without calling
        -- anyone").
    signature                   TEXT NOT NULL,
    is_active                   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_at                 TIMESTAMPTZ,
    promoted_by                 TEXT
        -- The Domain Authority's identity (FR-IRG-KEY-01).
);

-- At most one active governance policy per domain at any time. This is the
-- database-level half of "atomic promotion" (FR-IRG-CTL-04) -- the
-- application still does insert-then-flip in one transaction, but this
-- index makes a second concurrent "active" row impossible even under a bug.
CREATE UNIQUE INDEX ux_ir_governance_policy_one_active_per_domain
    ON ir_governance_policy_versions (domain_id)
    WHERE is_active;

CREATE INDEX ix_ir_governance_policy_domain_created
    ON ir_governance_policy_versions (domain_id, created_at);
