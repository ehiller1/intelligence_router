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

**MVP-0 in progress.** `ir_core` — the pure-library lattice types, the
eligibility resolver, and the distillation privacy gate — is built and
tested (38 tests, `pytest ir_core`). This is deliberately the first thing
built: no I/O, no infrastructure decisions, and every hard stop in the
autonomy ladder has an executable test before any service code exists.

Remaining MVP-0 work (needs infrastructure decisions — see
`docs/IMPLEMENTATION_PLAN.md` §8 "Decisions still open"):
- PostgreSQL migrations (schema is specified in `docs/IMPLEMENTATION_PLAN.md`
  and the Implementation Guide sent alongside this repo)
- Control plane API (signed governance-policy store, atomic promotion)
- JSON Schemas for the `ir.*` CloudEvents envelope

## Repo layout

```
ir_core/            pure library, no I/O — lattice types, eligibility,
                     resolution, lineage, distillation gating, TTL/posture
                     formulas. Everything else depends on this; this depends
                     on nothing else in the repo.
  types.py           GovernanceTier, PrivacyClass, Posture, LineageSet,
                     EligibilityBinding, tighten(), may_receive(), ttl_eff()
  resolution.py      class -> eligible set -> (override ->) selection
  distillation.py    privacy gating + export-ceiling hard stop for the
                     distillation flywheel (Adaptive FRD, out of MVP scope
                     but the gate belongs here so it exists before the
                     flywheel does)
  exceptions.py      HardStop — every blocked autonomy-ladder action raises
                     this with a stable `code`
  tests/             one property-test module (test_types.py) and one
                     hard-stop-per-requirement module (test_hard_stops.py)

docs/                the design documents this code implements
```

Planned, not yet built (see `docs/IMPLEMENTATION_PLAN.md` for the full
phase breakdown, MVP-1 through MVP-5, then the Adaptive track AD-1..6):

```
ir_controlplane/     signed governance-policy store, atomic promotion
ir_sidecar/          per-membrane resolver, governance lease, binding cache
ir_classifier/       ethical-load + privacy classifier, golden set, drift
ir_dispatch/         sole holder of model credentials; signs output stamps
ir_egress/           Publisher + Card/blackboard hooks; default-deny gate
ir_guider/           guider dispatch, deterministic signer, rule canaries
ir_attest/           attestation schema, verify lib, issuance CLI
ir_ledger/           hash-chained Decision Ledger
ir_posture/          integrity signals, suspicion score, posture, TTL
ir_registry/         dynamic membrane + Card-type registration
ir_conformance/      the attack-suite kit modules run in CI to certify
ir_console/          operator console, hold queue
```

## Running the tests

```bash
python3 -m venv .venv
./.venv/bin/pip install pytest hypothesis
./.venv/bin/python -m pytest -v
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
