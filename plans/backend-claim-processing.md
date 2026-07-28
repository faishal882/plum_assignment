# Plan: Explainable Health-Claim Processing Backend

> Source PRD: [Backend PRD — Explainable Health-Claim Processing](../backend_prd.md)

## Architectural decisions

Durable decisions that apply across all phases:

- **Application boundary**: FastAPI is the only backend authority. A future Next.js application is an API client and does not access persistence, documents, AWS providers, workflow state, or policy logic directly.
- **Routes**: `POST /v1/claims` submits a claim; `GET /v1/claims/{claim_id}` returns its authorized projection; `POST /v1/claims/{claim_id}/actions` applies versioned commands; `GET /v1/review-tasks` lists authorized review work; operations routes expose claim traces and evidence.
- **Execution model**: Submission is asynchronous and returns `202 Accepted`. A separate local worker leases durable PostgreSQL work and executes one fixed typed LangGraph workflow per claim version.
- **Persistence**: PostgreSQL is the only durable database. SQLAlchemy 2 async, Psycopg 3, and Alembic are used. Real PostgreSQL—not SQLite—is required for integration behavior.
- **Core records**: User, Member, Claim, Claim Version, Document, Document Version, Idempotency Record, Work Item, Workflow Run, Policy Source, Policy Overlay, Policy IR, Member Snapshot, Evidence Candidate, Reconciled Fact, Casefile, Rule Result, Amount Step, Decision, Review Task, Human Resolution, and Audit Event.
- **Identity**: The initial development adapter maps a unique case-insensitive username to an immutable user UUID. Authorization is enforced through a replaceable identity-provider boundary so JWT, OAuth, OIDC, or Cognito can be introduced later.
- **Documents**: Originals and rendered pages use a content-addressed local store. Sealed document versions are immutable, filenames are untrusted labels, and no user-controlled path may influence storage.
- **AWS boundaries**: Direct Boto3 is used for Textract. Bedrock is accessed through `ChatBedrockConverse` behind a project-owned structured-evidence model boundary. AWS and LangChain types do not enter the domain model.
- **Agent design**: Agents are bounded typed workflow capabilities, not autonomous financial decision-makers. LangGraph state carries identifiers, hashes, statuses, and small summaries rather than document bytes or raw provider bodies.
- **Financial authority**: Models produce evidence candidates only. Policy compilation and adjudication are deterministic Python operations over a frozen casefile and immutable Policy IR. Money is represented in integer paise.
- **Decision model**: Claim lifecycle, adjudication recommendation, and handling disposition are separate axes. `APPROVED`, `PARTIAL`, and `REJECTED` are adjudication results; action-required and manual-review states describe workflow handling.
- **Transaction boundary**: Claim acceptance and initial work creation commit atomically. Provider calls never run inside database transactions. Terminal decision, rule trace, amount trace, audit events, projection, and work completion commit atomically.
- **Observability**: PostgreSQL is the authoritative decision trace. Local Phoenix receives OpenInference/OpenTelemetry agent traces, and rotating JSONL files contain engineering logs. Neither Phoenix nor logs are required to reconstruct a decision.
- **Privacy**: Raw documents, OCR text, patient names, diagnoses, prompts, responses, credentials, and local paths are excluded from Phoenix and normal logs. Rich model capture is permitted only for explicitly synthetic evaluation.
- **Evaluation**: Unit and recorded profiles make no network calls. Live-intelligence evaluation is explicit and uses real Textract and Bedrock. Privileged oracle data remains isolated from production schemas and runtime modules.
- **Excluded infrastructure**: S3, SQS, SNS, CloudWatch, X-Ray, Redis, Kafka, hosted observability, and deployment architecture are outside this plan.

---

## Phase 1: Claim receipt and status projection

**User stories**: 1, 3, 6, 7

### What to build

Create the smallest useful backend slice: a member submits valid claim metadata, the backend persists a claim and initial work record atomically, returns an acceptance receipt, and exposes an authorized status projection. The worker does not adjudicate yet; this phase proves the public contract, persistence boundary, and asynchronous lifecycle.

### Acceptance criteria

- [ ] `POST /v1/claims` accepts a valid multipart request containing metadata and at least one bounded placeholder document.
- [ ] A successful request returns `202 Accepted`, a stable claim identifier, current version, lifecycle state, and status URL.
- [ ] Claim, claim version, initial audit event, and queued work item are committed in one PostgreSQL transaction.
- [ ] `GET /v1/claims/{claim_id}` returns the persisted member-safe projection.
- [ ] Lifecycle transitions from `RECEIVED` to `QUEUED` are explicit and machine-readable.
- [ ] Invalid metadata produces a stable structured error and creates no claim or work item.
- [ ] Contract and repository tests run against a real migrated PostgreSQL database.

---

## Phase 2: Local development identity boundary

**User stories**: 57, 58, 59

### What to build

Put identity and authorization in front of the Phase 1 path. Development requests resolve a unique username into an immutable principal, while claim ownership and role checks depend only on the project-owned identity contract.

### Acceptance criteria

- [ ] Seeded users have immutable UUIDs, unique case-insensitive usernames, and one or more supported roles.
- [ ] The local development identity mechanism resolves requests without introducing passwords, tokens, sessions, or OAuth flows.
- [ ] Renaming a username does not change historical ownership or audit identity.
- [ ] Members can submit and read only claims associated with their member identity.
- [ ] Unknown, malformed, or unauthorized identities receive stable errors without disclosing claim existence.
- [ ] Claim mutations retain the immutable user ID and a username snapshot.
- [ ] Tests prove that the local identity adapter can be replaced without changing claim application behavior.

---

## Phase 3: Safe multipart document ingestion

**User stories**: 2, 8, 9

### What to build

Replace placeholder document handling with bounded streaming ingestion into the local content-addressed store. Validate actual media, seal immutable originals, and make all storage behavior independent of untrusted filenames.

### Acceptance criteria

- [ ] PDF, JPEG, and PNG uploads are accepted after signature and structural validation.
- [ ] Files are streamed, hashed, synchronized, and atomically sealed without buffering the complete claim in application memory.
- [ ] Claims enforce at most 10 documents, 20 MiB per document, 50 MiB aggregate, and 10 pages per document.
- [ ] Corrupt, encrypted, unsupported, oversized, and over-page-limit uploads return actionable structured errors.
- [ ] Client filenames are stored only as labels and never form storage paths.
- [ ] Traversal, symlink, collision, partial-write, and interrupted-write tests cannot escape or corrupt the configured data root.
- [ ] A failed upload leaves no claim, work item, sealed document metadata, or unreferenced final artifact.

---

## Phase 4: Submission idempotency

**User stories**: 4, 5

### What to build

Make claim submission safe under client and network retries. Bind each member-scoped idempotency key to the canonical request identity and persist the original receipt.

### Acceptance criteria

- [ ] `POST /v1/claims` requires an idempotency key.
- [ ] Repeating the same canonical request with the same member and key returns the original status code and receipt.
- [ ] Reusing a key with different metadata, document manifest, or content hashes returns a conflict.
- [ ] Concurrent identical submissions create exactly one claim, one initial work item, and one set of document references.
- [ ] Idempotency records and claim acceptance commit atomically.
- [ ] A failed or rolled-back acceptance does not permanently reserve a key.
- [ ] Tests cover sequential retries, concurrent retries, conflicting payloads, and member scoping.

---

## Phase 5: Document replacement and action concurrency

**User stories**: 10, 11, 12

### What to build

Introduce the versioned claim-action contract used later for document correction and review. A member can replace a document without mutating the original claim evidence, and every action is concurrency-safe and idempotent.

### Acceptance criteria

- [ ] `POST /v1/claims/{claim_id}/actions` accepts a typed document-replacement command.
- [ ] Every command requires an idempotency key and expected claim version.
- [ ] Replacement creates a new immutable document version and claim version while preserving the original.
- [ ] Identical action retries return the original result without creating duplicate versions or work.
- [ ] A stale expected version is rejected with the current version and no mutation.
- [ ] Only actions allowed for the current lifecycle and principal role are accepted.
- [ ] The claim trace links the action, actor, previous version, new version, and replacement document.

---

## Phase 6: PostgreSQL work scheduling

**User stories**: 53, 54, 55

### What to build

Turn queued claims into durable local work. A worker leases due work using PostgreSQL locking, commits the lease, performs a minimal typed workflow step, and persists its outcome without holding locks across external work.

### Acceptance criteria

- [ ] Work items expose operation key, availability, status, attempt limits, lease owner, and lease expiry.
- [ ] Concurrent workers cannot lease the same operation simultaneously.
- [ ] Leasing uses PostgreSQL locking with skip-locked behavior and commits before processing begins.
- [ ] No provider or workflow execution occurs inside the leasing transaction.
- [ ] Retryable work is rescheduled through a future availability timestamp rather than process sleep.
- [ ] A unique operation key prevents duplicate logical work.
- [ ] Integration tests prove enqueue atomicity, lease exclusivity, due-time ordering, and retry scheduling.

---

## Phase 7: Worker recovery and LangGraph checkpoints

**User stories**: 48, 52, 55

### What to build

Establish the fixed typed LangGraph execution skeleton and make worker crashes recoverable. A claim run resumes from committed state using its workflow-run identifier and never duplicates already committed effects.

### Acceptance criteria

- [ ] Each workflow run has a stable identifier used as the LangGraph thread identifier and references one claim version.
- [ ] Graph state contains references and compact typed summaries, not uploaded bytes or full provider bodies.
- [ ] Checkpoints are durable in PostgreSQL.
- [ ] A worker terminated after a committed checkpoint can be replaced after lease expiry.
- [ ] Resumed execution starts from the last committed checkpoint instead of restarting completed side effects.
- [ ] Repeated workflow operations cannot create duplicate observations, audit events, or terminal decisions.
- [ ] Recovery tests terminate processing at controlled boundaries and prove eventual single completion.

---

## Phase 8: Policy and member data import

**User stories**: 31, 32, 78

### What to build

Create the setup-time import path for immutable policy sources, member records, dependents, claim history, and year-to-date utilization. The importer reports incomplete or contradictory data without inventing missing facts.

### Acceptance criteria

- [ ] Policy source bytes and their cryptographic hash are stored immutably.
- [ ] Member and dependent records are versioned and retain source provenance.
- [ ] Claim history and utilization are loaded into PostgreSQL rather than accepted from claim submissions.
- [ ] Missing dependent references and invalid source relationships produce structured findings.
- [ ] Missing data remains unknown and is never coerced into eligible or ineligible.
- [ ] Re-importing identical source content is idempotent.
- [ ] Imported records can be inspected through the local CLI without adding policy-mutation HTTP routes.

---

## Phase 9: Policy overlay compilation and activation

**User stories**: 33, 34, 35, 36, 37, 38

### What to build

Compile the immutable source policy and explicit assignment overlay into versioned Policy IR. Activation succeeds only when findings meet the configured severity gate, and claims pin the activated versions rather than reading mutable configuration.

### Acceptance criteria

- [ ] The assignment overlay has an independent version and hash and contains no test-case identifiers.
- [ ] Compilation emits schema, semantic, referential, vocabulary, and contradiction findings.
- [ ] Invalid or unresolved-error policy versions cannot activate.
- [ ] The compiled IR explicitly represents category-over-general precedence, ₹5,000 consultation limit, conditional MRI/CT authorization, and mandatory PET authorization.
- [ ] Activation is an auditable local CLI action and does not mutate source policy content.
- [ ] A newly accepted claim pins policy source, overlay, IR, and member snapshot versions.
- [ ] Compiler determinism tests produce the same IR hash for the same canonical inputs.

---

## Phase 10: Structured TC004 golden decision

**User stories**: 43, 44, 45, 46, 47, 75

### What to build

Complete the first adjudication tracer bullet using a privileged structured-component fixture that bypasses OCR. The fixed workflow freezes the supplied evidence, executes deterministic rules, persists the complete decision trace, and exposes an approved ₹1,350 member projection.

### Acceptance criteria

- [ ] The fixture adapter can seed TC004 evidence without placing privileged fields in a production request schema.
- [ ] The workflow evaluates eligibility, evidence sufficiency, applicable limits, and 10% co-pay in the approved rule order.
- [ ] Monetary arithmetic uses integer paise and produces exactly ₹1,350.
- [ ] The model boundary cannot provide a decision, reason code, or approved amount.
- [ ] Every rule result records status, policy path, evidence references, inputs, amount before, adjustment, and amount after.
- [ ] The same casefile and Policy IR produce the same canonical decision hash.
- [ ] Terminal decision, trace, projection, audit events, and work completion commit atomically.
- [ ] The member projection explains the ₹150 deduction without exposing privileged fixture or internal provider data.

---

## Phase 11: TC001 document-role gate

**User stories**: 13, 14, 15, 19

### What to build

Add bounded early document triage before full Textract processing. For TC001, identify that both uploads are prescriptions, determine that the required hospital bill is absent, and move the claim to action required.

### Acceptance criteria

- [ ] Local media inspection completes before model triage.
- [ ] The fast triage route returns a schema-constrained document role, readability result, and bounded identity observations.
- [ ] Unknown roles remain unknown rather than being forced into a supported class.
- [ ] TC001 identifies two observed prescriptions and the missing hospital bill.
- [ ] The member-facing action names both the observed and required document roles.
- [ ] The claim reaches `ACTION_REQUIRED` without page Textract, casefile adjudication, or financial recommendation.
- [ ] The trace proves that the expensive extraction and policy nodes did not execute.

---

## Phase 12: TC002 readability gate

**User stories**: 16, 17

### What to build

Extend early triage with document-specific readability handling. TC002 must request a replacement pharmacy bill and retain the claim as correctable rather than treating image quality as an eligibility decision.

### Acceptance criteria

- [ ] Readability is represented as a typed observation with document and preview provenance.
- [ ] Deterministic unreadable-document transforms produce repeatable fixture inputs.
- [ ] TC002 identifies the pharmacy bill as the affected document.
- [ ] The member action asks for replacement of that specific document.
- [ ] The lifecycle becomes `ACTION_REQUIRED` with no `REJECTED` adjudication.
- [ ] Full extraction and policy evaluation do not run for the unreadable input.
- [ ] Supplying a readable replacement creates a new claim version and makes the claim eligible to resume.

---

## Phase 13: TC003 patient-identity conflict

**User stories**: 18, 24, 25, 26

### What to build

Reconcile visible patient-name observations across documents and the pinned member snapshot. TC003 preserves the contradictory names and their sources, then asks for correction instead of selecting one silently.

### Acceptance criteria

- [ ] Identity observations retain producer, document version, page/region, source text hash, and confidence.
- [ ] Reconciliation represents patient identity as known, unknown, or conflict.
- [ ] TC003 retains both conflicting patient names and associates each with its source document.
- [ ] Neither confidence nor source order silently overwrites the conflict.
- [ ] The member-facing action describes the mismatch without exposing unrelated internal evidence.
- [ ] The claim reaches `ACTION_REQUIRED` or explicit identity review without adjudication.
- [ ] Corrective replacement creates a new case attempt while preserving the original conflict trace.

---

## Phase 14: Textract page-processing pipeline

**User stories**: 22, 23, 27

### What to build

Implement complete page-oriented OCR for locally stored documents. Render bounded pages, choose the appropriate synchronous Textract analysis per document profile, and merge provider output deterministically with full provenance.

### Acceptance criteria

- [ ] Every supported PDF page is rendered locally in stable order and remains linked to its immutable original.
- [ ] No rendered page exceeds the configured 5 MiB provider limit; unsafe pages request a clearer or smaller document rather than being dropped.
- [ ] Bills and receipts use expense analysis where appropriate; forms, tables, reports, and free text use the configured profile behavior.
- [ ] Direct Textract calls receive page bytes and require no S3 resource.
- [ ] Provider responses are mapped into project-owned typed observations with page and geometry provenance.
- [ ] Page-level results are idempotent and merge in deterministic order.
- [ ] Botocore-stubbed tests cover successful analysis, malformed responses, throttling, timeouts, and provider errors.
- [ ] Selected synthetic pages pass an explicitly invoked live Textract smoke test.

---

## Phase 15: Bedrock structured extraction

**User stories**: 23, 28, 47, 68

### What to build

Add schema-constrained semantic extraction over bounded document observations. The model normalizes clinical and billing concepts into evidence candidates while the application validates grounding and blocks any attempt to cross the financial authority boundary.

### Acceptance criteria

- [ ] Fast-triage and complex-extraction routes are configured independently behind the same project-owned model boundary.
- [ ] Both routes initially resolve to an explicit enabled and evaluation-approved Claude Sonnet model identifier.
- [ ] Structured outputs are validated against versioned Pydantic/JSON schemas.
- [ ] Outputs containing decisions, payable amounts, policy outcomes, or undeclared fields are rejected.
- [ ] Every accepted candidate references supporting document/page observations rather than unsupported model text.
- [ ] Schema, semantic, grounding, and authority-validation failures have distinct typed outcomes.
- [ ] Recorded sanitized responses exercise the default no-network integration path.
- [ ] An explicit synthetic live test records current schema adherence, latency, token usage, and provider request metadata.

---

## Phase 16: Evidence reconciliation and frozen casefiles

**User stories**: 24, 25, 26, 27, 28, 29, 30

### What to build

Combine roster, history, Textract, and Bedrock candidates into a canonical evidence graph. Preserve ambiguity, evaluate evidence sufficiency, and freeze exactly the casefile used by policy adjudication.

### Acceptance criteria

- [ ] Candidates retain producer, producer version, document version, page, geometry, schema version, confidence, and source hash.
- [ ] Candidates are grouped by canonical fact path without discarding their original representation.
- [ ] Reconciled facts explicitly distinguish known, unknown, and conflict.
- [ ] Bill totals, line items, claimed amounts, treatment dates, patient identity, and clinical concepts have deterministic reconciliation rules.
- [ ] Evidence sufficiency identifies every unresolved material fact and its required corrective action.
- [ ] Policy evaluation cannot begin until an immutable casefile version is frozen.
- [ ] The frozen casefile has a canonical content hash and pins all contributing evidence and member snapshots.
- [ ] Reconciliation property tests prove stable output under candidate reordering.

---

## Phase 17: Rendered TC004 end-to-end approval

**User stories**: 22, 23, 24, 27, 28, 29, 30, 44, 45, 46, 76

### What to build

Replace structured TC004 evidence with generated claim documents submitted through the real multipart API. Run document storage, triage, rendering, recorded OCR/extraction, reconciliation, policy evaluation, and projection as one repeatable end-to-end path.

### Acceptance criteria

- [ ] The rendered fixture enters only through `POST /v1/claims`.
- [ ] Production request DTOs never receive the case identifier, actual type, extracted text, expected decision, or expected amount.
- [ ] The worker completes every required workflow stage and persists its checkpoints.
- [ ] The casefile contains document- and page-linked evidence for all material adjudication facts.
- [ ] The final recommendation is `APPROVED` for exactly ₹1,350 with the 10% co-pay explanation.
- [ ] The rendered run and structured-component run produce equivalent material facts and decision traces.
- [ ] The case remains reproducible in the default recorded profile with no AWS calls.
- [ ] A separately tagged live-intelligence run exercises real Textract and Bedrock without changing expected policy behavior.

---

## Phase 18: TC005 waiting-period rules

**User stories**: 31, 32, 33, 34, 44, 45

### What to build

Add deterministic waiting-period evaluation using policy dates, member enrollment, condition evidence, and treatment dates. TC005 must reject with a precise eligibility date and a fully linked rule explanation.

### Acceptance criteria

- [ ] Waiting-period rules are compiled into Policy IR rather than embedded in workflow routing.
- [ ] Required member, condition, enrollment, and treatment-date facts come from the pinned snapshot and frozen casefile.
- [ ] Missing or conflicting material dates route to action or review instead of producing a guessed result.
- [ ] TC005 produces `REJECTED` with the `WAITING_PERIOD` reason.
- [ ] The explanation states the exact date from which diabetes-related claims become eligible.
- [ ] The rule trace links the policy path and each supporting date fact.
- [ ] Date-boundary property tests cover the day before, day of, and day after eligibility.

---

## Phase 19: TC006 dental evidence and partial approval

**User stories**: 20, 21, 35, 36, 41, 42, 44

### What to build

Add evidence-equivalence and line-item adjudication for dental claims. A sufficiently detailed bill can replace a separate dental report, while covered and excluded procedures receive independent results.

### Acceptance criteria

- [ ] Dental evidence sufficiency is based on procedure-level facts rather than unconditional presence of a dental-report role.
- [ ] A generic dental bill without procedure detail requests a dental report.
- [ ] A detailed bill containing adequate procedure evidence proceeds without a redundant document request.
- [ ] Root-canal and whitening items remain separate through extraction, reconciliation, and policy evaluation.
- [ ] TC006 produces `PARTIAL` with exactly ₹8,000 approved for root canal and ₹0 for whitening.
- [ ] Whitening carries its line-item exclusion reason and policy reference.
- [ ] The category-specific dental limit takes precedence over the general per-claim limit.
- [ ] The member projection itemizes approved and rejected charges and explains each adjustment.

---

## Phase 20: TC012 excluded-condition rejection

**User stories**: 28, 41, 44

### What to build

Apply supported condition and treatment exclusions to a fully evidenced claim. TC012 proves that clinical normalization can identify the applicable obesity/bariatric exclusion without allowing an unsupported model assertion to reject a claim.

### Acceptance criteria

- [ ] The normalized treatment concept retains links to source clinical evidence.
- [ ] An exclusion cannot fire from an ungrounded model label alone.
- [ ] TC012 produces `REJECTED` with `EXCLUDED_CONDITION`.
- [ ] The decision identifies the applicable policy exclusion and supporting evidence.
- [ ] Missing or conflicting clinical evidence routes to correction or review rather than rejection.
- [ ] The rendered evaluation records confidence above the assignment threshold while preserving the deterministic reason trace.
- [ ] Neighboring covered-treatment tests protect against over-broad exclusion matching.

---

## Phase 21: TC007 pre-authorization handling

**User stories**: 37, 38, 39, 40, 44

### What to build

Introduce verified pre-authorization evidence and conditional diagnostic rules. Missing authorization is different from supplied-but-unreadable or conflicting authorization, and all outcomes are derived from documents rather than member booleans.

### Acceptance criteria

- [ ] Pre-authorization evidence captures patient, treatment, validity period, reference, and applicable amount when present.
- [ ] MRI and CT require authorization only when the eligible amount exceeds ₹10,000.
- [ ] PET requires authorization regardless of the generic policy flag.
- [ ] Specific authorization rules override the contradictory generic false flag through Policy IR.
- [ ] TC007 produces `REJECTED` with `PRE_AUTH_MISSING`.
- [ ] The explanation states why authorization was required and how the member may resubmit.
- [ ] A supplied unreadable authorization routes to document correction rather than missing-authorization rejection.
- [ ] Conflicting authorization facts route to review and preserve every candidate.

---

## Phase 22: TC008 category-limit rejection

**User stories**: 35, 36, 44, 45, 46

### What to build

Implement explicit reject semantics for category limits. TC008 must compare the eligible consultation amount with the applicable limit and reject rather than silently cap the claim.

### Acceptance criteria

- [ ] Policy IR distinguishes reject, cap, and review limit semantics.
- [ ] Category-specific limits override the general per-claim limit.
- [ ] Excluded amounts are removed before the applicable limit comparison.
- [ ] TC008 compares ₹7,500 eligible consultation expense with the ₹5,000 consultation limit.
- [ ] The result is `REJECTED` with `PER_CLAIM_EXCEEDED`.
- [ ] The member explanation states both the claimed/eligible amount and applicable limit.
- [ ] Boundary tests cover amounts below, equal to, and above the limit.
- [ ] Decreasing a limit cannot increase an approved amount.

---

## Phase 23: TC010 calculation ordering

**User stories**: 43, 44, 45, 46

### What to build

Make financial transformations an ordered, inspectable pipeline. TC010 proves that the network discount is applied before co-pay and that every intermediate amount is persisted.

### Acceptance criteria

- [ ] The deterministic rule order places exclusions before limits, network discount before co-pay, and final recommendation last.
- [ ] TC010 applies a 20% network discount to ₹4,500, yielding ₹3,600.
- [ ] A 10% co-pay then deducts ₹360 and yields exactly ₹3,240.
- [ ] Every amount step records the before value, operation, adjustment, after value, policy path, and evidence references.
- [ ] Reversing discount and co-pay is detected by a trace-order regression test even if selected arithmetic happens to commute.
- [ ] Increasing co-pay cannot increase the approved amount.
- [ ] Approved amount always remains between zero and the eligible claimed amount.
- [ ] The member projection renders the complete discount and co-pay breakdown.

---

## Phase 24: TC009 anomaly signals and review workflow

**User stories**: 60, 61, 62, 63, 64, 65, 78

### What to build

Evaluate deterministic history-based anomaly signals and introduce durable human review. TC009 creates a review task for the unusual same-day claim pattern without turning the anomaly into an automatic financial rejection.

### Acceptance criteria

- [ ] Same-day history is read from the pinned PostgreSQL member snapshot, never supplied by the claim request.
- [ ] TC009 records each triggering velocity signal and routes the claim to `IN_REVIEW`.
- [ ] The assignment-compatible projection reports manual review without storing it as an adjudication outcome.
- [ ] `GET /v1/review-tasks` returns only tasks visible to an authorized reviewer.
- [ ] Reviewer detail includes evidence, conflicts, rules, calculations, failures, and allowed actions.
- [ ] Reviewer commands require an expected claim version and idempotency key.
- [ ] Accept, amend, reject, and request-document actions require structured reasons and respect task-specific allowed transitions.
- [ ] Human resolution preserves the original machine recommendation and records immutable before/after values and actor identity.
- [ ] Concurrent or repeated reviewer commands cannot produce conflicting resolutions.
- [ ] Member projections exclude internal provider, risk, and reviewer-only evidence details.

---

## Phase 25: Failure policy and TC011 degradation

**User stories**: 48, 49, 50, 51, 56, 80

### What to build

Classify component failures by retryability and decision criticality. Prove that critical failures block unsafe completion while the named evaluation-only anomaly-enrichment failure can degrade handling without erasing a valid deterministic recommendation.

### Acceptance criteria

- [ ] Provider timeouts start at 30 seconds per Textract page and 90 seconds per Bedrock request and are configurable.
- [ ] Textract and Bedrock start with concurrency limits of two and at most three provider attempts.
- [ ] Retryable failures use persisted exponential backoff with jitter.
- [ ] Deterministic invalid inputs, policy contradictions, and schema/semantic failures are not retried indefinitely.
- [ ] Critical OCR, identity, policy, and audit failures cannot produce automatic approval.
- [ ] Evaluation-only fault injection is inaccessible to production request schemas and application modules.
- [ ] TC011 injects only the named non-critical `ANOMALY_ENRICHMENT` failure.
- [ ] TC011 reaches `DECIDED` with an `APPROVED` ₹4,000 recommendation and `MANUAL_REVIEW_RECOMMENDED` handling.
- [ ] The degraded component, attempts, failure code, reduced completeness/confidence, and effect on handling are visible.
- [ ] The API does not return a 500 for the expected degradation.
- [ ] Audit persistence failure rolls back terminal completion, while engineering-log failure does not alter a valid domain transaction.

---

## Phase 26: Observability and complete evaluation gate

**User stories**: 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85

### What to build

Finish the diagnostic and quality system around the complete backend. Every workflow run is inspectable in local Phoenix, correlated with privacy-safe engineering logs, reconstructable from PostgreSQL, and evaluated across structured, rendered-recorded, and explicitly live profiles.

### Acceptance criteria

- [ ] Every claim workflow produces one correlated Phoenix trace tree with node entry, exit, duration, outcome, and error spans.
- [ ] Bedrock spans include route, exact model, prompt/schema versions, token usage, latency, provider request ID, and sanitized errors.
- [ ] Textract, reconciliation, policy evaluation, persistence, and review operations appear as custom spans in the same trace.
- [ ] API, worker, and evaluation processes write separate rotating JSONL logs carrying claim, workflow, trace, span, attempt, duration, and outcome identifiers.
- [ ] Default Phoenix attributes and logs contain no patient names, diagnoses, OCR text, document bytes, local paths, raw prompts/responses, or credentials.
- [ ] PHI canary tests fail when forbidden fields or values enter trace/log attributes.
- [ ] Rich prompt and response capture can be enabled only in an explicit synthetic-only evaluation profile.
- [ ] PostgreSQL retains the ordered workflow events, evidence references, frozen casefile, rule tree, amount steps, decision, failures, and human actions.
- [ ] Removing Phoenix data and JSONL logs does not prevent exact reconstruction of why a claim received its recommendation and handling.
- [ ] Unit and recorded profiles make no network calls and cannot incur AWS cost.
- [ ] Structured-component evaluation bypasses OCR and is labeled accordingly.
- [ ] Rendered E2E generates documents, applies deterministic quality transforms, seeds history/utilization, and enters through the production multipart API.
- [ ] Live-intelligence evaluation requires an explicit selector and calls real Textract and Bedrock only with synthetic inputs.
- [ ] Oracle fields and expected outcomes remain inaccessible until after the system result is finalized.
- [ ] The evaluation report records dataset, policy, overlay, model, prompt, schema, and execution-profile versions.
- [ ] TC001–TC012 each include expected and actual lifecycle, adjudication, amount, reasons, provenance, trace completeness, assumptions, and failures.
- [ ] All twelve cases satisfy their PRD acceptance outcomes in the recorded rendered suite.
- [ ] Selected synthetic cases satisfy the live-intelligence smoke gate without changing deterministic policy results.

---

## Completion definition

The backend implementation is complete when all 26 phase acceptance sections pass and:

- [ ] All twelve supplied cases enter through the same production multipart API.
- [ ] No production schema, workflow, policy evaluator, or provider adapter can read evaluation-oracle fields.
- [ ] All expected decisions, action-required states, reason codes, and exact approved amounts match.
- [ ] Every material fact has evidence provenance or an explicit unknown/conflict state.
- [ ] Every financial outcome has a deterministic policy and amount trace.
- [ ] Worker restarts, duplicate requests, stale actions, and provider retries cannot create duplicate terminal effects.
- [ ] Recorded tests run without AWS access; live-intelligence tests require explicit invocation.
- [ ] Phoenix explains agent execution, while PostgreSQL independently reconstructs the complete business decision.
- [ ] No frontend, hosted deployment, production authentication, or excluded infrastructure has been introduced.
