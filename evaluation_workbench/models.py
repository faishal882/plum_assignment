import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExecutionProfile(StrEnum):
    UNIT = "UNIT"
    STRUCTURED_COMPONENT = "STRUCTURED_COMPONENT"
    RENDERED_RECORDED = "RENDERED_RECORDED"
    LIVE_INTELLIGENCE = "LIVE_INTELLIGENCE"

    @property
    def uses_ocr(self) -> bool:
        return self in {
            ExecutionProfile.RENDERED_RECORDED,
            ExecutionProfile.LIVE_INTELLIGENCE,
        }

    @property
    def permits_external_network(self) -> bool:
        return self is ExecutionProfile.LIVE_INTELLIGENCE


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationCaseInput(_FrozenModel):
    case_id: str = Field(pattern=r"^TC\d{3}$")
    case_name: str
    description: str
    submission: dict[str, Any]


class SourceVersions(_FrozenModel):
    report_schema: str = "claims-evaluation-report-v1"
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    overlay_version: str
    overlay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str
    prompt_versions: tuple[str, ...]
    schema_versions: tuple[str, ...]
    graph_version: str
    execution_profile: ExecutionProfile
    ocr_mode: str

    @model_validator(mode="after")
    def enforce_profile_label(self) -> "SourceVersions":
        expected = "ENABLED" if self.execution_profile.uses_ocr else "BYPASSED"
        if self.ocr_mode != expected:
            raise ValueError(f"{self.execution_profile.value} must label OCR as {expected}")
        return self


class OutcomeSnapshot(_FrozenModel):
    lifecycle: str
    adjudication: str | None
    approved_paise: int | None = Field(ge=0)
    reason_codes: tuple[str, ...]
    provenance: tuple[str, ...]
    trace_complete: bool
    assumptions: tuple[str, ...]
    failures: tuple[str, ...]


class ActualCaseResult(_FrozenModel):
    case_id: str = Field(pattern=r"^TC\d{3}$")
    outcome: OutcomeSnapshot


class FinalizedEvaluationRun(_FrozenModel):
    versions: SourceVersions
    cases: tuple[ActualCaseResult, ...]
    finalized_at: datetime
    actuals_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_unique_cases(self) -> "FinalizedEvaluationRun":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("A finalized run cannot contain duplicate case IDs")
        return self

    @classmethod
    def digest_cases(cls, cases: tuple[ActualCaseResult, ...]) -> str:
        payload = json.dumps(
            [case.model_dump(mode="json") for case in cases],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return sha256(payload).hexdigest()


class CaseEvaluation(_FrozenModel):
    case_id: str
    case_name: str
    expected: OutcomeSnapshot
    actual: OutcomeSnapshot
    passed: bool
    mismatches: tuple[str, ...]


class EvaluationReport(_FrozenModel):
    versions: SourceVersions
    actuals_sha256: str
    finalized_at: datetime
    scored_at: datetime
    cases: tuple[CaseEvaluation, ...]
    passed: bool

    @model_validator(mode="after")
    def derive_consistent_gate(self) -> "EvaluationReport":
        if self.passed != all(case.passed for case in self.cases):
            raise ValueError("Report gate does not match its case results")
        return self
