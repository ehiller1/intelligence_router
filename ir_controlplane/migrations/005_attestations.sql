-- FR-IRG-ATT-02: binds a model id, lineage set, conformance-report
-- reference, and validity window. Issued by the Attestation Officer
-- (FR-IRG-KEY-03) -- a different human than the Router Steward.

CREATE TABLE ir_attestations (
    attestation_id               TEXT PRIMARY KEY,
    model_id                     TEXT NOT NULL REFERENCES ir_model_registry (model_id),
    lineage_set                  JSONB NOT NULL,
    conformance_report_ref       TEXT NOT NULL,
    validity_start                TIMESTAMPTZ NOT NULL DEFAULT now(),
    validity_end                  TIMESTAMPTZ NOT NULL,
    issued_by                    TEXT NOT NULL,
        -- FR-IRG-KEY-03: must differ from the model's onboarding Steward.
        -- Enforced in the application layer against the role registry, not
        -- expressible as a SQL constraint here.
    second_approver               TEXT,
        -- FR-IRG-KEY-03: required for normative/guider-tier attestations.
    signature                    TEXT NOT NULL,
    withdrawn_at                 TIMESTAMPTZ,
    withdrawn_reason              TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    version                      INTEGER NOT NULL DEFAULT 1
);

ALTER TABLE ir_model_registry
    ADD CONSTRAINT fk_ir_model_registry_attestation
    FOREIGN KEY (attestation_id) REFERENCES ir_attestations (attestation_id);

CREATE INDEX ix_ir_attestations_model_validity ON ir_attestations (model_id, validity_end);
CREATE INDEX ix_ir_attestations_withdrawn ON ir_attestations (withdrawn_at) WHERE withdrawn_at IS NOT NULL;
