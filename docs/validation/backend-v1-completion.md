# Backend v1 Completion Status

**Status: Backend v1 operational scope complete.**

This is a current-state report grounded in the current recorded gate, explicit live traces, and
sanitized proof artifacts. It does not claim arbitrary real-document accuracy.

Phase-by-phase evidence is indexed in [the Backend v1 acceptance audit](backend-v1-acceptance-audit.md).

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
- Fast triage now uses `triage-output-v3`: Bedrock returns semantic values plus exact OCR
  observation references, while the backend computes hashes and reconstructs page, region,
  confidence, preview, and document-version provenance. These references are persisted and included
  in PostgreSQL claim reconstruction.
- The post-hardening deterministic suite passes with **245 passed, 4 live-AWS checks skipped**; the
  twelve-case rendered acceptance gate passes independently.
- Test execution refuses the application database unless an explicit destructive override is set.
- `ruff format --check .`, `ruff check .`, `mypy`, and `alembic check` pass.
- With the user's explicit `CLAIMS_RUN_LIVE_AWS=1` setting, the full suite completed with
  **239 passed, 0 skipped** in 157.78 seconds. This includes the otherwise opt-in synthetic
  Textract, Bedrock, direct-TC004, and public-worker-TC004 live checks. With the default opt-out
  setting, those four live checks remain skipped rather than incurring AWS cost.
- The explicitly authorized synthetic live TC004 provider-to-policy tracer and public FastAPI →
  standalone-worker tracer passed on 2026-07-29: real Textract and Qwen evidence reached the
  deterministic ₹1,350 approval. Their sanitized result is recorded in
  [`artifacts/backend-v1/live-intelligence-summary.json`](../../artifacts/backend-v1/live-intelligence-summary.json).
- The explicitly authorized synthetic Textract and Bedrock smoke suite also passed: **2 passed**
  in 3.94 seconds.
- The complete live public-worker tracer verifies correlated API and worker Phoenix claim sessions
  and rejects synthetic patient/clinical canaries from span attributes.
- A manual local API → worker run on 2026-07-29 confirmed `GET /health/live`,
  `GET /health/ready`, submission, idempotent retry, member isolation, reviewer listing, Phoenix
  export, JSONL emission, and PostgreSQL reconstruction. A separately rendered synthetic invoice
  reached the worker and safely ended as `PROCESSING_FAILED` with
  `MODEL_SCHEMA_VALIDATION_FAILED`; it did not remain queued. The sanitized evidence is in
  [`artifacts/backend-v1/live-local-e2e-summary.json`](../../artifacts/backend-v1/live-local-e2e-summary.json).

## Recorded acceptance outcomes

The committed rendered evaluation artifact covers all cases through the normal composed worker:

| Case | Lifecycle | Decision | Amount (paise) | Primary reason |
|---|---|---|---:|---|
| TC001 | ACTION_REQUIRED | — | — | MISSING_REQUIRED_DOCUMENT |
| TC002 | ACTION_REQUIRED | — | — | UNREADABLE_DOCUMENT |
| TC003 | ACTION_REQUIRED | — | — | PATIENT_IDENTITY_CONFLICT |
| TC004 | DECIDED | APPROVED | 135000 | FINAL_APPROVED |
| TC005 | DECIDED | REJECTED | 0 | WAITING_PERIOD |
| TC006 | DECIDED | PARTIAL | 800000 | DENTAL_LINE_ITEM_EXCLUDED |
| TC007 | DECIDED | REJECTED | 0 | PRE_AUTH_MISSING |
| TC008 | DECIDED | REJECTED | 0 | PER_CLAIM_EXCEEDED |
| TC009 | IN_REVIEW | MANUAL_REVIEW | — | SAME_DAY_CLAIM_VELOCITY |
| TC010 | DECIDED | APPROVED | 324000 | NETWORK_DISCOUNT_APPLIED |
| TC011 | DECIDED | APPROVED | 400000 | FINAL_APPROVED |
| TC012 | DECIDED | REJECTED | 0 | EXCLUDED_CONDITION |

The source artifact also verifies complete workflow traces, no `ProcessingFixtureRow` use, and a
telemetry PHI-canary scan without committing raw runtime content.

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
- The manual synthetic invoice run demonstrates that arbitrary document layouts can still trigger
  model-schema safe failure. It is correctly observable and recoverable, but it is not proof that
  arbitrary real documents will be approved. The passing generated TC004 tracer is the bounded
  live acceptance claim.
- The AWS account currently rejects structured Bedrock invocation for the locally configured
  Anthropic inference profiles with `INVALID_PAYMENT_INSTRUMENT`. This is an account billing/access
  blocker rather than a triage-schema failure; recorded acceptance remains the executable gate
  until AWS access is restored.
- Backend v1 is a local operational backend. Authentication, remote deployment, arbitrary
  real-world OCR/model accuracy, and twelve-case live-provider coverage remain out of scope.
