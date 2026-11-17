# Intelligence Router

Governed, tiered model routing for the AOM substrate (Embark / iQueue). This
repo implements the requirements in `docs/FRD_MVP_v0.2_tracked.docx`
(`FR-IRG-*`) and, once released, the learning layer in
`docs/FRD_Adaptive_v1.1_tracked.docx` (`FR-IR-*`).

**Design documents (read these first):**
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — the decision log (§0), reconciliation of the two FRDs, phased build sequence
- [`docs/TRUST_ARCHITECTURE.md`](docs/TRUST_ARCHITECTURE.md) — threat model, the compliance-forcing interface, guider hardening, key custody, emergent posture/TTL
- `docs/FRD_MVP_v0.2_tracked.docx` — governed router requirements (`FR-IRG-*`), tracked changes from v0.1
- `docs/FRD_Adaptive_v1.1_tracked.docx` — learning-layer requirements (`FR-IR-*`), tracked changes from v1.0

## The one rule everything else follows from

**Governance precedes optimization.** The eligible model set for a request
is computed by governance code alone: reasoning class → effective governance
tier (after tightening) → privacy ceiling → attestation → lineage
compatibility. Nothing downstream — a cost optimizer, a learned selector, a
cached binding — can ever add to that set or relax it. Automated parameters
in the safety layer (posture, TTL, calibration thresholds) may only tighten
themselves; loosening is always a human act. See `docs/TRUST_ARCHITECTURE.md`
§1 for the three principles this is built from.

## Status

**MVP-0 complete, plus a minimal dispatch: 126/126 tests passing.**

**Privacy scale (decision R1a): P0 is the MOST sensitive class, P3 the least.** Earlier text and the FRD .docx files use the reverse (R1); see `docs/IMPLEMENTATION_PLAN.md`.

- `ir_dispatch` (minimal, ahead of MVP-1) — takes an `EligibilityBinding`,
  drops eligible models that have no `ServingEndpoint`, selects over the rest
  with the existing `apply_override` / lowest-cost rule, and makes one
  OpenAI-compatible `/v1/chat/completions` call with
  `model=<served_model_name>`. For distilled students that name is the LoRA
  adapter on a shared vLLM server, so several experts can share one
  deployment of their base model. Selection only ever runs over a subset of the
  binding. Not yet: stamp signing, emitting `ir.routing.bound` (the result
  returns its fields), retries/fallback, streaming.

- `ir_core` — pure-library lattice types, the eligibility resolver, and the
  distillation privacy gate. No I/O, no infrastructure decisions. Every
  hard stop in the autonomy ladder has an executable test.
- `schemas/` — JSON Schemas for every `ir.*` CloudEvents event, closing the
  MVP FRD's payload-schema `[ORCHESTRATOR-GAP]`. Tests confirm each schema
  is well-formed and reject the specific invalid cases the FRDs call out by
  name (a `routing.requested` payload with a smuggled `model` field, an
  event missing `env`, a posture loosen from `restricted` with no approver,
  etc.).
- `ir_controlplane/` — the signed governance-policy store: Ed25519
  signing/verification, atomic promotion (verified under real concurrent
  load with `ThreadPoolExecutor`, not just a unit test), and a thin FastAPI
  HTTP layer. SQL migrations are hand-verified against `ir_core.types`
  (every enum-shaped `CHECK` constraint is tested to match the Python
  lattice types exactly) but **not yet run against a live Postgres** — see
  `ir_controlplane/migrations/README.md` for why (this sandbox cannot run
  Postgres at all: it needs a `shmget` syscall the sandbox blocks
  unconditionally, even in `shared_memory_type=mmap` mode).

**A real concurrency bug was found and fixed during this build**, not
hypothesized: an initial `is_active` implementation stored it as an
independent flag flipped in two writes (deactivate old, activate new) under
a per-domain lock. The writes were correctly serialized, but an
unsynchronized reader scanning many versions could see a stale "true" left
from before a deactivation alongside a fresh "true" from after a different
activation — an apparent two-active-versions state that never actually
existed at any single instant. Fixed by making `is_active` a derived fact
read fresh from one atomic pointer (`ir_controlplane/store.py`'s class
docstring has the full account, including the Postgres-equivalent lesson:
promotion must be one `UPDATE` statement per domain, not two).

**Not yet built** (see `docs/IMPLEMENTATION_PLAN.md` for MVP-1 through
MVP-5, then the Adaptive track): the resolution engine's live service
wrapper (the logic exists in `ir_core.resolution`; MVP-1 wires it to real
model registry data and event handling), the classifier, the sidecar, the
guider service, the dispatch plane, the egress gate, and everything after.

## Repo layout

```
ir_core/             pure library, no I/O — lattice types, eligibility,
                      resolution, lineage, distillation gating, TTL/posture
                      formulas. Everything else depends on this; this
                      depends on nothing else in the repo.
  types.py            GovernanceTier, PrivacyClass, Posture, LineageSet,
                      EligibilityBinding, tighten(), may_receive(), ttl_eff()
  resolution.py       class -> eligible set -> (override ->) selection;
                      ModelRecord, ServingEndpoint (where a model answers)
  distillation.py     privacy gating + export-ceiling hard stop for the
                      distillation flywheel
  exceptions.py       HardStop — every blocked autonomy-ladder action
                      raises this with a stable `code`
  tests/              property tests (test_types.py) + one test per hard
                      stop (test_hard_stops.py) — 38 tests

schemas/              JSON Schema (Draft 2020-12) for the CloudEvents
                      envelope and every ir.* event payload
  envelope.schema.json           mandatory `env`, sim requires `run_id`
  events/*.schema.json           one file per event type (or shared, for
                                  the 14 ir.integrity.* signals)
  registry.py                    event type -> schema file lookup
  tests/test_schemas.py          well-formed + accepts/rejects the specific
                                  cases the FRDs call out — 29 tests

ir_dispatch/          minimal dispatch plane (see Status)
  dispatch.py          Dispatcher: binding -> servable subset -> selection
                       -> POST /v1/chat/completions; DispatchError codes
  tests/               selection never leaves the binding, overrides,
                       credentials only over https, endpoint failures, the
                       ir.routing.bound payload, and a real-HTTP fake vLLM
                       with two LoRA experts on one server

ir_controlplane/      signed governance-policy store + HTTP API
  signing.py           Ed25519 sign/verify (HSM integration point — see
                       the module docstring for what NOT to do in prod)
  store.py             PolicyStore interface + InMemoryPolicyStore
                       (atomic promotion via one lock per domain)
  service.py           GovernanceControlPlane — ties signing + store +
                       HardStop together; emits the promoted-event payload
  app.py               thin FastAPI wrapper; stateless, replica-safe
  migrations/           numbered SQL DDL (hand-verified, not yet run
                       against live Postgres — see migrations/README.md)
  tests/               signing round-trips, promotion incl. forged-
                       signature refusal, HTTP marshalling, migration/
                       ir_core.types consistency, and real-thread
                       concurrency (ThreadPoolExecutor, 50 workers,
                       20 repeated runs) — 39 tests

docs/                 the design documents this code implements
```

Planned, not yet built (see `docs/IMPLEMENTATION_PLAN.md` for the full
phase breakdown, MVP-1 through MVP-5, then the Adaptive track AD-1..6):

```
ir_sidecar/          per-membrane resolver, governance lease, binding cache
ir_classifier/       ethical-load + privacy classifier, golden set, drift
ir_dispatch/         (minimal version exists) stamp signing, retries, streaming
ir_egress/           Publisher + Card/blackboard hooks; default-deny gate
ir_guider/           guider dispatch, deterministic signer, rule canaries
ir_attest/           attestation schema, verify lib, issuance CLI
ir_ledger/           hash-chained Decision Ledger writer
ir_posture/          integrity signals, suspicion score, posture, TTL
ir_registry/         dynamic membrane + Card-type registration
ir_conformance/      the attack-suite kit modules run in CI to certify
ir_console/          operator console, hold queue
```

## Running the tests

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m pytest -v   # 126 tests
```

If pip's TLS handshake fails behind a corporate/sandboxed proxy with an
`OSStatus -26276` error despite `curl` working fine, that's pip's vendored
bundle failing to negotiate through the proxy's TLS termination — not a
real certificate problem. Work around it for the already-allowlisted PyPI
hosts:

```bash
./.venv/bin/pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org pytest hypothesis
```

## What "done" means for `ir_core`

Every hard stop in the MVP autonomy ladder (`docs/FRD_MVP_v0.2_tracked.docx`
§5.13) and the patched Adaptive autonomy ladder (§5.10) has a test in
`ir_core/tests/test_hard_stops.py` that raises `HardStop` with a stable
`.code`. That file's docstring is the checklist. If you add a governance
rule, add its test there before wiring it into a service.
