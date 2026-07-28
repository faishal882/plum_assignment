import json
from datetime import date
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.application.claims import ClaimsApplication
from claims_backend.config import Settings
from claims_backend.domain.claims import (
    ClaimCategory,
    DocumentManifestItem,
    SubmitClaim,
)
from claims_backend.domain.identity import Principal, Role
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    ClaimRow,
    ClaimVersionRow,
    ClaimWorkItemRow,
    UserRow,
)
from claims_backend.infrastructure.postgres.repositories import PostgresClaimsRepository


@pytest.mark.asyncio
async def test_submission_persists_the_complete_initial_claim_unit(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        application = ClaimsApplication(PostgresClaimsRepository(session))
        claim = await application.submit(_submission(), _principal())

    async with session_factory() as session:
        claim_count = await session.scalar(select(func.count()).select_from(ClaimRow))
        version_count = await session.scalar(select(func.count()).select_from(ClaimVersionRow))
        work_count = await session.scalar(select(func.count()).select_from(ClaimWorkItemRow))
        audit_events = (
            (
                await session.execute(
                    select(AuditEventRow)
                    .where(AuditEventRow.claim_id == claim.id)
                    .order_by(AuditEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )

    assert claim_count == 1
    assert version_count == 1
    assert work_count == 1
    assert [(event.sequence, event.event_type) for event in audit_events] == [
        (1, "CLAIM_RECEIVED"),
        (2, "CLAIM_QUEUED"),
    ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_username_rename_preserves_claim_ownership_and_audit_snapshot(
    migrated_database_url: str,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url))
    transport = ASGITransport(app=app)
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", b"%PDF-1.4 placeholder", "application/pdf")},
        )
        claim_id = submitted.json()["claim_id"]

        async with app.state.session_factory.begin() as session:
            await session.execute(
                update(UserRow)
                .where(UserRow.id == UUID("00000000-0000-0000-0000-000000000001"))
                .values(
                    username="renamed.emp001",
                    normalized_username="renamed.emp001",
                )
            )

        renamed_access = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "renamed.emp001"},
        )
        old_access = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert submitted.status_code == 202
    assert renamed_access.status_code == 200
    assert old_access.status_code == 401

    async with app.state.session_factory() as session:
        claim = await session.scalar(select(ClaimRow).where(ClaimRow.id == claim_id))
        events = (
            (
                await session.scalars(
                    select(AuditEventRow)
                    .where(AuditEventRow.claim_id == claim_id)
                    .order_by(AuditEventRow.sequence)
                )
            )
            .unique()
            .all()
        )

    assert claim is not None
    assert claim.owner_user_id == UUID("00000000-0000-0000-0000-000000000001")
    assert claim.owner_username_snapshot == "member.emp001"
    assert {event.actor_username_snapshot for event in events} == {"member.emp001"}
    assert {event.actor_user_id for event in events} == {claim.owner_user_id}

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_invalid_metadata_creates_no_claim_or_work(
    migrated_database_url: str,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={
                "metadata": json.dumps(
                    {
                        "member_id": "EMP001",
                        "policy_id": "PLUM_GHI_2024",
                        "claim_category": "CONSULTATION",
                        "treatment_date": "2024-11-01",
                        "claimed_amount": "-1.00",
                        "currency": "INR",
                        "documents": [
                            {"upload_index": 0, "client_document_id": "doc-prescription"}
                        ],
                    }
                )
            },
            files={"files": ("prescription.pdf", b"%PDF-1.4 placeholder", "application/pdf")},
        )

    assert response.status_code == 422

    async with app.state.session_factory() as session:
        claim_count = await session.scalar(select(func.count()).select_from(ClaimRow))
        work_count = await session.scalar(select(func.count()).select_from(ClaimWorkItemRow))

    assert claim_count == 0
    assert work_count == 0

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_work_item_failure_rolls_back_the_entire_submission(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE FUNCTION reject_claim_work_item() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'injected work-item failure'
                        USING ERRCODE = 'integrity_constraint_violation';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TRIGGER reject_claim_work_item_insert
                BEFORE INSERT ON claim_work_items
                FOR EACH ROW EXECUTE FUNCTION reject_claim_work_item()
                """
            )
        )

    try:
        async with session_factory() as session:
            application = ClaimsApplication(PostgresClaimsRepository(session))
            with pytest.raises(IntegrityError):
                await application.submit(_submission(), _principal())
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DROP TRIGGER reject_claim_work_item_insert ON claim_work_items")
            )
            await connection.execute(text("DROP FUNCTION reject_claim_work_item()"))

    async with session_factory() as session:
        counts = [
            await session.scalar(select(func.count()).select_from(table))
            for table in (ClaimRow, ClaimVersionRow, AuditEventRow, ClaimWorkItemRow)
        ]

    assert counts == [0, 0, 0, 0]

    await engine.dispose()


def _submission() -> SubmitClaim:
    return SubmitClaim(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_paise=150_000,
        currency="INR",
        documents=(DocumentManifestItem(0, "doc-prescription"),),
    )


def _principal() -> Principal:
    return Principal(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        username="member.emp001",
        roles=frozenset({Role.MEMBER}),
        member_id="EMP001",
    )
