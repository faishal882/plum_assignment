# Backend v1 Completion Status

**Status: Backend v1 operational scope complete.**

This is a current-state report grounded in the current recorded gate, explicit live traces, and
sanitized proof artifacts. It does not claim arbitrary real-document accuracy.

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
- The deterministic suite completed with **235 passed, 4 skipped** in 102.81 seconds. The four
  skipped checks are the explicitly opt-in synthetic Textract, Bedrock, direct-TC004, and
  public-worker-TC004 live tests.
- The explicitly authorized synthetic live TC004 provider-to-policy tracer and public FastAPI →
  standalone-worker tracer passed on 2026-07-29: real Textract and Qwen evidence reached the
  deterministic ₹1,350 approval. Their sanitized result is recorded in
  `artifacts/backend-v1/live-intelligence-summary.json`.
- The explicitly authorized synthetic Textract and Bedrock smoke suite also passed: **2 passed**
  in 3.94 seconds.
- The complete live public-worker tracer verifies correlated API and worker Phoenix claim sessions
  and rejects synthetic patient/clinical canaries from span attributes.

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

## Current limitations

- Recorded rendered evaluation is the primary Backend v1 correctness gate and runs through the
  operational recorded worker. It is synthetic/de-identified and does not establish real-world
  OCR/model accuracy for arbitrary customer documents.
- Live Textract/Bedrock variability is not represented as twelve-live-case coverage. The synthetic
  TC004 public-worker tracer passes with Textract-labelled total and diagnosis-line evidence
  decoders. Do not claim all twelve live cases pass.
- Backend v1 is a local operational backend. Authentication, remote deployment, arbitrary
  real-world OCR/model accuracy, and twelve-case live-provider coverage remain out of scope.
