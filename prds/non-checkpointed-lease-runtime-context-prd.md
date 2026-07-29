# Non-Checkpointed Workflow Lease Runtime Context PRD

## Problem Statement

Claim processing is durable across worker crashes and provider retries. LangGraph checkpoints currently include the active queue lease metadata alongside durable business workflow state. When a work item is reclaimed, the scheduler issues a new fencing token, but a resumed graph can restore the old token from its checkpoint. A terminal commit then correctly refuses the stale token, yet an unclassified exception can leave the work item leased.

From the claim-processing user's perspective, a transient provider failure must never cause a completed triage result to fail later because the worker changed. Terminal claim decisions and member-action requests must be committed only by the worker that currently owns the work item, and every failure must reach a durable, inspectable work state.

## Solution

Separate durable workflow business state from ephemeral execution authority.

LangGraph checkpoints will contain only claim-processing state: workflow progress, document findings, gate outcomes, casefile references, and terminal-state flags. Each graph invocation will receive an immutable runtime context containing the active `WorkLease` and invocation identity. Nodes that perform terminal persistence will obtain the lease only from that runtime context.

Existing checkpoints that contain historical lease fields will remain resumable. The new runtime will ignore those fields and use only the active lease supplied by the worker. Database terminal effects will remain atomically fenced by the current work item status, owner, token, and expiry. Unexpected processor exceptions will fail the active lease with a stable engineering code so no work remains indefinitely leased.

## User Stories

1. As a claims member, I want a transient Bedrock failure to retry safely, so that an otherwise valid claim can continue processing.
2. As a claims member, I want retries to preserve completed workflow progress, so that the system does not repeat already committed business effects.
3. As a claims member, I want the currently active worker to be the only worker that can create an action request, so that stale processing cannot change my claim.
4. As a claims member, I want the currently active worker to be the only worker that can commit an adjudication decision, so that claim outcomes are deterministic and auditable.
5. As an operator, I want reclaimed work to use a new fencing token, so that a crashed worker cannot commit after recovery begins.
6. As an operator, I want a resumed workflow to use the lease obtained for that invocation, so that checkpoint history cannot override current queue ownership.
7. As an operator, I want a stale-worker terminal write to be rejected without a business-side effect, so that lease loss is safe.
8. As an operator, I want retryable provider failures to remain retryable, so that temporary AWS failures do not become permanent claim failures.
9. As an operator, I want deterministic validation and policy failures to become terminal failures, so that invalid work does not retry indefinitely.
10. As an operator, I want unexpected processor exceptions to end in a durable failure state, so that no claim remains silently leased.
11. As a developer, I want execution authority to be represented by one immutable runtime-context interface, so that new terminal nodes cannot accidentally read a checkpointed lease.
12. As a developer, I want durable business state to have no lease fields, so that checkpoint contents remain stable across worker ownership changes.
13. As a developer, I want old checkpoints to resume during migration, so that deploying the change does not strand in-flight work.
14. As a developer, I want terminal persistence to be atomic, so that an action or decision cannot exist without the corresponding completed work item and workflow run.
15. As a developer, I want a lost lease to produce a typed outcome, so that callers can distinguish ownership loss from a processing defect.
16. As an evaluator, I want retry/resume traces to show the work attempt and lease-validation outcome, so that I can reconstruct why a terminal effect was accepted or rejected.
17. As an evaluator, I want lease identifiers in telemetry to be hashed, so that observability correlates ownership without exposing raw fencing tokens.
18. As a test author, I want reusable lease-runtime and terminal-fencing modules, so that failure scenarios can be tested without live OCR or Bedrock calls.

## Implementation Decisions

- Introduce an immutable workflow runtime-context module as the sole interface for active execution authority. It contains the active `WorkLease`, workflow-run identity, claim identity/version, attempt metadata, and observability correlation metadata available at invocation time.
- Configure the LangGraph state graph with a non-checkpointed context schema. Pass a fresh runtime context for every invocation, including resumes.
- Remove worker identity, lease token, lease timestamps, availability timestamp, attempt number, and attempt budget from the checkpointed workflow-state contract and its initial state.
- Update workflow-node wrappers to receive LangGraph runtime context and use it for attempt-aware events, logs, and terminal persistence.
- Update decision and member-action terminal nodes to pass only the runtime-context lease to their processors.
- Keep database-level lease fencing as the authoritative terminal-write boundary: work item must be leased by the current owner, match the current fencing token, and remain unexpired inside the terminal transaction.
- Preserve atomic terminal transactions: terminal record/action, claim projection, workflow effect, work completion, and workflow completion commit together.
- Model lease loss explicitly as a typed non-business outcome. It creates no terminal claim effect and does not overwrite the current owner’s work state.
- Classify known failures through the existing retry policy. Retryable failures schedule a retry; known non-retryable failures fail work; unknown processor exceptions fail the owned work item with `UNHANDLED_PROCESSING_ERROR` and retain the original trace/exception.
- Retain the existing checkpoint lease-refresh behavior only as a temporary migration compatibility guard. It must be deleted once no workflow path reads lease fields from checkpoint state.
- Existing checkpoints with historical lease values remain supported. On resume, those values are ignored; runtime context is authoritative.
- Emit flat, filterable observability attributes for work attempt, hashed lease token, lease-validation outcome, and terminal-commit outcome. Continue recording detailed provider and workflow output in span payloads.
- Do not alter public claim API response contracts as part of this work. The change is internal execution correctness and observability.

## Testing Decisions

- Tests must verify externally observable durability behavior, database terminal state, and fencing outcomes rather than private implementation calls alone.
- Unit-test the runtime-context construction and lease-hash/telemetry mapping as deterministic deep modules.
- Unit-test terminal-fencing outcome translation: current lease accepted, stale lease lost, and unknown exception failure finalization.
- Add integration coverage for a retryable failure followed by a reclaimed lease and resume through `commit_member_action`; assert the action is committed once using the second lease and the work item is completed.
- Add integration coverage for the same reclaim/resume path through `commit_decision`; assert the decision is committed once and the work item is completed.
- Add integration coverage where an old worker attempts a terminal commit after reclaim; assert no action/decision/effect is added by the old worker.
- Add integration coverage for an unexpected processor exception; assert the work item is not left `LEASED`, its failure code is `UNHANDLED_PROCESSING_ERROR`, and the claim projects `PROCESSING_FAILED`.
- Add migration compatibility coverage using a checkpoint created with legacy lease fields; assert a new runtime context resumes it successfully and ignores the stored token.
- Assert workflow events and Phoenix span attributes report the current attempt and a hashed lease identifier, never the raw lease token.
- Reuse the existing PostgreSQL scheduler, workflow recovery, and terminal action/decision integration-test patterns as prior art.

## Out of Scope

- Changing claim API endpoints, frontend behavior, or identity/authentication.
- Changing document triage prompts, Bedrock models, OCR providers, evidence normalization, or policy rules.
- Introducing distributed workers, SQS, or deployment infrastructure.
- Retrying arbitrary unknown exceptions automatically.
- Migrating or deleting historical checkpoint rows solely to remove legacy lease fields.
- Exposing raw lease tokens through Phoenix, JSONL logs, database projections, or public APIs.

## Further Notes

- The current lease-refresh fix prevents the immediate stale-token defect, but runtime context is the structural boundary that makes lease authority non-persistent by design.
- A work item being `LEASED` is not a business workflow state. It is a short-lived scheduler ownership fact and must never be treated as durable claim progress.
- The terminal database transaction remains the final authority even after runtime-context separation; context prevents accidental stale reads, while fencing prevents concurrent stale writes.
- Completion requires all listed test gates and formatting/type checks to pass before the temporary checkpoint-refresh compatibility path is removed.
