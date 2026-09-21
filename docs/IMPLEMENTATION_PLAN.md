# Intelligence Router — Implementation Plan

**Sources:** *Intelligence Router — MVP FRD* v0.1 (Sep 2026) and *Adaptive Intelligence Router FRD* v1.0 (Jul 15 2026)
**Plan date:** 2026-09-20 · **Status:** Reconciliation decided (see §0); ready for engineering review

**ID convention used here.** Both FRDs use the `FR-IR-*` prefix with colliding numbers, so this plan writes **`M:`** for MVP-FRD requirements (e.g. `M:RTR-03`; these become `FR-IRG-*` per decision R2) and **`A:`** for Adaptive-FRD requirements (e.g. `A:LRN-07`). Build phases are **MVP-0…MVP-5** (governed router) and **AD-1…AD-6** (adaptive track; the Adaptive FRD calls these P1–P6, renamed here because "P1" also means a privacy class).

---

## 0. Decision log

| # | Item | Decision (2026-09-20, Eric) | Follow-on edits |
|---|---|---|---|
| R1 | Privacy scale direction | **P3 = most sensitive, P0 = least** (MVP FRD direction). Code uses a named enum + single `may_receive(model_ceiling, data_class)` function; raw P-numbers are never compared. | Patch Adaptive FRD by mapping old→new P0→P3, P1→P2, P2→P1, P3→P0: §3.4 (telemetry = P1; distillation candidates = P0/P1, or P2 with consent + Redactor pass; **P3 excluded absolutely**), §5.10 hard stops, `A:DST-01`, acceptance step 11. **New rule:** a distillation dataset carries the max privacy class of its rows and may only be exported to a training destination whose ceiling covers it. |
| R3 | Two meanings of "policy" | **Two entities.** *Governance policy* (`ir_governance_policy_versions`, signed, Domain Authority, `ir.governance.policy.promoted`) and *selection policy* (`ir_selection_policy_versions`, learned, Steward, `ir.routing.policy.*`). Every binding/decision records both version ids; each selection version records the governance version it was learned under. Only governance promotion revokes cached bindings; a governance promotion that removes a champion from the eligible set invalidates the affected selection policy. | MVP FRD: rename "policy" → "governance policy" in §2.1, §4 (`policy.promoted`), §5.6, §6 Policy Card. Adaptive FRD: rename "policy version" → "selection policy version" in §3.3 (`ir_policy_versions`), §4, `A:LRN-08`, glossary. |
| R2 | `FR-IR-*` numbering collision | **MVP FRD re-prefixed to `FR-IRG-*`** (layer codes unchanged, e.g. `FR-IRG-FND-01`). Adaptive FRD IDs untouched. In this plan `M:X` ≡ `FR-IRG-X`, `A:X` ≡ `FR-IR-X`. | MVP FRD: header "Domain / prefix", all of §5, §10, §12, §13, change log. Cross-references from the Adaptive FRD to MVP requirements use the new prefix. |
| R4 | "Tier" ×3, "escalation" ×3 | **Vocabulary fixed:** `governance_tier` (commodity/normative/guider), `capability_tier` (lightweight…specialized), `authority_tier` (T0–T3). Raising governance tier = **tighten** (`ir.routing.tier.tightened`, replaces `route.escalated`). **"Escalation" means only a cascade hop** up the capability ladder (`ir.routing.escalation.triggered`, `maxEscalations`, escalation-rate KPI — all unchanged). Handing to a human = **hold** (`ir.guider.hold`, outcome `human_handoff`). | MVP FRD: §4 event rename; replace "escalate" with "tighten" (and "escalation map/rules" with "tightening map/rules") in UC-2, §5.6 `CTL-01`, §6 Policy Card, `CLS-03/04`, `RTR-03`, autonomy ladder, acceptance step 2; replace "escalates to a human" with "holds for a human" in UC-3, `GDR-04`. MVP console KPI is "tightening rate", not "escalation rate". Adaptive FRD: qualify "tier" as capability/authority tier in §3.1, §5.10. |
| R5 | Model overrides | **Override = preference within the eligible set, never around it.** Eligible set computed first (class → effective governance tier → privacy ceiling → attestation → lineage). Named model in set → used, `override_source` recorded, excluded from exploration. Not in set → **pin dropped, task routes normally, `override_refused` ledgered and surfaced to the pin's owner.** Sources limited to `template` and `admin` (T2, logged); runtime agents reference classes only. Guider class accepts no overrides. MVP ships `admin` only; template pins arrive in AD-3. | Adaptive FRD `FND-03`: precedence becomes *governance eligibility (tier, privacy, attestation, lineage) → override if eligible → selection policy → static default*. `EVI-01`: add "honoured only if eligible for the effective tier". `NBA-03`: repeated `override_refused` is a second trigger for pin-removal recommendations. MVP FRD `FND-04`: name the two permitted sources. New event field: `override_refused_reason`. |
| R6 | Ledger coverage | **Tiered + batch digest.** Relational decision row: always, every tier, full provenance. Ledger: governed tiers, tightened tasks, overrides/refusals, holds, attestation failures — **100%, never sampled**. Untightened commodity — 100% in MVP; from AD-1 sampled at a rate **set in governance policy** (signed, Domain Authority), with sampled-out rows hashed into a **periodic batch digest written to the ledger** so later alteration is detectable. | Adaptive FRD `AUD-01`: sampling keyed on governance tier + "untightened", rate lives in governance policy, add batch-digest clause; supersedes OI-6's per-class framing. MVP FRD `AUD-01`: note 100% applies through MVP and permanently for governed tiers. `ir_routing_decisions` gains `ledger_entry_id` (nullable) and `digest_batch_id` (nullable); exactly one is set. |
| D2 | Binding cache | **Key = `(reasoning_class, effective_governance_tier, privacy_class, governance_policy_version)`; classifier runs before lookup.** **Binding is split:** the cached, revocable, partition-served object is the *eligibility binding* (the allowed model set + provenance); *selection* runs per request over it (MVP: min-cost, deterministic; AD-4: Thompson sampler through the same `Selector` seam). **Classifier scope:** rules layer + fabric privacy tags run on every request; the model-based classifier may be skipped only for classes flagged `structural_input` in the signed governance policy. | MVP FRD `RTR-01`/`RTR-05`: binding = eligible set, not a single model; `RTR-04` provenance records the set and the selected model separately. `CLS-01`: add the `structural_input` exemption and that it is a governance-policy flag. Reasoning-class registry gains `structural_input` (default false). Golden set must include sensitive content submitted under `structural_input` classes to measure what the rules layer alone catches. |
| D3 | Classifier | **Self-hosted inside the membrane, P3 ceiling** (content is unclassified when it is read). **Governed like a guider:** pinned, outside the selector/bandit, attested, changes are reviewed Domain Authority acts. **Drift checker is lineage-diverse** from the primary. **Build: rules/lexicon floor + small self-hosted model, max wins; no retrieval in MVP.** Per-domain sensitivity via the tightening map (MVP FRD's "escalation map", renamed per R4) in governance policy. Golden set structured (framework tag, load grade, rationale, P-class) so it can later serve as retrieval corpus and distillation seed. **Closes [SUFFICIENCY-GAP-B]: model-only; retrieval deferred.** | MVP FRD: new `CLS-06` (classifier model pinned, attested, P3 ceiling, excluded from cost optimisation; change requires reviewed approval — mirror of `GDR-01/05`); `CLS-05` amended to require a different-lineage comparator; §9-B and §11 GAP-B closed with this decision; autonomy ladder gains "Change classifier model/version → Human approval". Registry needs ≥2 self-hosted lineages available at MVP-2 (one primary, one comparator) — check this against the ≥2 lineages the guider tier already needs. |
| D5 | Guider enforcement | **Signed verdict, three enforcement points.** Guider service (own deployable, own key) signs `(decision_id, output_hash, guider_model_id, verdict, ts)`. (1) Sidecar withholds governed output until a verdict arrives; (2) membrane **Publisher verifies the signature** before governed output leaves; (3) **Card/blackboard writes** of governed output verify it too. **Verdicts:** `pass` → release; `unavailable`/`uncertain` → hold + human (always); **`fail` → hold + human in MVP** (`ir.guider.hold`, `reason=fail`); from AD-3 `fail` → cascade hop up to `maxEscalations`, then hold. | MVP FRD `GDR-03`: name the three enforcement points and the verdict schema; `GDR-04`: add the `fail` case; §4 `guider.hold` gains `reason` (unavailable \| uncertain \| fail). **Two cross-team dependencies now, both to open in week 1:** membrane Publisher owners and Card/blackboard store owners. Governed outputs must carry `decision_id` + `governance_tier` metadata so both checkpoints can tell what needs a verdict — absence of metadata on a write from a governed binding is itself a refusal. `fail` holds are labelled data for the classifier golden set and AD-6 candidates. |
| D6 | Lineage | **Lineage is a transitive set**, not an id: `lineage(model) = lineage(base) ∪ ⋃ lineage(teachers)`, plus any model whose outputs it was trained on. **Disjointness test** (guider vs overseen, and classifier vs its drift comparator): no shared base family/provider, no shared teacher at any depth, no training on each other's outputs. **Client framework corpus is explicitly exempt.** Checked at governance promotion, registry change, and (AD-3+) every cascade hop. **Reserved-lineage rule:** a lineage pinned as guider for a boundary may not teach any model serving under that boundary; `A:NBA-02` checks before recommending a job and the T2 export approval shows the resulting lineage set. **Closes the MVP [OPEN] on "different lineage".** | MVP FRD: glossary "Lineage" and `GDR-02` rewritten to this definition; `FND-02` `lineage id` → `lineage set`; `ATT-02` attestation binds the lineage set and the conformance report must list base, teachers, and training-output sources. Adaptive FRD: §3.2 provenance adds teacher model ids; `DST-02` export records the teacher(s) of the winning outputs; `DST-03` re-entry computes the lineage set before `candidate`; `NBA-02` adds the reserved-lineage check. Console metric: count of lineage-diverse guider options per boundary. |
| D7 | Decision record | **Wide `ir_routing_decisions` from MVP-0** (Adaptive superset; Adaptive-only columns nullable/constant: `env='prod'`, `exploration_flag=false`, `predicted_quality=null`, single-element `hop_chain`), plus today's additions: both policy version ids, eligible set and selected model separately, `override_source`, `override_refused_reason`, `ledger_entry_id`/`digest_batch_id`, classifier grades + confidence. **Content as hashes and mesh event refs only.** **Outcome side in MVP:** `ir_outcome_events` created in MVP-0; from MVP-4, guider verdicts (`signal_type=guider`) and **human hold resolutions** — approve / edit / reject (`signal_type=human`) — are emitted as `ir.routing.outcome.observed`. Commodity accept/override capture, correction detection and `ir_reward_joins` stay in AD-1. | MVP FRD §6 Routing-Decision Card: replace key fields with the wide set; add an Outcome-Event Card; add `STT-03` (content never persisted — hashes/refs only); §4 registers `ir.routing.outcome.observed`. MVP-4 scope gains the hold-resolution UI action that emits the human signal (belongs with the console work in MVP-5 if the hold queue UI lands there). AD-1 shrinks to: commodity human signals, correction detector, reward join, buffering/backpressure, ledger sampling + batch digest. Its 30-day clock for **governed** classes starts at MVP-4. |
| R7 | Reasoning class vs task class | **One registry.** Reasoning class = Adaptive `task_class` + governance attributes (default governance tier, eligible set, `structural_input`, cascade-eligible, capability tier, latency target). Routing key stays `(class, domain, tenant, perturbation_type?, intent_id?, privacy_class)`; MVP resolves at class granularity. **Governance attributes attach at class level only** — finer keys affect selection, never governance. | MVP FRD `FND-01/03` and Adaptive FRD §3.1/`FND-01` cross-reference one registry (`ir_reasoning_classes`; Adaptive's `ir_task_classes` is dropped as a separate table). |
| R8 | Actors | Platform Operator ≡ **Router Steward**. **Domain Authority** owns governance policy, guider + classifier changes, ledger sampling rate. **Steward** owns selection policy, model lifecycle, budgets, λ. **Cost Owner** co-signs T3. **Auditor** read-only. Encoded as Decision Matrix rows from MVP-4. **Model activation:** commodity = Steward + Cost Owner (T3); **normative/guider eligibility = Steward + Cost Owner + Domain Authority.** | MVP FRD §3.1 rename operator → Router Steward; autonomy ladder names approvers per row. Adaptive FRD §2.1 adds Domain Authority and Auditor; `AUT-01` T3 row gains the governed-tier triple sign-off; §3.2 lifecycle `active` gate split by governance tier. Still open: named individuals and the T3 spend threshold (Adaptive OI-4). |
| R9 | Event envelope | **MVP adopts `ir.*`, CloudEvents, mandatory `env` from the first commit**; emits `env=prod` only; consumers reject events without `env`. Names: `ir.routing.requested`, `ir.routing.bound`, `ir.routing.tier.tightened`, `ir.routing.outcome.observed`, `ir.guider.hold`, `ir.attestation.failed`, `ir.classifier.drift`, `ir.governance.policy.promoted`, `ir.partition.entered/.cleared`. Payload JSON Schemas written in MVP-0. | MVP FRD §4 rewritten with these names + envelope; closes its [ORCHESTRATOR-GAP] on payload schemas once the schemas land. |
| #7 | Deployed privacy direction | **No router/Redactor code exists — nothing to migrate.** Router is built interface-first: one narrow contract, compliance enforced server-side, agents hold no model credentials, modules certified by an attack-suite conformance kit. | [Trust Architecture](Intelligence_Router_Trust_Architecture.md) §3. Risk 1 downgraded to "patch the July FRD". |
| D4 | Partition semantics | **Governed work stops the moment a partition is detected** — implemented as a signed, continuously renewed *governance lease*: no unexpired lease ⇒ no governed work. Commodity fail-open only for principals at `normal` posture. | [Trust Architecture](Intelligence_Router_Trust_Architecture.md) §5. MVP FRD `MBR-02`, UC-5 amended. |
| D8 | Threat model, guider hardening, keys | **Agents treated as potentially adversarial.** Three principles: *declared vs derived*, *default-deny stamps at every boundary*, *the ratchet* (automation may tighten; only humans loosen). Egress classification of the final artifact + router-side task taint; guider pulls its own context, model never touches the key, deterministic signer wrapper, rule canaries, single-use bound verdicts. Key custody table incl. new **Attestation Officer** role. **Extends D5.** | [Trust Architecture](Intelligence_Router_Trust_Architecture.md) §1, §2, §4, §9. New MVP FRD layer `FR-IRG-INT-*` (integrity) and `FR-IRG-KEY-*`. |
| D10 | Binding TTL | **Emergent.** `ir.integrity.*` signals feed a decaying suspicion score per principal (agent → team → module); posture lattice `normal < watch < restricted < quarantined`; `TTL_eff = clamp(TTL_base · 2^(−S/h), floor, base)`; posture is part of the cache key and a posture change pushes revocation. Bounds live in signed governance policy; operating values emerge. Relapse halves the decay rate. | [Trust Architecture](Intelligence_Router_Trust_Architecture.md) §6. Supersedes the fixed TTL proposal. MVP FRD `RTR-01/05` amended. |
| D11 | Classifier thresholds | **Emergent + learned, tighten-only.** Fast loop: posture moves the operating point per principal. Slow loop: audit sampling of untightened commodity work finds false negatives; a confirmed miss tightens automatically; over-tightening evidence becomes an NBA recommendation to the Domain Authority. Operating point is a versioned, ledgered **calibration state** inside a signed band. Non-`normal` principals excluded from learning. | [Trust Architecture](Intelligence_Router_Trust_Architecture.md) §7. Third versioned artefact; decisions record its version. MVP FRD `CLS-03/04` amended, new `CLS-07` (audit sampling). |
| D12 | Roles | **Agreed** as in R8, plus Attestation Officer. Names and T3 threshold still to be supplied. | — |
| D13 | Membranes and Cards | **Dynamic.** Membranes are module/agent/team-specific and created by manifest; Card types register at runtime with a `model_content` declaration; unknown membranes and undeclared model-content fields auto-register **tight** (provisional, `watch`, normative floor) and raise a signal. Retires the `membranes.yaml` / eight-Card [ORCHESTRATOR-GAP]s. | [Trust Architecture](Intelligence_Router_Trust_Architecture.md) §8. Both FRDs: replace static-registry references with the registration APIs. |
| D14 | Custody, quorum, threshold, roles | **Client Domain Authorities hold their own governance-key hardware token. Two lineage-disjoint guiders required for top-grade work from MVP release** (pool needs ≥3 mutually disjoint lineages per such boundary). **T3 threshold = USD 0.25** projected cost change per task execution (unit to confirm). **Five roles approved** (Domain Authority, Router Steward, Cost Owner, Auditor, Attestation Officer); individuals to be named per deployment. | Both FRDs patched as tracked changes: MVP FRD v0.2 (`FR-IRG-*`), Adaptive FRD v1.1. |

**All nine reconciliation items, the five flagged design calls, and the follow-up items #7–#13 are decided.** The security design behind D4/D8/D10/D11/D13 is in the companion [Trust Architecture](Intelligence_Router_Trust_Architecture.md). Sections 2–10 below have been updated to match; where they differ from this log, the log wins.

---

## 1. How the two documents fit together

They are not two versions of one spec; they are two layers of one system.

| | MVP FRD (Sep) | Adaptive FRD (Jul) |
|---|---|---|
| Question it answers | *Is this model **allowed** to do this work?* | *Which allowed model is **cheapest-best**?* |
| Core mechanism | Tiering, monotonic tightening, attestation, pinned guiders, fail-closed | Contextual bandit, cascade, shadow routing, distillation flywheel, simulator |
| Selection rule | Lowest-cost eligible model, declared (`M:RTR-02`) | Learned posterior, Thompson sampling (`A:LRN-01`) |
| Learn link | Explicitly deferred | The whole point |

**Composition rule this plan is built on:** the MVP's governance pipeline computes the *eligible set* (class → tier → privacy ceiling → attestation → lineage compatibility). The adaptive layer is only ever allowed to replace the **selector inside that set** — i.e. it swaps out `M:RTR-02`'s "lowest cost" with a learned choice, and nothing else. The optimizer never sees tiering, never sees guider routing, and cannot emit a signal that relaxes anything. That is what the MVP FRD means by "the safety layer is never coupled to an optimizer before controls exist," and it dictates the order: **MVP first, adaptive second**, with the MVP's schemas built forward-compatible so the adaptive track needs no migration.

---

## 2. Reconciliation items (all decided — see §0)

These are the contradictions found between the two FRDs. Each is now decided; the table is kept as the record of *what conflicted and why it mattered*. The authoritative resolution and the FRD edits it requires are in the §0 decision log. **Remaining work: patch both FRDs accordingly before MVP-0 schema work starts.**

| # | Conflict | Where | Why it matters | Resolution (summary) |
|---|---|---|---|---|
| **R1** | **Privacy scale is inverted between the docs.** MVP: P0 = least sensitive, P3 = most ("P2/P3 data never reaches a frontier API"; UC-1 routes P0 cheaply). Adaptive: P0 = most sensitive ("P0 is excluded absolutely" from distillation; "route P0 content to a non-approved endpoint" is a hard stop; P2 = "internal operational"). | MVP §5.2/5.4/§12 vs Adaptive §3.4/§5.10 | The Redactor gate is a single `data_class <= model_ceiling` comparison. Two teams coding from two docs produce a gate that sends the most sensitive data to vendor APIs — a silent hard-stop violation. | **P3 = most sensitive.** Named enum + single `may_receive()` ordering function — never compare raw integers. Adaptive FRD patched; distillation exports gated by destination ceiling. |
| **R2** | **`FR-IR-*` numbering collides**: FND-01..04, MFB-01, TRN-01/02, AUD-01/02, UI-01/02 mean different things in each doc. MVP change log already says "reconcile before merge." | Both §5 | Traceability, test naming, and ledger references become ambiguous. | Adaptive IDs unchanged; MVP set re-prefixed `FR-IRG-*`. |
| **R3** | **"Policy" means two things.** MVP: signed governance policy (classes, eligibility, tiering, tightening map), promoted by the Domain Authority. Adaptive: immutable snapshot of bandit posteriors/λ/budgets, promoted by the Router Steward. Both emit a `policy.promoted` event. | MVP §5.6 vs Adaptive `A:LRN-08` | One table / one event for both would let a learned-policy flip masquerade as a governance change, or vice-versa. | Two distinct entities: **governance policy** (`ir_governance_policy_versions`, signed) and **selection policy** (`ir_selection_policy_versions`, learned). Every binding/decision records *both* version ids. Distinct events: `ir.governance.policy.promoted` vs `ir.routing.policy.promoted`. |
| **R4** | **"Tier" means three things**: governance tier (commodity/normative/guider), capability tier (lightweight/mid/heavyweight/specialized), authority tier (T0–T3). Likewise "escalation": tier tightening (`route.escalated`) vs capability-ladder hop after a failed verification (`ir.routing.escalation.triggered`). | Throughout | Code and dashboards will conflate them. | Field names: `governance_tier`, `capability_tier`, `authority_tier`. Events: `ir.routing.tier.tightened` (MVP's `route.escalated`) vs `ir.routing.escalation.triggered` (cascade hop). |
| **R5** | **Model overrides.** MVP rejects any request naming a concrete model except a logged admin override (`M:FND-04`). Adaptive puts caller `modelOverride` second in precedence and keeps Template Engine pins first-class (`A:FND-03`, `A:EVI-01`). | | Pins are exactly the tiering bypass `M:FND-04` exists to prevent. | An override is a *constraint*, never a bypass: honoured only if the named model is inside the computed eligible set for the task's **effective** governance tier; otherwise the pin is dropped, the task routes normally, and `override_refused` is ledgered. Sources: `template`, `admin` only. Never for guider class. MVP ships admin-override only; template pins arrive in AD-3. |
| **R6** | **Ledger coverage.** MVP: every decision ledgered (`M:AUD-01`; acceptance step 9 reconstructs a commodity decision). Adaptive: 10% sampling for bulk classes (`A:AUD-01`). | | | MVP: 100%. A relational decision row is *always* written; when sampling arrives in AD-1 it applies to the ledger copy of **untightened commodity** decisions only, at a rate set in signed governance policy, with sampled-out rows covered by a ledgered batch digest. Governed tiers and exceptional events are never sampled. |
| **R7** | **Reasoning class vs task class / routing key.** | MVP §5.1 vs Adaptive §3.1 | Two registries for one concept. | One registry. A *reasoning class* is the Adaptive doc's `task_class` plus governance attributes (default governance tier, eligible set, cascade-eligible flag, latency target). The Adaptive *routing key* = `(reasoning_class, domain, tenant, perturbation_type?, intent_id?, privacy_class)` — the MVP simply uses the coarsest key. |
| **R8** | **Actors.** Platform operator / Domain authority / Auditor vs Router Steward / Cost Owner. | | Approval routing. | Domain Authority owns governance policy + guider changes. Router Steward (= MVP "platform operator") owns selection policy, model lifecycle, budgets. Cost Owner co-signs T3. Encode in the Decision Matrix from MVP-4 so AD phases only add rows. |
| **R9** | **Event namespace/envelope.** MVP events are un-namespaced with no envelope spec; Adaptive mandates `ir.*`, CloudEvents, and a required `env` attribute. | | | Adopt the Adaptive convention from day one. MVP emits `env=prod` only, but consumers already reject events lacking `env` (`A:TRN-02`). |

**Two smaller things to clean up:** the MVP FRD lists "Time to Pricing Confidence" as a router KPI (§9-D, §11) — this looks pasted from another domain's FRD; confirm or drop. And MVP UC-5 is ambiguous about whether a *valid cached* normative binding may be served during a partition — see D4 below (**still open**).

---

## 3. Target architecture

**Assumed stack** (consistent with the Embark platform boundary — Postgres, Redis Streams mesh, Python/CrewAI agents). Greenfield: no router code exists. Trust zones, the interface contract and key custody are specified in the companion Trust Architecture; the layout below includes its components.

```
intelligence-router/
  ir_sdk/             # generated client (untrusted zone): ir.reason(); convenience only, enforces nothing
  ir_dispatch/        # sole holder of model credentials; signs output stamps
  ir_egress/          # Publisher + Card/blackboard hooks: stamp check, egress classification, task taint
  ir_posture/         # ir.integrity.* signals, suspicion score, posture lattice, adaptive TTL, calibration state
  ir_registry/        # manifests, dynamic membrane + Card-type registries
  ir_conformance/     # attack-suite conformance kit for module CI / integration gate
  ir_core/            # pure library, no I/O: lattice types, eligibility, resolution, binding, provenance
  ir_controlplane/    # stateless API (replicated): registries, signed governance policy, promotion, attestation intake
  ir_sidecar/         # per-membrane resolver: policy cache, binding cache, classifier client, Redactor gate, partition FSM
  ir_classifier/      # ethical-load + privacy classifier service, rules layer, golden set, drift monitor
  ir_guider/          # guider dispatch + signed verdicts; Publisher-side verdict check
  ir_attest/          # attestation schema, verify lib, manual issuance CLI
  ir_ledger/          # Decision Ledger writer (hash-chained), reconstruction queries
  ir_console/         # operator console + governed policy editor
  ir_learning/        # (AD-4+) Learning Consumer, divergence monitor, policy versioning
  ir_shadow/          # (AD-5) shadow executor
  ir_distill/         # (AD-6) candidate capture, dataset export
  ir_sim_bridge/      # (AD-2) simulator contract: substitution layer adapter, prior export
  schemas/            # JSON Schema for every ir.* event; SQL migrations
  tests/invariants/   # hard-stop + property tests (run in CI on every phase)
```

**Request path (MVP):**
`ir.routing.requested` → sidecar reads fabric context (`M:MFB-01`) → classifier (ethical load, privacy class) → **tighten** (monotonic) → eligible set = class eligibility ∩ privacy ceiling ∩ valid attestation (governed tiers) ∩ lineage-compatible with the pinned guider → **eligibility binding** (cached) → per-request selection (MVP: lowest cost) → Redactor gate re-check at dispatch → model call → *(governed)* output held by sidecar → guider signs verdict → released to agent; Publisher and Card/blackboard writes verify the verdict → decision row + outcome event + ledger entry + `ir.routing.bound`.

### Design decisions that are easy to get wrong

**D1 — Monotonicity is a type, not a check.** `GovernanceTier` is an ordered lattice (`commodity < normative < guider`); the only combinator exposed is `tighten(a, b) = max(a, b)`. There is no constructor or API that lowers a tier, so `M:RTR-03`'s "structurally reject" is true by construction. Signals are a closed sum type of tightening signals; an unknown or "relaxing" signal fails deserialisation. Property test: for any sequence of signals, `effective_tier >= function_default` and is non-decreasing.

**D2 — The binding caches eligibility, keyed on the tightened result.** *(Decided.)* The classifier runs **per request** before the cache lookup; key = `(reasoning_class, effective_governance_tier, privacy_class, governance_policy_version)`. Without this, UC-2 (ordinary agent, bereavement content) would hit a cached commodity binding and the tightening would never happen. The cached, revocable, partition-served object is the **eligibility binding** — the allowed model *set* with provenance. **Selection runs per request** over that set through the `Selector` seam (MVP: min-cost, deterministic; AD-4: Thompson sampler), because a cached concrete model would make per-request exploration impossible. Rules layer + fabric privacy tags run on every request; the model-based classifier is skipped only for classes flagged `structural_input` in signed governance policy.

**D3 — The classifier must run on a max-ceiling, self-hosted model inside the membrane.** It sees content *before* the privacy class is known, so it can never be a vendor API call. *(Decided; closes [SUFFICIENCY-GAP-B].)* The classifier model is **governed like a guider**: pinned, outside the selector, attested, changed only by reviewed Domain Authority approval; its **drift comparator must be lineage-diverse** from it. Build: **model + deterministic rules, take the max** — a small self-hosted classifier model, plus a lexicon/rules layer and the data-ref privacy tags already in the Memory Fabric; any one of them can raise, none can lower (`M:CLS-04` falls out of the same lattice as D1). Retrieval-assisted classification is deferred; record the decision in §11 of the MVP FRD. Budget the latency: this adds a model call to *every* request, including sub-500 ms classes.

**D4 — Partition behaviour for governed tiers: fail closed immediately.** During a partition, revocations (policy change, withdrawn attestation — `M:RTR-05`, `M:ATT-03`) cannot reach the sidecar, so a "still valid" cached normative binding is unverifiable. Recommend: on `partition.entered`, normative/guider requests hold regardless of cache state; commodity serves from cache up to a max staleness. This matches acceptance step 7 literally.

**D5 — Non-bypassable oversight is enforced at egress, not at the router.** `M:GDR-03` cannot be satisfied by the router promising to call the guider. *(Decided.)* The guider service (own deployable, own key) signs a verdict over `(decision_id, output_hash, guider_model_id, verdict, ts)`, enforced at **three points**: (1) the sidecar withholds governed output from the agent until a verdict arrives; (2) the membrane **Publisher** refuses any governed-tier output lacking a valid `pass` verdict for that exact hash; (3) **Card/blackboard writes** of governed output verify it too, covering agent-to-agent use inside the membrane. Points 2 and 3 trust the guider's key, not the router. Governed outputs carry `decision_id` + `governance_tier` metadata; its absence on a write from a governed binding is a refusal. Verdicts: *pass* → release; *unavailable/uncertain* → `ir.guider.hold` + human, always (`M:GDR-04`); *fail* → **hold + human in MVP** (`reason=fail`), cascade hop then hold from AD-3.

**D6 — Lineage is a transitive set, and distillation propagates it.** *(Decided; closes the MVP [OPEN] on "different lineage".)* `lineage(model) = lineage(base) ∪ lineage(every teacher)`, plus any model whose outputs it was trained on. Disjointness test: no shared base family/provider, no shared teacher at any depth, no training on each other's outputs. **The client framework corpus is exempt** — guider and worker must share it. The check (`M:GDR-02`) runs at governance promotion, registry change, and per cascade hop. **Reserved-lineage rule:** a lineage pinned as guider for a boundary may not teach any model serving under that boundary; `A:NBA-02` checks before recommending a distillation job.

**D7 — Build the MVP decision record as the Adaptive superset.** `ir_routing_decisions` ships in MVP-0 with `env`, `routing_key`, `candidate_set`, `predicted_cost`, `predicted_quality` (null), `exploration_flag` (false), `override_source`, `hop_chain`, both policy version ids, content **hashes/refs only** (`A:MEM-02`). `ir_outcome_events` is created in MVP-0; from MVP-4, guider verdicts (`signal_type=guider`) **and human hold resolutions — approve / edit / reject (`signal_type=human`)** are emitted as `ir.routing.outcome.observed`, giving early ground truth on governed work. *(Decided.)* Consequence: AD-1's exit criterion (30 days of joined decision→outcome telemetry) starts accruing *during* the MVP instead of after it.

**D8 — Signing.** Ed25519, DSSE-style envelopes for governance policy versions, attestations, and guider verdicts; keys in the platform KMS; separate key per role (policy authority, attestation authority, guider service). MVP issuance is a CLI (`ir-attest issue`) run by a named human — resolves the MVP [OPEN] on signing authority once an owner is named.

**Failure matrix (implement as one table-driven module, test every cell):**

| Condition | Commodity | Normative | Guider |
|---|---|---|---|
| Control-plane partition | Serve from cache (fail open), bounded staleness | Hold for human | Hold for human |
| No eligible model under privacy ceiling | Ledgered refusal | Ledgered refusal | Ledgered refusal |
| Attestation missing/expired | n/a (not required) | Next attested model, else hold | Hold |
| Guider unavailable / uncertain | n/a | Hold + human | Hold + human |
| Guider verdict `fail` | n/a | MVP: hold + human. AD-3+: cascade hop ≤ `maxEscalations`, then hold | Hold + human |
| Pinned model not in eligible set | Drop pin, route normally, ledger `override_refused` | Same | Overrides never accepted |
| Classifier low confidence / unavailable | **Tighten** to normative | Stay | Stay |
| Endpoint timeout / 5xx | Fallback chain + circuit breaker | Fallback *within attested eligible set* only | No fallback |
| Mesh down | Route; buffer telemetry (`A:TRN-03`) | Route only if ledger write is durable locally | Same |

---

## 4. Track 1 — Governed MVP (MVP-0 … MVP-5)

Rough sizing assumes ~4 engineers + part-time domain reviewers; treat as order-of-magnitude until the existing router code is assessed. Total ≈ 12–14 weeks with the overlap shown in §7 **for the scope as originally planned; the Trust Architecture (D8/D10/D11/D13) adds roughly 4–5 weeks — ≈ 16–19 weeks** — mostly the dispatch plane, the egress gate, and the posture engine. Per-phase placement of that work is in Trust Architecture §10.

### MVP-0 — Foundations, state, control plane (~2 wk)
*Covers `M:FND-01..04`, `M:STT-01..02`, `M:CTL-01..04`.*
- Patch both FRDs per §0; write `ir_core` lattice types (D1), the privacy enum + `may_receive()`, and lineage-set disjointness (D6).
- Migrations: `ir_reasoning_classes` (single registry per R7, incl. `structural_input`), `ir_outcome_events`, `ir_model_registry` (source, capability, cost, residency, privacy ceiling, lineage set + teacher ids, attestation status, **lifecycle_state** from the Adaptive doc — MVP uses only `active`), `ir_governance_policy_versions` (signed blob + version), `ir_attestations`, `ir_routing_decisions` (D7). Optimistic-lock `version` column on every Card-bound table; decisions append-only.
- Card bindings: map the four MVP Cards onto these tables. **Blocked on** Adaptive OI-1 (canonical eight-Card registry) — get the registry, don't invent bindings.
- Control-plane API: CRUD behind review workflow hooks, atomic promote (single transaction: insert version → flip active pointer → emit `ir.governance.policy.promoted`), signature verification on read. Stateless; ≥2 replicas behind the platform LB.
- Request validation: reject concrete model names (`M:FND-04`), admin-override path ledgered.
- JSON Schemas for all MVP events in CloudEvents envelope with `env` (R9) — closes the MVP [ORCHESTRATOR-GAP] on payload schemas.
- **Start now, in parallel (long pole):** classifier golden-set labelling with domain reviewers (see MVP-2).
- **Exit:** policy v1 authored, signed, promoted; registry seeded with ≥1 model per source type; promotion is atomic under a concurrent-writer test.

### MVP-1 — Resolution engine, attestation, transport (~2 wk)
*Covers `M:RTR-01..05`, `M:ATT-01..03`, `M:TRN-01..02`.*
- Eligibility pipeline + lowest-cost selector behind a `Selector` interface (the seam the bandit plugs into later).
- **Eligibility binding** (allowed set + provenance + TTL); per-request selection over it; cache keyed per D2; revocation on `ir.governance.policy.promoted` and `ir.attestation.withdrawn`; revocation index `attestation_id → bindings`.
- `ir_attest`: schema (`model_id`, `lineage`, `conformance_report_ref`, validity window, signature), verify lib, issuance CLI, expiry sweeper that emits `ir.attestation.failed` and triggers revocation.
- Redis Streams: request/response envelope for `ir.routing.requested` / `ir.routing.bound`; consumer groups for ledger writer and console.
- **Exit:** acceptance steps 1 and 5 pass against a stubbed classifier (always "no load, lowest class"); step 8 (promote → converge → revoke) passes with one resolver.

### MVP-2 — Classifier + monotonic overrides (~3 wk, golden set starts in MVP-0)
*Covers `M:CLS-01..05`, `M:MFB-01`.*
- Classifier service per D3: graded ethical/doctrinal/pastoral load + P-class, each with confidence. Rules layer + model; output = max. Classifier model pinned + attested (new `M:CLS-06`); `structural_input` classes take the rules-only path.
- Tightening map (the MVP FRD's "escalation map", renamed per R4) lives in governance policy (`M:CLS-03`); low confidence ⇒ tighten (`M:CLS-04`). Initial thresholds are an MVP [OPEN] — propose conservative defaults, tune against the golden set, have the Domain Authority sign off.
- Golden set: a few hundred labelled tasks per framework, including adversarially *ordinary-looking* sensitive ones (the UC-2 shape) and sensitive content submitted under `structural_input` classes. Rows carry framework tag, load grade, rationale and P-class so the set can later seed retrieval or distillation. This is the classifier's regression suite and its version gate.
- Drift (`M:CLS-05`): sample N% of live traffic to a **lineage-diverse** second classifier (needs ≥2 self-hosted lineages in the pool — check jointly with the guider tier's needs); agreement below threshold emits `ir.classifier.drift`. Also re-run the golden set on every classifier or prompt change.
- Memory Fabric read via the context-pack read path (working + session layers only).
- **Exit:** acceptance step 2 passes; golden-set recall on "must-tighten" items meets the signed-off target (recall matters far more than precision here — over-tightening costs money, under-tightening is the silent failure the FRD warns about); p95 classifier latency measured and budgeted per class.

### MVP-3 — Sidecar, Redactor gate, partition tolerance (~2 wk)
*Covers `M:MBR-01..04`.*
- Package resolver + caches as the membrane sidecar; policy convergence (subscribe + periodic version poll; report `policy_version` in heartbeat so the console can show convergence).
- Redactor gate evaluated **twice**: when computing the eligible set, and again at dispatch against the actual payload's class (defence against a stale binding). Uses the R1 ordering function.
- Partition FSM per D4; `ir.partition.entered/.cleared`; staleness bound for commodity.
- Receptor interface: define the contract, ship disabled, contract test only (`M:MBR-04`).
- Confirm membrane IDs against `membranes.yaml` (open gap in both FRDs).
- **Exit:** acceptance steps 3 and 7 pass under fault injection (network cut to control plane; most-sensitive-class payload aimed at a vendor model).

### MVP-4 — Guider tier, authority, audit (~3 wk)
*Covers `M:GDR-01..05`, `M:APV-01..02`, `M:AUD-01..02`.*
- Guider dispatch service + signed verdicts; three enforcement points (D5): sidecar hold, Publisher check, Card/blackboard write check. **Two cross-team dependencies — membrane Publisher owners and Card/blackboard store owners; open both in week 1.**
- Hold queue with resolve actions (approve / edit / reject) that emit `signal_type=human` outcome events (D7).
- Guider routing is a pinned table in governance policy, excluded from the `Selector` entirely (`M:GDR-01`); lineage-set disjointness validated at promotion and registry change (D6); changes go through a reviewed approval (`M:GDR-05`).
- Decision Matrix rows for the MVP autonomy ladder (R8); hard stops as code-level invariants **plus** tests in `tests/invariants/`.
- Ledger: hash-chained append-only entries (each entry commits to the previous hash; periodic anchor), reconstruction query API. 100% coverage in MVP (R6). Emit guider verdicts as `ir.routing.outcome.observed` (D7).
- **Exit:** acceptance steps 4, 6, 9 pass; tests that strip the verdict from a governed output prove both the Publisher and a Card write block it; a guider `fail` produces a hold with `reason=fail`; tamper test on the ledger detects a modified row.

### MVP-5 — Control surface + acceptance (~2 wk)
*Covers `M:UI-01..02`, `M:VAL-01..02`.*
- Operator console: tier mix, tightening rate, classifier agreement, guider holds, attestation expiry horizon, sidecar policy-version convergence, partition state. Built via the platform's UI-emission conventions.
- Governed policy editor: draft → diff against active → reviewer approval → signed promote. No other write path to the policy store exists.
- Scripted end-to-end acceptance test (MVP §12, all 9 steps) as a repeatable CI job in a single-domain staging environment; per-request trace showing detect → decide → act → verify → document.
- Set KPI owners/thresholds ([SUFFICIENCY-GAP-D]).
- **Exit = MVP release:** §12 passes end to end; zero hard-stop violations; all R-items closed in the FRDs.

---

## 5. Track 2 — Adaptive router (AD-1 … AD-6)

**Gate to start changing production behaviour (AD-3 onward):** MVP released, and the following guard-rails written into governance policy:
1. The bandit's arm set is *exactly* the MVP eligible set for the task's effective tier — it cannot add arms.
2. Guider-class routing is never an arm, never explored, never shadow-swapped (`M:GDR-01`).
3. Exploration excludes any task that was tightened or carries a privacy restriction (already in `A:LRN-03`; make "was tightened" explicit).
4. **Normative tier: learn in shadow only** until the Domain Authority opts a class in. Commodity tier learns first.
5. Shadow challengers pass the same Redactor gate — restricted data is never shadow-routed to a vendor endpoint.
6. The guider is now both overseer and reward proxy, so `A:LRN-07` (divergence monitor + auto-freeze) is a precondition for any live learning, not a nice-to-have.

| Phase | Build | Notes specific to merging with the MVP | Exit (from Adaptive §10) |
|---|---|---|---|
| **AD-1 Instrument** (~2 wk + 30-day clock) | Remaining `ir.*` streams, `ir_outcome_events`, `ir_reward_joins`, human accept/override + correction signals, local buffering/backpressure (`A:TRN-03`), ledger sampling for commodity (R6) | Largely pre-paid by D7 — mostly adding human/correction outcome sources and the join. The 30-day clock likely starts during MVP-4. | 30 days joined decision→outcome telemetry on top classes |
| **AD-2 Simulator integration** (~4–5 wk, **can run in parallel with MVP-3…5**; different code, no prod impact) | Model Call Substitution Layer (live / recorded-corpus / surrogate), DSL `routing` block, redacted trace import, golden routing sets, four router invariants, prior-export artifact, env-isolation injection tests (`A:SIM-01..10`) | Needs Adaptive OI-7 (surrogate calibration method). Surrogate calibration needs prod telemetry, so recorded-corpus mode lands first. Add governance invariants to the sim too: monotonicity and privacy-ceiling as always-on invariants. | Green learning run; cold-start priors exported for one class |
| **AD-3 Cascade, static policy** (~3 wk) | Cheap-first cascade + capability ladder, `maxEscalations`, availability-vs-quality split + circuit breakers (`A:FND-04/06`), Template Engine overrides as constraints (`A:EVI-01/02`, R5) | Each hop re-runs eligibility **and** the lineage check against the pinned guider (D6). Cascade only for cascade-eligible classes; commodity tier first. Needs OI-6 and, for regulated tenants, OI-3. | Escalation rate stable; no latency regression on direct-route classes |
| **AD-4 Online learning** (~5 wk) | Learning Consumer (idempotent, env-partitioned), Thompson sampler behind the MVP `Selector` seam, discounted posteriors, exploration budget per key, divergence monitor + freeze, immutable selection-policy versions + rollback, fabric L3 persistence via Memory Integration Service | Needs OI-4, OI-5, OI-9. Selection-policy versions are a separate entity from governance policy (R3); bindings record both. | One key migrated to a cheaper champion with quality held; freeze fires in injection test |
| **AD-5 Shadow + promotion governance** (~4 wk) | Shadow executor with membrane hold, `ir_shadow_results`, NBA promotion/pin-removal recommendations, T2/T3 approval Cards with evidence packets, cooling window, ops intents incl. `explain_route`, Router Control Surface additions, sim → shadow → prod pipeline | Extends the MVP console and Decision Matrix rather than building new ones. Injection test: no shadow output reaches any Publisher path. | Sim-originated policy passes shadow and is promoted via T2 with full provenance |
| **AD-6 Flywheel + twin** (~4 wk + first fine-tune cycle) | Distillation candidate capture (privacy-gated per R1: P0/P1, consented P2, never P3), versioned dataset export, model re-entry lifecycle (candidate → sim-qualified → shadow → active), Digital Twin sensitivity feed, routing drift review in CI, L4 consolidation, optional L5 federation (default off, OI-8) | Re-entering distilled models carry teacher lineage (D6) and need a (manual) attestation before serving any governed tier. This is also where MVP Phase-2 items — federation/receptor enablement and automated attestation issuance — get scheduled. | A fine-tuned model re-enters and measurably absorbs escalations |

Adaptive §12's 17-step acceptance test is the definition of done for Track 2; run it with the MVP §12 suite still green.

---

## 6. Verification strategy

- **Invariant suite, runs on every commit from MVP-0:** tier never decreases (property test, D1); no payload above a model's ceiling is dispatched (both gate positions); no unattested model in a governed tier; no governed output published without a valid verdict; guider lineage ∩ worker lineage = ∅; *(AD)* sim events never move prod posteriors (bit-identical check); shadow output never reaches a Publisher path; most-restricted-class content never enters a distillation row.
- **Fault injection:** control-plane cut, guider offline, attestation expiry mid-flight, mesh down, classifier down, replayed/duplicated events.
- **Golden sets:** classifier golden set (MVP-2) and per-class golden routing sets (AD-2) are versioned artifacts with owners.
- **Acceptance:** MVP §12 (9 steps) and Adaptive §12 (17 steps) as scripted CI jobs against staging.

---

## 7. Sequencing and critical path

```
wk:        1  2  3  4  5  6  7  8  9 10 11 12 13 14 | 15 ......................... ~34
MVP-0      ████
MVP-1            ████
MVP-2      ░░░░░░░░ ██████        (░ = golden-set labelling, domain reviewers)
MVP-3                     ████
MVP-4                  ██████     (Publisher change negotiated from wk 1)
MVP-5                           ████
AD-2 (sim)                ░░████████████   (parallel; separate engineers, no prod impact)
AD-1                           ░░░░ 30-day clock ░░░░ |██
AD-3                                                 | ███
AD-4                                                 |    █████
AD-5                                                 |         ████
AD-6                                                 |             ████ + fine-tune cycle
```

**Critical path:** R1 decision → schemas → resolution → classifier golden set → Publisher-side guider enforcement → acceptance. The two items most likely to slip are both people-dependent, not code-dependent: **golden-set labelling by domain reviewers** and the **verdict checks owned by other teams (membrane Publisher, Card/blackboard store)**. Start all three in week 1.

---

## 8. Decisions still open, in the order they block work

| By | Decision | Owner | Recommended default |
|---|---|---|---|
| Before MVP-0 | Named individuals for the five approved roles, per deployment; confirm the unit of the USD 0.25 T3 threshold | Eric | Per task execution |
| MVP-1 | KMS/HSM product and workload-identity service | Eng + security | Per hosting environment |
| MVP-1 | Seed values for policy bands: `TTL_base`/`TTL_floor`, `h`, posture thresholds, signal weights, lease interval, audit-sample floor | Eng + Domain Authority | Conservative seeds; they adapt from there |
| MVP-2 | Width of the signed threshold band (operating point is emergent, D11); which classes (if any) get `structural_input`; which two self-hosted lineages serve as classifier + comparator | Eng + Domain Authority | Conservative thresholds tuned on golden set; no class flagged until golden-set evidence exists |
| MVP-5 | KPI owners + alert thresholds [GAP-D]; "Time to Pricing Confidence" keep/drop | Ops | Drop unless someone claims it |
| AD-2 | Surrogate calibration method (OI-7) | Eng | — |
| AD-1 | Commodity ledger sampling rate + digest batch interval (R6; replaces OI-6) | Domain Authority | 10%; hourly digest |
| AD-3 | Vertical compliance overlays (OI-3) | Eric + vertical leads | — |
| AD-4 | λ per class + cost normalisation (OI-5); attribution windows (OI-9); Steward/Cost Owner + T3 threshold (OI-4); whether normative tier may ever learn live | Steward + Finance + Domain Authority | Shadow-only for normative |
| Non-blocking | L5 federation opt-in (OI-8) | Eric | Off |

---

## 9. Top risks

1. **Privacy-scale inversion (R1)** — decided (P3 = most sensitive) and no code exists yet, so the exposure is the July FRD text. Mitigation: patch it first; enum + `may_receive()` + invariant test before any schema is written.
2. **Classifier under-tightening** is silent by nature. Mitigation: recall-weighted golden set, rules layer as a floor, drift monitor, "unavailable ⇒ tighten."
3. **Classifier latency** on sub-second classes. Mitigation: measure in MVP-2; rules-only fast path may be acceptable for classes whose *inputs* are structurally non-narrative (embedding, schema validation) — but that is a governance-policy decision, not an engineering shortcut.
4. **Guider as both overseer and reward signal** invites reward hacking once learning starts. Mitigation: divergence monitor is a hard precondition for AD-4; guider routing stays outside the optimizer permanently.
5. **Lineage pool narrows** as the flywheel distils from winners. Mitigation: lineage-as-set (D6); track "lineage-diverse guider availability" as a console metric.
6. **Adaptive safety parameters become an attack surface** if they can move in both directions. Mitigation: the ratchet principle (Trust Architecture §1) — automation only tightens; loosening is a human act on recommendation.
7. **Egress classification cost.** Every non-exact-match publish incurs a classifier call and possibly a guider call. Mitigation: exact-hash fast path; measure in MVP-3; budget it per membrane.

---

## 10. First two weeks

1. Patch both FRDs per the §0 decision log (the "Follow-on edits" column is the edit list). Confirm with the Redactor/Fabric owner that deployed code already treats P3 as most sensitive.
2. Name the five role holders; decide governance-key custody; run the domain root key ceremony.
3. Greenfield confirmed: write the interface contract first (`ReasoningRequest` / `SealedResult` / `EgressCheck` schemas, manifest format) and the `ir-conformance` attack suite skeleton, before any service code.
4. Open the conversation with the membrane Publisher owners **and** the Card/blackboard store owners about verdict enforcement (D5).
5. Recruit domain reviewers and begin classifier golden-set labelling.
6. Land `ir_core` (lattice, privacy enum, eligibility pipeline, `Selector` seam) with the invariant test suite — before any service code.
7. Land migrations + event schemas (D7, R9).
