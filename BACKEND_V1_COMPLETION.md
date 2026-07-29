# Backend v1 Completion Status

**Status: in progress — not yet eligible to claim Backend v1 complete.**

This is a current-state report. It deliberately does not convert recorded-evaluation fixtures or
unverified historical test counts into an operational-completion claim.

## Implemented and verified

- FastAPI accepts multipart claims and exposes member-scoped claim projections.
- `claims-worker run-once` and `claims-worker run-loop` lease durable PostgreSQL work.
- `RECORDED_LOCAL` is the default profile; live AWS requires both the live profile and explicit
  `CLAIMS_RUN_LIVE_AWS=1` authorization.
- All twelve assignment cases now pass through the public API and normal composed
  `RECORDED_LOCAL` worker without a `ProcessingFixtureRow`. This includes corrective actions,
  rejection, partial approval, review routing, controlled local degradation, and approval paths.
- The recorded rendered evaluation gate uses that same operational worker construction; the
  OCR-bypassed structured runner remains a separate diagnostic control.
- Worker leases have owner/token fencing, heartbeats, bounded shutdown behavior, and checkpoint
  recovery coverage.
- Exhausted or non-retryable processing reaches `PROCESSING_FAILED` with a member-safe code and
  retry guidance.
- API, workflow, replacement, review, and evaluation spans use the claim ID as Phoenix
  `session.id`. Recorded evaluation spans capture schema validity, grounding coverage, trace
  completeness, reconstruction, provenance/failure counts, and aggregate pass-rate metrics.
  PostgreSQL workflow events and JSONL records retain local reconstruction data.
- Test execution refuses the application database unless an explicit destructive override is set.
- `ruff format --check .`, `ruff check .`, `mypy`, and `alembic check` pass.
- The deterministic suite completed with **227 passed, 3 skipped** in 91.02 seconds. The three
  skipped checks are the explicitly opt-in synthetic Textract, Bedrock, and full-live-TC004 tests.
- The explicitly authorized synthetic live TC004 provider-to-policy tracer passed on 2026-07-29:
  real Textract and Qwen evidence reached the deterministic ₹1,350 approval. Its sanitized result
  is recorded in `artifacts/backend-v1/live-intelligence-summary.json`.

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

- Complete recovery construction from a compatible persisted historical execution contract.
- Add an explicitly authorized synthetic full live AWS tracer through the public API and standalone
  worker boundary.
- Add the remaining live-only evidence after an explicitly authorized run; recorded-evaluation,
  version-manifest, privacy, and deterministic test-summary artifacts are committed.

## Current limitations

- Recorded rendered evaluation is the primary Backend v1 correctness gate and runs through the
  operational recorded worker. It is synthetic/de-identified and does not establish real-world
  OCR/model accuracy for arbitrary customer documents.
- Live Textract/Bedrock variability is not represented as twelve-live-case coverage. The synthetic
  direct TC004 provider-to-policy tracer passes with Textract-labelled total and diagnosis-line
  evidence decoders; it does not yet prove the public API and standalone-worker live boundary.
  Do not claim all twelve live cases pass.
- Backend v1 completion must not be claimed until the unchecked acceptance criteria in
  `plans/backend-v1-operational-completion.md` are closed with current evidence.
