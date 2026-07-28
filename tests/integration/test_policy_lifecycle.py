import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.application.policy_admin import (
    PolicyActivationBlockedError,
    PolicyAdministrationApplication,
)
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.cli import main as cli_main
from claims_backend.domain.identity import Principal, Role
from claims_backend.domain.policy import (
    FindingCategory,
    PolicyFindingSeverity,
    PolicyVersionStatus,
)
from claims_backend.infrastructure.postgres.policy_repository import (
    PostgresPolicyRepository,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.policy.compiler import COMPILER_VERSION, PolicyCompiler

POLICY_PATH = Path("problem_statement/policy_terms.json")
OVERLAY_PATH = Path("config/policy/assignment-overlay-v1.json")
POLICY_BYTES = POLICY_PATH.read_bytes()
OVERLAY_BYTES = OVERLAY_PATH.read_bytes()
pytestmark = pytest.mark.clean_setup_data


@pytest.mark.asyncio
async def test_persists_versioned_overlay_and_idempotent_compilation(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    setup = SetupDataApplication(PostgresSetupImportRepository(factory))
    source = await setup.import_sources(POLICY_BYTES, source_name=POLICY_PATH.name)
    policies = PolicyAdministrationApplication(
        PostgresPolicyRepository(factory),
        PolicyCompiler(),
    )

    first = await policies.compile(
        source.policy_source_sha256,
        OVERLAY_BYTES,
        overlay_source_name=OVERLAY_PATH.name,
    )
    repeated = await policies.compile(
        source.policy_source_sha256,
        OVERLAY_BYTES,
        overlay_source_name=OVERLAY_PATH.name,
    )
    inspected = await policies.inspect_version(first.policy_version_id)

    assert repeated == first
    assert inspected == first
    assert first.version == 1
    assert first.overlay_id == "assignment-overlay"
    assert first.overlay_version == 1
    assert first.compiler_version == COMPILER_VERSION
    assert first.status is PolicyVersionStatus.COMPILED
    assert first.ir_sha256 is not None
    assert {finding.category for finding in first.findings} >= {
        FindingCategory.SEMANTIC,
        FindingCategory.REFERENTIAL,
        FindingCategory.VOCABULARY,
        FindingCategory.CONTRADICTION,
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_error_findings_block_activation(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    setup = SetupDataApplication(PostgresSetupImportRepository(factory))
    source = await setup.import_sources(POLICY_BYTES, source_name=POLICY_PATH.name)
    policies = PolicyAdministrationApplication(
        PostgresPolicyRepository(factory),
        PolicyCompiler(),
    )
    invalid_overlay = json.loads(OVERLAY_BYTES)
    invalid_overlay["base_policy_sha256"] = "0" * 64
    compiled = await policies.compile(
        source.policy_source_sha256,
        json.dumps(invalid_overlay).encode(),
        overlay_source_name="invalid-overlay.json",
    )

    assert compiled.status is PolicyVersionStatus.INVALID
    assert any(
        finding.category is FindingCategory.REFERENTIAL
        and finding.severity is PolicyFindingSeverity.ERROR
        for finding in compiled.findings
    )
    with pytest.raises(PolicyActivationBlockedError):
        await policies.activate(compiled.policy_version_id, _operator())
    assert await policies.list_activation_events(compiled.policy_version_id) == ()
    await engine.dispose()


@pytest.mark.asyncio
async def test_operator_activation_is_atomic_and_auditable(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    setup = SetupDataApplication(PostgresSetupImportRepository(factory))
    source = await setup.import_sources(POLICY_BYTES, source_name=POLICY_PATH.name)
    policies = PolicyAdministrationApplication(
        PostgresPolicyRepository(factory),
        PolicyCompiler(),
    )
    compiled = await policies.compile(
        source.policy_source_sha256,
        OVERLAY_BYTES,
        overlay_source_name=OVERLAY_PATH.name,
    )

    active = await policies.activate(compiled.policy_version_id, _operator())
    replayed = await policies.activate(compiled.policy_version_id, _operator())
    events = await policies.list_activation_events(compiled.policy_version_id)

    assert active.status is PolicyVersionStatus.ACTIVE
    assert active.activated_by == "operator.local"
    assert active.activated_at is not None
    assert replayed == active
    assert len(events) == 1
    assert events[0].actor == "operator.local"
    assert events[0].from_status is PolicyVersionStatus.COMPILED
    assert events[0].to_status is PolicyVersionStatus.ACTIVE
    assert events[0].ir_sha256 == compiled.ir_sha256
    await engine.dispose()


def _operator() -> Principal:
    return Principal(
        user_id=UUID("00000000-0000-0000-0000-000000000102"),
        username="operator.local",
        roles=frozenset({Role.OPERATOR}),
        member_id=None,
    )


def test_policy_lifecycle_is_available_only_through_auditable_local_cli(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLAIMS_DATABASE_URL", migrated_database_url)
    assert cli_main(["setup", "import", "--policy", str(POLICY_PATH)]) == 0
    imported = json.loads(capsys.readouterr().out)

    assert (
        cli_main(
            [
                "policy",
                "compile",
                "--source-sha",
                imported["policy_source_sha256"],
                "--overlay",
                str(OVERLAY_PATH),
            ]
        )
        == 0
    )
    compiled = json.loads(capsys.readouterr().out)
    assert compiled["status"] == "COMPILED"

    assert (
        cli_main(
            [
                "policy",
                "activate",
                "--policy-version-id",
                compiled["policy_version_id"],
                "--actor",
                "operator.local",
            ]
        )
        == 0
    )
    active = json.loads(capsys.readouterr().out)
    assert active["status"] == "ACTIVE"
    assert active["activated_by"] == "operator.local"

    assert (
        cli_main(
            [
                "policy",
                "findings",
                "--policy-version-id",
                compiled["policy_version_id"],
            ]
        )
        == 0
    )
    findings = json.loads(capsys.readouterr().out)
    assert {finding["category"] for finding in findings} >= {
        "SEMANTIC",
        "REFERENTIAL",
        "VOCABULARY",
        "CONTRADICTION",
    }

    from claims_backend.api.app import create_app
    from claims_backend.config import Settings

    paths = create_app(Settings(database_url=migrated_database_url)).openapi()["paths"]
    assert all("policy" not in path for path in paths)
