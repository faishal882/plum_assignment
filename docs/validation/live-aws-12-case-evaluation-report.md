# Live AWS 12-Case Evaluation Report

Generated from a real end-to-end run on 2026-07-30. Every case used the public
FastAPI submission path, the PostgreSQL-backed queue, the standalone worker,
Amazon Textract, and Amazon Bedrock. No recorded processing fixture was seeded
for the claim path. The machine-readable evidence is in
[`live-12-evaluation-report.json`](../../artifacts/backend-v1/live-12-evaluation-report.json).

## Result

```text
Command:
CLAIMS_RUN_LIVE_AWS=1 CLAIMS_EXECUTION_PROFILE=LIVE_INTELLIGENCE \
  uv run pytest tests/live/test_live_evaluation_gate.py -q -s

pytest result: 1 passed (the report-generation test)
assignment cases executed: 12
oracle-equivalent cases: 3
non-equivalent cases: 9
provider mode: LIVE_INTELLIGENCE
OCR provider: AMAZON_TEXTRACT (ap-south-1)
model provider: AMAZON_BEDROCK (us-west-2)
model: deepseek.v3.2
elapsed time: 401.21 seconds
```

The pytest pass means the harness executed and recorded all twelve cases; it is
not a claim that all twelve live model outputs match the deterministic oracle.
The recorded-rendered evaluation remains the repeatable acceptance gate.

## Per-case outcomes

| Case | Expected outcome | Live outcome | Result | Main observation |
|---|---|---|---|---|
| TC001 | `ACTION_REQUIRED` / missing document | `ACTION_REQUIRED` / missing document | PASS | Matching policy result |
| TC002 | `ACTION_REQUIRED` / unreadable document | `ACTION_REQUIRED` / unreadable document | PASS | Matching policy result |
| TC003 | `ACTION_REQUIRED` / patient identity conflict | `ACTION_REQUIRED` / patient identity conflict | PASS | Matching policy result |
| TC004 | `DECIDED` / approved ₹1,350 | `ACTION_REQUIRED` | FAIL | Evidence reconciliation required before adjudication |
| TC005 | `DECIDED` / waiting-period rejection | `ACTION_REQUIRED` | FAIL | Evidence reconciliation required |
| TC006 | `DECIDED` / partial dental decision | `ACTION_REQUIRED` | FAIL | Dental procedure evidence required |
| TC007 | `DECIDED` / pre-auth rejection | `ACTION_REQUIRED` | FAIL | Evidence reconciliation required |
| TC008 | `DECIDED` / per-claim-limit rejection | `ACTION_REQUIRED` | FAIL | Evidence reconciliation required |
| TC009 | `IN_REVIEW` / velocity review | `ACTION_REQUIRED` | FAIL | Evidence reconciliation required |
| TC010 | `DECIDED` / approved ₹3,240 | `ACTION_REQUIRED` | FAIL | Evidence reconciliation required |
| TC011 | `DECIDED` / approved ₹4,000 with anomaly failure | `DECIDED` / approved ₹4,000 | FAIL | Decision matched, expected anomaly enrichment was absent |
| TC012 | `DECIDED` / excluded-condition rejection | `ACTION_REQUIRED` | FAIL | Evidence reconciliation required |

## Interpretation

The live run demonstrates that the operational path is real: uploads are
accepted, documents are rendered, Textract observations are persisted, Bedrock
triage/extraction runs, workflow spans are created, and terminal or
`ACTION_REQUIRED` states are reconstructed from PostgreSQL. The three passing
cases also show that live output can reach the expected policy branches.

The nine non-equivalent cases are safe failures or conservative holds, not
silent approvals. The dominant limitation is model-dependent evidence
extraction: when required fields cannot be reconciled to grounded OCR
observations, the policy engine correctly refuses to adjudicate. TC011 reached
the expected approval amount but did not reproduce the oracle's optional anomaly
enrichment failure, which is an observable semantic difference rather than a
financial safety failure.

Live model output is variable. A previous isolated TC004 smoke run reached the
approved decision, while this fresh twelve-case run safely held TC004 for
evidence reconciliation. This is why the deterministic recorded-rendered gate
is the acceptance criterion and this report is the honest live-provider
capability report.

## Observability and artifacts

- Each case records claim ID, duration, trace IDs, span count, and span names in
  the JSON artifact.
- Application and worker JSONL logs are written under the test's temporary log
  directory and the normal local `data/logs/` directory.
- When Phoenix is running and configured, the same workflow spans are exported
  to the `plum-claims-local` project; the test's in-memory exporter is used only
  to make this artifact self-contained.
- The JSON artifact contains no AWS credentials.

## Reproduce

Use the live command above. It is intentionally opt-in and can incur AWS
charges. For the deterministic twelve-case acceptance gate, use:

```bash
uv run pytest \
  tests/integration/test_rendered_evaluation_gate.py::test_all_twelve_cases_pass_the_recorded_rendered_evaluation_gate \
  -q
```
