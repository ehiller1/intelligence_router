-- The wide decision record (decision D7): built as the Adaptive FRD's
-- superset from MVP-0 so that track needs no migration when it lands.
-- Adaptive-only columns (exploration_flag, predicted_quality, env, hop_chain
-- beyond one element) are nullable or constant through the MVP.
--
-- Append-only (FR-IRG-STT-01): the application must never UPDATE a row
-- here except to attach ledger_entry_id / digest_batch_id / outcome_event_id
-- after the fact -- and even those are write-once (see the trigger below).

CREATE TABLE ir_routing_decisions (
    decision_id                  TEXT PRIMARY KEY,
    routing_key                  TEXT NOT NULL,
    reasoning_class               TEXT NOT NULL REFERENCES ir_reasoning_classes (name),
    eligible_model_ids            JSONB NOT NULL,
    selected_model_id             TEXT NOT NULL,
    governance_tier               TEXT NOT NULL
        CHECK (governance_tier IN ('commodity', 'normative', 'guider')),
    privacy_class                 TEXT NOT NULL
        CHECK (privacy_class IN ('P0', 'P1', 'P2', 'P3')),
    effective_posture             TEXT NOT NULL DEFAULT 'normal'
        CHECK (effective_posture IN ('normal', 'watch', 'restricted', 'quarantined')),
    governance_policy_version     TEXT NOT NULL REFERENCES ir_governance_policy_versions (version_id),
    selection_policy_version      TEXT REFERENCES ir_selection_policy_versions (version_id),
    calibration_state_version     TEXT REFERENCES ir_calibration_state_versions (version_id),
    classifier_grade              TEXT,
    classifier_confidence         NUMERIC(5, 4),
    override_source                TEXT CHECK (override_source IN ('admin', 'template', NULL)),
    override_refused_reason        TEXT,
    exploration_flag               BOOLEAN NOT NULL DEFAULT FALSE,
        -- Adaptive-only (FR-IR-LRN-03); always FALSE through the MVP.
    predicted_cost                 NUMERIC(12, 6),
    predicted_quality              NUMERIC(5, 4),
        -- Adaptive-only; NULL through the MVP (no learned posterior yet).
    hop_chain                     JSONB NOT NULL DEFAULT '[]'::JSONB,
        -- Single element through the MVP (no cascade until AD-3).
    env                            TEXT NOT NULL DEFAULT 'prod'
        CHECK (env IN ('prod', 'shadow', 'sim')),
    run_id                         TEXT,  -- required when env='sim'; see CHECK below
    content_hash                   TEXT,
    event_refs                     JSONB NOT NULL DEFAULT '[]'::JSONB,
        -- decision: content is never persisted here (FR-IRG-STT-03) --
        -- only hashes and mesh event references.
    ledger_entry_id                TEXT,
    digest_batch_id                TEXT,
    outcome_event_id               TEXT,
    actor_identity                 TEXT NOT NULL,
        -- workload identity of the calling agent, from the mTLS
        -- certificate -- never a payload field (Trust Architecture §3.1).
    occurred_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    version                        INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT ck_sim_requires_run_id
        CHECK (env != 'sim' OR run_id IS NOT NULL),
    CONSTRAINT ck_ledger_xor_digest
        CHECK (
            (ledger_entry_id IS NOT NULL AND digest_batch_id IS NULL)
            OR (ledger_entry_id IS NULL AND digest_batch_id IS NOT NULL)
            OR (ledger_entry_id IS NULL AND digest_batch_id IS NULL)
            -- both NULL = pending ledger write; enforced non-NULL-forever
            -- by the application's ledger-writer consumer, not by this
            -- constraint (a DB-level "must eventually be set" isn't
            -- expressible as a CHECK).
        )
);

CREATE INDEX ix_ir_routing_decisions_key_time ON ir_routing_decisions (routing_key, occurred_at);
CREATE INDEX ix_ir_routing_decisions_model_time ON ir_routing_decisions (selected_model_id, occurred_at);
CREATE INDEX ix_ir_routing_decisions_policy ON ir_routing_decisions (governance_policy_version);
CREATE INDEX ix_ir_routing_decisions_tier ON ir_routing_decisions (governance_tier);
CREATE INDEX ix_ir_routing_decisions_privacy ON ir_routing_decisions (privacy_class);
CREATE INDEX ix_ir_routing_decisions_actor ON ir_routing_decisions (actor_identity, occurred_at);
CREATE INDEX ix_ir_routing_decisions_env_run ON ir_routing_decisions (env, run_id) WHERE env = 'sim';
