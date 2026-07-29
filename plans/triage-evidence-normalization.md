# Plan: Triage Evidence Reference Normalization

> Source PRD:
> [Triage Evidence Reference Normalization PRD](../prds/triage-evidence-normalization-prd.md)

## Architectural decisions

Durable decisions that apply across all phases:

- **Trust boundary**: Model responses are untrusted provider data. Observation identifiers become
  canonical evidence only after deterministic backend validation and normalization.
- **Contract separation**: The provider-facing triage schema and the canonical resolved-triage
  schema are separate contracts with independent versions.
- **New route versions**: New workflows use `fast-triage-prompt-v3` with
  `triage-provider-output-v4`.
- **Canonical version**: Resolved triage remains schema version 3 because its persisted business
  shape and meaning do not change.
- **Evidence policy**: `triage-evidence-policy-v1` is immutable, owned by code, and pinned in the
  workflow execution contract. It is not configurable through `.env`.
- **Provider safety ceiling**: Provider-output v4 accepts 1–100 role references and 1–100
  readability references per predicted document.
- **Canonical limit**: At most five unique grounded role references and five unique grounded
  readability references are retained per document.
- **Validation order**: Every supplied reference is resolved against the current document before
  deduplication or canonical reduction. An invalid reference anywhere rejects the result.
- **Selection order**: Valid references are stable-deduplicated and the first five unique
  references are retained. Provider order is meaningful because the prompt requires
  strongest-to-weakest ordering.
- **Identity boundary**: Identity selections keep their existing maximum of two and retain their
  existing single-observation grounding rules.
- **Retry semantics**: Valid over-citation and duplicate references are normalized without another
  model call. Malformed output and invalid grounding continue through the existing fail-closed
  path.
- **Error taxonomy**: More than 100 references in either evidence field produces
  `MODEL_OUTPUT_LIMIT_EXCEEDED`. Other provider-structure failures remain
  `MODEL_SCHEMA_VALIDATION_FAILED`; unavailable or cross-document references remain grounding
  failures.
- **Prompt behavior**: The model is instructed to return 1–5 direct references per evidence field,
  ordered strongest to weakest, and not to cite every OCR line.
- **Persistence**: PostgreSQL stores only canonical evidence in the triage result, plus a bounded
  normalization report and deterministic raw-provider-output SHA-256.
- **Raw response boundary**: PostgreSQL does not gain a generic raw model invocation ledger.
  Complete provider input/output remains available through the existing Phoenix tracing
  configuration.
- **Reconstruction**: PostgreSQL remains sufficient to reconstruct the canonical decision and
  explain evidence normalization without Phoenix.
- **Observability**: Fast triage emits a child normalization span containing supplied, unique,
  retained, and dropped references, counts, reason codes, digest, and execution versions.
- **Metrics**: Numeric normalization metrics use bounded dimensions only. Observation identifiers
  are trace data, never metric labels.
- **Compatibility**: Workflows pinned to `fast-triage-prompt-v2` and `triage-output-v3` remain
  executable with their legacy behavior.
- **API compatibility**: The member-facing FastAPI request and response schemas do not change.
- **Model independence**: The configured Bedrock model is not changed as part of this feature.
  Model evaluation happens after the correctness boundary is fixed.
- **Deferred work**: Large-document OCR selection, chunking, semantic reranking, and general model
  output repair remain outside this plan.

## Plan status

- [ ] Phase 1: Versioned triage foundation
- [ ] Phase 2: Valid over-citation tracer
- [ ] Phase 3: Duplicate-reference normalization
- [ ] Phase 4: Adversarial failure boundaries
- [ ] Phase 5: Durable recovery and legacy compatibility
- [ ] Phase 6: Acceptance and regression closure

---

## Phase 1: Versioned triage foundation

**User stories**: 3–4, 21–34

### What to build

Establish the new versioned path using a normal model response that already contains 1–5 unique,
grounded references. This first tracer runs from workflow creation through prompt selection,
provider parsing, evidence-policy resolution, canonical triage, PostgreSQL persistence,
reconstruction, and Phoenix tracing without requiring over-citation to exercise the path.

The new provider contract is deliberately tolerant up to the safety ceiling, while the canonical
result remains bounded by the policy. The execution contract records the evidence-policy version
alongside the existing route versions. The database change is additive, and the public API remains
unchanged.

This phase creates the complete version and audit spine used by every later behavioral slice. It
must not yet rely on duplicates or more than five references to prove success.

### Acceptance criteria

#### Provider and prompt contract

- [ ] `fast-triage-prompt-v3` is registered as a supported prompt.
- [ ] The v3 prompt requires 1–5 role references and 1–5 readability references per document.
- [ ] The v3 prompt requires strongest-to-weakest reference order.
- [ ] The v3 prompt gives direct role/readability evidence examples.
- [ ] The v3 prompt explicitly prohibits citing every OCR observation.
- [ ] The existing instruction to copy supplied observation identifiers exactly remains present.
- [ ] The prompt continues to forbid model-generated hashes, page data, regions, policy
  conclusions, and payable amounts.
- [ ] `triage-provider-output-v4` is represented by a provider-facing schema distinct from the
  canonical resolved-triage schema.
- [ ] Provider-output v4 accepts structurally valid evidence-reference sequences containing
  between 1 and 100 items.
- [ ] Provider-output v4 continues to reject unknown fields, invalid enums, invalid identifier
  formats, missing documents, duplicate document predictions, and excessive identity selections.
- [ ] The canonical resolved result remains schema version 3.

#### Policy and workflow contract

- [ ] `triage-evidence-policy-v1` resolves through an immutable code-owned policy registry.
- [ ] Policy v1 exposes the 100-reference safety ceiling and five-reference canonical limit.
- [ ] Policy v1 defines full-sequence grounding, stable deduplication, and first-five retention.
- [ ] Workflow creation pins the evidence-policy version with its model route.
- [ ] Newly created workflows select the v3 prompt, v4 provider schema, and policy-v1 combination.
- [ ] The evidence-policy version is included in the durable execution-contract representation.
- [ ] No environment setting can alter policy-v1 behavior.
- [ ] Unknown prompt, provider-schema, or policy versions are rejected explicitly.
- [ ] Unsupported version combinations are rejected before a model call.

#### No-op normalization tracer

- [ ] A normal response containing one unique grounded reference per field parses through
  provider-output v4.
- [ ] Every reference is validated against OCR observations belonging to the predicted document.
- [ ] The normalizer returns unchanged canonical role and readability reference tuples.
- [ ] No deduplication or truncation reason code is emitted for an unchanged response.
- [ ] Readability preview provenance comes from the first retained readability reference.
- [ ] Identity values continue to be hydrated from backend-owned observations.
- [ ] The workflow reaches the same downstream state it reached before the new boundary.

#### Persistence and reconstruction

- [ ] The database migration adds nullable normalization-report and raw-output-digest storage
  without rewriting existing triage results.
- [ ] A new triage result stores canonical evidence references in the existing business fields.
- [ ] A new triage result stores an evidence normalization report for both evidence fields.
- [ ] The unchanged report records received, unique, and retained counts consistently.
- [ ] The unchanged report records zero duplicate and over-citation drops.
- [ ] The report records policy-v1 and contains no invented normalization reason code.
- [ ] The raw provider-output digest is computed from deterministic canonical JSON.
- [ ] Repeated hashing of semantically identical output with different object-key ordering yields
  the same digest.
- [ ] Internal reconstruction returns canonical evidence, the normalization report, and raw-output
  digest.
- [ ] The public claim projection does not expose new internal fields.

#### Observability

- [ ] Fast triage emits a child evidence-normalization span under the existing workflow/model
  trace.
- [ ] The span belongs to the existing claim session and claim-version trace.
- [ ] The span records supplied, unique, retained, and dropped references for both fields.
- [ ] The span records received, unique, retained, duplicate-drop, and over-citation-drop counts.
- [ ] The span records model route, model identifier, prompt version, provider-schema version,
  canonical-schema version, evidence-policy version, and raw-output digest.
- [ ] The normal no-op case is distinguishable from a recovered normalization case.
- [ ] Numeric metrics use bounded field, outcome, route, and version dimensions.
- [ ] Observation identifiers do not appear as metric labels.
- [ ] PostgreSQL and Phoenix contain the same canonical references and raw-output digest.

#### Phase verification

- [ ] Focused provider-contract tests pass.
- [ ] Focused policy-resolution tests pass.
- [ ] The no-op normalization unit tests pass.
- [ ] The normal-response persistence and reconstruction integration test passes.
- [ ] The normal-response Phoenix span test passes.
- [ ] Existing deterministic tests remain passing before Phase 2 begins.

---

## Phase 2: Valid over-citation tracer

**User stories**: 1–2, 5, 9, 14–18, 35–38, 41–42, 45–52, 54, 56, 60

### What to build

Deliver the central tracer bullet using the captured DeepSeek-style response with 30 valid
readability references. The response must pass the provider boundary, have all 30 references
grounded against the correct document, retain the first five unique references, persist the exact
normalization transformation, and continue through normal claim processing without a model retry.

The same deterministic behavior applies to role evidence. This slice proves that changing the
provider model is unnecessary to recover from valid over-citation and that the backend—not prompt
compliance—is the correctness boundary.

### Acceptance criteria

#### Complete-reference validation

- [ ] A v4 provider response containing 30 valid readability references parses successfully.
- [ ] A v4 provider response containing 30 valid role references parses successfully.
- [ ] All supplied references are checked against observations belonging to the current document.
- [ ] Validation is completed before any reference is discarded.
- [ ] The provider response's original order is preserved during validation.
- [ ] Role and readability sequences are processed independently.

#### Canonical reduction

- [ ] Thirty valid unique references produce exactly five canonical references.
- [ ] The retained references are the first five supplied references.
- [ ] The remaining 25 references are classified as over-citation drops.
- [ ] The output emits `TRIAGE_EVIDENCE_REFS_TRUNCATED`.
- [ ] The output does not emit the deduplication code when all 30 references are unique.
- [ ] Canonical selection is identical across repeated executions.
- [ ] Readability preview provenance is derived from the first retained readability reference.
- [ ] Canonical resolved triage remains schema version 3.
- [ ] Document role, readability status, and identity semantics are not changed by reduction.

#### No-retry behavior

- [ ] Valid over-citation completes without a second model invocation.
- [ ] The model-attempt count remains one.
- [ ] The claim proceeds through the same downstream gates as an equivalent concise response.
- [ ] The behavior is implemented independently of any model identifier.
- [ ] The captured response passes using the currently configured model route.

#### Durable audit

- [ ] PostgreSQL stores exactly five canonical role references when role over-citation occurs.
- [ ] PostgreSQL stores exactly five canonical readability references when readability
  over-citation occurs.
- [ ] The normalization report records 30 received, 30 unique, five retained, zero duplicate
  drops, and 25 over-citation drops for the captured field.
- [ ] The report contains all five retained references.
- [ ] The report contains all 25 over-citation-dropped references.
- [ ] The report contains `TRIAGE_EVIDENCE_REFS_TRUNCATED`.
- [ ] The report and business reference columns agree exactly.
- [ ] Reconstruction after closing and reopening the database session returns the same report.
- [ ] The persisted raw-output digest matches a newly computed digest of the captured response.
- [ ] The report remains bounded by the 100-reference and ten-document provider limits.

#### Trace and metrics

- [ ] Phoenix receives the complete captured provider response through the existing model span.
- [ ] The normalization child span records all 30 supplied references.
- [ ] The normalization child span records the five retained and 25 dropped references.
- [ ] The child span records the truncation reason code.
- [ ] The child span counts match the PostgreSQL report counts.
- [ ] The child span digest matches the PostgreSQL digest.
- [ ] The over-citation metric increments once for the affected field.
- [ ] Received, retained, and over-citation-drop numeric metrics have the expected values.
- [ ] Observation references are not used as metric dimensions.

#### Phase verification

- [ ] A unit test proves 30 valid references normalize to five.
- [ ] A captured-response application test proves the DeepSeek-style payload parses and resolves.
- [ ] A persistence integration test proves canonical references and the report are atomic.
- [ ] A workflow integration test proves no retry and normal downstream continuation.
- [ ] A Phoenix integration test proves raw and canonical evidence visibility.
- [ ] Phase 1 tests remain passing.

---

## Phase 3: Duplicate-reference normalization

**User stories**: 12–13, 16–17, 37–40, 45–52, 54

### What to build

Extend the successful v4 path to treat repeated valid references as recoverable model noise.
Duplicate removal is stable: the first occurrence is retained in its original position and later
occurrences are recorded as duplicate drops. Duplicates do not consume one of the five canonical
slots.

Prove pure deduplication and mixed deduplication-plus-over-citation end-to-end, including
PostgreSQL reconstruction and Phoenix traces.

### Acceptance criteria

#### Stable deduplication

- [ ] Repeated valid references no longer fail grounding under provider-output v4.
- [ ] Every occurrence is grounded before duplicate removal.
- [ ] The first occurrence of each reference determines unique-reference order.
- [ ] Later occurrences are removed deterministically.
- [ ] Duplicate occurrences do not consume canonical slots.
- [ ] A unique reference following duplicates can still enter the first-five canonical set.
- [ ] Repeated normalization of the same sequence produces byte-equivalent canonical output and
  report data.
- [ ] Role and readability duplicates are normalized independently.

#### Reason classification

- [ ] Pure duplicate input emits `TRIAGE_EVIDENCE_REFS_DEDUPLICATED`.
- [ ] Pure duplicate input does not emit the truncation code when five or fewer unique references
  remain.
- [ ] More than five unique references plus duplicates emits both deduplication and truncation
  codes.
- [ ] Duplicate-dropped references and over-citation-dropped references are reported separately.
- [ ] Received count equals retained count plus duplicate-drop count plus over-citation-drop count.
- [ ] Unique count equals retained count plus over-citation-drop count.

#### No-retry and downstream behavior

- [ ] Duplicate-only normalization does not trigger a second model call.
- [ ] Mixed duplicate and over-citation normalization does not trigger a second model call.
- [ ] Preview provenance follows the first retained readability reference after stable
  deduplication.
- [ ] Role, readability, identity, and downstream adjudication results match an equivalent concise
  response.

#### Durable audit and tracing

- [ ] PostgreSQL stores only stable-deduplicated canonical references.
- [ ] The normalization report preserves the received sequence and partitions dropped occurrences
  by reason.
- [ ] The report records both reason codes when both behaviors occur.
- [ ] Reconstruction produces the same canonical references and drop partitions.
- [ ] The normalization span contains received, unique, retained, duplicate-dropped, and
  over-citation-dropped sequences.
- [ ] Trace counts and reason codes agree with PostgreSQL.
- [ ] Deduplication metrics use bounded dimensions.
- [ ] No observation identifier is emitted as a metric label.

#### Phase verification

- [ ] Unit tests cover adjacent duplicates, separated duplicates, all-identical references, and
  duplicates around the fifth canonical boundary.
- [ ] Unit tests cover duplicate-only and duplicate-plus-over-citation reports.
- [ ] An application test proves a duplicate provider response succeeds without retry.
- [ ] A persistence/reconstruction test proves duplicate audit data is durable.
- [ ] A Phoenix test proves duplicate and mixed reason visibility.
- [ ] Phases 1–2 tests remain passing.

---

## Phase 4: Adversarial failure boundaries

**User stories**: 6–11, 53, 55

### What to build

Prove that tolerance does not weaken the grounding boundary. Explicitly distinguish provider output
that is too large, structurally malformed, incomplete, or grounded to unavailable evidence.

Most importantly, validate adversarial references after the canonical prefix. A structurally valid
but unavailable or cross-document reference in position 30 must fail the complete result rather
than being hidden by first-five retention. Each failure must be visible in the workflow trace and
must not persist a misleading canonical triage result.

### Acceptance criteria

#### Safety ceiling

- [ ] Exactly 100 role references are accepted by provider-output v4.
- [ ] Exactly 100 readability references are accepted by provider-output v4.
- [ ] A 101st role reference produces `MODEL_OUTPUT_LIMIT_EXCEEDED`.
- [ ] A 101st readability reference produces `MODEL_OUTPUT_LIMIT_EXCEEDED`.
- [ ] Output-limit failure is distinguishable from generic schema validation in logs and traces.
- [ ] An output-limit failure performs no canonical reduction.
- [ ] An output-limit failure persists no successful triage result or normalization report.

#### Structural validation

- [ ] Empty required role references remain rejected.
- [ ] Empty required readability references remain rejected.
- [ ] Malformed observation identifiers remain rejected by the provider schema.
- [ ] Missing document predictions remain rejected.
- [ ] Duplicate predictions for one client document remain rejected.
- [ ] Predictions for unknown client documents remain rejected.
- [ ] Excessive identity selections remain rejected.
- [ ] Structural failures retain `MODEL_SCHEMA_VALIDATION_FAILED` unless they are specifically
  output-limit failures.

#### Complete grounding

- [ ] An unavailable reference in position one fails grounding.
- [ ] An unavailable reference in position 30 fails grounding.
- [ ] A reference belonging to another submitted document in position one fails grounding.
- [ ] A cross-document reference in position 30 fails grounding.
- [ ] A duplicate of an unavailable reference still fails grounding before deduplication.
- [ ] A sequence whose first five references are valid still fails when a later reference is
  invalid.
- [ ] Neither deduplication nor truncation is allowed to conceal a grounding failure.
- [ ] Identity values not present in referenced OCR text continue to fail grounding.
- [ ] Missing backend preview provenance continues to fail safely.

#### Failure persistence and observability

- [ ] The normalization span records the failure category and failed evidence field.
- [ ] The trace preserves the supplied reference sequence needed to diagnose the failure.
- [ ] Output-limit, schema, and grounding failures have distinct bounded outcome values.
- [ ] Failure metrics contain no reference identifiers as labels.
- [ ] No canonical document triage result is committed after a failed normalization.
- [ ] Existing durable retry and terminal-failure rules remain authoritative.
- [ ] A failed attempt cannot leave a partial normalization report that appears successful.

#### Phase verification

- [ ] Boundary tests cover 100 and 101 references for both evidence fields.
- [ ] Schema tests cover every retained structural constraint.
- [ ] Grounding tests cover unavailable and cross-document references after the canonical prefix.
- [ ] Transactional integration tests prove no misleading canonical result is persisted.
- [ ] Observability tests prove failure taxonomy and diagnostic trace content.
- [ ] Phases 1–3 tests remain passing.

---

## Phase 5: Durable recovery and legacy compatibility

**User stories**: 26–44, 58

### What to build

Complete the durability boundary for both new and historical workflows. A new workflow must resume
with its pinned evidence policy even if current runtime defaults change. A legacy workflow pinned
to the v2 prompt and v3 provider schema must continue using its legacy parser and behavior.

Existing database rows without normalization metadata remain reconstructable and explicitly report
that the metadata is unavailable. New rows retain enough data to match their durable canonical
evidence to a Phoenix provider response using the raw-output digest.

### Acceptance criteria

#### New workflow recovery

- [ ] A newly created workflow persists prompt-v3, provider-output-v4, canonical-output-v3, and
  policy-v1 identities.
- [ ] Recovery reconstructs the exact provider schema and evidence policy from the execution
  contract.
- [ ] Changing current route defaults does not change a resumed workflow.
- [ ] Changing the configured model identifier does not change a resumed workflow's pinned model.
- [ ] A recovered workflow produces the same canonical references as its original process.
- [ ] Unsupported policy versions fail recovery before leasing or invoking provider work.
- [ ] Unsupported route combinations fail recovery explicitly rather than falling back.

#### Legacy workflow execution

- [ ] A legacy execution contract containing prompt-v2 and provider-output-v3 remains readable.
- [ ] Absence of a policy field is accepted only for the explicitly supported legacy combination.
- [ ] A legacy workflow rebuilds its v3 provider parser rather than adopting v4 behavior.
- [ ] A legacy response at its prior accepted boundary behaves exactly as before.
- [ ] A legacy response outside its prior schema limit retains its prior failure behavior.
- [ ] Legacy recovery does not synthesize a policy-v1 normalization report.
- [ ] A missing policy field on any nonlegacy route is rejected.

#### Database compatibility

- [ ] The additive migration upgrades a database containing historical triage rows.
- [ ] Historical rows retain their original canonical evidence columns.
- [ ] Historical rows with null normalization metadata remain reconstructable.
- [ ] Reconstruction labels missing legacy normalization metadata as unavailable.
- [ ] Reconstruction never invents received or dropped references for a legacy row.
- [ ] New rows require a policy version, normalization report, and raw-output digest at the
  application boundary.
- [ ] New persistence writes canonical references and audit metadata atomically.
- [ ] Schema-drift detection recognizes the new columns and constraints.

#### Durable reconstruction

- [ ] A new normalized result can be reconstructed after worker and API restart.
- [ ] Reconstructed canonical references match the persisted business columns.
- [ ] Reconstructed normalization counts and partitions are internally consistent.
- [ ] Reconstructed evidence-policy version matches the workflow execution contract.
- [ ] Reconstructed raw-output digest matches the normalization report.
- [ ] PostgreSQL reconstruction remains sufficient after Phoenix data is unavailable.
- [ ] Phoenix and PostgreSQL can be correlated when both are available.
- [ ] Complete raw provider output is not duplicated into a new generic database ledger.

#### API compatibility

- [ ] Claim submission accepts the same public request shape.
- [ ] Claim polling returns the same public response shape.
- [ ] Review and member-action contracts are unchanged.
- [ ] No normalization detail, raw output, or internal evidence reference is added to the member
  response.

#### Phase verification

- [ ] Recovery tests prove a new workflow retains policy-v1 across changed runtime defaults.
- [ ] Compatibility tests prove legacy v2/v3 workflows remain executable.
- [ ] Negative tests reject missing or unknown policy versions on nonlegacy routes.
- [ ] Migration tests upgrade representative historical rows.
- [ ] Reconstruction tests cover both legacy-null and new-report rows.
- [ ] Public API contract tests show no response-schema change.
- [ ] Phases 1–4 tests remain passing.

---

## Phase 6: Acceptance and regression closure

**User stories**: 19–20, 25, 43, 56–59

### What to build

Close the feature with proof that the new boundary fixes the captured live-model behavior without
changing model configuration, identity semantics, downstream claim decisions, or public APIs.

Run focused normalization tests, the full deterministic suite, legacy recovery coverage, database
checks, and the twelve-case recorded rendered evaluation gate. Verify that the same retained
references and raw-output digest can be located in PostgreSQL and Phoenix. Record the actual
results without claiming paid live behavior that was not exercised.

### Acceptance criteria

#### Captured regression

- [ ] The captured DeepSeek-style response with 30 valid readability references passes.
- [ ] The captured response retains exactly five readability references.
- [ ] The captured response invokes the model exactly once.
- [ ] The captured response persists the expected truncation report.
- [ ] The captured response emits the expected Phoenix child span and metrics.
- [ ] The captured response passes without changing the configured Bedrock model.

#### Semantic non-regression

- [ ] Identity-selection maximum remains two.
- [ ] Identity value grounding remains unchanged.
- [ ] Document role and readability enums remain unchanged.
- [ ] Preview provenance still comes from backend-owned render data.
- [ ] Models remain unable to supply hashes, page numbers, regions, policy decisions, or payable
  amounts.
- [ ] Downstream evidence sufficiency, policy adjudication, and payable-amount calculation remain
  deterministic.
- [ ] An equivalent concise and over-cited response yields the same claim outcome.
- [ ] Member-facing API schemas remain unchanged.

#### Evaluation gates

- [ ] All evidence-normalization unit tests pass.
- [ ] All provider-contract and routing tests pass.
- [ ] All persistence, reconstruction, workflow recovery, and observability integration tests
  pass.
- [ ] All legacy pinned-workflow tests pass.
- [ ] All twelve recorded rendered evaluation cases pass.
- [ ] The complete deterministic test suite passes.
- [ ] Any skipped test is explicitly identified as paid-live or otherwise outside this PRD.

#### Repository quality gates

- [ ] Formatting check passes.
- [ ] Lint check passes.
- [ ] Strict type checking passes.
- [ ] Database migration drift check passes.
- [ ] Whitespace and patch-integrity checks pass.
- [ ] The repository contains no committed raw claim documents, runtime logs, credentials, or
  generated Phoenix storage from verification.

#### Audit agreement

- [ ] PostgreSQL canonical references match Phoenix retained references for the acceptance claim.
- [ ] PostgreSQL raw-output digest matches the digest recorded in Phoenix.
- [ ] PostgreSQL reason codes and counts match the normalization span.
- [ ] Reconstruction succeeds when Phoenix is treated as unavailable.
- [ ] Metrics expose counts and bounded outcomes without observation IDs as dimensions.
- [ ] Failure traces distinguish output-limit, schema, and grounding failures.

#### Completion record

- [ ] The implementation plan status marks all six phases complete only after their individual
  acceptance criteria pass.
- [ ] The backend completion documentation describes the tolerant-provider/strict-canonical
  boundary.
- [ ] The documentation records the prompt, provider-schema, canonical-schema, and policy versions.
- [ ] The documentation states that model switching was not required for the correctness fix.
- [ ] The documentation keeps large-document selection/chunking and general output repair listed
  as follow-up work.
- [ ] Recorded verification results use actual current counts and do not overstate live AWS
  coverage.

## Definition of done

This plan is complete when:

- a captured 30-reference provider response succeeds without retry;
- every provider reference is grounded before any reduction;
- canonical role and readability evidence are independently bounded to five references;
- duplicates and over-citation are deterministically classified and reconstructed;
- 101 references, malformed output, and invalid grounding fail with the correct category;
- new workflows recover with policy-v1 while legacy v2/v3 workflows retain their behavior;
- PostgreSQL and Phoenix agree on canonical references, normalization counts, versions, and raw
  output digest;
- public API and downstream adjudication semantics remain unchanged; and
- all focused, deterministic, recorded-evaluation, formatting, lint, type, and migration gates
  pass.
