# Backend v1 Completion Status

**Status: in progress — not yet eligible to claim Backend v1 complete.**

This is a current-state report. It deliberately does not convert recorded-evaluation fixtures or
unverified historical test counts into an operational-completion claim.

## Implemented and verified

- FastAPI accepts multipart claims and exposes member-scoped claim projections.
- `claims-worker run-once` and `claims-worker run-loop` lease durable PostgreSQL work.
- `RECORDED_LOCAL` is the default profile; live AWS requires both the live profile and explicit
  `CLAIMS_RUN_LIVE_AWS=1` authorization.
- A public no-fixture action-required tracer and a public no-fixture synthetic clean-decision
  tracer pass through the actual worker composition.
- Worker leases have owner/token fencing, heartbeats, bounded shutdown behavior, and checkpoint
  recovery coverage.
- Exhausted or non-retryable processing reaches `PROCESSING_FAILED` with a member-safe code and
  retry guidance.
- API and workflow spans use the claim ID as Phoenix `session.id`; PostgreSQL workflow events and
  JSONL records retain local reconstruction data.
- Test execution refuses the application database unless an explicit destructive override is set.
- `ruff format --check .`, `ruff check .`, `mypy`, and `alembic check` pass.

## Local operation

```bash
uv run alembic upgrade head
uv run uvicorn claims_backend.api.app:app --reload
uv run claims-worker run-loop
```

For a one-work-item smoke pass:

```bash
uv run claims-worker run-once
```

Health endpoints:

- `GET /health/live`
- `GET /health/ready`

Local records are under the configured `CLAIMS_LOG_ROOT`; Phoenix is available when its local OTLP
endpoint is configured. PostgreSQL contains durable work, workflow events, effects, casefiles,
decisions, review records, and audit records.

## Remaining work before completion

- Persist and recover the complete execution contract: profile, provider versions, model, prompts,
  schemas, and graph version.
- Move all twelve recorded cases to normal no-fixture operational routing, including correction,
  eligibility, partial-approval, review, and degradation cases.
- Complete Phoenix evaluations and claim-session coverage for replacement and review activity.
- Add an explicitly authorized synthetic full live AWS tracer and document its actual result.
- Generate committed sanitized evaluation, version-manifest, privacy, and current test-summary
  artifacts.
- Re-run and capture the final complete deterministic suite with its exact pass/skip count.

## Current limitations

- Recorded rendered evaluation remains the primary broad correctness gate; it is not yet the same
  as every case using the operational recorded worker composition.
- Live Textract/Bedrock variability is not represented as twelve-live-case coverage.
- Backend v1 completion must not be claimed until the unchecked acceptance criteria in
  `plans/backend-v1-operational-completion.md` are closed with current evidence.
