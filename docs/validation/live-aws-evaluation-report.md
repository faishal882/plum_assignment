# Live AWS Evaluation Report

Generated: 2026-07-30
Project: Plum Claims Processing System
Execution profile: `LIVE_INTELLIGENCE`
AWS gate: `CLAIMS_RUN_LIVE_AWS=1`

## Executive result

The live AWS evaluation passed all four enabled live tests:

```text
4 passed
```

The run exercised real Amazon Textract and Amazon Bedrock calls. It did not use the recorded intelligence adapters.

| Scope | Result | Evidence |
|---|---:|---|
| Textract schema/provider smoke | PASS | `test_synthetic_page_passes_live_textract_schema_smoke` |
| Bedrock structured-output/provider smoke | PASS | `test_synthetic_ocr_passes_live_bedrock_structured_output_smoke` |
| Live OCR + Bedrock + deterministic policy TC004 | PASS | `test_live_tc004_intelligence_preserves_exact_policy_result` |
| Public FastAPI → PostgreSQL queue → standard worker TC004 | PASS | `test_live_tc004_runs_through_public_api_and_standard_worker` |

The public end-to-end claim reached:

```json
{
  "lifecycle_status": "DECIDED",
  "recommendation": "APPROVED",
  "approved_amount": "1350.00",
  "currency": "INR"
}
```

The approval reflects the deterministic policy result for a ₹1,500 consultation claim with the configured 10% consultation co-pay.

## Exact commands

Provider smoke tests:

```bash
CLAIMS_RUN_LIVE_AWS=1 \
CLAIMS_EXECUTION_PROFILE=LIVE_INTELLIGENCE \
uv run pytest tests/live/test_textract_live.py tests/live/test_bedrock_live.py -vv -rA
```

Result:

```text
2 passed in 6.70s
```

Live intelligence and public worker tests:

```bash
CLAIMS_RUN_LIVE_AWS=1 \
CLAIMS_EXECUTION_PROFILE=LIVE_INTELLIGENCE \
uv run pytest \
  tests/live/test_tc004_live_intelligence.py \
  tests/live/test_live_worker_tc004.py \
  -vv -rA
```

Result:

```text
2 passed in 58.99s
```

Combined live-suite result:

```text
4 passed
```

## Providers and model configuration

The live run used the values loaded from the local environment. Secrets and AWS credentials are intentionally not included in this report.

```text
OCR provider: Amazon Textract
Textract region: ap-south-1
Model provider: Amazon Bedrock Converse
Bedrock region: us-west-2
Model ID: deepseek.v3.2
```

The model ID is environment-configured through `CLAIMS_BEDROCK_MODEL_ID`; it is not hard-coded into the workflow.

## What the live tests prove

### Provider smoke

The Textract test sends a generated JPEG page to the real Textract adapter and verifies:

- a provider request ID is returned;
- OCR observations are returned;
- observations retain the backend document-version ID;
- observations retain page number and schema invariants.

The Bedrock test sends a bounded synthetic OCR input to the real structured-output transport and verifies:

- a provider request ID;
- positive input/output token counts;
- positive latency;
- a stop reason;
- structured candidates grounded to the supplied observation ID.

### Direct live TC004

The direct live test runs the real provider path for a synthetic prescription and hospital bill, then passes the resulting OCR/model evidence through:

```text
Textract observations
→ Bedrock structured extraction
→ backend provenance attachment
→ evidence reconciliation
→ frozen casefile
→ deterministic policy adjudicator
```

It verifies an exact approved amount of `135000` paise and the presence of the consultation co-pay rule.

### Public worker TC004

The public tracer performs the operational path:

```text
POST /v1/claims
→ claim/version/document persistence
→ durable claim_work_item
→ worker lease
→ LangGraph workflow
→ live Textract and Bedrock
→ PostgreSQL decision commit
→ GET /v1/claims/{id}
```

It verifies that the API returns `202`, the normal worker processes the queued claim, the final projection is `DECIDED`, and the approved amount is `1350.00 INR`.

The test also captures API and worker OpenTelemetry spans in an in-memory exporter and verifies a claim-correlated `api.claim_submitted` span and `claim.workflow` span. This proves trace creation and correlation in the live workflow test.

## Trace and observability evidence

The live workflow creates the following logical trace hierarchy:

```text
api.request
└── api.claim_submitted

claim.workflow
├── claim.workflow.load_claim
├── claim.workflow.media_inspect
├── claim.workflow.render_documents
├── claim.workflow.ocr_documents
│   └── textract.analyze_page
├── claim.workflow.extract_evidence
│   └── bedrock.converse
├── claim.workflow.reconcile_casefile
├── claim.workflow.adjudicate
└── claim.workflow.commit_decision
```

The Bedrock span records route/model/schema metadata, provider request ID, input/output token counts, latency, stop reason, and structured output attributes. The worker workflow records node outcome, attempt number, workflow run ID, claim ID, lease validation outcome, and terminal commit outcome.

For a persistent Phoenix UI trace rather than the test's in-memory exporter, run Phoenix before the API/worker and keep these settings enabled:

```dotenv
CLAIMS_OBSERVABILITY_ENABLED=1
CLAIMS_PHOENIX_ENDPOINT=http://127.0.0.1:6006/v1/traces
CLAIMS_PHOENIX_PROJECT=plum-claims-local
```

Then execute the public-worker test or submit a claim manually through the running API and worker. The test result above proves the spans were emitted and correlated; it does not claim that the test exporter itself persisted spans into a Phoenix server.

## Data and safety scope

The live tests use generated synthetic documents containing fictional claim data. They do not use production member records or real PHI. The live tests are provider-integration evidence, not a production readiness claim.

The backend still fails closed when live output cannot be grounded, parsed, or reconciled. A provider/model failure becomes a processing failure or an action-required branch; it cannot directly produce an unsupported approval or payment amount.

## What this report does not claim

This report does **not** claim that all 12 assignment cases pass with live AWS. The 12-case acceptance gate remains the recorded rendered evaluation because it is deterministic and repeatable:

```bash
uv run pytest \
  tests/integration/test_rendered_evaluation_gate.py::test_all_twelve_cases_pass_the_recorded_rendered_evaluation_gate \
  -q
```

Live coverage currently proves one complete case, TC004, plus independent Textract and Bedrock smoke tests. Other live cases may encounter model omissions, unsupported aliases, malformed structured output, OCR variability, or provider limits. Those failures are recorded as known limitations rather than hidden behind recorded fixtures.

## Reproducibility checklist

- [x] `CLAIMS_RUN_LIVE_AWS=1` was set.
- [x] `CLAIMS_EXECUTION_PROFILE=LIVE_INTELLIGENCE` was set.
- [x] Real Textract was called.
- [x] Real Bedrock Converse was called.
- [x] Direct live TC004 passed.
- [x] Public API-to-standard-worker TC004 passed.
- [x] Deterministic policy output was verified after live extraction.
- [x] Trace creation and API/worker claim correlation were verified.
- [x] No AWS credentials or secrets are included in this artifact.
- [x] The report does not overclaim all 12 live cases.
