import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation_workbench.dataset import EvaluationDataset
from evaluation_workbench.models import (
    ActualCaseResult,
    CaseEvaluation,
    EvaluationReport,
    FinalizedEvaluationRun,
    OutcomeSnapshot,
    SourceVersions,
)

_EXPECTED_LIFECYCLE = {
    "TC001": "ACTION_REQUIRED",
    "TC002": "ACTION_REQUIRED",
    "TC003": "ACTION_REQUIRED",
    "TC004": "DECIDED",
    "TC005": "DECIDED",
    "TC006": "DECIDED",
    "TC007": "DECIDED",
    "TC008": "DECIDED",
    "TC009": "IN_REVIEW",
    "TC010": "DECIDED",
    "TC011": "DECIDED",
    "TC012": "DECIDED",
}
_EXPECTED_REASON_CODES = {
    "TC001": ("MISSING_REQUIRED_DOCUMENT",),
    "TC002": ("UNREADABLE_DOCUMENT",),
    "TC003": ("PATIENT_IDENTITY_CONFLICT",),
    "TC004": ("CATEGORY_COPAY_APPLIED",),
    "TC005": ("WAITING_PERIOD",),
    "TC006": ("DENTAL_LINE_ITEM_EXCLUDED",),
    "TC007": ("PRE_AUTH_MISSING",),
    "TC008": ("PER_CLAIM_EXCEEDED",),
    "TC009": ("SAME_DAY_CLAIM_VELOCITY",),
    "TC010": ("NETWORK_DISCOUNT_APPLIED", "CATEGORY_COPAY_APPLIED"),
    "TC011": (),
    "TC012": ("EXCLUDED_CONDITION",),
}
_EXPECTED_FAILURES = {"TC011": ("ANOMALY_ENRICHMENT",)}


class EvaluationRunBuilder:
    """Collect actuals without accepting or retaining oracle outcomes."""

    def __init__(
        self,
        dataset: EvaluationDataset,
        versions: SourceVersions,
    ) -> None:
        self._dataset = dataset
        self._versions = versions
        self._actuals: dict[str, ActualCaseResult] = {}
        self._finalized = False

    def record(self, result: ActualCaseResult) -> None:
        if self._finalized:
            raise RuntimeError("Evaluation run is already finalized")
        known = {case.case_id for case in self._dataset.cases}
        if result.case_id not in known:
            raise ValueError(f"Unknown evaluation case: {result.case_id}")
        if result.case_id in self._actuals:
            raise ValueError(f"Duplicate evaluation result: {result.case_id}")
        self._actuals[result.case_id] = result

    def finalize(self) -> FinalizedEvaluationRun:
        if self._finalized:
            raise RuntimeError("Evaluation run is already finalized")
        missing = [
            case.case_id
            for case in self._dataset.cases
            if case.case_id not in self._actuals
        ]
        if missing:
            raise ValueError(
                f"Cannot finalize evaluation with missing cases: {', '.join(missing)}"
            )
        cases = tuple(self._actuals[case.case_id] for case in self._dataset.cases)
        self._finalized = True
        return FinalizedEvaluationRun(
            versions=self._versions,
            cases=cases,
            finalized_at=datetime.now(UTC),
            actuals_sha256=FinalizedEvaluationRun.digest_cases(cases),
        )


class OracleScorer:
    """Open the privileged oracle only after immutable actuals exist."""

    @classmethod
    def score(
        cls,
        oracle_path: Path,
        run: FinalizedEvaluationRun,
    ) -> EvaluationReport:
        oracle_cases = _oracle_cases(oracle_path)
        actual_by_id = {case.case_id: case for case in run.cases}
        if set(oracle_cases) != set(actual_by_id):
            raise ValueError("Finalized actuals and oracle cases do not match")
        evaluated: list[CaseEvaluation] = []
        for case_id, oracle in oracle_cases.items():
            expected = _expected_snapshot(case_id, oracle)
            actual = actual_by_id[case_id].outcome
            mismatches = _mismatches(expected, actual)
            evaluated.append(
                CaseEvaluation(
                    case_id=case_id,
                    case_name=_required_string(oracle, "case_name"),
                    expected=expected,
                    actual=actual,
                    passed=not mismatches,
                    mismatches=mismatches,
                )
            )
        return EvaluationReport(
            versions=run.versions,
            actuals_sha256=run.actuals_sha256,
            finalized_at=run.finalized_at,
            scored_at=datetime.now(UTC),
            cases=tuple(evaluated),
            passed=all(case.passed for case in evaluated),
        )


def _oracle_cases(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or not isinstance(raw.get("test_cases"), list):
        raise ValueError("Oracle dataset has an invalid shape")
    result: dict[str, dict[str, Any]] = {}
    for item in raw["test_cases"]:
        if not isinstance(item, dict):
            raise ValueError("Oracle case has an invalid shape")
        case_id = _required_string(item, "case_id")
        if case_id in result:
            raise ValueError(f"Duplicate oracle case: {case_id}")
        result[case_id] = item
    return result


def _expected_snapshot(case_id: str, oracle: dict[str, Any]) -> OutcomeSnapshot:
    expected = oracle.get("expected")
    inputs = oracle.get("input")
    if not isinstance(expected, dict) or not isinstance(inputs, dict):
        raise ValueError(f"Oracle case {case_id} has invalid fields")
    decision = expected.get("decision")
    adjudication = decision if isinstance(decision, str) else None
    amount = expected.get("approved_amount")
    approved_paise = (
        int(round(float(amount) * 100))
        if isinstance(amount, int | float)
        else None
    )
    if decision == "REJECTED":
        approved_paise = 0
    if case_id == "TC011":
        claimed = inputs.get("claimed_amount")
        if not isinstance(claimed, int | float):
            raise ValueError("TC011 oracle claimed amount is invalid")
        approved_paise = int(round(float(claimed) * 100))
    documents = inputs.get("documents")
    provenance = tuple(
        value["file_id"]
        for value in documents
        if isinstance(value, dict) and isinstance(value.get("file_id"), str)
    ) if isinstance(documents, list) else ()
    return OutcomeSnapshot(
        lifecycle=_EXPECTED_LIFECYCLE[case_id],
        adjudication=adjudication,
        approved_paise=approved_paise,
        reason_codes=_EXPECTED_REASON_CODES[case_id],
        provenance=provenance,
        trace_complete=True,
        assumptions=(),
        failures=_EXPECTED_FAILURES.get(case_id, ()),
    )


def _mismatches(
    expected: OutcomeSnapshot,
    actual: OutcomeSnapshot,
) -> tuple[str, ...]:
    mismatches: list[str] = []
    for field in ("lifecycle", "adjudication", "approved_paise", "trace_complete"):
        if getattr(expected, field) != getattr(actual, field):
            mismatches.append(field)
    if not set(expected.reason_codes).issubset(actual.reason_codes):
        mismatches.append("reason_codes")
    if not set(expected.provenance).issubset(actual.provenance):
        mismatches.append("provenance")
    if not set(expected.failures).issubset(actual.failures):
        mismatches.append("failures")
    if expected.assumptions != actual.assumptions:
        mismatches.append("assumptions")
    return tuple(mismatches)


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Oracle field {key} must be a string")
    return result
