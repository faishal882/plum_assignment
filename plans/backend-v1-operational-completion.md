# Plan: Backend v1 Operational Completion

> Source PRD: [Backend v1 Operational Completion PRD](../prds/backend_v1_operational_prd.md)

## Architectural decisions

Durable decisions that apply across all phases:

- **Scope**: Complete the existing Backend v1 without reorganizing the current application,
  domain, infrastructure, model, policy, or observability packages.
- **Application boundary**: FastAPI remains the only frontend-facing authority. Frontend
  implementation is deferred, but every new lifecycle, progress, health, action, and error value
  is part of the documented frontend contract.
- **Execution model**: Claim submission returns `202 Accepted`. A standalone local worker leases
  durable PostgreSQL work and executes one typed LangGraph workflow per immutable claim version.
- **Worker interface**: The executable exposes `claims-worker run-once` and
  `claims-worker run-loop`.
- **Construction boundary**: API-independent worker construction is centralized and reused by the
  executable, operational integration tests, and evaluation runner.
- **Work authority**: PostgreSQL `claim_work_items` remains the only durable queue. No SQS, Redis,
  Kafka, in-memory queue, or FastAPI background task is introduced.
- **Lease safety**: Leasing uses committed PostgreSQL leases and fencing tokens. Active work
  renews its lease; a worker that loses its lease cannot commit terminal effects.
- **Workflow recovery**: LangGraph checkpoints remain in PostgreSQL. Workflow runs retain stable
  identifiers and resume from the last committed checkpoint.
- **Execution profiles**: `RECORDED_LOCAL` is the default cost-free operational profile.
  `LIVE_INTELLIGENCE` is the explicit AWS profile. Structured component execution remains
  test-only.
- **AWS authorization**: AWS adapters can be constructed only when
  `CLAIMS_EXECUTION_PROFILE=LIVE_INTELLIGENCE` and `CLAIMS_RUN_LIVE_AWS=1`.
- **Recorded providers**: Recorded OCR, triage, and extraction results are selected through
  canonical input hashes. They cannot inspect case IDs, oracle outcomes, or privileged request
  fields.
- **Document flow**: Operational processing follows render, discovery OCR, fast triage, early
  gate, role-aware analysis, grounded complex extraction, reconciliation, and deterministic
  adjudication.
- **Model authority**: Textract and Qwen produce observations and evidence candidates only.
  Deterministic Python policy evaluation retains sole authority over recommendations and money.
- **Material facts**: Missing facts remain missing. Known provider aliases may be normalized only
  through a versioned registry and only when grounded to source OCR evidence.
- **Lifecycle**: Public stopped states are `ACTION_REQUIRED`, `IN_REVIEW`, `DECIDED`, and
  `PROCESSING_FAILED`. A claim cannot remain `QUEUED` after its work item has terminally
  completed.
- **Failure semantics**: `ACTION_REQUIRED` means the member can correct evidence.
  `PROCESSING_FAILED` means processing exhausted its durable retry budget. Neither is an
  adjudication rejection.
- **Transaction boundary**: Terminal claim projection, workflow state, work state, audit event,
  decision or failure trace, rules, and amount steps commit consistently.
- **Observability**: The claim ID is the Phoenix session ID. Each claim version has a distinct
  workflow trace. API, worker, provider, replacement, and review activity are correlated without
  recording protected medical content.
- **Decision trace**: PostgreSQL remains sufficient to reconstruct a decision after Phoenix and
  JSONL diagnostic copies are deleted.
- **Metrics**: Phoenix uses trace-derived attributes and evaluations. PostgreSQL and JSONL retain
  local operational records. No additional metrics service is introduced.
- **Evaluation**: All twelve recorded rendered cases are the primary correctness gate. At least
  one selected synthetic claim must pass through the complete live AWS path.
- **Artifacts**: Sanitized evaluation reports, test summaries, privacy results, and version
  manifests are durable proof artifacts. Raw documents, OCR bodies, prompts, responses, JSONL
  runtime logs, Phoenix storage, and credentials are never committed.
- **Database safety**: The test database must differ from the normal application database unless
  an explicit destructive-test override is supplied.
- **Data boundary**: Backend v1 supports arbitrary real-format PDF, JPEG, and PNG documents, but
  testing is limited to synthetic or de-identified content.

## Current implementation progress

This status is intentionally narrower than the acceptance checklists below. It records only
verified completed slices; unchecked acceptance criteria remain work to do.

- [x] Shared typed runtime settings and execution-profile safeguards (`a59a2e9`, `f32fa14`).
- [x] Standalone `claims-worker run-once` and `claims-worker run-loop` commands (`d68f2ef`,
  `57d4846`).
- [x] Public no-fixture TC001-style action-required tracer using recorded discovery OCR
  (`7b6c6fa`).
- [x] Public no-fixture synthetic clean-decision tracer through deterministic adjudication
  (`f761e68`, `93ffaa9`).
- [x] Worker lease heartbeat, bounded shutdown behavior, and recovery-safe fencing (`f554bdc`).
- [x] Public `PROCESSING_FAILED` projection for terminal worker failure (`f9a3077`).
- [x] Member-safe processing-failure error and retry contract (`4fa3438`).
- [x] Terminal processing failure closes the corresponding workflow run as `FAILED`.
- [x] Role-aware OCR is independently persisted and supplied to extraction; discovery OCR remains
  isolated for triage.
- [x] Workflow root spans expose queue wait and terminal outcome alongside duration, graph,
  profile, and attempt metadata.
- [x] Hash-keyed recorded OCR/model corpus supports the TC004-format prescription and hospital
  bill path without a processing fixture.
- [x] Recorded corpus includes the TC005 diabetes waiting-period document pair.
- [x] Recorded corpus includes the TC006 dental line-item document.
- [x] Recorded corpus includes TC007 MRI authorization documents and treatment extraction.
- [x] Recorded corpus includes the TC008 category-limit document pair.
- [x] Recorded corpus includes the TC009 same-day-velocity document pair.
- [x] Recorded corpus includes the TC010 network-discount document pair.
- [x] Recorded corpus includes the TC011 graceful-degradation document pair.
- [x] Recorded corpus includes the TC012 excluded-treatment document pair.
- [x] Synthetic early-gate documents encode patient identity in their immutable bytes, enabling
  hash-keyed TC001–TC003 role, readability, and identity evidence.
- [x] Assignment-shaped TC004 documents pass through the public API and standard recorded worker
  without a processing fixture.
- [x] Assignment-shaped TC001 documents reach the expected early corrective state through the
  standard recorded worker without a processing fixture.
- [x] Assignment-shaped TC002 documents request replacement of the recorded unreadable pharmacy
  bill through the standard recorded worker without a processing fixture.
- [x] Assignment-shaped TC003 documents surface their patient identity conflict through the
  standard recorded worker without a processing fixture.
- [x] Unrecorded local documents fail closed as `PROCESSING_FAILED` rather than leaving leased
  work unresolved.
- [x] Assignment-shaped TC005 reaches its waiting-period decision through the standard recorded
  worker without a processing fixture.
- [x] Assignment-shaped TC006 reaches its itemized partial dental decision through the standard
  recorded worker without a processing fixture.
- [x] Assignment-shaped TC007 reaches its pre-authorization decision through the standard
  recorded worker without a processing fixture.
- [x] Assignment-shaped TC008 reaches its per-claim-limit decision through the standard recorded
  worker without a processing fixture.
- [x] Assignment-shaped TC009 reaches an auditable same-day-velocity review task through the
  standard recorded worker without a processing fixture.
- [x] Assignment-shaped TC010 applies network discount before co-pay through the standard
  recorded worker without a processing fixture.
- [x] Assignment-shaped TC011 proves configured local anomaly degradation through the standard
  recorded worker without a processing fixture or request-level injection.
- [x] Assignment-shaped TC012 reaches its excluded-treatment decision through the standard
  recorded worker without a processing fixture.
- [x] All twelve assignment outcomes pass their public API → standard recorded worker gate with
  no `ProcessingFixtureRow` seed (`12 passed`).
- [x] The twelve-case recorded rendered evaluation gate uses the standard composed worker; its
  structured-component runner remains a separate OCR-bypassed diagnostic control.
- [x] Recorded evaluation spans expose schema, grounding, trace-completeness, reconstruction,
  provenance, failure-count, and aggregate pass-rate metrics for Phoenix.
- [x] Replacement and review activity carry the originating claim's Phoenix session correlation.
- [x] Role-aware OCR observation identifiers are verified to remain isolated across Textract
  profiles, preventing cross-role evidence reuse.
- [x] The versioned `clinical.diagnosis` compatibility alias preserves original-path and registry
  provenance alongside its grounded canonical evidence.
- [x] The extraction prompt explicitly requires `clinical.condition` and rejects the legacy
  diagnosis path as normal output.
- [ ] Sanitized recorded-evaluation, version-manifest, and telemetry-privacy proof artifacts are
  committed without runtime logs, documents, OCR, prompts, responses, or trace identifiers.
- [ ] Final deterministic suite evidence is recorded with current pass/skip counts; all skips
  require explicit paid-AWS authorization.
- [ ] Explicit paid-AWS synthetic TC004 provider-to-policy tracer passes with real Textract and
  Qwen; exact provider-labelled totals and `Diagnosis:` lines are persisted as versioned,
  grounded Textract-derived evidence when model output is blank.
- [ ] Explicit paid-AWS synthetic TC004 claim passes through public multipart FastAPI submission,
  PostgreSQL leasing, the standard standalone worker construction, real Textract and Qwen, and
  deterministic ₹1,350 adjudication (`tests/live/test_live_worker_tc004.py`).
- [ ] The complete live tracer verifies correlated API/worker Phoenix claim sessions and PHI-safe
  span attributes in the same explicitly authorized run.
- [x] API submission spans correlated to the claim Phoenix session (`8dad379`).
- [x] Local health checks and frontend worker/polling contract (`57d4846`, `2086cec`).
- [x] Test database isolation guard and explicit destructive override (`cf69c35`).
- [x] Repository formatting, lint, strict typing, and Alembic drift checks (`9cffc2e`).
- [x] Immutable workflow execution-contract persistence and changed-runtime recovery guard.
- [x] Historical prompt v3 and route contracts can be rebuilt from persisted execution metadata;
  composition rejects incompatible profile/provider contracts before adapter construction.
- [x] Operational no-fixture clean-decision tracer and all twelve recorded cases pass through the
  public API and standard worker construction.
- [x] Recovery construction resolves supported persisted provider/model/prompt contracts before
  execution; an existing v3 workflow never silently adopts the current v4 runtime.
- [x] Unified claim-session test proves correlated API/worker Phoenix sessions, durable workflow
  event trace IDs, separate JSONL streams, and content-free telemetry canary scans.
- [ ] Explicit live AWS complete tracer, versioned alias compatibility, and sanitized closure
  artifacts are verified.

---

## Phase 1: Safe runtime and execution-profile selection

**User stories**: 4, 9–16, 39, 43

### What to build

Establish the shared operational construction boundary and prove that it selects a complete,
internally consistent provider set before any work is leased. Recorded mode starts without AWS
access. Live mode starts only after both the live profile and paid-provider authorization are
present. The selected execution contract is frozen when a workflow begins.

This phase delivers a safe runtime foundation that later worker phases can use without duplicating
provider and repository construction.

### Acceptance criteria

- [x] The API, worker command, and operational tests load the same typed environment
  configuration.
- [x] Missing required configuration produces one safe startup error listing the missing keys.
- [x] `RECORDED_LOCAL` is the committed default execution profile.
- [x] Paid AWS execution is disabled in committed and normal local configuration.
- [x] Recorded mode constructs only recorded provider adapters.
- [ ] Recorded mode rejects non-loopback external network access.
- [x] Live mode refuses to construct AWS adapters when paid-AWS authorization is absent.
- [x] Paid-AWS authorization without the live execution profile does not construct AWS adapters.
- [x] Live mode constructs the configured Textract and Bedrock adapters only when both safeguards
  are present.
- [x] The construction boundary creates a complete worker dependency set without relying on
  FastAPI request state.
- [x] Invalid partial processor configurations cannot reach work execution.
- [x] Workflow creation persists execution profile, OCR provider version, model ID, prompt
  versions, schema versions, and graph version.
- [x] Workflow recovery uses the pinned execution contract rather than silently adopting changed
  process configuration.
- [x] Readiness can validate local configuration without contacting Textract or Bedrock.
- [x] Unit tests cover the complete profile-selection and fail-closed matrix.

---

## Phase 2: Public no-fixture action-required tracer

**User stories**: 1–2, 17–20, 23, 31, 40, 52–54

### What to build

Deliver the first complete operational path. A member submits a TC001-style claim through the
public multipart API. A standalone run-once worker leases its durable work, renders the submitted
documents, obtains recorded discovery OCR selected by input hash, performs grounded recorded
triage, identifies the missing required document role, and commits an `ACTION_REQUIRED` result.

The path must not create or read a processing fixture row. This slice proves that normal
submission, durable work, worker execution, document intelligence, claim transition, public
projection, PostgreSQL reconstruction, and worker telemetry operate together.

### Acceptance criteria

- [x] `claims-worker run-once` is registered as an executable command.
- [x] The command loads environment configuration and connects to the configured PostgreSQL
  database.
- [x] The worker initializes the LangGraph checkpoint schema before processing.
- [x] A public multipart submission returns `202 Accepted` and creates one available work item.
- [x] The worker leases the submitted claim through the PostgreSQL scheduler.
- [x] No processing fixture row exists for the submitted claim version.
- [x] Normal routing selects the recorded document-intelligence path from the execution profile,
  not fixture presence.
- [x] Submitted documents are rendered into bounded immutable page artifacts.
- [x] Recorded discovery OCR is selected by canonical page input identity.
- [x] Fast triage consumes bounded discovery observations and covers every submitted document
  exactly once.
- [x] Triage output cites persisted discovery observations for material classifications.
- [x] The early gate identifies the observed roles and missing required role.
- [x] Complex extraction and policy adjudication do not execute after the failed early gate.
- [x] Claim, work, workflow, member action, audit, and projection states commit consistently.
- [x] The work item and workflow complete while the claim reaches `ACTION_REQUIRED`.
- [x] The claim cannot remain `QUEUED` after work completion.
- [x] `GET /v1/claims/{claim_id}` exposes the affected documents and requested correction.
- [x] PostgreSQL reconstruction contains the ordered workflow, evidence, action, and audit history.
- [x] The worker writes a correlated rotating JSONL record.
- [x] A public end-to-end test proves the complete no-fixture behavior.

---

## Phase 3: Continuous worker and frontend polling

**User stories**: 3, 38–43, 51

### What to build

Turn the run-once tracer into a usable local asynchronous backend. A continuous worker starts
before a claim exists, polls PostgreSQL without holding transactions open, processes work
submitted later by the API, and exposes sufficient progress for a frontend to poll until the
claim leaves `QUEUED`.

Add liveness and readiness contracts for local process diagnosis. Health checks remain free of
AWS calls.

### Acceptance criteria

- [x] `claims-worker run-loop` is registered as an executable command.
- [x] The loop starts successfully when no work is currently due.
- [x] Idle polling does not retain a database transaction or work lease.
- [x] A claim submitted after worker startup is discovered and processed.
- [x] The loop processes one claim at a time for Backend v1.
- [x] Polling interval and worker identity are controlled by validated configuration.
- [x] `GET /health/live` reports API-process liveness without dependency checks.
- [x] `GET /health/ready` verifies runtime configuration and PostgreSQL connectivity.
- [x] Readiness fails safely when PostgreSQL is unavailable.
- [x] Neither health endpoint constructs or calls AWS providers.
- [x] Claim status exposes stable machine-readable progress while work is queued and running.
- [x] A frontend can submit a claim and poll until it reaches `ACTION_REQUIRED`.
- [x] Existing submission, claim, action, and review contracts remain backward compatible except
  for additive lifecycle and progress values.
- [x] API and worker processes write separate JSONL files.
- [x] The frontend integration documentation describes worker startup, health endpoints, polling,
  progress, and stopped states.
- [x] An integration test starts the loop, submits work afterward, observes progression, and
  terminates the loop cleanly.

---

## Phase 4: Lease renewal and graceful recovery

**User stories**: 5–8, 15–16, 35, 37

### What to build

Make long-running local processing safe across worker shutdown, lease expiry, and process
replacement. The active worker renews its lease while provider work is in progress. Shutdown
stops new leasing, completes or safely abandons the active operation within a bounded period,
flushes diagnostics, and closes resources. A replacement worker resumes from committed
checkpoints.

### Acceptance criteria

- [x] Active work renews its lease before expiry.
- [x] Lease renewal uses the current owner and fencing token.
- [x] A stale owner or token cannot renew a reclaimed lease.
- [x] The worker stops leasing new work after SIGINT or SIGTERM.
- [x] Idle shutdown completes without waiting for the poll interval.
- [x] Active shutdown allows the current operation a configured bounded completion period.
- [x] Forced termination leaves work recoverable after lease expiry.
- [x] A replacement worker reclaims expired work with a new fencing token.
- [x] A replacement worker resumes from the last committed LangGraph checkpoint.
- [x] Completed workflow effects are not duplicated after recovery.
- [x] A worker that loses its lease cannot commit a terminal claim effect.
- [x] Long provider calls do not hold database transactions open.
- [x] The worker flushes JSONL records and Phoenix spans before normal exit.
- [x] The worker disposes of its PostgreSQL engine before normal exit.
- [x] Recovery tests prove one eventual terminal effect across interrupted workers.
- [x] Lease-heartbeat tests use short deterministic intervals without calling external providers.

---

## Phase 5: Exhausted failure lifecycle

**User stories**: 31–36, 41

### What to build

Provide a truthful public result when processing cannot safely complete. Drive a classified
retryable failure through durable retries and transition the claim to `PROCESSING_FAILED` after
the attempt budget is exhausted. Preserve safe member messaging and complete internal diagnostic
history without conflating processing failure with adjudication rejection or member action.

### Acceptance criteria

- [x] `PROCESSING_FAILED` is a supported domain and public API lifecycle.
- [x] Retryable failures return work to available state with a persisted future due time.
- [x] Retry scheduling follows configured bounded backoff and jitter.
- [x] A retry does not duplicate rendered pages, OCR observations, evidence, audit events, or
  terminal effects.
- [x] Exhausting the work attempt budget transitions the work item to failed.
- [x] Exhaustion transitions the workflow run and claim projection consistently.
- [x] The terminal failure appends an immutable audit event.
- [x] The terminal failure retains sanitized component, attempt, retryability, and failure-code
  details for operations.
- [x] Member projection exposes a stable safe error code and retry guidance.
- [x] Member projection excludes provider response bodies, OCR text, patient facts, credentials,
  and internal exception messages.
- [x] `ACTION_REQUIRED` remains reserved for a member-correctable evidence problem.
- [x] No adjudication recommendation or approved amount is created for processing failure.
- [x] The claim cannot remain `QUEUED` after the failed work item becomes terminal.
- [x] PostgreSQL reconstruction explains every attempt and the final failure transition.
- [x] Frontend integration documentation defines the processing-failed state and expected UI
  handling.
- [x] Contract and integration tests cover retry, exhaustion, projection, audit, and
  reconstruction.

---

## Phase 6: Public no-fixture clean-decision tracer

**User stories**: 25–30, 52–55

### What to build

Extend the operational recorded path through the complete positive decision workflow. Submit a
TC004-style claim through the public API, run the standalone worker, pass discovery triage,
perform role-aware recorded OCR and grounded recorded Qwen extraction, reconcile evidence,
freeze a casefile, apply deterministic policy, and commit the exact decision and amount.

No fixture row or oracle field may control routing, evidence, or outcome.

### Acceptance criteria

- [x] A public multipart claim with prescription and bill documents is accepted and queued.
- [x] No processing fixture row exists for the claim version.
- [x] Discovery OCR and grounded fast triage identify both required document roles.
- [x] The successful early gate continues into role-aware document analysis.
- [x] Recorded role-aware OCR responses are selected by canonical input identity.
- [x] Recorded complex-extraction responses are selected by canonical bounded-observation input.
- [x] Recorded providers cannot access expected outcome fields or case identifiers.
- [x] Every material extracted candidate cites a persisted OCR observation.
- [x] Authority validation rejects any model attempt to provide a decision or payable amount.
- [x] Reconciliation preserves sources, conflicts, unknowns, and canonical fact states.
- [x] The frozen casefile records immutable evidence, member, policy, and claim snapshot hashes.
- [x] Deterministic adjudication produces the expected recommendation, exact amount, rule trace,
  and amount trace.
- [x] Decision, projection, rules, calculations, audit, workflow, and work completion commit
  atomically.
- [x] The claim reaches `DECIDED` and cannot remain queued.
- [x] The public projection explains the recommendation and deduction without exposing internal
  provider content.
- [x] PostgreSQL reconstruction reproduces the complete evidence-to-decision path.
- [x] Replaying the same immutable inputs produces the same canonical decision hash.
- [x] A public no-fixture clean-decision integration test proves the complete path.

---

## Phase 7: Complete early-gate correction paths

**User stories**: 17–24, 55

### What to build

Move every early-gate assignment case onto the normal recorded runtime. Cover missing required
roles, unreadable documents, conflicting patient identities, targeted document replacement,
claim-version creation, and successful reprocessing without fixture-selected routing.

### Acceptance criteria

- [x] TC001 identifies both observed prescriptions and the missing hospital bill.
- [x] TC001 reaches `ACTION_REQUIRED` without complex extraction or adjudication.
- [x] TC002 identifies the unreadable pharmacy bill by stable client document ID.
- [x] TC002 requests replacement rather than rejecting or failing the claim.
- [x] TC003 preserves each conflicting patient identity observation and its document provenance.
- [x] TC003 reaches a corrective state without policy adjudication.
- [x] Unknown document roles remain unknown rather than being coerced to a known role.
- [x] Triage output covers every submitted document exactly once for all three cases.
- [x] Every material triage value is grounded to discovery OCR evidence.
- [x] Replacement uploads create immutable document and claim versions.
- [x] Replacement supersedes older pending work without mutating prior evidence.
- [x] Reprocessing uses the new claim version and a distinct workflow trace.
- [x] Prior workflow, action, evidence, and audit history remain reconstructable.
- [x] Normal processing for these cases creates no processing fixture rows.
- [x] Recorded early-gate tests cannot contact external networks.
- [x] Public projections expose only member-safe document correction details.

---

## Phase 8: Eligibility, authorization, and exclusion outcomes

**User stories**: 26–30, 55

### What to build

Move the waiting-period, pre-authorization, category-limit, and excluded-condition cases through
the operational recorded runtime. Each case must start at the public API, use the standalone
worker construction, derive evidence through the no-fixture document path, and commit a
deterministic explainable decision.

### Acceptance criteria

- [x] TC005 reaches `DECIDED` with the expected waiting-period rejection.
- [x] TC005 records the member join date, treatment date, applicable waiting rule, and eligibility
  date with provenance.
- [x] TC007 reaches `DECIDED` with the expected missing-pre-authorization rejection.
- [x] TC007 distinguishes absent supported authorization evidence from unreadable or conflicting
  authorization evidence.
- [x] TC008 reaches `DECIDED` with the expected category-limit rejection and amount trace.
- [x] TC012 reaches `DECIDED` with the expected excluded-condition rejection.
- [x] Every material fact is supported, conflicting, or explicitly unknown.
- [x] Every outcome references the pinned immutable policy and overlay.
- [x] Every rule result identifies its policy path and evidence references.
- [x] No model output directly selects an adjudication recommendation.
- [x] No case-specific branch, fixture route, or oracle field influences runtime behavior.
- [x] Terminal writes remain atomic and replay-safe.
- [x] Public projections provide member-safe explanations.
- [x] PostgreSQL reconstruction reproduces each complete decision.
- [x] Recorded execution remains network-free.

---

## Phase 9: Partial approval and calculation outcomes

**User stories**: 26–30, 55

### What to build

Move the line-item partial-approval and network-discount calculation cases through the operational
recorded runtime. Preserve individual billed items through extraction, reconciliation, policy
evaluation, and explanation so that calculation order and exclusions remain auditable.

### Acceptance criteria

- [x] TC006 reaches `DECIDED` with the expected partial approval and exact approved amount.
- [x] Root-canal and whitening line items remain distinct through every processing stage.
- [x] The covered line item and excluded line item retain separate provenance.
- [x] Category-specific limit precedence is visible in the rule and amount trace.
- [x] TC010 reaches `DECIDED` with the expected exact approved amount.
- [x] Network discount is applied before co-pay.
- [x] Every amount step records the amount before, named adjustment, adjustment amount, and amount
  after.
- [x] All calculations use integer paise and explicit rounding.
- [x] Replaying the same casefile and policy produces the same calculation and decision hash.
- [x] No model supplies an approved amount, deduction, limit result, or rule outcome.
- [x] Public explanations identify covered items, excluded items, discounts, co-pay, and final
  amount without exposing raw provider content.
- [x] Terminal writes remain atomic and replay-safe.
- [x] PostgreSQL reconstruction preserves the complete line-item and calculation path.
- [x] Both cases use normal no-fixture routing in recorded mode.

---

## Phase 10: Review and degraded-processing outcomes

**User stories**: 34, 50, 55

### What to build

Move the same-day velocity and anomaly-enrichment degradation cases through the operational
recorded runtime. Prove that handling disposition remains separate from adjudication, that
noncritical degradation cannot erase a deterministic recommendation, and that the existing
review workflow remains fully reconstructable.

### Acceptance criteria

- [x] TC009 reaches `IN_REVIEW` with the expected same-day velocity signals.
- [x] TC009 retains its machine recommendation and calculation separately from review status.
- [x] An authorized reviewer can list and inspect the generated review task.
- [x] Review detail exposes evidence, conflicts, rules, calculations, failures, and allowed
  actions through member-safe and reviewer-appropriate projections.
- [x] TC011 reaches the expected adjudication recommendation while recording the named degraded
  component.
- [x] TC011 records reduced processing completeness and confidence.
- [x] TC011 records recommended manual handling without changing the deterministic policy result.
- [x] A noncritical engineering or enrichment failure cannot roll back a valid domain decision.
- [x] A critical audit or terminal-persistence failure prevents terminal completion.
- [x] Human resolution preserves the original machine proposal.
- [x] Review commands remain authorized, version-fenced, and idempotent.
- [x] Review spans continue from or correlate with the claim workflow context.
- [x] PostgreSQL reconstruction includes machine recommendation, degradation, review task, and
  human resolution.
- [x] Both cases use the normal no-fixture recorded runtime.

---

## Phase 11: Claim-session observability

**User stories**: 44–51

### What to build

Make one claim navigable as a Phoenix session across asynchronous API, worker, provider,
replacement, and review activity. Add the agreed privacy-safe operational attributes and
trace-level evaluations while preserving PostgreSQL as the complete business explanation.

### Acceptance criteria

- [x] Every claim-related span carries `session.id` equal to the claim ID once the claim is known.
- [x] Each immutable claim version has a distinct workflow trace within the claim session.
- [x] Workflow-run ID remains stable across checkpoint recovery.
- [x] API submission and worker execution are correlated across the asynchronous boundary.
- [x] Replacement processing appears in the same claim session and a new version trace.
- [x] Review inspection and resolution appear in the same claim session.
- [x] Workflow root spans include queue wait, total duration, graph version, execution profile,
  attempt, and terminal outcome.
- [x] Node spans include node identity, component, duration, attempt, and outcome.
- [x] Textract spans include provider profile, request ID, latency, and retry count.
- [x] Bedrock spans include route, model, prompt/schema versions, token counts, latency, stop
  reason, request ID, and sanitized failure type.
- [x] Reconciliation spans include candidate count, conflict state, and sufficiency without
  medical values.
- [x] Trace evaluations record schema validity, evidence grounding, trace completeness,
  reconstruction completeness, policy determinism, and telemetry privacy.
- [x] API, worker, and evaluation JSONL records share claim, workflow, trace, span, attempt,
  duration, and outcome identifiers where applicable.
- [x] PHI canaries reject patient names, medical content, OCR text, document bytes, local paths,
  prompts, raw responses, credentials, and configured synthetic canaries.
- [x] Normal observability capture remains content-free.
- [x] Removing Phoenix and JSONL data does not alter or prevent PostgreSQL reconstruction.
- [x] A claim-session boundary test verifies hierarchy, correlation, evaluations, logs, and
  privacy in one execution.

---

## Phase 12: Complete live AWS claim tracer

**User stories**: 14–16, 25–30, 56–57

### What to build

Prove that a generated synthetic TC004-style claim can traverse the complete operational path
using real AWS providers. Submit through FastAPI, lease through PostgreSQL, execute through the
standalone worker and LangGraph, perform Textract discovery and role-aware analysis, extract
grounded evidence with Qwen, reconcile the evidence, apply deterministic policy, and return the
expected public decision.

Tighten the live extraction contract and add controlled grounded compatibility for known field
aliases. The live gate remains explicit and paid.

### Acceptance criteria

- [x] The live test is skipped unless both the live profile and paid-AWS authorization are
  explicitly selected.
- [x] The live test uses generated synthetic documents containing no identifiable patient data.
- [x] The claim enters only through the public multipart API.
- [x] The claim is processed by the same standalone worker construction used for normal local
  operation.
- [x] No processing fixture row or recorded provider adapter is used.
- [x] Real Textract discovery OCR precedes fast triage.
- [x] Fast triage covers every submitted document and grounds its output.
- [x] Role-aware Textract analysis runs where required.
- [x] Real Qwen structured extraction uses the pinned model, prompt, schema, and route versions.
- [x] Prompt guidance permits only canonical fact paths and explicitly requires role-specific
  material facts.
- [x] `clinical.diagnosis` may normalize to `clinical.condition` only through the versioned alias
  registry and grounded evidence.
- [x] Alias normalization records source path, target path, registry version, and evidence
  references without medical values in telemetry.
- [x] Missing `billing.total` or another material fact is never invented.
- [x] Ungrounded, unauthorized, extra, or invalid model fields fail safely.
- [x] Reconciliation and policy code—not the model—produce the final recommendation and amount.
- [ ] The selected claim reaches the expected terminal projection and exact deterministic result.
- [ ] PostgreSQL reconstructs the complete live provider-to-decision path.
- [ ] Phoenix contains the complete live claim session with provider metadata and no prohibited
  content.
- [ ] Separate Textract and Bedrock live smoke tests continue to pass.
- [x] Default tests do not execute this paid gate.
- [x] Live limitations and provider variability are documented without claiming all twelve live
  cases pass.

---

## Phase 13: Durable acceptance evidence and Backend v1 closure

**User stories**: 55, 58–65

### What to build

Close Backend v1 with reproducible evidence rather than historical claims. Protect manual local
data from destructive tests, run the complete deterministic and recorded acceptance suites,
generate sanitized versioned proof artifacts, fix every static quality gate, and publish an
honest completion report and frontend integration contract.

### Acceptance criteria

- [x] The configured test database differs from the normal application database.
- [x] Test startup refuses identical application and test database targets unless an explicit
  destructive-test override is present.
- [x] Database-safety tests prove the refusal and explicit override behavior.
- [ ] The complete deterministic suite passes with paid AWS disabled.
- [x] The public no-fixture action-required test passes.
- [x] The public no-fixture clean-decision test passes.
- [x] All twelve recorded rendered evaluation cases pass.
- [x] Every recorded case uses the operational worker construction and normal no-fixture routing.
- [ ] The recorded evaluation report is saved outside temporary test storage.
- [ ] The report contains expected and actual lifecycle, adjudication, amount, reason codes,
  provenance, assumptions, failures, and trace completeness for TC001–TC012.
- [ ] The version manifest records dataset, policy, overlay, execution profile, OCR, model, prompt,
  schema, graph, reconstruction contract, source revision, and artifact hashes.
- [ ] The test summary records actual current counts and skipped live tests rather than historical
  hardcoded totals.
- [ ] The telemetry privacy report records the completed canary scan without including scanned
  medical content.
- [ ] Sanitized proof artifacts are committed.
- [x] Raw documents, page artifacts, OCR bodies, prompts, model responses, JSONL runtime logs,
  Phoenix storage, database files, and credentials remain excluded.
- [ ] The explicitly selected Textract and Bedrock smoke results are documented.
- [ ] The explicitly selected complete live claim result is documented.
- [x] Known live provider limitations and safe-failure behavior are documented honestly.
- [x] Formatting check passes after applying the configured formatter.
- [x] Lint passes.
- [x] Strict type checking passes.
- [x] Migration drift check passes.
- [x] Repository diff whitespace validation passes.
- [ ] Backend completion documentation includes architecture, implemented and excluded scope,
  current commands and results, all twelve recorded outcomes, live results, limitations, API
  startup, worker startup, log inspection, Phoenix inspection, PostgreSQL inspection, and
  frontend integration.
- [ ] The completion checklist contains no unchecked Backend v1 requirement.
- [x] Identifiable patient-data processing remains explicitly unsupported.

---

## Completion definition

The plan is complete only when all thirteen phase acceptance sections pass and:

- [x] A normally started FastAPI process accepts a valid claim.
- [x] A normally started standalone worker advances the claim.
- [x] Normal processing does not depend on `ProcessingFixtureRow`.
- [x] Recorded mode provides a complete cost-free frontend integration path.
- [ ] Live mode provides a complete explicitly authorized Textract-and-Bedrock path.
- [x] A work item cannot terminally complete while its claim remains `QUEUED`.
- [x] Exhausted processing failures reach `PROCESSING_FAILED`.
- [x] All twelve recorded rendered cases pass through the operational runtime.
- [ ] At least one synthetic live claim passes through the public durable workflow.
- [x] PostgreSQL reconstructs every material decision and handling step.
- [x] Phoenix groups the complete claim journey into a privacy-safe session.
- [x] API, worker, and evaluation JSONL logs are produced.
- [ ] Durable sanitized artifacts prove the test, evaluation, version, and privacy results.
- [x] Formatting, lint, typing, migrations, and repository validation pass.
- [x] Paid AWS remains disabled by default.
- [x] Documentation states current evidence and limitations without overstating real-world or live
  coverage.
