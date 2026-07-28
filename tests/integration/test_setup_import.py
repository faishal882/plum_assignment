import json
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.cli import main as cli_main
from claims_backend.domain.setup_data import FactState
from claims_backend.infrastructure.postgres.models import (
    ClaimHistoryRow,
    ImportFindingRow,
    MemberRow,
    MemberVersionRow,
    PolicySourceRow,
    SetupImportRow,
    UtilizationSnapshotRow,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)

POLICY_PATH = Path("problem_statement/policy_terms.json")
POLICY_BYTES = POLICY_PATH.read_bytes()


@pytest.mark.asyncio
async def test_imports_exact_policy_source_and_is_idempotent(
    migrated_database_url: str,
) -> None:
    policy_bytes = POLICY_BYTES
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = SetupDataApplication(PostgresSetupImportRepository(session_factory))

    first = await application.import_sources(policy_bytes, source_name=POLICY_PATH.name)
    repeated = await application.import_sources(policy_bytes, source_name=POLICY_PATH.name)

    assert repeated == first
    assert first.policy_id == "PLUM_GHI_2024"
    assert first.policy_source_sha256 == sha256(policy_bytes).hexdigest()
    assert first.member_versions_created == 12
    async with session_factory() as session:
        source = (await session.scalars(select(PolicySourceRow))).one()
        assert source.source_bytes == policy_bytes
        assert await session.scalar(select(func.count()).select_from(PolicySourceRow)) == 1
        assert await session.scalar(select(func.count()).select_from(SetupImportRow)) == 1
        assert await session.scalar(select(func.count()).select_from(MemberVersionRow)) == 12
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_policy_source_mutation(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = SetupDataApplication(PostgresSetupImportRepository(session_factory))
    receipt = await application.import_sources(POLICY_BYTES, source_name=POLICY_PATH.name)

    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    """
                    UPDATE policy_sources
                    SET source_bytes = :changed
                    WHERE source_sha256 = :source_sha256
                    """
                ),
                {
                    "changed": b"changed",
                    "source_sha256": receipt.policy_source_sha256,
                },
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_versions_members_and_reports_missing_relationships(
    migrated_database_url: str,
) -> None:
    policy_bytes = POLICY_BYTES
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = SetupDataApplication(PostgresSetupImportRepository(session_factory))

    receipt = await application.import_sources(policy_bytes, source_name=POLICY_PATH.name)
    member = await application.inspect_member("PLUM_GHI_2024", "DEP001")

    assert member is not None
    assert member.version == 1
    assert member.primary_member_id == "EMP001"
    assert member.source_sha256 == receipt.policy_source_sha256
    assert member.utilization_state is FactState.UNKNOWN
    assert member.used_paise is None
    assert {
        (finding.code, finding.subject_id)
        for finding in receipt.findings
        if finding.code == "MISSING_DEPENDENT_RECORD"
    } == {
        ("MISSING_DEPENDENT_RECORD", "DEP003"),
        ("MISSING_DEPENDENT_RECORD", "DEP004"),
        ("MISSING_DEPENDENT_RECORD", "DEP005"),
        ("MISSING_DEPENDENT_RECORD", "DEP006"),
    }
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MemberRow)) == 12
        assert await session.scalar(select(func.count()).select_from(ImportFindingRow)) == 4
    await engine.dispose()


@pytest.mark.asyncio
async def test_imports_history_and_utilization_without_inventing_missing_facts(
    migrated_database_url: str,
) -> None:
    member_data = {
        "policy_id": "PLUM_GHI_2024",
        "as_of_date": "2024-11-03",
        "claim_history": [
            {
                "history_claim_id": "HIST-001",
                "member_id": "EMP008",
                "treatment_date": "2024-10-30",
                "amount": "1200.50",
                "currency": "INR",
                "provider": "City Clinic",
            }
        ],
        "utilization": [
            {
                "member_id": "EMP001",
                "period_start": "2024-04-01",
                "period_end": "2025-03-31",
                "used_amount": "5000.00",
                "currency": "INR",
                "as_of_date": "2024-11-01",
            }
        ],
    }
    member_data_bytes = json.dumps(member_data, separators=(",", ":")).encode()
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = SetupDataApplication(PostgresSetupImportRepository(session_factory))

    receipt = await application.import_sources(
        POLICY_BYTES,
        source_name=POLICY_PATH.name,
        member_data_bytes=member_data_bytes,
        member_data_source_name="member_data.json",
    )
    known = await application.inspect_member("PLUM_GHI_2024", "EMP001")
    unknown = await application.inspect_member("PLUM_GHI_2024", "EMP002")

    assert receipt.history_records_created == 1
    assert receipt.utilization_records_created == 1
    assert known is not None
    assert known.utilization_state is FactState.KNOWN
    assert known.used_paise == 500_000
    assert unknown is not None
    assert unknown.utilization_state is FactState.UNKNOWN
    assert unknown.used_paise is None
    async with session_factory() as session:
        history = (await session.scalars(select(ClaimHistoryRow))).one()
        utilization = (await session.scalars(select(UtilizationSnapshotRow))).one()
        assert history.amount_paise == 120_050
        assert utilization.used_paise == 500_000
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_member_data_relationship_becomes_a_finding(
    migrated_database_url: str,
) -> None:
    member_data_bytes = json.dumps(
        {
            "policy_id": "PLUM_GHI_2024",
            "as_of_date": "2024-11-03",
            "claim_history": [
                {
                    "history_claim_id": "UNKNOWN-1",
                    "member_id": "NOT-A-MEMBER",
                    "treatment_date": "2024-10-30",
                    "amount": "100.00",
                    "currency": "INR",
                }
            ],
            "utilization": [],
        }
    ).encode()
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = SetupDataApplication(PostgresSetupImportRepository(session_factory))

    receipt = await application.import_sources(
        POLICY_BYTES,
        source_name=POLICY_PATH.name,
        member_data_bytes=member_data_bytes,
        member_data_source_name="member-data.json",
    )

    assert receipt.history_records_created == 0
    assert any(
        finding.code == "UNKNOWN_MEMBER_REFERENCE"
        and finding.subject_id == "NOT-A-MEMBER"
        for finding in receipt.findings
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_changed_policy_source_creates_new_member_versions(
    migrated_database_url: str,
) -> None:
    source = json.loads(POLICY_BYTES)
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = SetupDataApplication(PostgresSetupImportRepository(session_factory))

    first = await application.import_sources(
        json.dumps(source, sort_keys=True).encode(),
        source_name="policy-v1.json",
    )
    source["members"][0]["name"] = "Rajesh Kumar Updated"
    second = await application.import_sources(
        json.dumps(source, sort_keys=True).encode(),
        source_name="policy-v2.json",
    )
    current = await application.inspect_member("PLUM_GHI_2024", "EMP001")

    assert first.import_id != second.import_id
    assert current is not None
    assert current.version == 2
    assert current.name == "Rajesh Kumar Updated"
    async with session_factory() as session:
        versions = (
                await session.scalars(
                    select(MemberVersionRow)
                    .join(MemberRow, MemberRow.id == MemberVersionRow.member_id)
                .where(MemberRow.external_member_id == "EMP001")
                .order_by(MemberVersionRow.version)
            )
        ).all()
        assert [version.version for version in versions] == [1, 2]
        assert versions[0].source_pointer == "/members/0"
        assert versions[1].source_pointer == "/members/0"
    await engine.dispose()


def test_local_cli_imports_and_inspects_without_http_routes(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLAIMS_DATABASE_URL", migrated_database_url)

    assert cli_main(["setup", "import", "--policy", str(POLICY_PATH)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["policy_id"] == "PLUM_GHI_2024"
    assert imported["member_versions_created"] == 12

    assert (
        cli_main(
            [
                "setup",
                "inspect-member",
                "--policy-id",
                "PLUM_GHI_2024",
                "--member-id",
                "DEP001",
            ]
        )
        == 0
    )
    member = json.loads(capsys.readouterr().out)
    assert member["primary_member_id"] == "EMP001"
    assert member["utilization_state"] == "UNKNOWN"

    assert (
        cli_main(
            ["setup", "inspect-import", "--import-id", imported["import_id"]]
        )
        == 0
    )
    inspected = json.loads(capsys.readouterr().out)
    assert inspected == imported

    # The setup importer remains a local administrative boundary.
    from claims_backend.api.app import create_app
    from claims_backend.config import Settings

    paths = create_app(Settings(database_url=migrated_database_url)).openapi()["paths"]
    assert all("policy" not in path and "setup" not in path for path in paths)
