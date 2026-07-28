# Backend PRD — Explainable Health-Claim Processing

**Status:** Approved for implementation  
**Product scope:** Backend v1  
**Primary framework:** FastAPI  
**Frontend:** Deferred; a future Next.js application will consume the FastAPI contract  
**Architecture authority:** `final_arch_v2.md`  
**Domain language:** `CONTEXT.md`

> Operational completion requirements are defined in
> [`backend_v1_operational_prd.md`](backend_v1_operational_prd.md).

## Problem Statement

Members submit health-insurance claims with medical and billing documents. Reviewing those documents, reconciling their contents, applying policy rules, calculating eligible amounts, and explaining the result is currently a manual process. The process is slow, inconsistent, difficult to audit, and cannot scale without increasing operations effort.

The backend must accept a claim, identify incorrect or unreadable documents before expensive processing, extract structured evidence from imperfect medical documents, reconcile conflicts, apply policy terms deterministically, and return an explainable recommendation. It must handle provider and workflow failures without crashing or silently producing unsafe decisions.

The supplied assignment package creates additional engineering constraints:

- The source policy contains contradictions and incomplete references.
- The twelve test cases include privileged oracle fields that must not enter the public API.
- Several expected outcomes require explicit policy clarifications.
- Medical documents are untrusted and may be blurry, handwritten, stamped, malformed, or contain prompt-injection text.
- Agent execution must be observable without making the agent trace the source of financial truth.
- The project runs locally and must avoid unnecessary hosted infrastructure.

Backend v1 must support all twelve supplied cases through the same public API used by a future frontend. It must not pass the cases through test-specific branches or by accepting oracle fields.

## Solution

Build a backend-first modular monolith with FastAPI as the only application API. A separate local worker executes a fixed LangGraph workflow. PostgreSQL stores claims, users, members, policies, work leases, checkpoints, evidence, decisions, reviews, and the immutable claim trace. Documents are stored in a content-addressed local filesystem.

The workflow uses bounded specialist agents for document triage, structured extraction, evidence reconciliation, and anomaly signals. AWS Textract performs OCR, layout, table, form, and expense analysis. AWS Bedrock Runtime, accessed through `ChatBedrockConverse`, performs schema-constrained classification and semantic extraction. Models may produce evidence candidates but may not produce authoritative claim decisions or payable amounts.

Policy terms and an explicit assignment overlay are compiled into immutable Policy IR. Pure deterministic Python evaluators apply eligibility, waiting periods, exclusions, pre-authorization, discounts, limits, and co-pay rules using integer paise. Every rule emits a structured result linked to policy paths and supporting evidence.

Agent execution is instrumented using OpenInference/OpenTelemetry and visualized through a local Arize Phoenix instance. Privacy-safe engineering logs are written as rotating JSONL. PostgreSQL remains the authoritative record explaining why the claim received its result.

The public backend surface is intentionally small:

- Submit a claim.
- Read the current claim projection.
- Apply an allowed member or reviewer action.
- List review tasks for a local reviewer.
- Inspect an operations trace.

Policy import, compilation, findings inspection, activation, and diagnostics are local CLI operations rather than mutable HTTP administration APIs. Claim evaluation remains an internal worker operation reached through the claim API.

### Backend-v1 outcomes

Backend v1 is successful when:

- All twelve supplied cases enter through the public multipart submission endpoint.
- Every case produces the expected decision or action-required state.
- Expected approved amounts match exactly.
- Every material fact is linked to evidence or marked unknown/conflicting.
- Every adjudication contains a deterministic rule and amount trace.
- Agent execution is visible in Phoenix.
- The business decision remains reconstructable from PostgreSQL without Phoenix or local log files.
- Default tests and recorded evaluation runs make no AWS calls.
- Selected synthetic cases pass through live Textract and Bedrock.

## User Stories

### Member submission and status

1. As a member, I want to submit claim metadata and documents in one request, so that starting a claim is simple.
2. As a member, I want the backend to accept multiple PDF, JPEG, and PNG documents, so that I can provide the evidence I have.
3. As a member, I want an accepted claim to return immediately with a claim identifier, so that I do not wait for OCR and model processing.
4. As a member, I want duplicate submission retries to return the original claim, so that network retries do not create duplicate claims.
5. As a member, I want a conflicting reuse of an idempotency key to be rejected, so that an accidental request mismatch is visible.
6. As a member, I want to retrieve the current status of my claim, so that I know whether it is queued, processing, waiting for action, under review, or decided.
7. As a member, I want progress stages to be machine-readable, so that a future frontend can render a reliable status stepper.
8. As a member, I want unsupported, corrupt, encrypted, oversized, or over-page-limit uploads to produce specific errors, so that I know how to correct them.
9. As a member, I want uploaded filenames to be treated as labels rather than trusted storage paths, so that malicious paths cannot affect local files.
10. As a member, I want replacement documents to create new immutable versions, so that the original submission and prior reasoning remain auditable.
11. As a member, I want claim actions to be idempotent, so that retrying a correction cannot apply it twice.
12. As a member, I want stale actions to be rejected, so that I cannot overwrite a newer claim state.

### Early document validation

13. As a member, I want the system to identify the actual role of each document, so that filenames or my labels are not trusted blindly.
14. As a member, I want the system to stop before full processing when a required document role is missing, so that I can fix the submission quickly.
15. As a member, I want a wrong-document message to name the observed role and required role, so that I know exactly what to upload.
16. As a member, I want an unreadable-document message to identify the affected document, so that I can replace the correct file.
17. As a member, I want an unreadable document to request replacement rather than reject the claim, so that a capture-quality problem is not treated as ineligibility.
18. As a member, I want conflicting patient names to be shown with their source documents, so that I can correct the mismatch.
19. As a member, I want unknown document roles to remain unknown, so that the system does not force a misleading classification.
20. As a member, I want equivalent evidence in a detailed dental bill to satisfy the procedure-evidence requirement, so that I am not asked for a redundant dental report.
21. As a member, I want a dental report requested when a bill lacks procedure-level detail, so that the adjudicator receives sufficient evidence.

### Evidence extraction and reconciliation

22. As an operations reviewer, I want OCR tokens and extracted fields linked to page and region provenance, so that I can verify them against the document.
23. As an operations reviewer, I want Textract and Bedrock observations kept separate, so that I can see which provider produced each candidate.
24. As an operations reviewer, I want patient identity reconciled across documents and the roster, so that another person's documents cannot be adjudicated silently.
25. As an operations reviewer, I want conflicting facts preserved rather than overwritten, so that ambiguity remains visible.
26. As an operations reviewer, I want missing critical facts represented as unknown, so that absence of evidence is not converted into a negative fact.
27. As an operations reviewer, I want bill totals reconciled against line items and claimed amounts, so that monetary discrepancies are explicit.
28. As an operations reviewer, I want clinical terminology normalized while retaining source text references, so that policy rules can use canonical concepts without losing provenance.
29. As an operations reviewer, I want every frozen casefile to have a content hash and version, so that historical decisions are reproducible.
30. As an operations reviewer, I want evidence sufficiency evaluated before policy adjudication, so that incomplete claims do not receive unsafe automatic outcomes.

### Policy and adjudication

31. As a policy operator, I want source policy terms preserved unchanged, so that the original configuration remains auditable.
32. As a policy operator, I want policy contradictions emitted as structured findings, so that ambiguities cannot be hidden.
33. As a policy operator, I want an explicit versioned overlay to clarify assignment rules, so that expected behavior does not require test-specific code.
34. As a policy operator, I want policy terms and overlays compiled before activation, so that invalid policies cannot govern claims.
35. As a policy operator, I want category-specific limits to override the general per-claim limit, so that specific coverage rules have clear precedence.
36. As a policy operator, I want the consultation category limit clarified as ₹5,000 in the assignment overlay, so that the supplied consultation cases are coherent.
37. As a policy operator, I want MRI and CT pre-authorization required above ₹10,000, so that threshold-based authorization is deterministic.
38. As a policy operator, I want PET scans to require pre-authorization, so that the specific policy requirement is enforced.
39. As a member, I want missing required pre-authorization to produce a specific rejection and resubmission explanation, so that I know what was required.
40. As an operations reviewer, I want an unreadable or conflicting pre-authorization document routed for correction or review, so that it is not treated as conclusively absent.
41. As an operations reviewer, I want exclusions applied at the line-item level, so that covered and excluded treatments remain distinguishable.
42. As a member, I want partial approvals to identify approved and rejected line items, so that the payable amount is understandable.
43. As a member, I want network discount applied before co-pay, so that the calculation follows the clarified rule order.
44. As a member, I want every deduction to show its reason, policy path, amount before, adjustment, and amount after, so that I can follow the calculation.
45. As an engineer, I want the same casefile and policy version to produce the same decision hash, so that adjudication is reproducible.
46. As an engineer, I want all monetary calculations performed in integer paise, so that floating-point behavior cannot affect payment recommendations.
47. As an engineer, I want model output schemas to forbid decisions and approved amounts, so that models cannot cross the financial authority boundary.

### Failures and operational handling

48. As a member, I want provider timeouts to be retried without producing duplicate claim evidence, so that transient failures are recoverable.
49. As an operations reviewer, I want every retry and degradation recorded in the trace, so that incomplete processing is visible.
50. As an operations reviewer, I want critical OCR, identity, or policy failures to block automatic handling, so that missing required evidence cannot cause approval.
51. As an operations reviewer, I want a non-critical anomaly-enrichment failure to preserve the policy recommendation while recommending review, so that TC011 is represented without conflating decision and handling.
52. As an engineer, I want a worker restart to reclaim expired work and resume from its last checkpoint, so that local process failure does not lose a claim.
53. As an engineer, I want PostgreSQL work items created in the same transaction as claim acceptance, so that no accepted claim is left unscheduled.
54. As an engineer, I want provider work to run outside database transactions, so that slow AWS calls do not hold database locks.
55. As an engineer, I want retry schedules stored durably, so that the process does not sleep while holding application state in memory.
56. As an engineer, I want policy or audit persistence failures to prevent terminal commit, so that the API never reports an unrecorded decision.

### Manual review and identity boundary

57. As a local user, I want a unique username mapped to an immutable user identity, so that usernames may change without corrupting historical ownership.
58. As an engineer, I want authentication hidden behind an identity-provider port, so that JWT, OAuth, OIDC, or Cognito can be added later.
59. As a member user, I want to access only claims linked to my member identity, so that application authorization is testable before real authentication exists.
60. As a reviewer user, I want to list open review tasks, so that I can find claims needing human judgment.
61. As a reviewer user, I want to inspect evidence, conflicts, policy rules, calculations, and failures before acting, so that review is informed.
62. As a reviewer user, I want allowed actions constrained by review-task type, so that invalid state transitions are rejected.
63. As a reviewer user, I want to accept, amend, reject, or request documents with a structured reason, so that the action is auditable.
64. As a reviewer user, I want my action to preserve the original machine recommendation, so that human overrides remain distinguishable.
65. As an operator user, I want policy and trace diagnostics restricted from member projections, so that members do not receive internal risk or provider details.

### Agent observability and logs

66. As an engineer, I want every claim-processing run represented as a Phoenix trace, so that I can inspect the complete agent execution tree.
67. As an engineer, I want LangGraph node entry, exit, duration, and outcome captured automatically, so that graph behavior is visible.
68. As an engineer, I want Bedrock calls to show model, prompt version, schema version, tokens, latency, and errors, so that model behavior can be diagnosed.
69. As an engineer, I want custom spans around Textract, reconciliation, policy evaluation, and persistence, so that non-LLM steps appear in the same trace.
70. As an engineer, I want trace and span identifiers copied into structured logs, so that logs and visual traces can be correlated.
71. As an engineer, I want logs split by API, worker, and evaluation process, so that local diagnosis is manageable.
72. As a privacy reviewer, I want Phoenix and logs to exclude patient names, diagnoses, OCR text, document bytes, local paths, and raw model bodies by default, so that observability does not become a medical-data store.
73. As an evaluator, I want a synthetic-only mode that can capture richer model payloads explicitly, so that prompts and schemas can be debugged without real medical data.
74. As an operations reviewer, I want the business claim trace available even if Phoenix data and JSON logs are deleted, so that explainability is not vendor-dependent.

### Evaluation and quality

75. As an evaluator, I want structured-component tests that bypass OCR, so that reconciliation and policy regressions are isolated.
76. As an evaluator, I want rendered-document tests that submit generated files through FastAPI, so that OCR-to-decision behavior is exercised honestly.
77. As an evaluator, I want oracle fields unavailable to production request schemas, so that the implementation cannot cheat.
78. As an evaluator, I want claim history and YTD utilization seeded in PostgreSQL, so that those values are calculated by the backend.
79. As an evaluator, I want unreadable documents generated through deterministic transforms, so that quality cases are repeatable.
80. As an evaluator, I want component failures injected through named evaluation-only fault points, so that resilience tests are deterministic.
81. As an evaluator, I want the recorded profile to make no network calls, so that regression tests are fast and cost-free.
82. As an evaluator, I want live-intelligence tests to require an explicit flag, so that AWS cost is never incurred accidentally.
83. As an evaluator, I want each report to identify policy, model, prompt, schema, dataset, and execution-profile versions, so that results are comparable.
84. As an evaluator, I want exact decision, amount, reason-code, provenance, and trace scoring, so that pass/fail is not based on a vague judge.
85. As an evaluator, I want all twelve cases to include complete result and trace artifacts, so that failures can be explained.

## Implementation Decisions

### System boundary

- FastAPI is the only backend application authority.
- A future Next.js application will be a client of the FastAPI contract.
- Next.js will not access PostgreSQL, local documents, Textract, Bedrock, LangGraph, or policy evaluators directly.
- Backend v1 is asynchronous: submission returns `202 Accepted`, and a separate local worker processes durable PostgreSQL work.
- FastAPI background tasks and in-memory queues are not durable workflow mechanisms.
- The backend is a modular monolith with a separate API process, worker process, CLI, PostgreSQL process, and local Phoenix process.

### Deep modules

The backend will expose one deep claim-processing application boundary with three operations:

- Submit a claim with an idempotency key.
- Retrieve the authorized claim projection.
- Apply an authorized, versioned claim command.

The application boundary hides:

- Local document persistence and versioning.
- Durable work creation and leasing.
- LangGraph execution and checkpoints.
- Textract and Bedrock calls.
- Evidence reconciliation.
- Policy compilation and evaluation.
- Review task creation and resolution.
- Decision and audit persistence.
- Agent trace instrumentation.

Internal deep modules are:

- Claim Processing.
- Local Document Store.
- Document Intelligence.
- Claim Evidence Casefile.
- Versioned Policy Adjudicator.
- Work Scheduler.
- Manual Review.
- Decision Record.
- Evaluation Workbench.
- Local Identity Provider.

LangGraph nodes are adapters around these modules rather than the modules themselves.

### API contract

Backend v1 exposes:

- `POST /v1/claims` for multipart claim submission.
- `GET /v1/claims/{claim_id}` for the authorized current claim projection.
- `POST /v1/claims/{claim_id}/actions` for idempotent member or reviewer commands.
- `GET /v1/review-tasks` for authorized review-task listing.
- `GET /v1/ops/claims/{claim_id}/trace` for the authoritative operations trace.
- `GET /v1/ops/claims/{claim_id}/evidence` for reviewer evidence details.

Claim submission uses:

- A required idempotency header.
- A JSON metadata form part.
- One or more streamed file parts.
- A document manifest mapping file position to an opaque client document identifier.

The production submission schema rejects:

- Actual document type.
- Extracted document content.
- Ground-truth readability.
- Patient-name oracle fields.
- Caller-supplied claim history.
- Caller-supplied YTD utilization.
- Component-failure simulation.
- Caller-selected model or policy behavior.

Wrong, missing, unreadable, or conflicting documents are persisted claim states with an actionable next action. They are not general HTTP failures. Request syntax, authorization, unknown resources, idempotency conflicts, unsupported media, and storage-limit violations use structured API errors.

### Identity and authorization

- Backend v1 does not implement passwords, JWT issuance, OAuth, refresh tokens, sessions, or account-management APIs.
- Users have immutable UUID identifiers and unique case-insensitive usernames.
- Usernames may be renamed without changing claim or audit ownership.
- A replaceable identity-provider port resolves requests to a principal.
- The initial local adapter resolves a development username header against seeded users.
- Roles are member, reviewer, and operator.
- Members may submit/read their claims and satisfy member actions.
- Reviewers may inspect operations projections and resolve review tasks.
- Operators may run privileged diagnostics where applicable.
- Every mutation records the immutable user identifier and username snapshot.

### Upload and local document storage

- Supported upload formats are PDF, JPEG, and PNG.
- Maximum files per claim: 10.
- Maximum original size per file: 20 MiB.
- Maximum aggregate upload size per claim: 50 MiB.
- Maximum pages per document: 10.
- Maximum rendered Textract page size: 5 MiB.
- Encrypted, corrupt, unsupported, oversized, or over-page-limit documents are rejected with actionable errors.
- Files are streamed, hashed, MIME-validated, synchronized, and atomically sealed.
- Storage paths contain opaque identifiers or content hashes, never user filenames or medical data.
- Relative paths must resolve beneath the configured data root.
- Symlinks and traversal are forbidden.
- Sealed document versions are immutable.
- Replacement documents create new versions and never overwrite originals.
- PDF pages are rendered locally into ordered bounded PNG/JPEG derivatives.

### Database and transactions

- PostgreSQL is the only durable database.
- SQLAlchemy 2 async sessions and Psycopg 3 are used for persistence.
- Alembic manages schema migrations.
- SQLAlchemy ORM is used for ordinary persistence.
- SQLAlchemy Core or explicit SQL is allowed for locking, leasing, and performance-critical queries.
- SQLite is not treated as a PostgreSQL-equivalent integration-test substitute.
- Database transactions remain short and never wrap Textract or Bedrock calls.
- Claim acceptance, document metadata, audit event, idempotency response, and initial work item commit atomically.
- Terminal decision, rule trace, amount steps, claim projection, audit events, and work completion commit atomically.

### Work scheduling

- A PostgreSQL work table is the durable local scheduler.
- Work items contain an operation key, availability time, status, attempts, maximum attempts, lease owner, lease expiry, and sanitized failure code.
- Workers claim due work using PostgreSQL row locking with skip-locked semantics.
- A worker commits the lease before performing provider work.
- Expired leases are reclaimable.
- Retries set a future availability time rather than sleeping in a database transaction.
- Optional database notifications may wake the worker, but the table row remains authoritative.
- FastAPI background tasks, SQS, Redis, and Kafka are not part of backend v1.

### LangGraph workflow

- One fixed LangGraph workflow executes each claim-processing run.
- The workflow-run identifier is the LangGraph thread identifier.
- Each run references exactly one claim version.
- Graph state contains identifiers, hashes, route decisions, statuses, and small summaries rather than document bytes or complete OCR/model bodies.
- The graph uses PostgreSQL checkpoints.
- The workflow consists of claim loading, document triage, early gate, page rendering, document extraction, evidence reconciliation, anomaly signals, deterministic adjudication, and routing/persistence.
- Agents do not communicate through unrestricted free-form conversations.
- Human review is implemented through explicit application commands and LangGraph interruption/resumption.
- The policy evaluator is deterministic code and is not an LLM agent.

### Document intelligence

- Seven typed document roles are supported: prescription, hospital bill, pharmacy bill, laboratory report, diagnostic report, dental report, and pre-authorization.
- Discharge summaries may be recognized but use a generic optional-document representation in backend v1.
- Unknown roles remain unknown.
- Local media inspection precedes model/provider processing.
- A fast logical Bedrock route performs document-role, readability, and selected early identity triage on bounded previews.
- The required-document gate runs before full Textract processing.
- Detailed actionable feedback names the affected document, observed role, required role, and corrective action.
- A dental report is conditionally required only when other evidence does not establish procedure-level facts.
- Synchronous Textract processes locally rendered page bytes.
- Bills and receipts use expense analysis where appropriate.
- Forms, tables, and reports use document analysis features appropriate to the profile.
- Free-text documents use text/layout analysis.
- Page artifacts are persisted and merged deterministically.
- No page may be dropped or reordered silently.

### Bedrock model integration

- `ChatBedrockConverse` is used behind a project-owned structured-evidence model port.
- LangChain and Bedrock types do not enter domain contracts.
- Direct Boto3 is used for Textract.
- Two logical Bedrock routes exist: fast triage and complex extraction.
- Both routes initially point to the configured, enabled, evaluation-approved Qwen 3 235B A22B model.
- Model identifiers are configuration rather than hardcoded domain constants.
- Temperature is zero where supported.
- Pydantic structured output is required.
- Model schemas forbid decisions, payable amounts, policy outcomes, and arbitrary tools.
- Model output is untrusted until schema, semantic, grounding, and authority validation succeeds.
- A later evaluation may move the fast route to a cheaper model without changing domain interfaces.

### Evidence and casefile

- All extracted values begin as evidence candidates.
- Candidates include producer, producer version, document version, page, geometry, schema version, confidence, and source hash.
- Reconciliation groups candidates by canonical fact path.
- Facts have known, unknown, or conflict states.
- Conflicting candidates remain available for review.
- Member roster and history facts originate from PostgreSQL rather than submission data.
- The casefile freezes the reconciled evidence set used by adjudication.
- Every casefile has an immutable version and content hash.
- Policy evaluation receives only a frozen casefile and compiled policy version.

### Policy source, overlay, and execution

- Source policy JSON remains immutable and is stored with its hash.
- The assignment overlay remains explicit, immutable, versioned, and separately hashed.
- The overlay contains domain clarifications and never test identifiers.
- Policy compilation emits structured schema, semantic, referential, vocabulary, and contradiction findings.
- Invalid policy versions cannot activate.
- Compilation, inspection, and activation are CLI-only in backend v1.
- The setup importer loads policy source, overlay, compiled IR, and member roster into PostgreSQL.
- Claims pin member and policy snapshot references.
- Missing dependent records remain validation findings and unknown eligibility facts.
- Category-specific limits override the general per-claim limit.
- The assignment consultation category limit is ₹5,000.
- Dental procedure evidence may be satisfied by a detailed line-item bill.
- MRI and CT require pre-authorization when the eligible amount exceeds ₹10,000.
- PET requires pre-authorization.
- Specific pre-authorization rules override the generic false flag.
- Pre-authorization must be supported by a verifiable document.
- Policy rules are pure deterministic Python evaluators over compiled Policy IR.
- No third-party rules engine is introduced.
- Money uses integer paise.
- Evaluation order is eligibility, evidence sufficiency, waiting periods, exclusions, pre-authorization, network discount, category limit, annual/family remaining limit, co-pay, and final recommendation.
- Excluded items are removed before category-limit evaluation.
- Network discount is applied before co-pay.
- Eligible amounts above a reject-semantics category limit produce rejection rather than silent capping.
- Every rule result includes status, reason, policy path, supporting evidence, inputs, and amount transformation.

### Decision, lifecycle, and handling

- Lifecycle and adjudication are separate axes.
- Lifecycle states are received, queued, triaging, extracting, reconciling, adjudicating, action required, in review, decided, system blocked, and cancelled.
- Adjudication recommendations are approved, partial, and rejected.
- Handling dispositions describe whether automatic completion, member action, required review, or recommended review applies.
- The assignment-compatible projection may return manual review where required without storing it as a financial outcome.
- TC011 produces an approved recommendation with manual review recommended and a visible degraded anomaly-enrichment component.
- Critical OCR, identity, policy, or audit failure cannot produce automatic approval.
- A deterministic reason-template renderer is the explanation fallback.

### Manual review

- Review tasks are durable PostgreSQL records.
- Tasks identify unresolved facts, policy ambiguity, anomaly signals, or degraded components.
- Tasks expose only allowed action types.
- Review commands include expected claim version and idempotency key.
- Optimistic concurrency prevents two reviewers from applying conflicting actions.
- Human resolutions and overrides are immutable records linked to the machine recommendation.
- Reviewer identity, structured reason, note, and before/after values are retained.
- Backend v1 implements review APIs but no review frontend.

### Retry and failure behavior

- Initial Textract timeout is 30 seconds per page.
- Initial Bedrock timeout is 90 seconds.
- Maximum provider attempts are three.
- Initial Textract and Bedrock concurrency limits are two each.
- Initial worker lease duration is five minutes.
- Values are configurable.
- Exponential backoff with jitter is used.
- Timeouts, throttling, connection failures, and selected provider 5xx errors are retryable.
- Invalid inputs, unsupported media, policy contradictions, and deterministic schema/semantic failures are not retried indefinitely.
- Required evidence failures route to correction, review, or system blocked.
- Optional failures may continue only when evidence sufficiency remains satisfied.
- Every failure, retry, fallback, and degradation is visible in the trace.

### Agent observability

- Arize Phoenix runs locally and is the required agent-trace backend.
- OpenInference/OpenTelemetry instruments LangGraph and model calls.
- Direct Textract, reconciliation, policy, and persistence operations receive custom spans.
- Phoenix traces contain graph structure, timings, outcomes, errors, provider request IDs, token usage, and pinned versions.
- Phoenix receives no patient names, diagnoses, OCR text, document bytes, local paths, raw prompts, raw responses, or credentials by default.
- Synthetic evaluation may explicitly enable richer safe payloads.
- Trace identifiers propagate into structured application logs.
- Phoenix is diagnostic and not the business decision authority.

### Engineering logs and domain trace

- Structured application logs use JSON and rotate locally by size/count.
- API, worker, and evaluation processes write separate files.
- Logs contain timestamps, severity, component, claim/run/span identifiers, attempt, duration, outcome, provider metadata, and sanitized error class.
- Log-write failures are visible through stderr and diagnostics.
- PostgreSQL stores append-only workflow events, evidence references, casefiles, rule trees, amount steps, decisions, failures, and review actions.
- A claim decision must be reconstructable using PostgreSQL after Phoenix and log data are removed.
- Domain audit persistence failure prevents terminal decision commit.

### Evaluation profiles

- Unit mode uses deterministic fakes and no network.
- Recorded mode uses sanitized provider recordings and no network.
- Live-intelligence mode uses real Textract and Bedrock only when explicitly selected.
- Normal test commands cannot incur AWS cost.
- Provider recordings contain no PHI.
- Model, prompt, schema, or route changes require live comparison before recordings are updated.
- Eval reports identify the execution profile used.

### Assignment fixture adapter

- The fixture adapter owns access to privileged test fields.
- Structured component mode builds privileged evidence inputs and bypasses OCR.
- Rendered E2E mode generates PDFs/images, applies deterministic quality transformations, seeds repository history, installs named failures, and submits through the public API.
- Expected outcomes remain isolated until the system result exists.
- The production application cannot import the fixture adapter or fault plan.
- The full twelve-case report includes the actual result, expected result, match status, trace references, assumptions, and failures.

## Testing Decisions

### Testing principles

- Tests assert externally observable behavior through deep-module or public API boundaries.
- Tests do not assert incidental LangGraph node implementation details unless ordering is a business invariant.
- Tests use real PostgreSQL semantics for locking, JSONB, constraints, migrations, and concurrency.
- Tests distinguish pure policy correctness, structured component behavior, rendered E2E behavior, recorded provider integration, and live provider behavior.
- A test that injects structured content cannot claim to validate OCR.
- Golden outputs do not override identified source-policy contradictions silently.
- Every significant component has success, malformed-input, boundary, retry, and failure tests.

### Test tooling

- Pytest is the primary runner.
- Pytest asyncio support is used for asynchronous application and repository tests.
- Hypothesis is used for monetary, date, limit, ordering, and idempotency properties.
- HTTPX asynchronous clients exercise FastAPI endpoints.
- A real PostgreSQL container runs repository, migration, scheduling, and workflow tests.
- Botocore stubs validate Textract request/response and error mapping.
- Recorded sanitized Bedrock responses validate schema and workflow integration.
- Ruff enforces lint and formatting.
- Mypy enforces static type boundaries.

### Module boundary tests

- Claim Processing is tested through submit, get, and action operations.
- Local Document Store is tested for streaming, hashes, atomic sealing, immutability, traversal, symlinks, corruption, limits, and replacement versions.
- Document Intelligence is tested for profile routing, ordered page processing, typed provider outcomes, and provenance.
- Claim Evidence Casefile is tested for identity, dates, money, normalization, conflicts, and unknowns.
- Versioned Policy Adjudicator is tested for compilation, precedence, rule order, arithmetic, reason traces, and determinism.
- Work Scheduler is tested for atomic enqueue, leases, expiry, retry scheduling, concurrency, and duplicate operation keys.
- Manual Review is tested for task routing, allowed commands, optimistic concurrency, idempotency, and immutable overrides.
- Decision Record is tested for atomic terminal persistence and audit failure.
- Evaluation Workbench is tested for oracle separation and execution-profile isolation.
- Identity Provider is tested for username lookup, roles, claim authorization, and replaceability.

### Mandatory behavior tests

- Production submission rejects all oracle-only fields.
- Multipart uploads stream without buffering entire documents in application memory.
- Reusing an idempotency key with the same canonical request returns the original receipt.
- Reusing an idempotency key with a different request returns a conflict.
- Claim and initial work-item creation are atomic.
- A worker crash and expired lease resume from the last committed checkpoint.
- Repeated provider operations cannot create duplicate observations or decisions.
- Wrong-document and unreadable-document cases stop before adjudication.
- Patient-name conflicts are not collapsed silently.
- Every trusted material fact has provenance.
- Missing facts remain unknown.
- Model output containing decision or amount fields is rejected.
- Same casefile and policy version produce the same canonical decision.
- Approved amounts remain between zero and the eligible claimed amount.
- Excluded line items cannot receive an approved amount.
- Increasing co-pay cannot increase the approved amount.
- Decreasing a limit cannot increase the approved amount.
- Network discount occurs before co-pay.
- Missing pre-authorization follows the clarified conditional rules.
- Non-critical anomaly-enrichment failure produces a visible approved recommendation with review recommended.
- Critical evidence failure cannot auto-approve.
- Audit failure prevents terminal commit.
- Engineering trace/log failure does not alter a valid domain transaction.
- Stale reviewer commands fail.
- Repeated reviewer command keys return the original result.
- Member projections do not expose internal provider, risk, or raw evidence content.
- Reviewer projections contain evidence, rule, calculation, failure, and override traces.
- Phoenix span/log attributes pass PHI canary scanning.
- Deleting Phoenix and JSON logs does not prevent PostgreSQL claim reconstruction.

### Assignment acceptance tests

- TC001 produces action required, identifies two prescriptions, names the missing hospital bill, and contains no adjudication.
- TC002 requests replacement of the unreadable pharmacy bill and does not reject the claim.
- TC003 retains both patient names and requests correction/review without adjudication.
- TC004 produces approved ₹1,350 with a 10% co-pay trace.
- TC005 rejects for waiting period and reports the eligibility date.
- TC006 produces partial ₹8,000 with covered root canal and excluded whitening line items.
- TC007 rejects for missing required MRI pre-authorization and explains resubmission.
- TC008 rejects because the ₹7,500 eligible consultation amount exceeds the ₹5,000 category limit.
- TC009 routes to manual review and lists the same-day velocity signals.
- TC010 produces approved ₹3,240 and shows network discount before co-pay.
- TC011 produces an approved ₹4,000 recommendation, a degraded anomaly-enrichment component, reduced completeness/confidence, and manual review recommended.
- TC012 rejects for the supported excluded obesity/bariatric treatment.

## Out of Scope

- Next.js implementation and all frontend components.
- Password storage and verification.
- JWT creation, refresh tokens, OAuth, OIDC, Cognito, and session management.
- User-registration, password-reset, and account-management APIs.
- Payment execution or payment ledger.
- Insurer, hospital, pharmacy, or third-party claims-system integrations.
- Hosted environments and remote operation.
- Production availability, compliance, retention, or regulatory certification claims.
- S3, SQS, SNS, CloudWatch, X-Ray, Redis, Kafka, and hosted observability.
- Policy administration over HTTP.
- Policy administration UI.
- Review UI.
- Notification delivery through email, SMS, or push.
- Malware-scanning service integration.
- Native asynchronous multipage Textract.
- Arbitrarily large documents.
- General-purpose autonomous agent planning.
- A vector database or semantic policy retrieval.
- Automated fraud rejection or a learned fraud-scoring model.
- Model-generated financial decisions.
- Supporting every possible medical document format or language.

## Further Notes

### Approved implementation sequence

1. Establish project tooling, settings, migrations, PostgreSQL, domain value objects, and import boundaries.
2. Implement policy import, overlay, compiler, findings, pure rules, and property tests.
3. Implement the claim facade, identity boundary, multipart acceptance, local documents, idempotency, audit, and PostgreSQL work scheduler.
4. Implement the fixed LangGraph skeleton, checkpoints, worker leases, retries, and recorded provider ports.
5. Implement early document triage and the TC001–TC003 action-required slice.
6. Implement Textract page analysis, Bedrock structured extraction, evidence provenance, and casefile reconciliation.
7. Implement deterministic adjudication and the TC004 clean-approval slice.
8. Implement failure injection and the TC011 graceful-degradation slice.
9. Implement remaining category, waiting-period, pre-authorization, line-item, anomaly, and review behavior.
10. Implement Phoenix instrumentation, structured logs, trace endpoints, fixture rendering, and the full evaluation report.

### Delivery strategy

Implementation should follow vertical tracer bullets rather than completing every infrastructure layer first:

- First prove wrong-document early stopping.
- Then prove clean approval from upload through persisted decision.
- Then prove graceful degradation.
- Expand to the remaining nine cases after the authority, persistence, and trace boundaries work end to end.

### Current repository state

The repository contains the assignment inputs, final architecture, and domain glossary but no backend application code. There is no existing implementation whose behavior must be preserved.

### GitHub issue publication

This PRD is suitable as a GitHub issue body. The repository currently has no configured GitHub remote, so issue creation must wait until an issue target exists.
