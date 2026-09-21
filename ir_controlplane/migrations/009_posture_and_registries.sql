-- FR-IRG-INT-05, decision D10: per-principal posture. One current row per
-- principal (optimistic lock via version); every change is separately
-- ledgered via ir_posture_history (append-only), matching "every change
-- ledgered" from the Trust Architecture.

CREATE TABLE ir_posture (
    principal                     TEXT PRIMARY KEY,
        -- workload identity: an agent, or (at a discount) an agent team or
        -- module -- see Trust Architecture §6.1 on rollup.
    score                          NUMERIC(10, 4) NOT NULL DEFAULT 0,
    posture                        TEXT NOT NULL DEFAULT 'normal'
        CHECK (posture IN ('normal', 'watch', 'restricted', 'quarantined')),
    decay_rate                     NUMERIC(10, 6) NOT NULL,
        -- halves on relapse (Trust Architecture §6.4); starts at the
        -- governance-policy default.
    effective_ttl_seconds          NUMERIC(10, 2),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    version                        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE ir_posture_history (
    history_id                     TEXT PRIMARY KEY,
    principal                      TEXT NOT NULL,
    from_posture                   TEXT NOT NULL,
    to_posture                     TEXT NOT NULL,
    direction                      TEXT NOT NULL CHECK (direction IN ('tighten', 'loosen')),
    score                          NUMERIC(10, 4) NOT NULL,
    contributing_signal_types      JSONB NOT NULL DEFAULT '[]'::JSONB,
    approved_by                    TEXT,
    occurred_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_posture_history_loosen_from_restricted_needs_approval
        CHECK (
            direction = 'tighten'
            OR from_posture NOT IN ('restricted', 'quarantined')
            OR approved_by IS NOT NULL
        )
);

CREATE INDEX ix_ir_posture_history_principal ON ir_posture_history (principal, occurred_at);

-- FR-IRG-MBR-05 / STT-04, decision D13: dynamic membrane and Card-type
-- registries. New entries from an unknown workload auto-register in
-- 'provisional' status at watch posture with a normative floor
-- (application-enforced); a human or manifest update confirms them.

CREATE TABLE ir_membrane_registrations (
    membrane_id                    TEXT PRIMARY KEY,
    owner_principal                 TEXT NOT NULL,
    manifest_ref                    TEXT,
    trust_domain                    TEXT NOT NULL,
    status                          TEXT NOT NULL DEFAULT 'provisional'
        CHECK (status IN ('provisional', 'confirmed')),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    version                         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE ir_card_type_registrations (
    card_type                       TEXT NOT NULL,
    field_name                      TEXT NOT NULL,
    owner_principal                  TEXT NOT NULL,
    model_content                    BOOLEAN NOT NULL DEFAULT FALSE,
    status                           TEXT NOT NULL DEFAULT 'provisional'
        CHECK (status IN ('provisional', 'confirmed')),
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    version                          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (card_type, field_name)
);

CREATE INDEX ix_ir_card_type_model_content
    ON ir_card_type_registrations (card_type)
    WHERE model_content;
