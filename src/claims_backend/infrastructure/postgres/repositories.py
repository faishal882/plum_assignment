from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from claims_backend.domain.claims import Claim, ClaimCategory, ClaimLifecycle, SubmitClaim
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    ClaimRow,
    ClaimVersionRow,
    ClaimWorkItemRow,
)


class PostgresClaimsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, submission: SubmitClaim) -> Claim:
        claim_id = uuid4()
        now = datetime.now(UTC)
        version = 1

        row = ClaimRow(
            id=claim_id,
            member_id=submission.member_id,
            policy_id=submission.policy_id,
            category=submission.category.value,
            treatment_date=submission.treatment_date,
            claimed_paise=submission.claimed_paise,
            currency=submission.currency,
            lifecycle_status=ClaimLifecycle.QUEUED.value,
            current_version=version,
            created_at=now,
            updated_at=now,
        )
        manifest = [
            {
                "upload_index": item.upload_index,
                "client_document_id": item.client_document_id,
            }
            for item in submission.documents
        ]

        async with self._session.begin():
            self._session.add(row)
            await self._session.flush((row,))
            self._session.add(
                ClaimVersionRow(
                    id=uuid4(),
                    claim_id=claim_id,
                    version=version,
                    submission={"documents": manifest},
                    created_at=now,
                )
            )
            self._session.add_all(
                [
                    AuditEventRow(
                        id=uuid4(),
                        claim_id=claim_id,
                        sequence=1,
                        event_type="CLAIM_RECEIVED",
                        payload={"lifecycle_status": ClaimLifecycle.RECEIVED.value},
                        created_at=now,
                    ),
                    AuditEventRow(
                        id=uuid4(),
                        claim_id=claim_id,
                        sequence=2,
                        event_type="CLAIM_QUEUED",
                        payload={"lifecycle_status": ClaimLifecycle.QUEUED.value},
                        created_at=now,
                    ),
                ]
            )
            self._session.add(
                ClaimWorkItemRow(
                    id=uuid4(),
                    claim_id=claim_id,
                    operation_key=f"claim:{claim_id}:process:v{version}",
                    status="AVAILABLE",
                    available_at=now,
                    attempt_count=0,
                    max_attempts=3,
                    created_at=now,
                    updated_at=now,
                )
            )

        return _to_domain(row)

    async def get(self, claim_id: UUID) -> Claim | None:
        result = await self._session.execute(select(ClaimRow).where(ClaimRow.id == claim_id))
        row = result.scalar_one_or_none()
        return None if row is None else _to_domain(row)


def _to_domain(row: ClaimRow) -> Claim:
    return Claim(
        id=row.id,
        version=row.current_version,
        member_id=row.member_id,
        policy_id=row.policy_id,
        category=ClaimCategory(row.category),
        treatment_date=row.treatment_date,
        claimed_paise=row.claimed_paise,
        currency=row.currency,
        lifecycle=ClaimLifecycle(row.lifecycle_status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
