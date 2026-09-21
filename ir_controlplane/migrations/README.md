# Migrations

Plain, numbered SQL files (no ORM/Alembic dependency yet — add one when the
control plane's real Postgres-backed repository implementation lands; the
in-memory implementation used for MVP-0 testing does not need it).

Apply in order against Postgres 15+:

```bash
for f in ir_controlplane/migrations/0*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

**Not yet verified against a live Postgres instance.** The sandboxed
environment this was authored in blocks the `shmget` syscall Postgres needs
for its shared-memory segment (`initdb` fails with "could not create shared
memory segment: Operation not permitted" regardless of `shared_memory_type`),
so these files have been reviewed by hand against the schema in
`docs/IMPLEMENTATION_PLAN.md` §4 but not executed. **Run them against a real
Postgres 15+ before relying on them** — that's ordinary CI work, not a design
gap.

## Design notes carried over from the decision log

- Every table that participates in optimistic locking carries a `version`
  integer column, incremented by the application on every update
  (decision: MVP FRD FR-IRG-STT-01/02).
- `ir_routing_decisions` is the wide record built in MVP-0 as the superset
  the Adaptive FRD needs (decision D7) — Adaptive-only columns are nullable.
- `ledger_entry_id` and `digest_batch_id` on `ir_routing_decisions` are
  mutually exclusive and exactly one must be set for a decision that has
  left the "pending ledger write" state (decision R6).
- Enum-shaped columns (`governance_tier`, `privacy_class`, `posture`, …) use
  `CHECK` constraints rather than native Postgres `ENUM` types, so adding a
  value is a migration that doesn't require `ALTER TYPE ... ADD VALUE`
  (which cannot run inside a transaction on older Postgres and complicates
  rollback). The check-constraint values must stay in lockstep with
  `ir_core.types` — see `ir_controlplane/tests/test_migrations_match_core_types.py`.
