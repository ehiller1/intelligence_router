-- FR-IRG-AUD-01/02, decision R6: tamper-evident, hash-chained ledger.
-- entry_hash commits to previous_entry_hash, so altering any historical row
-- breaks every subsequent hash -- detectable without needing to compare
-- against an external copy (though FR-IRG-KEY-05 also anchors periodic
-- heads to write-once storage in a separate account for that stronger
-- guarantee).
--
-- Coverage per decision R6: governed tiers, tightened tasks, overrides and
-- refusals, holds, attestation failures, and any principal not at normal
-- posture -- 100%, never sampled. Untightened commodity decisions from a
-- normal-posture principal may be sampled (rate in governance policy); the
-- ones NOT individually ledgered are instead covered by a periodic digest
-- batch (ir_ledger_digest_batches, below) so nothing is unprotected.

CREATE TABLE ir_ledger_entries (
    entry_id                     TEXT PRIMARY KEY,
    decision_id_hash              TEXT NOT NULL,
        -- hash of the decision_id + a content commitment, not the
        -- decision_id in the clear, so the ledger itself carries no
        -- queryable link back to task content (FR-IRG-STT-03 applies here
        -- too: the ledger is provenance, not a content store).
    previous_entry_hash           TEXT,
        -- NULL only for the very first entry in a domain's chain.
    entry_hash                    TEXT NOT NULL,
        -- entry_hash = H(previous_entry_hash || decision_id_hash || payload || timestamp)
        -- computed by the application; this migration only stores it.
    payload                       JSONB NOT NULL,
        -- Provenance per FR-IRG-AUD-01: actor, class, both/all three
        -- policy versions, chosen model, governance tier, signals, outcome.
    signature                     TEXT NOT NULL,
    occurred_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_ir_ledger_entries_time ON ir_ledger_entries (occurred_at);
CREATE UNIQUE INDEX ux_ir_ledger_entries_chain ON ir_ledger_entries (entry_hash);

ALTER TABLE ir_routing_decisions
    ADD CONSTRAINT fk_ir_routing_decisions_ledger
    FOREIGN KEY (ledger_entry_id) REFERENCES ir_ledger_entries (entry_id);

-- Periodic digest covering sampled-out commodity decisions (decision R6).
-- The batch's own digest_hash is what gets a single ir_ledger_entries row
-- written for it -- so every decision is EITHER individually ledgered OR
-- covered by exactly one digest batch that IS ledgered. Nothing falls
-- through both.
CREATE TABLE ir_ledger_digest_batches (
    digest_batch_id                TEXT PRIMARY KEY,
    window_start                    TIMESTAMPTZ NOT NULL,
    window_end                      TIMESTAMPTZ NOT NULL,
    decision_count                  INTEGER NOT NULL,
    digest_hash                     TEXT NOT NULL,
        -- Merkle root or simple ordered hash of the covered decisions'
        -- content_hash values -- application's choice; either detects
        -- after-the-fact tampering with any covered row.
    ledger_entry_id                 TEXT NOT NULL REFERENCES ir_ledger_entries (entry_id),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ir_routing_decisions
    ADD CONSTRAINT fk_ir_routing_decisions_digest
    FOREIGN KEY (digest_batch_id) REFERENCES ir_ledger_digest_batches (digest_batch_id);
