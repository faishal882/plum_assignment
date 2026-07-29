# Deep Durable Claim-Processing Orchestration Refactor PRD

## Problem Statement

The backend has a durable claims workflow with PostgreSQL work leasing, LangGraph checkpoints,
execution-contract pinning, retries, terminal lease fencing, durable events and effects, and
provider-specific document intelligence. Its external behavior is reliable, but its internal
orchestration boundary is shallow and expensive to change.

The worker-facing claim processor exposes individual workflow phases such as routing, media
inspection, rendering, OCR, triage, extraction, reconciliation, adjudication, and terminal
commit. LangGraph mirrors those phases as nodes, the PostgreSQL implementation owns the same
phase vocabulary, runtime composition assembles every collaborator, and tests frequently rebuild
the complete graph and processor stack. A change to one processing phase can therefore require
synchronized changes across several layers even when the worker only needs to advance one leased
claim.

From a developer's perspective, understanding durable claim execution requires navigating many
modules and learning LangGraph, persistence, provider, retry, and lease-fencing details before
making a safe change. From a test author's perspective, the easiest tests target internal phases,
while the highest-risk defects occur in their ordering, recovery, idempotency, and terminal
transactions. From an operator's or claimant's perspective, a structural refactor must not change
claim outcomes, public APIs, recovery behavior, or decision auditability.

## Solution

Introduce one deep durable claim-processing module with a small worker-facing boundary:
initialization of durable processing resources and processing of one active work lease. The
module will own workflow-run discovery and creation, execution-contract resolution, first-run
versus resume behavior, LangGraph construction, checkpoint access, phase sequencing, durable
events and effects, retry classification, observability, and translation into the existing work
outcomes.

The worker will remain responsible for polling, heartbeat and shutdown behavior, but it will no
longer construct LangGraph runtimes, select historical execution profiles, cache workflows, or
call individual claim-processing phases. Document intelligence, casefile preparation, and
terminal persistence will remain cohesive internal capabilities behind the deep boundary.

The internal implementation will be organized around workflow, processing operations, and
persistence. Existing document, model, policy, AWS, local-storage, and domain modules remain
independent dependencies. PostgreSQL and the local filesystem remain local-substitutable
dependencies for tests. Textract and Bedrock remain true external dependencies behind the
existing project-owned ports and recorded adapters.

The migration will be incremental. The new boundary will first wrap the existing implementation,
then absorb runtime resolution and graph orchestration, and finally replace the shallow phase
protocol. Existing workflow identities and checkpoint contracts will remain compatible during
pure code movement. A workflow version will change only when topology or checkpointed state
semantics change.

## User Stories

1. As a claims member, I want this refactor to preserve my claim's lifecycle and outcome, so that internal restructuring does not change how my claim is handled.
2. As a claims member, I want interrupted claim processing to resume from durable progress, so that completed work is not unnecessarily repeated.
3. As a claims member, I want terminal decisions to remain atomic, so that I never observe a decision without its corresponding trace and completed work state.
4. As a claims member, I want action-required outcomes to remain atomic, so that corrective instructions cannot be separated from the claim state that requires them.
5. As a claims member, I want duplicate or resumed execution to remain idempotent, so that retries do not create duplicate decisions, actions, or audit events.
6. As a reviewer, I want review-producing decisions to retain their evidence and rule traces, so that the refactor does not reduce explainability.
7. As an operator, I want a worker to process a leased claim through one stable entry point, so that operational behavior is independent of workflow implementation details.
8. As an operator, I want a reclaimed work item to use its current lease, so that a stale worker cannot commit a terminal business effect.
9. As an operator, I want retryable failures to preserve workflow progress, so that transient provider failures do not restart the claim unnecessarily.
10. As an operator, I want deterministic failures to reach an explicit durable failure state, so that invalid work does not retry indefinitely.
11. As an operator, I want unsupported historical execution contracts to fail closed before processing, so that old work is never resumed with incompatible providers.
12. As an operator, I want workflow events and effects to retain their existing meaning, so that current reconstruction and debugging procedures continue to work.
13. As an operator, I want workflow and node telemetry to remain correlated, so that I can trace a work attempt across retries and terminal outcomes.
14. As an operator, I want raw lease tokens and private claim content to remain excluded from normal telemetry, so that the refactor preserves privacy boundaries.
15. As a backend developer, I want a two-operation durable-processing boundary, so that callers cannot depend on individual workflow phases.
16. As a backend developer, I want LangGraph types to remain internal, so that application callers and domain contracts do not depend on the workflow framework.
17. As a backend developer, I want PostgreSQL workflow details hidden behind the processing module, so that orchestration changes do not spread through the worker.
18. As a backend developer, I want execution-contract resolution owned by durable processing, so that new and resumed runs follow one compatibility policy.
19. As a backend developer, I want graph nodes and conditional routing to be private implementation details, so that topology can evolve without changing the worker contract.
20. As a backend developer, I want document processing operations grouped cohesively, so that rendering, OCR, triage, and extraction behavior is easier to navigate.
21. As a backend developer, I want casefile operations grouped cohesively, so that reconciliation, freezing, and evaluation share one internal ownership boundary.
22. As a backend developer, I want terminal operations grouped around the lease-fenced transaction, so that decision and member-action commits preserve the same safety rules.
23. As a backend developer, I want processing trace reads separated from processing commands, so that read-side diagnostics do not enlarge the command interface.
24. As a backend developer, I want one composition root for durable processing, so that production and recorded profiles cannot be assembled inconsistently by callers.
25. As a backend developer, I want existing provider ports reused, so that the refactor does not introduce a second OCR or model abstraction.
26. As a backend developer, I want existing domain value objects reused, so that structural movement does not create duplicate claim, workflow, lease, or outcome types.
27. As a backend developer, I want internal operations to remain concrete unless substitution is required, so that the refactor does not replace one shallow interface with many new ones.
28. As a backend developer, I want import boundaries enforced, so that worker and API code cannot reach private graph nodes or processing phases.
29. As a maintainer, I want the migration to preserve the current graph identity while behavior is unchanged, so that in-flight workflows remain resumable.
30. As a maintainer, I want graph-version changes tied to persisted-state or topology changes, so that versioning communicates real compatibility boundaries.
31. As a maintainer, I want the old orchestration modules removed after parity, so that there is only one supported path through durable processing.
32. As a maintainer, I want documentation to describe the new ownership boundary, so that future contributors know where workflow responsibilities belong.
33. As a test author, I want to exercise claim processing through the same boundary used by the worker, so that tests cover real sequencing and recovery behavior.
34. As a test author, I want deterministic recorded OCR and model adapters, so that processing-boundary tests run without network access or AWS cost.
35. As a test author, I want real PostgreSQL checkpoint and transaction behavior in integration tests, so that recovery and fencing tests match production semantics.
36. As a test author, I want controlled crash hooks at durable workflow boundaries, so that recovery can be tested without exposing phase methods as public APIs.
37. As a test author, I want direct phase-mocking tests replaced after boundary parity, so that tests survive internal reorganization.
38. As a test author, I want focused adapter tests to remain separate, so that Textract, Bedrock, storage, and PostgreSQL contracts can fail independently of orchestration.
39. As an evaluator, I want recorded acceptance cases to produce identical durable outcomes before and after the refactor, so that structural improvement does not alter correctness.
40. As an evaluator, I want claim reconstruction to remain complete, so that every decision, action, effect, event, failure, and evidence reference remains auditable.

## Implementation Decisions

- Introduce a durable claim-processing module as a feature-centered deep module rather than adding another layer-wide collection of forwarding classes.
- Expose only initialization and processing of one active work lease as the worker-facing command boundary.
- Return the existing typed work outcomes for completed, atomically committed, lease-lost, retry, and failed execution.
- Keep worker polling, heartbeat renewal, idle waiting, shutdown, and process-resource disposal outside the durable-processing command boundary.
- Move workflow-run discovery, creation, status transitions, retry translation, and completion mapping behind the durable-processing boundary.
- Resolve new and resumed runtimes from the persisted execution contract. Current process settings may select a new run but must not silently replace the contract of an existing run.
- Keep LangGraph as the workflow runtime implementation while preventing its graph, checkpoint, runtime, and state types from entering public application or domain contracts.
- Preserve durable graph node names, graph identity, effect keys, event meanings, and checkpointed state during behavior-preserving migration.
- Change the workflow version only when graph topology or checkpoint-state semantics become incompatible.
- Keep the active work lease in non-checkpointed invocation context and pass it directly to terminal operations.
- Preserve database lease fencing as the final authority for terminal writes. The current owner, token, status, and expiry must be validated within the terminal transaction.
- Preserve atomic terminal transactions for the business outcome, claim projection, workflow effect, workflow completion, audit state, and work completion.
- Continue performing provider calls outside database transactions.
- Organize private workflow internals around engine invocation, topology, checkpoint-safe state, and telemetry.
- Organize private processing operations into document processing, casefile preparation, and terminal persistence based on their authority and transaction boundaries.
- Keep individual graph phases private. Do not recreate the existing phase-level processor as a public or broadly shared protocol.
- Separate command processing from processing-trace reads so diagnostic queries cannot expand the command surface.
- Introduce one durable-processing composition root that selects recorded or live provider adapters, repositories, storage, observability, and compatible workflow runtime.
- Reuse the existing OCR, structured-model, page-artifact, document-store, policy, observability, and work-scheduler boundaries.
- Treat PostgreSQL workflow state, checkpoints, and local document storage as local-substitutable dependencies in tests.
- Treat Textract and Bedrock as true external dependencies and use recorded or controlled fake implementations in deterministic processing tests.
- Avoid introducing a workflow-plugin or generic step framework in this refactor. Extension points will be added only when a concrete second workflow demonstrates the need.
- Avoid introducing new persistence tables or public API schemas solely for module relocation.
- Enforce import boundaries so worker code depends only on durable processing, scheduler behavior, runtime resources, and typed work outcomes.
- Use an incremental strangler migration: add the new facade, migrate runtime resolution, move graph orchestration, move private operations, switch callers, prove parity, then delete the old path.
- Retain compatibility adapters only for the duration of migration and delete them when all production and test callers use the new boundary.
- Document module ownership, dependency direction, workflow compatibility rules, and the criteria for future graph-version changes.

## Testing Decisions

- Good tests will assert observable outcomes through the durable-processing boundary rather than call or mock private graph phases.
- Boundary tests will assert both the returned work outcome and authoritative persisted state.
- PostgreSQL integration tests will use the existing migrated test database because SQLite or pure repository mocks cannot prove checkpoint, locking, idempotency, and fencing behavior.
- Deterministic processing tests will use the existing recorded OCR and structured-model adapters and a temporary local document root.
- Add a fresh-run boundary test for each terminal route: completed workflow, committed decision, committed member action, retry, permanent failure, and lease loss.
- Add recovery tests that interrupt execution after durable effects and verify resume without duplicated effects, events, observations, decisions, actions, or audit records.
- Add a decision-path fencing test proving that a stale lease cannot commit after work is reclaimed.
- Add a member-action fencing test proving that a stale lease cannot commit after work is reclaimed.
- Add an execution-contract test proving that an incomplete historical run resumes with the compatible persisted contract even when current defaults change.
- Add a fail-closed test for unknown workflow versions and unsupported execution contracts.
- Add tests proving that provider calls do not execute inside the terminal database transaction.
- Add tests proving that workflow events, effects, graph identity, and reconstruction output remain compatible during the behavior-preserving move.
- Add observability tests for root and node spans, work-attempt correlation, lease-validation outcome, terminal-commit outcome, and absence of raw lease tokens.
- Add composition tests proving that recorded profiles do not construct AWS clients and live profiles use only authorized adapters.
- Preserve focused tests for the PostgreSQL work scheduler, Textract adapter, Bedrock adapter, document storage, page rendering, OCR persistence, structured extraction, policy adjudication, and reconstruction.
- Preserve rendered evaluation and contract suites as end-to-end regression gates; do not duplicate their assertions in new lower-level tests.
- Replace direct orchestration tests that instantiate the old workflow processor, LangGraph runtime, or phase-level PostgreSQL processor once equivalent boundary coverage exists.
- Replace runtime-resolution unit tests with execution-contract boundary tests through durable processing.
- Allow private crash hooks only as test instrumentation for recovery boundaries; they must not become production commands or public extension APIs.
- Verify the refactor with formatting, lint, strict type checking, migration checks, focused processing tests, the full deterministic suite, and existing rendered acceptance cases.

## Out of Scope

- Changing member, reviewer, operator, or frontend API contracts.
- Combining claim submission, reads, or document-replacement commands into this worker-facing module.
- Changing claim lifecycle, adjudication recommendations, review behavior, policy rules, financial calculations, or member explanations.
- Changing OCR prompts, model routes, evidence schemas, reconciliation behavior, or execution-profile semantics.
- Replacing LangGraph with another workflow framework.
- Introducing a generic workflow-plugin framework or supporting arbitrary user-defined workflows.
- Introducing SQS, Kafka, Redis, distributed deployment, or additional cloud infrastructure.
- Moving all existing backend packages to a feature-first architecture.
- Rewriting unrelated PostgreSQL repositories, API routes, policy modules, or model adapters.
- Changing database schemas solely to match the proposed module organization.
- Deleting or rewriting historical checkpoint rows.
- Removing compatibility with incomplete workflows created before the refactor.
- Expanding telemetry to include raw lease tokens, documents, OCR content, prompts, model responses, or other private claim data.
- Optimizing processing performance unless a regression is introduced by the refactor.

## Further Notes

- This is an internal architecture refactor, but its acceptance boundary is behavioral: public APIs and durable claim outcomes must remain unchanged.
- The desired result is a deep module, not simply a different folder layout. Success means that the worker and most tests no longer know the workflow phases or LangGraph implementation.
- The current architecture documentation already calls for a modular monolith with deep modules. This PRD narrows that direction to the durable worker-orchestration boundary and does not attempt the larger business-facade consolidation.
- The migration should begin with a facade around the current implementation. Large file moves or operation splits should happen only after boundary tests protect compatibility.
- Completion requires all old orchestration callers to migrate and the superseded public phase protocol and compatibility path to be deleted.
- No graph-version bump is expected for pure module movement. If state keys, node names, edges, or checkpoint semantics change, that change requires an explicit compatibility decision and separate rollout evidence.
