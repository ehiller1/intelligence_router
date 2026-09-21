-- FR-IRG-UI-03, decision D7: guider verdicts and human hold resolutions,
-- joined to a decision. Created empty in MVP-0; written to from MVP-4.

CREATE TABLE ir_outcome_events (
    outcome_event_id              TEXT PRIMARY KEY,
    decision_id                   TEXT NOT NULL REFERENCES ir_routing_decisions (decision_id),
    signal_type                   TEXT NOT NULL CHECK (signal_type IN ('guider', 'human')),
    verdict                       TEXT NOT NULL
        CHECK (verdict IN ('pass', 'fail', 'unavailable', 'uncertain', 'approve', 'edit', 'reject')),
    score                         NUMERIC(5, 4),
    latency_ms                    INTEGER,
    label                         TEXT
        CHECK (label IN ('confirmed_workaround', 'benign_defect', 'false_signal', NULL)),
    occurred_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_ir_outcome_events_decision ON ir_outcome_events (decision_id);
CREATE INDEX ix_ir_outcome_events_time ON ir_outcome_events (occurred_at);
