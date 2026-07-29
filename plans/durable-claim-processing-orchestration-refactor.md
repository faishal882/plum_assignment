# Plan: Deep Durable Claim-Processing Orchestration Refactor

> Source PRD:
> [Deep Durable Claim-Processing Orchestration Refactor PRD](../prds/durable-claim-processing-orchestration-refactor-prd.md)
> ([GitHub issue #1](https://github.com/faishal882/plum_assignment/issues/1))

## Architectural decisions

Durable decisions that apply across all phases:

- **Public APIs**: Member, reviewer, operator, and frontend HTTP contracts do not change.
- **Processing boundary**: Durable claim processing exposes only initialization and processing of
  one active work lease to its worker caller.
- **Worker ownership**: Polling, heartbeat renewal, idle waiting, shutdown, and process-resource
  disposal remain worker responsibilities.
- **Workflow ownership**: Workflow-run discovery, creation, execution-contract resolution,
  first-run versus resume behavior, graph invocation, checkpoint access, retry translation, and
  work-outcome mapping belong to the deep processing module.
- **Workflow runtime**: LangGraph remains the implementation, but LangGraph and checkpoint types
  do not enter public application or domain contracts.
- **Compatibility**: Behavior-preserving movement retains the current graph identity, node names,
  effect keys, event meanings, and checkpointed state. A graph version changes only for an
  incompatible topology or persisted-state change.
- **Execution contracts**: New work may use current defaults. Existing work always resolves from
  its persisted execution contract and fails closed if that contract is unsupported.
- **Runtime authority**: The active work lease remains non-checkpointed invocation context.
  Historical checkpoint data cannot override the current scheduler lease.
- **Terminal authority**: PostgreSQL validates work status, owner, fencing token, and expiry in
  the same transaction as a terminal decision or member action.
- **Atomicity**: Terminal business state, claim projection, workflow effect, workflow completion,
  audit state, and work completion commit together.
- **Provider calls**: OCR and model calls never run inside authoritative database transactions.
- **Dependencies**: PostgreSQL checkpoints, repositories, and local document storage are
  local-substitutable. Textract and Bedrock are true external dependencies behind existing
  project-owned ports and recorded adapters.
- **Internal organization**: Private implementation is grouped around workflow execution,
  document operations, casefile operations, terminal operations, and persistence. Individual
  graph phases do not become public extension points.
- **Trace reads**: Processing-trace reconstruction is a separate read-side capability and does
  not enlarge the processing command surface.
- **Composition**: One processing composition root selects compatible repositories, storage,
  providers, workflow runtime, and observability.
- **Migration**: Use an incremental strangler approach. Establish boundary parity before moving
  internals, migrate callers before deleting compatibility paths, and maintain one executable
  processing path at the end.
- **Testing**: New tests assert returned work outcomes and authoritative persisted state through
  the worker-used boundary. Old orchestration tests are replaced, not retained as a second layer,
  after equivalent boundary coverage exists.
- **Privacy**: Raw lease tokens, documents, OCR text, prompts, model responses, and private claim
  content remain absent from normal logs and public projections.
- **Excluded changes**: This plan does not change policy behavior, evidence schemas, provider
  routes, claim lifecycle semantics, public APIs, or deployment infrastructure.

---

## Phase 1: Stable Processing Facade

**User stories**: 7, 15–19, 24–28, 33–34

### What to build

Introduce the deep processing boundary around the current durable workflow and switch the worker
to invoke it for a complete recorded happy path. The first slice deliberately delegates to the
existing orchestration internally; its purpose is to establish the final caller contract,
composition ownership, and boundary-test harness before code movement begins.

The worker must be able to initialize processing resources, lease one item, process it through the
new boundary, and observe the same typed work outcome and database state as before. Recorded
providers and the local PostgreSQL environment provide the deterministic proof path.

### Acceptance criteria

- [ ] The worker depends on one durable-processing boundary rather than individual graph or
      processing-phase collaborators.
- [ ] The boundary supports initialization and processing of one active work lease.
- [ ] Processing returns the existing typed outcomes without introducing duplicate workflow or
      work-outcome models.
- [ ] The initial implementation delegates to the existing durable workflow without changing
      graph identity, node names, checkpoint state, effects, events, or terminal behavior.
- [ ] One recorded claim executes end-to-end through the new boundary and reaches its expected
      durable terminal state.
- [ ] The boundary test asserts the returned work outcome, work-item state, workflow-run state,
      claim projection, effects, and events.
- [ ] The recorded path does not construct AWS clients or make network calls.
- [ ] The worker no longer performs direct LangGraph construction for the migrated path.
- [ ] Existing public claim and review contract tests remain unchanged and passing.
- [ ] Strict type checking proves that worker-facing contracts contain no LangGraph,
      checkpoint-provider, or AWS types.

---

## Phase 2: Persisted-Contract Recovery

**User stories**: 2, 5, 11, 18, 29–30, 35–36

### What to build

Move new-run and resumed-run runtime resolution behind the processing boundary. Demonstrate the
complete recovery path by interrupting a recorded workflow after durable progress, changing the
current process default, reclaiming the work, and resuming it with the execution contract pinned
to the existing workflow run.

This slice makes compatibility policy a responsibility of durable processing rather than the
worker. Existing checkpoints and graph identity remain valid, and an unsupported historical
contract fails before executing another graph node.

### Acceptance criteria

- [ ] New workflows pin the execution contract selected by the authorized current profile.
- [ ] Resumed workflows resolve their runtime exclusively from the persisted execution contract.
- [ ] Changing the current default profile does not change the runtime selected for an incomplete
      historical workflow.
- [ ] Compatible runtimes may be reused by contract without exposing runtime caching to the
      worker.
- [ ] An unsupported profile, provider version, model route, prompt version, schema version, or
      evidence-policy version fails closed before node execution.
- [ ] A controlled interruption after a durable effect resumes from the existing checkpoint.
- [ ] Resume does not duplicate the previously committed effect, event, observation, action,
      decision, or audit record.
- [ ] The resumed invocation uses the current reclaimed lease rather than historical checkpoint
      ownership data.
- [ ] Existing graph identity, state keys, node names, and conditional routing remain unchanged.
- [ ] Compatibility tests cover both a legacy incomplete checkpoint and a newly created run.
- [ ] Runtime-resolution unit tests are replaced by boundary tests through durable processing
      once parity is established.

---

## Phase 3: Action-Required Terminal Path

**User stories**: 4, 8, 20, 22, 33–35, 39–40

### What to build

Move the complete action-required tracer behind the deep module: document inspection and
preparation, bounded triage, durable workflow effects, and an atomically committed member action.
Use a recorded claim that deterministically reaches action required so the slice proves the real
document-processing path without live AWS dependencies.

The active runtime lease must cross the private workflow and operation boundaries without entering
checkpointed state. A stale or reclaimed worker must be unable to commit the member action.

### Acceptance criteria

- [ ] The action-required claim enters through the same processing boundary used by the worker.
- [ ] Document inspection, rendering or discovery as applicable, triage, routing, and member
      action creation remain private processing operations.
- [ ] Provider work occurs outside authoritative database transactions.
- [ ] The member action, claim projection, terminal workflow effect, workflow completion, audit
      state, and work completion commit atomically.
- [ ] The terminal transaction validates the active work status, owner, fencing token, and lease
      expiry.
- [ ] A stale lease produces the typed lease-lost outcome and creates no terminal business effect.
- [ ] Repeating or resuming the same logical operation creates no duplicate action, effect, event,
      or audit record.
- [ ] The member-facing action contents and claim lifecycle are identical to the pre-refactor
      recorded result.
- [ ] Reconstruction retains the action, affected documents, workflow events, effects, and actor
      or system provenance required before the refactor.
- [ ] Tests assert the terminal outcome only through the processing boundary and authoritative
      persisted state.
- [ ] Existing focused document-rendering, OCR, triage, and provider-adapter tests remain
      independent of orchestration.

---

## Phase 4: Decision Terminal Path

**User stories**: 1, 3, 6, 8, 21–22, 33–35, 39–40

### What to build

Move the complete deterministic-decision tracer behind the deep module: evidence loading,
reconciliation, casefile freezing, policy evaluation, rule and amount trace construction, and
lease-fenced decision commit. Use recorded or structured evidence that produces a stable expected
decision so the slice can compare the durable result before and after internal movement.

This phase establishes casefile and terminal-decision operations as private cohesive capabilities
without changing evidence, policy, calculation, review, or member-explanation semantics.

### Acceptance criteria

- [ ] The decision-producing claim enters through the worker-used processing boundary.
- [ ] Evidence reconciliation, casefile freezing, deterministic policy evaluation, and decision
      preparation remain private processing operations.
- [ ] The same canonical inputs produce the same casefile hash, decision hash, recommendation,
      approved amount, reason codes, and member explanation as before the refactor.
- [ ] The decision, complete rule trace, amount trace, claim projection, terminal workflow effect,
      workflow completion, audit state, and work completion commit atomically.
- [ ] The terminal transaction validates the active lease within the same transaction as the
      decision.
- [ ] A stale lease cannot create a decision, overwrite a projection, complete a workflow, or add
      a terminal effect.
- [ ] Repeated or resumed execution creates no duplicate casefile, decision, rule result, effect,
      event, or audit record.
- [ ] Review-producing decisions preserve their evidence, signal codes, machine recommendation,
      allowed reviewer actions, and reconstruction data.
- [ ] Model outputs remain evidence-only and cannot supply the recommendation, approved amount,
      or policy reason code.
- [ ] Existing policy and evidence unit/property tests remain focused on their public domain
      behavior rather than workflow orchestration.
- [ ] Recorded and structured adjudication acceptance cases pass through the new boundary.

---

## Phase 5: Failure and Retry Outcomes

**User stories**: 2, 5, 9–10, 12–14, 35–36

### What to build

Make every worker-visible processing outcome originate from the deep boundary. Exercise retryable
provider failure, deterministic terminal failure, lease loss, already-completed replay, terminal
commit, normal completion, and unexpected exception as complete processing paths.

The slice preserves durable progress and makes failure handling observable without exposing graph
phases. Controlled failure hooks remain private test instrumentation at workflow durability
boundaries.

### Acceptance criteria

- [ ] A retryable provider failure returns a typed retry outcome with the configured bounded
      schedule and preserves committed workflow progress.
- [ ] A known non-retryable failure returns a typed failed outcome and projects the existing stable
      processing-failure code.
- [ ] Lease loss returns the typed lease-lost outcome and does not mutate terminal claim state.
- [ ] An already completed workflow returns the completed outcome without rerunning graph work.
- [ ] An atomically committed terminal path returns the committed outcome without a second work
      completion transaction.
- [ ] A non-terminal finalized path returns the normal completed outcome and marks the workflow
      and work item consistently.
- [ ] An unexpected processing exception cannot leave currently owned work indefinitely leased.
- [ ] Retry and failure paths do not duplicate durable effects, events, observations, actions,
      decisions, or audit records.
- [ ] Retry timing remains deterministic under injected clock and entropy in focused tests.
- [ ] Controlled crash and failure hooks are unavailable through production command interfaces.
- [ ] Direct tests of the superseded orchestration wrapper and its phase-level failure plumbing
      are deleted after equivalent boundary coverage passes.

---

## Phase 6: Observability and Reconstruction

**User stories**: 12–14, 23, 32, 38, 40

### What to build

Complete the diagnostic side of the deep boundary. Preserve uniform workflow and node telemetry,
durable event and effect semantics, and full PostgreSQL reconstruction while separating processing
commands from trace reads.

Verify one recovered run and one terminal run through both the authoritative reconstruction and
sanitized observability views. Operational correlation must remain useful without making private
graph operations public.

### Acceptance criteria

- [ ] Processing trace reads are available through a separate read-side capability rather than
      the command processor.
- [ ] PostgreSQL reconstruction remains sufficient without Phoenix or JSONL logs.
- [ ] Reconstruction includes workflow runs, events, effects, failures, casefiles, decisions,
      member actions, review records, and applicable evidence references exactly as before.
- [ ] Root workflow and node spans retain claim, workflow, execution-profile, attempt, outcome,
      and duration correlation.
- [ ] Terminal spans record lease-validation and terminal-commit outcomes.
- [ ] Retry and resume traces identify the current attempt rather than historical checkpoint
      ownership.
- [ ] Durable workflow event and effect types retain their existing meaning and ordering.
- [ ] Raw lease tokens, document contents, OCR text, prompts, model responses, patient data, and
      local storage paths remain absent from normal telemetry.
- [ ] Processing telemetry failure cannot roll back or invalidate an authoritative terminal
      transaction.
- [ ] Recorded recovery and terminal scenarios produce reconstructable and correlated diagnostic
      evidence.
- [ ] Existing observability and reconstruction tests are recentered on public read and processing
      boundaries without duplicating adapter-specific checks.

---

## Phase 7: Exclusive Cutover and Cleanup

**User stories**: 1, 16–17, 19, 23, 28, 31–32, 37–40

### What to build

Migrate every worker, command, integration harness, and supported test caller to the deep
processing boundary. Remove the old phase-level processor protocol, orchestration facade,
workflow composition path, and temporary compatibility adapters once boundary parity is proven.

Finish by enforcing import direction, documenting module ownership and workflow-version rules,
and validating every deterministic acceptance path. The end state must have one supported durable
processing path rather than old and new architectures living side by side.

### Acceptance criteria

- [ ] All production worker and command callers use the deep processing boundary.
- [ ] No API, worker, test, or unrelated application module imports private workflow topology,
      checkpoint state, graph nodes, or processing operations.
- [ ] The old public phase-level processor and orchestration path are removed.
- [ ] Temporary delegation and compatibility adapters introduced during migration are removed.
- [ ] Redundant direct-phase and orchestration-construction tests are deleted after boundary
      parity.
- [ ] Focused scheduler, storage, provider, evidence, policy, reconstruction, and adapter tests
      remain because they cover independent public boundaries.
- [ ] Import-boundary enforcement prevents new callers from depending on private processing
      internals.
- [ ] Architecture and operator documentation describe the processing boundary, dependency
      direction, composition ownership, recovery contract, and graph-version criteria.
- [ ] No database migration or public API schema change was introduced solely for file movement.
- [ ] Public claim, action, and review contract suites pass unchanged.
- [ ] Workflow recovery, execution-contract compatibility, lease-fencing, failure, observability,
      reconstruction, recorded-document, structured-adjudication, and rendered-evaluation suites
      pass.
- [ ] Formatting, lint, strict type checking, migration validation, and the full deterministic
      test suite pass.
- [ ] The final architecture contains exactly one supported worker-to-processing execution path.
