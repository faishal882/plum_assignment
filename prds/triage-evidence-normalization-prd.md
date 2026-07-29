# Triage Evidence Reference Normalization PRD

**Status:** Approved for implementation planning  
**Scope:** Make fast-triage evidence handling tolerant of valid model over-citation while preserving
strict grounding, deterministic provenance, and replay compatibility  
**Parent product requirements:** `backend_v1_operational_prd.md`  
**Domain language:** [`../CONTEXT.md`](../CONTEXT.md)  
**External API impact:** None

## Problem Statement

The fast-triage model performs semantic work over backend-issued OCR observations. It classifies
each document, determines readability, selects patient-name evidence, and cites opaque observation
identifiers as support for its conclusions.

The current provider-output schema allows at most 20 role evidence references and at most 20
readability evidence references per document. This limit is enforced while parsing the untrusted
provider response, before the application can resolve those references against backend-owned OCR
observations.

A live model can correctly classify a document and cite only valid observation identifiers while
still returning more evidence than the application needs. A captured DeepSeek response returned
30 valid readability references. Pydantic rejected the entire response with
`MODEL_SCHEMA_VALIDATION_FAILED` solely because it exceeded the schema's 20-reference limit.
Grounding and canonicalization never ran.

This creates four architectural problems:

1. A recoverable model behavior is treated as an unrecoverable schema failure.
2. An arbitrary canonical-storage preference leaks into the provider boundary.
3. Increasing the schema limit from 20 to 50 only moves the failure threshold and does not define
   deterministic evidence-selection behavior.
4. Blindly truncating before validation could hide an invented, unavailable, or cross-document
   reference after the retained prefix.

The system needs separate contracts for:

- what an untrusted provider may return;
- what the application will accept as grounded;
- what evidence the backend retains as canonical decision support; and
- what normalization information is persisted and traced for auditability.

The change must work across model providers, preserve existing pinned workflows, keep decision
reconstruction possible from PostgreSQL, and avoid changing the member-facing claim API.

## Solution

Introduce a versioned evidence-reference normalization boundary between provider-output parsing and
canonical triage resolution.

New fast-triage workflows will use:

- prompt version `fast-triage-prompt-v3`;
- provider-output schema version `triage-provider-output-v4`;
- evidence policy version `triage-evidence-policy-v1`; and
- the existing canonical resolved-triage schema version 3, because its persisted business shape
  does not change.

The new prompt will direct the model to return 1–5 observation references for each role and
readability conclusion, ordered from strongest to weakest. It will tell the model to cite direct,
discriminative lines such as the document title, patient line, bill or receipt line, prescription
line, or total-amount line instead of citing every OCR line.

The provider DTO will remain strict about structure, document count, identifier format, enum
values, required fields, and unknown fields. It will no longer impose the old canonical maximum of
20 references. It will enforce an application safety ceiling of 100 references per evidence field.
Exceeding that ceiling will produce the explicit error code `MODEL_OUTPUT_LIMIT_EXCEEDED`, rather
than a generic schema-validation failure.

For each document and for each of the two evidence fields, the backend will:

1. validate every supplied reference against the OCR observations belonging to that document;
2. reject the complete result if any reference is unavailable or belongs to another document,
   even when the invalid reference appears after the fifth item;
3. remove duplicate references while preserving the model's first-occurrence order;
4. retain the first five unique grounded references as the canonical evidence set;
5. record counts, selected references, dropped references, and normalization reason codes; and
6. use the first retained readability reference to select preview provenance.

Valid over-citation and duplicates are recoverable normalization cases and will not trigger another
model call. Invalid grounding, malformed output, missing evidence, missing document coverage, and
unsupported versions continue to fail safely.

The evidence policy will be immutable, code-owned, and pinned in each workflow execution contract.
It will not be configurable through `.env`. A resumed workflow will use the policy version recorded
when that workflow was created, regardless of the application's current defaults.

PostgreSQL will persist canonical references and a bounded normalization report, plus the
deterministic SHA-256 digest of the raw provider response. It will not store the complete raw
provider response as a new business record. Phoenix will retain the complete model invocation and
a child normalization span containing the supplied and retained references, counts, reason codes,
and execution versions.

The existing `fast-triage-prompt-v2` and `triage-output-v3` route remains supported for workflows
already pinned to it. New workflows use the new prompt, provider schema, and evidence policy.

## User Stories

### Correct provider handling

1. As a member, I want a correctly understood document to continue processing when the model cites
   more valid evidence than necessary, so that harmless over-citation does not stop my claim.
2. As a member, I want the same behavior regardless of the selected Bedrock model, so that claim
   reliability does not depend on one provider's citation style.
3. As an engineer, I want provider output treated as untrusted input, so that model-generated
   references never become canonical merely because they satisfy JSON syntax.
4. As an engineer, I want provider-format constraints separated from canonical evidence limits, so
   that a persistence preference cannot cause an early model-schema failure.
5. As an engineer, I want each evidence field to accept up to 100 provider references, so that
   realistic over-citation can be normalized within a bounded resource budget.
6. As an operator, I want responses above the absolute safety ceiling to fail with
   `MODEL_OUTPUT_LIMIT_EXCEEDED`, so that output-size failures are distinguishable from malformed
   schemas.
7. As an operator, I want missing or empty required evidence fields to remain failures, so that
   tolerance does not weaken the requirement for grounded support.
8. As an operator, I want malformed observation identifiers to remain schema failures, so that the
   resolver receives only structurally valid opaque references.

### Grounding and normalization

9. As an auditor, I want every provider-supplied reference validated before any reference is
   discarded, so that truncation cannot conceal fabricated evidence.
10. As an auditor, I want a reference to another document rejected, so that evidence cannot leak
    across document boundaries.
11. As an auditor, I want an unknown reference rejected even when it occurs after the first five
    references, so that the canonical prefix cannot mask an ungrounded response.
12. As an engineer, I want duplicate valid references accepted and deterministically deduplicated,
    so that repeated citations do not stop processing.
13. As an engineer, I want duplicate removal to preserve first-occurrence order, so that
    normalization is stable and reproducible.
14. As an operations reviewer, I want at most five role references retained per document, so that
    the canonical evidence set remains concise.
15. As an operations reviewer, I want at most five readability references retained per document,
    so that the canonical evidence set remains concise.
16. As an operations reviewer, I want role and readability evidence normalized independently, so
    that one field's citation behavior cannot alter the other field.
17. As an engineer, I want the first five unique grounded references retained, so that selection
    remains deterministic without introducing a second heuristic ranker.
18. As an auditor, I want the preview derived from the first retained readability reference, so
    that preview provenance follows the canonical evidence order.
19. As an engineer, I want identity selections to retain their existing maximum of two and their
    existing single-observation grounding behavior, so that this change does not broaden identity
    semantics.
20. As a policy owner, I want normalization to affect only evidence references, so that document
    role, readability, identity, and downstream adjudication authority remain unchanged.

### Prompt behavior

21. As a model integrator, I want the prompt to request 1–5 references, so that compliant models
    naturally return a concise result.
22. As a model integrator, I want references ordered strongest to weakest, so that deterministic
    prefix retention preserves the provider's stated relevance.
23. As a model integrator, I want direct examples of useful evidence lines, so that the model
    prefers discriminative evidence over generic OCR text.
24. As a model integrator, I want the prompt to prohibit citing every OCR line, so that token use
    and trace noise remain bounded.
25. As an evaluator, I want prompt improvement and backend tolerance tested independently, so that
    prompt compliance is not mistaken for a correctness boundary.

### Versioning and recovery

26. As an auditor, I want the prompt, provider schema, canonical schema, and evidence policy
    versions recorded separately, so that each transformation can be reconstructed.
27. As an engineer, I want new workflows pinned to `fast-triage-prompt-v3`, so that concise
    strongest-first citation guidance is reproducible.
28. As an engineer, I want new provider responses validated as `triage-provider-output-v4`, so
    that the tolerant wire contract is distinguishable from the prior contract.
29. As an engineer, I want canonical resolved results to remain at schema version 3, so that an
    unchanged business object is not versioned merely because its input boundary changed.
30. As an engineer, I want `triage-evidence-policy-v1` stored in the execution contract, so that
    normalization behavior is immutable for the life of a workflow.
31. As an operator, I want a resumed workflow to use its persisted evidence policy, so that a
    process restart cannot change the meaning of stored work.
32. As an operator, I want old workflows pinned to `fast-triage-prompt-v2` and
    `triage-output-v3` to remain executable, so that deployment of the change does not strand
    in-flight work.
33. As an engineer, I want unsupported version combinations to fail explicitly, so that the
    application never guesses which policy should apply.
34. As an engineer, I want evidence-policy selection owned by code rather than `.env`, so that
    local configuration cannot silently change deterministic evidence handling.

### Persistence and reconstruction

35. As an auditor, I want PostgreSQL to store only the retained canonical evidence references as
    the triage result, so that business reconstruction uses the same evidence as adjudication.
36. As an auditor, I want PostgreSQL to store a normalization report, so that I can explain how
    the provider references became canonical references without Phoenix.
37. As an auditor, I want the report to identify received, unique, retained, duplicate, and
    dropped counts, so that the transformation is quantitatively clear.
38. As an auditor, I want the report to include selected and dropped opaque references, so that
    the exact deterministic transformation can be verified.
39. As an auditor, I want normalization reason codes persisted, so that deduplication and
    over-citation can be distinguished.
40. As an auditor, I want the applicable evidence-policy version persisted with the report, so
    that the report has an explicit interpretation.
41. As an auditor, I want the deterministic digest of the raw provider output persisted, so that
    a captured trace can be matched to the durable record.
42. As a maintainer, I want the report bounded by the provider safety ceiling and document limit,
    so that a model cannot create unbounded JSONB records.
43. As a maintainer, I want decision reconstruction to expose canonical references and
    normalization metadata, so that a claim can be audited after traces expire.
44. As a maintainer, I do not want a new generic provider-invocation ledger introduced by this
    feature, so that the change remains focused on the triage correctness boundary.

### Observability

45. As an engineer, I want evidence normalization represented as a child span of fast triage, so
    that model output and deterministic backend handling are visible in one trace.
46. As an engineer, I want the normalization span to include raw supplied references, unique
    references, retained references, and dropped references, so that a live failure can be
    reconstructed from Phoenix.
47. As an engineer, I want the span to include received, unique, retained, duplicate, and dropped
    counts for each evidence field, so that over-citation is immediately visible.
48. As an engineer, I want model, prompt, provider-schema, canonical-schema, and evidence-policy
    versions on the span, so that traces are comparable across changes.
49. As an engineer, I want normalization reason codes on the span, so that successful recovery is
    distinguishable from an unchanged response.
50. As an engineer, I want the raw provider-output digest on the span and durable record, so that
    the two evidence surfaces can be correlated.
51. As an evaluator, I want over-citation and deduplication counts emitted as low-cardinality
    metrics, so that model behavior can be compared without using observation identifiers as
    metric labels.
52. As an evaluator, I want normalization outcome, model route, and version dimensions to use
    bounded values, so that Phoenix metrics remain scalable.
53. As an engineer, I want normalization failures recorded with their explicit error category, so
    that grounding failures, output-limit failures, and schema failures are separable.

### Reliability and evaluation

54. As an engineer, I want valid over-citation normalized without retrying the model, so that a
    deterministic repair does not add latency, cost, or nondeterminism.
55. As an engineer, I want invalid grounding to continue through the existing safe-failure path,
    so that tolerance cannot convert unsupported evidence into a decision.
56. As an evaluator, I want the captured 30-reference DeepSeek-style response to succeed without
    changing models, so that the architecture fix proves it addresses the root cause.
57. As an evaluator, I want all existing recorded rendered cases to remain passing, so that the
    normalization change does not weaken Backend v1 correctness.
58. As an evaluator, I want legacy pinned-route tests to remain passing, so that backward
    compatibility is proven rather than assumed.
59. As a model owner, I want model changes evaluated after this boundary is corrected, so that
    model selection is based on quality rather than used to mask a schema-design defect.
60. As a maintainer, I want normalization implemented as an isolated deterministic module, so that
    it can be exhaustively tested without invoking OCR, Bedrock, PostgreSQL, or LangGraph.

## Implementation Decisions

### Contract separation

- Introduce a dedicated provider-facing triage DTO for
  `triage-provider-output-v4`. It represents untrusted semantic predictions and is not the
  canonical domain result.
- Keep strict validation for required fields, identifier syntax, document count, enum values,
  unknown fields, and identity-selection count.
- Allow 1–100 role references and 1–100 readability references per predicted document in the v4
  provider DTO.
- Preserve the existing v3 provider DTO and parser for workflows pinned to the legacy route.
- Preserve canonical resolved-triage schema version 3 because its externally meaningful shape and
  semantics do not change.
- Map provider parsing errors by category. A reference-field count above 100 produces
  `MODEL_OUTPUT_LIMIT_EXCEEDED`; other structural errors continue to produce
  `MODEL_SCHEMA_VALIDATION_FAILED`.

### Evidence policy deep module

- Add an immutable `EvidenceReferencePolicy` abstraction selected by version.
- The v1 policy defines:
  - provider safety ceiling: 100 references per evidence field;
  - canonical role-reference limit: 5;
  - canonical readability-reference limit: 5;
  - stable first-occurrence deduplication;
  - complete grounding validation before reduction; and
  - strongest-first provider order as the canonical tie-breaker.
- Expose one deterministic normalization operation that accepts provider references, available
  references for the current document, an evidence-field kind, and a policy.
- Return both a canonical reference tuple and a structured normalization result.
- Do not introduce keyword ranking, confidence ranking, semantic reranking, or another model call
  in policy v1.
- Validate the full supplied sequence against the current document before deduplication or
  truncation. Any unavailable or cross-document reference rejects the result.
- Stable-deduplicate valid references, retain the first five unique references, and classify
  omitted items as duplicate drops or over-citation drops.
- Emit `TRIAGE_EVIDENCE_REFS_DEDUPLICATED` when duplicate occurrences are removed.
- Emit `TRIAGE_EVIDENCE_REFS_TRUNCATED` when more than five unique grounded references are reduced
  to the canonical limit.
- Permit both reason codes on the same field when both conditions occur.
- Keep role and readability normalization results separate.
- Leave identity-observation rules unchanged.

### Resolution and preview provenance

- Resolve document coverage before evidence normalization: each document with OCR observations
  must have exactly one prediction.
- Normalize role and readability references against only the observations belonging to the
  predicted document version.
- Construct canonical triage results exclusively from normalized reference tuples.
- Resolve readability preview provenance from the first retained readability reference.
- Continue to hydrate page number, region, OCR confidence, source-text hash, and preview
  provenance from backend-owned observations rather than model output.
- Do not retry the model for duplicate references or valid over-citation.
- Continue to reject invalid grounding, ungrounded identity values, missing previews, and
  incomplete document coverage through existing fail-closed behavior.

### Prompt and route registry

- Add `fast-triage-prompt-v3` with explicit instructions to return 1–5 direct evidence references
  per role and readability field, ordered strongest to weakest.
- Tell the model to prefer document titles, patient lines, role-specific headings, receipts,
  prescription markers, totals, and other direct evidence.
- Tell the model not to enumerate every OCR line and never to create or modify observation IDs.
- Make the new prompt/provider-schema/policy combination the default for newly created workflows.
- Retain a compatibility registry for the legacy v2/v3 combination.
- Reject unknown prompt, provider-schema, and evidence-policy combinations explicitly.

### Workflow execution contract

- Extend the durable execution contract with the evidence-reference policy version.
- New workflows pin `triage-evidence-policy-v1` alongside their model route, model identifier,
  region, prompt version, and provider-schema version.
- Existing serialized contracts without the new field are interpreted only through the explicitly
  supported legacy fast-triage combination and its legacy behavior.
- Recovery reconstructs the model route and evidence policy from the persisted execution contract,
  not from current defaults.
- Evidence policy versions are code-owned constants and are not exposed as environment
  configuration.

### Normalization report

- Create a structured, frozen normalization-report contract.
- Store one report for each triaged document, with independent role and readability field results.
- Each field result records:
  - received count;
  - unique count;
  - retained count;
  - duplicate-drop count;
  - over-citation-drop count;
  - received references;
  - retained references;
  - duplicate dropped references;
  - over-citation dropped references; and
  - normalization reason codes.
- The document report records the evidence-policy version and raw provider-output SHA-256.
- Compute the raw-output digest from a deterministic canonical JSON serialization of the provider
  response.
- Persist canonical references in their existing business columns and persist the report in a new
  JSONB column associated with the document triage result.
- Expose the report through internal decision reconstruction. Do not add it to the member-facing
  claim API.
- Do not persist the full raw response as a new PostgreSQL business record in this feature.

### Observability

- Add a fast-triage evidence-normalization child span within the existing claim session and
  workflow trace.
- Record the provider response, normalized result, raw/unique/retained/dropped references, counts,
  reason codes, digest, model identifier, route, prompt version, provider-schema version,
  canonical-schema version, and evidence-policy version.
- Record failures on the normalization span before propagating them through the existing
  safe-failure path.
- Emit low-cardinality numeric metrics for received, unique, retained, duplicate, and
  over-citation-drop counts.
- Use only bounded dimensions such as evidence field, normalization outcome, model route, prompt
  version, provider-schema version, and policy version. Observation identifiers must not become
  metric labels.
- Retain the current project decision that full model input/output and OCR data are available in
  Phoenix for assignment debugging.

### Modules to build or modify

- **Provider triage contract module:** owns versioned untrusted response schemas and error
  classification.
- **Evidence policy registry:** resolves immutable policies by version and rejects unsupported
  versions.
- **Evidence reference normalizer:** the deep, deterministic module that validates, deduplicates,
  bounds, and reports one evidence-reference sequence.
- **Triage resolver:** orchestrates document coverage, invokes the normalizer for both evidence
  fields, hydrates backend provenance, and returns canonical results plus reports.
- **Fast-triage application boundary:** selects the provider DTO by the pinned route and calculates
  the raw-output digest.
- **Model route registry:** supports both the new v3/v4 route and the legacy v2/v3 route.
- **Workflow execution contract:** pins and restores the evidence-policy version.
- **Triage persistence adapter:** stores canonical references, provider-output digest, and
  normalization report atomically.
- **Decision reconstruction adapter:** includes normalization metadata in the internal audit
  reconstruction.
- **Observability instrumentation:** emits the normalization child span, attributes, errors, and
  low-cardinality metrics.
- **Database migration:** adds the bounded report and raw-output digest storage required for new
  results while preserving existing rows.

### Compatibility and migration

- The database migration is additive. Existing triage rows may have no normalization report or raw
  digest.
- Reconstructed legacy rows explicitly identify normalization metadata as unavailable rather than
  inventing it.
- The legacy route preserves its existing parse and resolution behavior for pinned workflows.
- New workflow creation uses the new route and policy after the migration is applied.
- No existing public request or response field changes.
- No existing claim state or adjudication rule changes.

## Testing Decisions

### Testing principles

- Tests assert externally observable contracts: accepted or rejected output, canonical evidence,
  error code, persisted audit result, recovered execution behavior, trace content, and unchanged
  public API behavior.
- The deterministic normalizer receives the most exhaustive unit coverage because it is the
  correctness and trust boundary.
- Tests avoid asserting private helper calls, internal collection types, or incidental SQL query
  order.
- Provider tests use captured, sanitized responses and do not require a paid model call.
- Integration tests prove persistence, recovery, reconstruction, and tracing using the same
  application composition as normal processing.

### Unit tests

- A provider response with 30 valid role references parses under v4.
- A provider response with 30 valid readability references parses under v4.
- A provider response with exactly 100 references parses under v4.
- A provider response with 101 references returns `MODEL_OUTPUT_LIMIT_EXCEEDED`.
- Empty required evidence references remain rejected.
- Malformed observation identifiers remain rejected.
- Thirty valid unique references are all validated and the first five are retained.
- A structurally valid but unavailable reference at position 30 fails grounding.
- A cross-document reference at position 30 fails grounding.
- Duplicate references are stable-deduplicated.
- A duplicate appearing before a later unique reference does not consume a canonical slot.
- A mixed duplicate and over-citation case records both reason codes.
- Canonical selection is deterministic across repeated executions.
- Role and readability fields are normalized independently.
- The first retained readability reference determines preview provenance.
- Identity selection behavior and its two-item maximum remain unchanged.
- The normalization report counts and reference partitions are internally consistent.
- Raw provider-output hashing is stable across equivalent dictionary ordering.
- Unsupported evidence-policy versions are rejected.
- Unsupported prompt/provider-schema/policy combinations are rejected.
- Legacy v3 provider parsing retains its prior behavior.

### Integration tests

- A captured DeepSeek-style response with 30 valid readability references completes triage and
  persists five canonical references without invoking the model again.
- PostgreSQL stores canonical role and readability references, the complete bounded normalization
  report, policy version, and raw-output digest atomically.
- Internal reconstruction returns the same canonical references and normalization report after
  application restart.
- A normalized result proceeds through the downstream document-role and identity gates without
  semantic changes.
- An invalid reference after the canonical prefix fails the workflow through the existing safe
  path and persists no misleading canonical triage result.
- A 101-reference response produces the explicit output-limit failure category.
- Phoenix receives the raw model invocation and a child normalization span with raw and retained
  references, counts, versions, digest, and outcome.
- Phoenix metrics contain bounded dimensions and do not use observation IDs as labels.
- A workflow created with the new route recovers with the same evidence-policy version after
  runtime defaults change.
- A workflow pinned to the legacy v2/v3 route remains executable after the new route becomes the
  default.
- Existing triage rows without normalization metadata remain reconstructable.
- The public claim submission and claim status schemas remain unchanged.

### Regression and acceptance gates

- The captured 30-reference DeepSeek-style payload succeeds without changing the configured model.
- All twelve recorded rendered evaluation cases continue to pass.
- Existing deterministic tests continue to pass.
- Legacy workflow execution-contract tests continue to pass.
- Database migration upgrade and schema-drift checks pass.
- Formatting, lint, and type checks pass.
- The feature is accepted only when PostgreSQL reconstruction and Phoenix tracing show the same
  retained references and raw-output digest.

## Out of Scope

- Changing the configured Bedrock model solely to avoid over-citation.
- Adding a model retry for valid over-citation or duplicates.
- Building a general LLM output-repair subsystem.
- Semantic reranking, keyword scoring, confidence scoring, or a second model call for evidence
  selection.
- Changing identity-selection limits or identity reconciliation.
- Changing document-role, readability, evidence-sufficiency, policy, or payable-amount semantics.
- Changing member-facing FastAPI request or response schemas.
- Persisting every raw provider invocation in a new generic invocation ledger.
- Removing full-content Phoenix tracing requested for assignment debugging.
- Deterministic OCR observation selection, large-document chunking, or multi-pass triage. These
  remain a separate follow-up requirement.
- Frontend implementation.
- Deployment or production infrastructure changes.

## Further Notes

- Raising the old maximum from 20 to 50 is not an accepted solution. Any single parsing threshold
  used as the canonical limit recreates the same failure at a different count.
- Prompt improvements reduce the frequency of over-citation but are not a trust boundary. The
  backend must remain correct when a model ignores the prompt.
- The first-five policy deliberately relies on strongest-first provider ordering. This is simple,
  deterministic, and testable. If evaluation later shows poor evidence quality, a new policy
  version may introduce deterministic ranking without changing historical workflows.
- The absolute ceiling protects parsing, persistence, and trace size. It is a safety constraint,
  not the canonical evidence limit.
- The raw provider response remains available in Phoenix under the project's current debugging
  configuration. PostgreSQL remains the durable source of canonical decision evidence and the
  normalization audit.
- Future work on large documents should reduce the OCR observation set presented to the model
  before inference. It must not weaken the rule that every returned reference is validated before
  canonical reduction.
