import json
import socket
from pathlib import Path

import pytest

from evaluation_workbench import (
    ActualCaseResult,
    EvaluationRunBuilder,
    ExecutionProfile,
    ExternalNetworkDenied,
    OracleScorer,
    OutcomeSnapshot,
    ProfileAuthorizationError,
    SourceVersions,
    execution_guard,
    load_evaluation_inputs,
)

_DATASET_PATH = Path("problem_statement/test_cases.json")
_DECISIONS = {
    "TC001": ("ACTION_REQUIRED", None, None),
    "TC002": ("ACTION_REQUIRED", None, None),
    "TC003": ("ACTION_REQUIRED", None, None),
    "TC004": ("DECIDED", "APPROVED", 135_000),
    "TC005": ("DECIDED", "REJECTED", 0),
    "TC006": ("DECIDED", "PARTIAL", 800_000),
    "TC007": ("DECIDED", "REJECTED", 0),
    "TC008": ("DECIDED", "REJECTED", 0),
    "TC009": ("IN_REVIEW", "MANUAL_REVIEW", None),
    "TC010": ("DECIDED", "APPROVED", 324_000),
    "TC011": ("DECIDED", "APPROVED", 400_000),
    "TC012": ("DECIDED", "REJECTED", 0),
}
_REASONS = {
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


def test_public_dataset_loader_discards_oracle_fields() -> None:
    dataset = load_evaluation_inputs(_DATASET_PATH)

    serialized = json.dumps(dataset.model_dump(mode="json"))
    assert len(dataset.cases) == 12
    assert '"expected"' not in serialized
    assert "system_must" not in serialized
    assert not hasattr(dataset.cases[0], "expected")


def test_actuals_are_finalized_before_oracle_scoring() -> None:
    dataset = load_evaluation_inputs(_DATASET_PATH)
    builder = EvaluationRunBuilder(dataset, _versions())
    source = json.loads(_DATASET_PATH.read_text())
    documents = {
        case["case_id"]: tuple(document["file_id"] for document in case["input"]["documents"])
        for case in source["test_cases"]
    }
    for case in dataset.cases:
        lifecycle, adjudication, amount = _DECISIONS[case.case_id]
        builder.record(
            ActualCaseResult(
                case_id=case.case_id,
                outcome=OutcomeSnapshot(
                    lifecycle=lifecycle,
                    adjudication=adjudication,
                    approved_paise=amount,
                    reason_codes=_REASONS[case.case_id],
                    provenance=documents[case.case_id],
                    trace_complete=True,
                    assumptions=(),
                    failures=(
                        ("ANOMALY_ENRICHMENT",) if case.case_id == "TC011" else ()
                    ),
                ),
            )
        )

    run = builder.finalize()
    report = OracleScorer.score(_DATASET_PATH, run)

    assert report.passed is True
    assert len(report.cases) == 12
    assert report.actuals_sha256 == run.actuals_sha256
    with pytest.raises(RuntimeError, match="already finalized"):
        builder.record(run.cases[0])


def test_structured_profile_is_explicitly_labeled_as_ocr_bypassed() -> None:
    with pytest.raises(ValueError, match="label OCR as BYPASSED"):
        _versions(
            profile=ExecutionProfile.STRUCTURED_COMPONENT,
            ocr_mode="ENABLED",
        )

    versions = _versions(profile=ExecutionProfile.STRUCTURED_COMPONENT)
    assert versions.ocr_mode == "BYPASSED"


def test_recorded_profiles_deny_external_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected: list[object] = []

    def fake_connect(_: socket.socket, address: object) -> None:
        connected.append(address)

    monkeypatch.setattr(socket.socket, "connect", fake_connect)
    client = socket.socket()
    with execution_guard(ExecutionProfile.RENDERED_RECORDED, synthetic_only=True):
        client.connect(("127.0.0.1", 55432))
        with pytest.raises(ExternalNetworkDenied, match="bedrock"):
            client.connect(("bedrock-runtime.us-west-2.amazonaws.com", 443))
    client.close()
    assert connected == [("127.0.0.1", 55432)]


def test_live_profile_requires_both_explicit_selector_and_synthetic_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLAIMS_RUN_LIVE_AWS", raising=False)
    with pytest.raises(ProfileAuthorizationError, match="CLAIMS_RUN_LIVE_AWS"):
        with execution_guard(ExecutionProfile.LIVE_INTELLIGENCE, synthetic_only=True):
            pass

    monkeypatch.setenv("CLAIMS_RUN_LIVE_AWS", "1")
    with pytest.raises(ProfileAuthorizationError, match="synthetic"):
        with execution_guard(ExecutionProfile.LIVE_INTELLIGENCE, synthetic_only=False):
            pass
    with execution_guard(ExecutionProfile.LIVE_INTELLIGENCE, synthetic_only=True):
        pass


def _versions(
    *,
    profile: ExecutionProfile = ExecutionProfile.RENDERED_RECORDED,
    ocr_mode: str | None = None,
) -> SourceVersions:
    return SourceVersions(
        dataset_version="1.0",
        dataset_sha256="a" * 64,
        policy_version="PLUM_GHI_2024:1",
        policy_sha256="b" * 64,
        overlay_version="policy-overlay-v1",
        overlay_sha256="c" * 64,
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
        prompt_versions=(
            "fast-triage-prompt-v1",
            "complex-extraction-prompt-v2",
        ),
        schema_versions=("triage-output-v2", "complex-extraction-v1"),
        graph_version="claim-processing-v7",
        execution_profile=profile,
        ocr_mode=(
            ocr_mode
            if ocr_mode is not None
            else ("ENABLED" if profile.uses_ocr else "BYPASSED")
        ),
    )
