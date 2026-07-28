import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from evaluation_workbench.models import EvaluationCaseInput


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    description: str
    cases: tuple[EvaluationCaseInput, ...]


def load_evaluation_inputs(path: Path) -> EvaluationDataset:
    """Load public inputs without retaining any expected/oracle fields."""
    raw = _mapping(json.loads(path.read_text()))
    raw_cases = raw.get("test_cases")
    if not isinstance(raw_cases, list):
        raise ValueError("Evaluation dataset must contain a test_cases list")
    cases: list[EvaluationCaseInput] = []
    for value in raw_cases:
        case = _mapping(value)
        cases.append(
            EvaluationCaseInput(
                case_id=_string(case, "case_id"),
                case_name=_string(case, "case_name"),
                description=_string(case, "description"),
                submission=dict(_mapping(case.get("input"))),
            )
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Evaluation dataset contains duplicate case IDs")
    return EvaluationDataset(
        version=_string(raw, "version"),
        description=_string(raw, "description"),
        cases=tuple(cases),
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Evaluation dataset contains an invalid object")
    return value


def _string(value: dict[str, Any], key: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field:
        raise ValueError(f"Evaluation dataset field {key} must be a string")
    return field
