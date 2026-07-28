import asyncio
from collections.abc import Iterator
from os import environ
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.application.policy_admin import PolicyAdministrationApplication
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.domain.identity import Principal, Role
from claims_backend.infrastructure.postgres.policy_repository import (
    PostgresPolicyRepository,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.policy.compiler import PolicyCompiler

_POLICY_PATH = Path("problem_statement/policy_terms.json")
_OVERLAY_PATH = Path("config/policy/assignment-overlay-v1.json")
_POLICY_BYTES = _POLICY_PATH.read_bytes()
_OVERLAY_BYTES = _OVERLAY_PATH.read_bytes()


@pytest.fixture(scope="session")
def postgres_database_url() -> Iterator[str]:
    database_url = environ.get(
        "CLAIMS_TEST_DATABASE_URL",
        "postgresql+psycopg://claims:claims@127.0.0.1:55432/claims",
    )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    _reset_database(database_url, include_setup=True)
    yield database_url


@pytest.fixture
def migrated_database_url(
    postgres_database_url: str,
    request: pytest.FixtureRequest,
) -> Iterator[str]:
    clean_setup = request.node.get_closest_marker("clean_setup_data") is not None
    _reset_database(postgres_database_url, include_setup=clean_setup)
    if not clean_setup:
        asyncio.run(_ensure_active_policy(postgres_database_url))
    yield postgres_database_url


def _reset_database(database_url: str, *, include_setup: bool) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        setup_tables = (
            ", member_utilization_snapshots, member_claim_history, "
            "policy_activation_events, policy_findings, policy_versions, "
            "policy_overlays, import_findings, member_versions, members, "
            "setup_imports, policy_sources"
            if include_setup
            else ""
        )
        connection.execute(
            text(
                "TRUNCATE TABLE rule_results, decision_records, casefiles, "
                "processing_fixtures, workflow_effects, workflow_runs, claim_actions, "
                "idempotency_keys, document_versions, documents, claim_work_items, "
                f"audit_events, claim_versions, claims{setup_tables} "
                "RESTART IDENTITY CASCADE"
            )
        )
        connection.execute(
            text(
                """
                UPDATE users
                SET username = CASE id
                    WHEN '00000000-0000-0000-0000-000000000001' THEN 'member.emp001'
                    WHEN '00000000-0000-0000-0000-000000000002' THEN 'member.emp002'
                    WHEN '00000000-0000-0000-0000-000000000101' THEN 'reviewer.local'
                    WHEN '00000000-0000-0000-0000-000000000102' THEN 'operator.local'
                END,
                normalized_username = CASE id
                    WHEN '00000000-0000-0000-0000-000000000001' THEN 'member.emp001'
                    WHEN '00000000-0000-0000-0000-000000000002' THEN 'member.emp002'
                    WHEN '00000000-0000-0000-0000-000000000101' THEN 'reviewer.local'
                    WHEN '00000000-0000-0000-0000-000000000102' THEN 'operator.local'
                END
                WHERE id IN (
                    '00000000-0000-0000-0000-000000000001',
                    '00000000-0000-0000-0000-000000000002',
                    '00000000-0000-0000-0000-000000000101',
                    '00000000-0000-0000-0000-000000000102'
                )
                """
            )
        )
    engine.dispose()


async def _ensure_active_policy(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        setup = SetupDataApplication(PostgresSetupImportRepository(factory))
        imported = await setup.import_sources(
            _POLICY_BYTES,
            source_name=_POLICY_PATH.name,
        )
        policies = PolicyAdministrationApplication(
            PostgresPolicyRepository(factory),
            PolicyCompiler(),
        )
        compiled = await policies.compile(
            imported.policy_source_sha256,
            _OVERLAY_BYTES,
            overlay_source_name=_OVERLAY_PATH.name,
        )
        await policies.activate(
            compiled.policy_version_id,
            Principal(
                user_id=UUID("00000000-0000-0000-0000-000000000102"),
                username="operator.local",
                roles=frozenset({Role.OPERATOR}),
                member_id=None,
            ),
        )
    finally:
        await engine.dispose()
