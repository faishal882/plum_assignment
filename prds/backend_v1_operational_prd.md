# Backend v1 Operational Completion PRD

**Status:** Approved for implementation planning  
**Scope:** Close the operational gap in the existing Backend v1  
**Parent product requirements:** `backend_prd.md`  
**Architecture authority:** [`docs/architecture.md`](../docs/architecture.md)
**Domain language:** [`CONTEXT.md`](../CONTEXT.md)
**Frontend:** Consumer of the existing FastAPI contract; frontend implementation remains deferred

## Problem Statement

The backend already accepts claim submissions, stores immutable documents and claim versions,
creates durable PostgreSQL work, executes a typed LangGraph workflow in integration tests,
performs recorded OCR and structured extraction, applies deterministic policy rules, persists
decisions, supports review, reconstructs claim decisions, and emits privacy-safe traces and logs.

It is not yet operational as a normally started local application:

- There is no standalone worker executable.
- Publicly submitted claims remain queued unless tests manually construct and invoke a worker.
- Normal workflow routing depends on evaluation-only processing fixtures.
- Document triage consumes pre-seeded model output instead of inspecting an uploaded document.
- The live AWS test invokes components directly rather than exercising the public API, durable
  work queue, worker, LangGraph workflow, and terminal claim transition together.
- A no-fixture public end-to-end test does not exist.
- Recorded evaluation reports are written to temporary test storage instead of durable proof
  artifacts.
- Phoenix receives traces, but claim-level sessions and the agreed operational metrics are not
  represented completely.
- Exhausted processing failures can leave the public claim state unable to explain that processing
  has stopped.
- The formatting gate does not currently pass.

Because of these gaps, a frontend can submit and poll a claim but cannot rely on the claim
advancing during a normal local run. The backend also cannot yet be presented honestly as capable
of accepting an arbitrary real-format document and processing it through the configured AWS
intelligence path.

## Solution

Complete the existing architecture without reorganizing the current application, domain,
infrastructure, model, policy, or observability packages.

Add a standalone local worker and a small shared composition boundary. The worker will load
configuration, connect to PostgreSQL, initialize LangGraph checkpointing, lease due claim work,
execute the existing claim workflow, renew active leases, emit worker telemetry, and shut down
cleanly.

Replace fixture-selected normal routing with explicit execution profiles:

- `RECORDED_LOCAL` is the default cost-free operational and frontend-development profile. It uses
  sanitized recorded provider results selected by canonical input hashes and cannot contact AWS.
- `LIVE_INTELLIGENCE` is the explicit real-provider profile. It may construct AWS adapters only
  when paid live execution is separately authorized.
- Structured component fixtures remain available only to component and evaluation tests.

For real document processing, render bounded pages first, obtain generic discovery OCR from
Textract, and run schema-constrained fast triage over bounded OCR observations. Triage determines
document role, readability, and selected identity evidence without trusting filenames or frontend
labels. Documents that pass the early gate continue through role-aware OCR when needed, grounded
Qwen extraction, evidence reconciliation, deterministic policy adjudication, and terminal
persistence.

All model outputs remain untrusted evidence candidates. Models may not determine coverage,
adjudication recommendation, or payable amount.

Add the `PROCESSING_FAILED` lifecycle for work that exhausts its retry budget without producing a
safe result. This state is distinct from `ACTION_REQUIRED`, which is reserved for a correction the
member can perform, and from an adjudication rejection.

Finish the diagnostic and proof surface by grouping all traces for one claim into a Phoenix
session, recording privacy-safe operational attributes and evaluations, producing durable
evaluation artifacts, and documenting the exact evidence supporting the Backend v1 completion
claim.

## User Stories

### Worker operation

1. As a developer, I want a standalone worker command, so that queued claims advance without test
   code manually assembling the processor.
2. As a developer, I want a run-once worker mode, so that I can process one due item during
   debugging and smoke testing.
3. As a developer, I want a continuous worker mode, so that a frontend can submit claims while a
   local processor remains active.
4. As a developer, I want the worker to load the same environment configuration as the API and
   CLI, so that runtime behavior is predictable.
5. As an operator, I want the worker to stop leasing new work during shutdown, so that termination
   does not abandon newly acquired claims.
6. As an operator, I want the worker to finish or safely release its active operation before
   shutdown, so that work is recoverable.
7. As an operator, I want active leases renewed during long OCR or model work, so that another
   worker does not duplicate expensive provider calls.
8. As an engineer, I want the worker to flush traces and logs and close PostgreSQL cleanly, so
   that local diagnostic data is not lost.
9. As an engineer, I want one shared construction boundary used by the real worker and integration
   tests, so that test-only wiring cannot become more complete than the application.

### Execution profiles and provider safety

10. As a frontend developer, I want a cost-free recorded profile, so that I can develop and test
    the complete asynchronous experience without AWS charges.
11. As an evaluator, I want the recorded profile to reject non-loopback network access, so that a
    regression test cannot contact AWS accidentally.
12. As an evaluator, I want recorded provider results selected by canonical input identity, so
    that results do not depend on invocation order or expected outcomes.
13. As an evaluator, I want an unknown recorded input to fail explicitly, so that the backend does
    not invent evidence for an unsupported document.
14. As an engineer, I want live provider construction to require both the live execution profile
    and an explicit paid-AWS switch, so that selecting one setting cannot incur cost accidentally.
15. As an auditor, I want the execution profile and exact provider, graph, prompt, model, and schema
    versions persisted with the workflow, so that recovery and reconstruction identify the
    processing contract used.
16. As an engineer, I want a resumed workflow to retain its pinned execution contract, so that a
    configuration change cannot silently change the meaning of an in-progress claim.

### Real document triage and extraction

17. As a member, I want uploaded PDF, JPEG, and PNG documents inspected by their content rather
    than their filename, so that mislabeled files do not silently enter the wrong workflow.
18. As a member, I want bounded pages rendered before intelligence processing, so that PDFs and
    images enter a consistent provider-safe representation.
19. As an operations reviewer, I want generic discovery OCR performed before document triage, so
    that a text-based model receives grounded document observations.
20. As an operations reviewer, I want every triage result to cover exactly one submitted document
    and cite discovery evidence, so that classifications are complete and auditable.
21. As a member, I want uncertain document roles preserved as unknown, so that the system does not
    guess a role.
22. As a member, I want unreadable documents to produce a targeted replacement action, so that a
    processing problem is not mistaken for ineligibility.
23. As a member, I want missing required document roles identified before complex extraction, so
    that unnecessary provider work is avoided.
24. As a member, I want identity conflicts linked to their source documents, so that I can correct
    the affected upload.
25. As an engineer, I want role-aware Textract analysis used only after discovery triage when it
    adds required structure, so that expense, form, and table extraction remains accurate.
26. As an operations reviewer, I want Qwen extraction candidates grounded to persisted OCR
    observations, so that unsupported model output is rejected.
27. As an operations reviewer, I want missing material fields to remain missing, so that a model
    cannot invent a bill total, diagnosis, treatment, or patient identity.
28. As an engineer, I want controlled field aliases normalized through a versioned registry, so
    that known provider variation can be accepted without weakening the schema.
29. As an auditor, I want alias normalization recorded without retaining medical text in telemetry,
    so that the transformation is explainable and privacy-safe.
30. As a policy owner, I want financial decisions to remain deterministic after extraction, so
    that Textract or Qwen never becomes payment authority.

### Processing failure and recovery

31. As a member, I want a claim to leave `QUEUED` when processing has permanently stopped, so that
    the frontend does not poll forever.
32. As a member, I want exhausted system or provider failures represented as
    `PROCESSING_FAILED`, so that they are not confused with a rejection or a requested document.
33. As a member, I want processing failures presented through safe, actionable codes, so that
    provider internals and sensitive evidence are not exposed.
34. As an operations reviewer, I want the complete internal failure history retained in the claim
    trace, so that the failure can be diagnosed.
35. As an engineer, I want retryable provider failures rescheduled durably, so that a worker
    restart does not lose the retry.
36. As an engineer, I want exhausted retries to update work, workflow, claim, and audit state
    consistently, so that no subsystem reports a contradictory terminal condition.
37. As an engineer, I want a lost lease to prevent an obsolete worker from committing a terminal
    effect, so that concurrent recovery is safe.

### Frontend operational contract

38. As a frontend developer, I want a liveness endpoint, so that I can determine whether the API
    process is running.
39. As a frontend developer, I want a readiness endpoint, so that I can determine whether the API
    can reach PostgreSQL and has valid runtime configuration.
40. As a frontend developer, I want claim polling to expose machine-readable progress, so that the
    interface can render the current processing stage.
41. As a frontend developer, I want the public claim lifecycle to include queued, action-required,
    in-review, decided, and processing-failed outcomes, so that every stopped state has a clear UI
    representation.
42. As a frontend developer, I want the existing submission, status, action, and review contracts
    to remain backward compatible except for additive lifecycle and progress values, so that the
    operational work does not require an unrelated frontend redesign.
43. As an operator, I want readiness checks to avoid calling Textract or Bedrock, so that health
    probes cannot incur cost.

### Agent observability

44. As an engineer, I want every trace related to a claim grouped under the claim identifier as a
    Phoenix session, so that submission, processing, correction, and review can be inspected
    together.
45. As an engineer, I want each claim version to have a distinct workflow trace, so that immutable
    versions remain distinguishable within the session.
46. As an engineer, I want API and worker execution correlated across the asynchronous boundary,
    so that the path from submission to outcome is navigable.
47. As an engineer, I want queue wait, workflow duration, node duration, work attempts, retries,
    provider latency, token counts, schema failures, candidate counts, evidence sufficiency, and
    terminal outcome represented by privacy-safe trace attributes, so that operational behavior is
    measurable in Phoenix.
48. As an evaluator, I want trace-level evaluations for schema validity, evidence grounding, trace
    completeness, reconstruction completeness, deterministic policy behavior, and telemetry
    privacy, so that quality signals are comparable.
49. As a privacy reviewer, I want patient names, medical facts, OCR text, document bytes, local
    paths, prompts, raw responses, and credentials excluded from normal spans and logs, so that
    observability does not become a medical-data store.
50. As an auditor, I want PostgreSQL to remain sufficient to reconstruct the decision after
    Phoenix and JSONL logs are deleted, so that diagnostics are not the source of business truth.
51. As an engineer, I want API, worker, and evaluation processes to write separate rotating JSONL
    logs, so that local troubleshooting remains manageable.

### Evaluation and completion evidence

52. As an evaluator, I want a public no-fixture end-to-end test, so that normal operational
    processing is proven independently of privileged fixture rows.
53. As an evaluator, I want the no-fixture test to submit through the public API and use the real
    worker composition, so that it exercises the frontend integration path.
54. As an evaluator, I want the no-fixture claim to reach action-required, in-review, or decided as
    expected, so that the operational proof cannot pass by merely recording a processing failure.
55. As an evaluator, I want all twelve supplied cases to continue passing the recorded rendered
    gate, so that operational changes do not weaken correctness.
56. As an evaluator, I want at least one complete synthetic claim to pass through the live API,
    durable queue, worker, LangGraph, Textract, Bedrock, reconciliation, and adjudication path, so
    that real provider integration is tested honestly.
57. As an evaluator, I want live AWS tests excluded from the default suite, so that normal
    verification remains cost-free.
58. As an evaluator, I want recorded evaluation reports saved outside temporary test storage, so
    that Backend v1 claims have durable proof.
59. As an evaluator, I want proof artifacts to identify source hashes, execution profile, model,
    prompt, schema, OCR, graph, reconstruction, test result, and telemetry privacy versions, so that
    results are reproducible.
60. As an evaluator, I want proof summaries to record the actual test counts, so that documentation
    does not become false when tests are added.
61. As a maintainer, I want formatting, lint, type, migration, deterministic, recorded, and selected
    live gates documented with their current results, so that completion is evidence-based.
62. As a maintainer, I want a completion report that distinguishes implemented capabilities,
    limitations, skipped paid tests, and known safe failures, so that Backend v1 is not overstated.

### Local-data safety

63. As a developer, I want the test database separated from the manual application database, so
    that running tests cannot erase claims submitted through the frontend.
64. As a developer, I want destructive tests to refuse the normal database unless explicitly
    overridden, so that accidental data loss is difficult.
65. As a privacy reviewer, I want Backend v1 real-world testing limited to synthetic or
    de-identified documents, so that deferred authentication, encryption, TLS, retention, and
    compliance controls are not misrepresented.

## Implementation Decisions

### Scope and architecture

- Complete the current architecture without performing the proposed feature-package
  reorganization.
- Preserve the existing application, domain, infrastructure, model, policy, and observability
  boundaries unless a targeted change is required for operational completion.
- Introduce one small construction boundary shared by the worker and integration tests.
- Keep FastAPI as the only frontend-facing authority.
- Keep PostgreSQL as the work queue, workflow state store, checkpoint store, audit authority, and
  decision source of truth.
- Keep original and rendered documents in the content-addressed local filesystem.
- Do not add S3, SQS, Redis, CloudWatch, Prometheus, Kafka, or a second agent framework.

### Worker

- Register one standalone worker executable with run-once and continuous-loop modes.
- Process one claim at a time for local Backend v1.
- Lease work only through the existing PostgreSQL scheduler and fencing-token contract.
- Renew the active lease during long processing.
- Stop leasing before graceful shutdown and apply a bounded shutdown period.
- Initialize LangGraph checkpoint tables before processing.
- Flush worker JSONL logs and Phoenix spans before process exit.
- Treat process exit, lease loss, retry, and terminal failure as explicit observable outcomes.

### Profiles and provider construction

- Support `RECORDED_LOCAL` as the default operational profile and `LIVE_INTELLIGENCE` as an
  explicit paid-provider profile.
- Retain structured component execution only for tests and evaluation.
- Recorded adapters select sanitized responses using canonical document or observation input
  hashes.
- Recorded adapters cannot read expected case outcomes, case-specific policy answers, or public
  request oracle fields.
- Unknown recorded inputs fail explicitly.
- AWS adapters may be constructed only when the live profile and paid-AWS authorization are both
  enabled.
- The committed default disables paid AWS execution.
- Pin execution profile and provider/model/prompt/schema/graph versions when a workflow run starts.

### Document intelligence

- Change the operational workflow order to render, discovery OCR, fast triage, early gate,
  role-aware analysis, complex extraction, reconciliation, and adjudication.
- Discovery OCR uses generic Textract text detection over bounded rendered pages.
- Fast triage consumes bounded discovery observations rather than filenames, oracle labels, or raw
  filesystem paths.
- Triage output must cover every submitted document exactly once and ground material
  classifications and identity observations.
- Unknown roles and insufficient readability remain explicit.
- Role-aware Textract processing may perform a second provider call when expense, form, or table
  structure is required.
- Complex extraction remains schema-constrained and grounding-validated.
- Prompt guidance explicitly requires canonical material fact paths.
- Known aliases are allowed only through an explicit versioned registry. The initial compatibility
  mapping permits `clinical.diagnosis` to normalize to `clinical.condition` when grounded.
- Missing `billing.total` or another material fact is never synthesized.
- Reconciliation and deterministic policy evaluation retain sole authority over the final
  recommendation and payable amount.

### Claim lifecycle and failure behavior

- Add `PROCESSING_FAILED` as a public lifecycle.
- Use `PROCESSING_FAILED` only after processing cannot safely continue and the retry budget is
  exhausted.
- Keep `ACTION_REQUIRED` for member-correctable evidence problems.
- Keep `IN_REVIEW` for claims requiring human judgment.
- Keep adjudication rejection separate from processing failure.
- Terminal processing failure must update the claim projection, work item, workflow run, audit
  event, and failure trace consistently.
- Public errors expose stable safe codes; detailed provider information remains internal.

### API and frontend integration

- Preserve the current claim submission, status, member action, and review APIs.
- Add liveness and readiness endpoints.
- Readiness verifies local configuration and PostgreSQL connectivity but does not call AWS.
- Extend the claim projection additively with processing-failed and agreed progress values.
- Continue polling the claim status endpoint; no websocket, server-sent event, or worker HTTP
  service is introduced.
- Update the frontend integration contract for every additive status, progress, health, and error
  value.

### Observability

- Use the claim identifier as the Phoenix session identifier.
- Use a distinct workflow trace for each immutable claim version.
- Persist or link sufficient asynchronous trace context to correlate API submission and worker
  processing.
- Continue storing workflow trace and span identifiers with PostgreSQL workflow events.
- Record privacy-safe trace attributes for queue, workflow, provider, retry, extraction,
  reconciliation, and terminal behavior.
- Record Phoenix trace evaluations for schema validity, evidence grounding, trace completeness,
  reconstruction completeness, deterministic policy behavior, and PHI safety.
- Use trace-derived metrics in Phoenix and PostgreSQL/JSONL operational records; do not add a
  separate metric service.
- Preserve the existing default prohibition on rich medical and model content.

### Evaluation and proof artifacts

- Add a public no-fixture end-to-end test using the production API and worker construction.
- Assert explicitly that no processing fixture row exists for that claim.
- Retain all twelve recorded rendered cases as the primary Backend v1 correctness gate.
- Require one selected synthetic live API-to-decision case plus Textract and Bedrock provider
  smoke tests.
- Keep all paid live tests explicitly selected and excluded from default verification.
- Save sanitized recorded evaluation, test summary, telemetry privacy, and version manifest
  artifacts in a durable Backend v1 artifact set.
- Commit sanitized proof artifacts but never commit raw documents, OCR bodies, prompts, responses,
  JSONL runtime logs, Phoenix storage, or provider credentials.
- Create a Backend v1 completion report only from current executed evidence.
- Report actual current test totals rather than retaining historical hardcoded counts.

### Local data protection

- Require the test database to differ from the normal application database.
- Refuse destructive integration setup against the normal database unless an explicit override is
  present.
- Limit Backend v1 document testing to synthetic or de-identified content.

## Testing Decisions

### Testing principles

- Test externally observable behavior rather than private orchestration details.
- Use the same construction boundary for the real worker and operational integration tests.
- Use real migrated PostgreSQL for lease, checkpoint, transaction, reconstruction, and concurrency
  behavior.
- Use the local filesystem implementation for document and page-artifact boundary tests.
- Mock only the true external Textract, Bedrock, and Phoenix boundaries.
- Recorded tests must fail if they attempt non-loopback network access.
- Live tests must use generated synthetic content and require explicit paid-AWS authorization.
- Oracle data must remain inaccessible until actual results are finalized.

### Required worker tests

- Run once with no due work.
- Lease and successfully process one due claim.
- Continuous loop processes work submitted after startup.
- Shutdown while idle.
- Shutdown while work is active.
- Lease renewal prevents reclamation.
- Lost lease prevents an obsolete terminal commit.
- Retryable failure is rescheduled.
- Exhausted failure transitions the claim to processing failed.
- Restart resumes from the last committed checkpoint.
- Worker telemetry flushes on shutdown.

Prior art: existing scheduler concurrency, workflow recovery, failure-policy, and workflow
observability tests.

### Required document-intelligence tests

- Discovery OCR precedes triage.
- Triage covers each submitted document exactly once.
- Unknown roles remain unknown.
- Missing roles stop before complex extraction.
- Unreadable documents request targeted replacement.
- Conflicting identities retain all grounded observations.
- Role-aware OCR follows successful triage.
- Complex candidates require valid OCR references.
- Known aliases normalize only when grounded.
- Missing material fields remain absent and cause a safe action, review, or processing failure.
- No model output can contain decision or payable-amount authority.

Prior art: existing document-role, readability, identity-conflict, OCR-persistence, structured-model,
and rendered-case tests.

### Required public and frontend contract tests

- Public submission returns an accepted queued claim.
- A no-fixture recorded claim leaves queued after worker execution.
- Every stopped lifecycle is represented in the member-safe projection.
- Processing-failed output contains a safe code and no provider-sensitive detail.
- Liveness succeeds without dependency checks.
- Readiness fails safely when PostgreSQL is unavailable.
- Readiness does not call AWS.
- Existing claim, action, and review response contracts remain compatible.

Prior art: existing claim and action API contract suites.

### Required observability and reconstruction tests

- API, worker, provider, workflow, and review spans share the expected claim session.
- Each claim version has the correct workflow trace.
- Required queue, provider, workflow, retry, and terminal attributes are present.
- Required trace evaluations are attached to the selected trace.
- API, worker, and evaluation JSONL files contain trace correlation fields.
- PHI canaries fail spans, evaluations, or logs containing forbidden content.
- PostgreSQL reconstructs the same claim after deleting Phoenix and JSONL diagnostic copies.

Prior art: existing observability, workflow observability, review workflow, reconstruction, and
rendered evaluation tests.

### Required acceptance gates

- The complete default deterministic suite passes with paid AWS disabled.
- The public no-fixture end-to-end test passes.
- All twelve recorded rendered cases pass.
- The sanitized recorded evaluation artifact is generated and validates successfully.
- Textract and Bedrock live smoke tests pass when explicitly selected.
- At least one synthetic live claim passes from public submission through terminal projection.
- Formatting, lint, strict typing, and migration drift checks pass.
- The normal and test database safety guard is verified.

## Out of Scope

- Reorganizing the codebase into new feature-oriented packages.
- Frontend implementation.
- Processing identifiable patient data.
- Production authentication or authorization infrastructure.
- JWT, OAuth, OIDC, Cognito, user registration, or session management.
- Encryption-at-rest key management, TLS termination, compliance certification, or formal data
  retention operations.
- Hosted deployment or production scaling.
- More than one concurrently processed claim per local worker.
- Guaranteeing automatic adjudication for every unseen medical document.
- Requiring all twelve supplied cases to pass through paid live AWS.
- Automatic updates to recorded provider responses.
- A worker HTTP server or dashboard.
- WebSockets, server-sent events, email, SMS, or push notifications.
- S3, SQS, Redis, Kafka, CloudWatch, Prometheus, or another workflow framework.
- Model-generated policy decisions, recommendations, or payable amounts.

## Further Notes

### Backend v1 completion definition

Backend v1 is operationally complete only when:

1. A normally started API accepts a valid claim.
2. A normally started worker leases and processes that claim.
3. Normal processing does not depend on a processing fixture row.
4. The claim cannot remain queued after its work item has terminally completed.
5. Recorded local processing works without AWS.
6. Live intelligence uses real Textract and Bedrock only after explicit authorization.
7. All twelve recorded rendered cases pass.
8. One synthetic live claim passes through the complete public and durable workflow.
9. PostgreSQL reconstructs the complete evidence, workflow, policy, calculation, decision, failure,
   and review history.
10. API, worker, and evaluation JSONL logs are generated.
11. Phoenix contains correlated claim sessions, workflow traces, provider spans, and agreed
    evaluations.
12. Telemetry contains no prohibited medical content or credentials.
13. Formatting, lint, typing, migration, deterministic, recorded, and selected live gates pass.
14. Paid AWS is disabled by default.
15. Sanitized proof artifacts and the completion report describe current evidence and limitations
    honestly.

### Approved delivery order

1. Add typed worker, profile, lease, and live-AWS configuration.
2. Add the shared runtime construction boundary.
3. Add standalone worker run-once and continuous-loop commands.
4. Replace normal-path fixture routing with execution-profile routing.
5. Implement render-first discovery OCR and grounded fast triage.
6. Wire role-aware Textract and grounded Qwen extraction into normal processing.
7. Add processing-failed terminal behavior and lease renewal.
8. Add the public no-fixture end-to-end test.
9. Add Phoenix sessions, trace attributes, evaluations, and worker logs.
10. Add the complete synthetic live API-to-decision test.
11. Save the recorded evaluation and completion proof artifacts.
12. Fix formatting and run every completion gate.
13. Update the existing implementation plan only with verified delivered results.

This PRD intentionally defines product behavior and acceptance evidence. The subsequent
tracer-bullet implementation plan should determine granular phases, dependency order, and commit
boundaries without weakening these requirements.
