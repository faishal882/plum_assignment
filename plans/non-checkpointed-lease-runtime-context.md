# Plan: Non-Checkpointed Lease Runtime Context

> Source PRD: [Non-Checkpointed Workflow Lease Runtime Context](../prds/non-checkpointed-lease-runtime-context-prd.md)

## Architectural decisions

- **Public routes**: No claim API or frontend contract changes.
- **Durable workflow state**: Checkpoints contain only business workflow progress, document/gate findings, casefile references, and terminal flags. Queue ownership is excluded.
- **Runtime authority**: Each graph invocation receives immutable, non-checkpointed execution context containing the active `WorkLease`, workflow identity, claim identity/version, and invocation metadata.
- **Lease fencing**: PostgreSQL remains authoritative. A terminal write requires the current work item to be leased by the active owner, match the active fencing token, and be unexpired inside the same transaction.
- **Terminal effects**: Action/decision records, claim projection, workflow effect, work completion, and workflow completion remain atomic.
- **Failure outcomes**: Known retryable failures schedule retry; known terminal failures fail work; lease loss produces no terminal business effect; unexpected processor exceptions fail the currently owned item as `UNHANDLED_PROCESSING_ERROR`.
- **Migration**: Existing checkpoints may contain legacy lease fields. They remain resumable, but runtime context is authoritative and checkpoint lease values are ignored.
- **Observability**: Emit current work attempt, hashed lease identifier, lease-validation outcome, and terminal-commit outcome as filterable attributes. Raw lease tokens never appear in telemetry.

---

## Phase 1: Runtime Context Boundary

**User stories**: 11, 12, 13, 18

### What to build

Establish one immutable runtime-context contract for each graph invocation. New checkpoints no longer persist lease ownership, while a legacy checkpoint resumes with its current scheduler lease supplied by runtime context.

### Acceptance criteria

- [x] A new checkpoint contains no worker ID, lease token, lease timestamps, availability time, attempt number, or attempt budget.
- [x] Every graph invocation, including resume, receives a fresh active lease through non-checkpointed runtime context.
- [x] A legacy checkpoint containing lease fields resumes successfully and ignores its stored lease token.
- [x] Runtime-context construction and migration compatibility are covered by focused tests.

---

## Phase 2: Active-Lease Member Action Commit

**User stories**: 3, 5, 6, 7, 14, 15

### What to build

Run an interrupted early-triage claim through a reclaim and resume into the member-action terminal path. The action is committed only by the reclaimed worker’s active lease and completes all terminal state atomically.

### Acceptance criteria

- [x] A retry/reclaim receives a new fencing token and resumed member-action commit uses that token.
- [x] The member action, claim `ACTION_REQUIRED` projection, workflow effect, workflow completion, and work completion are committed once together.
- [x] A stale worker cannot add a member action or terminal workflow effect after reclaim.
- [x] Lease loss is typed and produces no terminal claim mutation.

---

## Phase 3: Active-Lease Decision Commit

**User stories**: 2, 4, 5, 6, 7, 14, 15

### What to build

Apply the same active runtime-lease contract to the adjudication terminal path, preserving existing casefile and policy business state through a retry while preventing stale decision commits.

### Acceptance criteria

- [x] A reclaimed workflow resumes to a decision commit using the current runtime lease.
- [x] A decision record, claim projection, workflow effect, work completion, and workflow completion remain atomic.
- [x] A stale worker cannot create a decision, overwrite the projection, or duplicate a terminal effect.
- [x] Existing policy and casefile acceptance behavior remains unchanged.

---

## Phase 4: Failure Finalization

**User stories**: 1, 8, 9, 10

### What to build

Make every processor outcome durable and explicit: provider failures follow retry policy, deterministic failures terminate safely, lease loss is ownership-neutral, and unknown exceptions cannot strand work in `LEASED`.

### Acceptance criteria

- [x] Retryable provider failures schedule a bounded retry and preserve workflow business progress.
- [x] Known non-retryable failures project `PROCESSING_FAILED` with the correct stable code.
- [x] An unexpected processor exception fails the currently owned item as `UNHANDLED_PROCESSING_ERROR` and retains the original error trace.
- [x] No worker path leaves a non-expired work item in `LEASED` after its handler terminates unexpectedly.

---

## Phase 5: Traceable Lease Outcomes

**User stories**: 16, 17

### What to build

Expose the execution ownership lifecycle in Phoenix and JSONL logs without exposing the raw fencing token, so retries and terminal-write outcomes can be reconstructed directly from a trace.

### Acceptance criteria

- [x] Workflow and terminal spans include current work attempt, hashed lease identity, lease-validation outcome, and terminal-commit outcome as flat attributes.
- [x] Retry/resume traces identify the active attempt rather than a checkpointed historical attempt.
- [x] Raw lease tokens are absent from span attributes, span payloads, JSONL logs, and public responses.
- [x] Phoenix filters can isolate rejected stale-lease terminal attempts.

---

## Phase 6: Compatibility Cleanup Gate

**User stories**: 2, 12, 13, 18

### What to build

Prove the architecture works across legacy and new checkpoints, remove the temporary checkpoint lease-refresh compatibility path, and validate the complete durable-work contract.

### Acceptance criteria

- [x] Legacy checkpoint resume, member-action reclaim/resume, decision reclaim/resume, stale-worker fencing, and unhandled-exception tests all pass.
- [x] The temporary checkpoint lease-refresh path is removed because no workflow node reads lease state from the checkpoint.
- [x] Focused integration, formatting, lint, type, migration, and full deterministic suites pass.
- [x] The implementation and trace behavior are documented for local operators.
