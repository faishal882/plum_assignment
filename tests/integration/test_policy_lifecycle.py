from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.application.policy_admin import PolicyAdministrationApplication
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.domain.policy import FindingCategory, PolicyVersionStatus
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
