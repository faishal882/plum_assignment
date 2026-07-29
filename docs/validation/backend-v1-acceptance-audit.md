# Backend v1 Acceptance Audit

This audit records the current evidence for each implementation phase in
`plans/backend-v1-operational-completion.md`. It is intentionally evidence-first: the detailed
checkboxes in that historical planning document are not used as test results.

## Verified evidence

| Phase | Scope | Current evidence |
|---|---|---|
| 1 | Runtime profiles and construction | `tests/unit/test_runtime_composition.py`, `tests/integration/test_execution_contract.py` |
| 2 | Public no-fixture action path | `tests/integration/test_document_role_gate.py` TC001–TC003 gates |
| 3 | Worker loop, health, frontend contract | `tests/integration/test_document_role_gate.py`, `tests/integration/test_work_scheduler.py`, [`docs/frontend-integration.md`](../frontend-integration.md) |
| 4 | Lease safety and recovery | `tests/integration/test_work_scheduler.py`, `tests/integration/test_workflow_recovery.py` |
| 5 | Failure lifecycle | `tests/unit/test_failure_policy.py`, `tests/integration/test_document_role_gate.py` |
| 6 | Clean no-fixture decision | `tests/integration/test_document_role_gate.py` TC004 gate |
| 7 | Corrective role/identity paths | `tests/integration/test_document_role_gate.py` TC001–TC003 gates |
| 8 | Deterministic rejection paths | `tests/integration/test_document_role_gate.py` TC005, TC007, TC008, TC012 gates |
| 9 | Partial/adjustment paths | `tests/integration/test_document_role_gate.py` TC006 and TC010 gates |
| 10 | Review/degradation paths | `tests/integration/test_document_role_gate.py` TC009 and TC011 gates |
| 11 | Privacy-safe observability | `tests/integration/test_workflow_observability.py`, `tests/integration/test_rendered_evaluation_gate.py` |
| 12 | Explicit live AWS flow | `tests/live/test_textract_live.py`, `tests/live/test_bedrock_live.py`, `tests/live/test_live_worker_tc004.py` |
| 13 | Proof artifacts and quality gates | [`artifacts/backend-v1/`](../../artifacts/backend-v1/), [`backend-v1-completion.md`](backend-v1-completion.md), `uv run pytest -q` |

## Current commands and results

- Cost-free default verification: `CLAIMS_RUN_LIVE_AWS=0 uv run pytest -q` → **235 passed, 4 live-AWS skipped** in 102.81s.
- Latest explicitly authorized live verification: `CLAIMS_RUN_LIVE_AWS=1 uv run pytest -q` → **239 passed, 0 skipped** in 157.78s.
- Recorded acceptance: `uv run pytest tests/integration/test_rendered_evaluation_gate.py::test_all_twelve_cases_pass_the_recorded_rendered_evaluation_gate -q` → passed.
- Explicit live provider smokes: Textract and Bedrock → **2 passed** in 3.94s.
- Explicit live durable claim: `tests/live/test_live_worker_tc004.py` → passed in 46.25s.
- Static gates: `ruff format --check .`, `ruff check .`, `mypy`, `alembic check`, and
  `git diff --check` → passed at the final audit.

## Evidence limits

- The recorded gate proves the supported local operational path; it is not a measure of arbitrary
  real-document OCR/model accuracy.
- The live gate is synthetic, explicitly paid-AWS authorized, and covers TC004 only.
- Authentication, deployment, and broad live-provider coverage are outside Backend v1 scope.
