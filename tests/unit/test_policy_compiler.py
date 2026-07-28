import json
from hashlib import sha256
from pathlib import Path

from claims_backend.domain.policy import (
    FindingCategory,
    LimitOutcome,
    LimitPrecedence,
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
    assert not first.has_errors
    assert FindingCategory.VOCABULARY in {finding.category for finding in first.findings}

    overlay_text = json.dumps(json.loads(OVERLAY_BYTES)).casefold()
    assert "case_id" not in overlay_text
    assert "test_case" not in overlay_text
    assert all(f"tc{number:03}" not in overlay_text for number in range(1, 100))
