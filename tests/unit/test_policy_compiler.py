import json
from hashlib import sha256
from pathlib import Path

from claims_backend.domain.policy import (
    FindingCategory,
    LimitOutcome,
    LimitPrecedence,
    PolicyFindingSeverity,
    PreAuthorizationMode,
)
from claims_backend.policy.compiler import PolicyCompiler

POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()
OVERLAY_BYTES = Path("config/policy/assignment-overlay-v1.json").read_bytes()


def test_compiles_deterministic_assignment_policy_ir() -> None:
    compiler = PolicyCompiler()

    first = compiler.compile(POLICY_BYTES, OVERLAY_BYTES)
    repeated = compiler.compile(POLICY_BYTES, OVERLAY_BYTES)

    assert first.ir is not None
    assert repeated.ir is not None
    assert first.ir_sha256 == repeated.ir_sha256
    assert first.canonical_ir == repeated.canonical_ir
    assert first.source_sha256 == sha256(POLICY_BYTES).hexdigest()
    assert first.overlay_sha256 == sha256(OVERLAY_BYTES).hexdigest()
    assert first.ir.limit_precedence is LimitPrecedence.CATEGORY_OVER_GENERAL
    assert first.ir.limit_exceeded_outcome is LimitOutcome.REJECT
    assert first.ir.category_rules["CONSULTATION"].limit_paise == 500_000
    assert first.ir.pre_authorization_rules["MRI"].mode is PreAuthorizationMode.ABOVE_THRESHOLD
    assert first.ir.pre_authorization_rules["MRI"].threshold_paise == 1_000_000
    assert first.ir.pre_authorization_rules["CT_SCAN"].mode is PreAuthorizationMode.ABOVE_THRESHOLD
    assert first.ir.pre_authorization_rules["CT_SCAN"].threshold_paise == 1_000_000
    assert first.ir.pre_authorization_rules["PET"].mode is PreAuthorizationMode.ALWAYS
    assert first.ir.pre_authorization_rules["PET"].threshold_paise is None
    assert first.ir.waiting_period_rules.initial.days == 30
    assert first.ir.waiting_period_rules.pre_existing.days == 365
    diabetes = first.ir.waiting_period_rules.specific_conditions["diabetes"]
    assert diabetes.days == 90
    assert diabetes.source_pointer == "/waiting_periods/specific_conditions/diabetes"
    assert diabetes.rule_id == "waiting_period.specific_condition.diabetes"
    assert not first.has_errors
    assert FindingCategory.VOCABULARY in {finding.category for finding in first.findings}

    overlay_text = json.dumps(json.loads(OVERLAY_BYTES)).casefold()
    assert "case_id" not in overlay_text
    assert "test_case" not in overlay_text
    assert all(f"tc{number:03}" not in overlay_text for number in range(1, 100))


def test_schema_and_referential_errors_produce_no_policy_ir() -> None:
    compiler = PolicyCompiler()
    malformed = compiler.compile(POLICY_BYTES, b'{"overlay_id":"incomplete"}')
    wrong_base = json.loads(OVERLAY_BYTES)
    wrong_base["base_policy_sha256"] = "0" * 64
    mismatched = compiler.compile(
        POLICY_BYTES,
        json.dumps(wrong_base).encode(),
    )

    assert malformed.ir is None
    assert malformed.has_errors
    assert {finding.category for finding in malformed.findings} == {FindingCategory.SCHEMA}
    assert mismatched.ir is None
    assert any(
        finding.category is FindingCategory.REFERENTIAL
        and finding.severity is PolicyFindingSeverity.ERROR
        and finding.code == "OVERLAY_BASE_POLICY_MISMATCH"
        for finding in mismatched.findings
    )


def test_overlay_cannot_encode_evaluation_case_identifiers() -> None:
    overlay = json.loads(OVERLAY_BYTES)
    overlay["clarifications"]["relationship_aliases"]["CASE"] = "TC008"

    compilation = PolicyCompiler().compile(
        POLICY_BYTES,
        json.dumps(overlay).encode(),
    )

    assert compilation.ir is None
    assert any(
        finding.code == "TEST_IDENTIFIER_FORBIDDEN"
        and finding.category is FindingCategory.SEMANTIC
        and finding.severity is PolicyFindingSeverity.ERROR
        for finding in compilation.findings
    )
