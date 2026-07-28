from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from claims_backend.application.claims import (
    ClaimCreationResult,
    IdempotencyConflictError,
)
from claims_backend.application.documents import StoredDocument
from claims_backend.domain.claims import Claim, ClaimCategory, ClaimLifecycle, SubmitClaim
from claims_backend.domain.identity import Principal
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    ClaimRow,
    ClaimVersionRow,
    ClaimWorkItemRow,
    DocumentRow,
    DocumentVersionRow,
    IdempotencyKeyRow,
)


class PostgresClaimsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        submission: SubmitClaim,
        principal: Principal,
        documents: tuple[StoredDocument, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> ClaimCreationResult:
        claim_id = uuid4()
        now = datetime.now(UTC)
        version = 1

        manifest = [
            {
                "upload_index": item.upload_index,
                "client_document_id": item.client_document_id,
            }
            for item in submission.documents
        ]

        async with self._session.begin():
            inserted_claim_id = await self._session.scalar(
                insert(IdempotencyKeyRow)
                .values(
                    id=uuid4(),
                    scope_user_id=principal.user_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    response_claim_id=claim_id,
                    response_status=202,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(constraint="idempotency_keys_user_key_uq")
                .returning(IdempotencyKeyRow.response_claim_id)
            )
            if inserted_claim_id is None:
                existing = (
                    await self._session.execute(
                        select(IdempotencyKeyRow)
                        .where(
                            IdempotencyKeyRow.scope_user_id == principal.user_id,
                            IdempotencyKeyRow.idempotency_key == idempotency_key,
                        )
                        .with_for_update()
                    )
                ).scalar_one()
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError
                existing_claim = (
                    await self._session.execute(
                        select(ClaimRow).where(ClaimRow.id == existing.response_claim_id)
                    )
                ).scalar_one()
                return ClaimCreationResult(
                    claim=_to_domain(existing_claim),
                    replayed=True,
                )

            row = ClaimRow(
                id=claim_id,
                owner_user_id=principal.user_id,
                owner_username_snapshot=principal.username,
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
            document_rows = [
                DocumentRow(
                    id=uuid4(),
                    claim_id=claim_id,
                    client_document_id=manifest_item.client_document_id,
                    upload_index=manifest_item.upload_index,
                    created_at=now,
                )
                for manifest_item in submission.documents
            ]
            self._session.add_all(document_rows)
            await self._session.flush(document_rows)
            self._session.add_all(
                [
                    DocumentVersionRow(
                        id=stored.storage_id,
                        document_id=document.id,
                        version=1,
                        original_filename=stored.original_filename,
                        media_type=stored.media_type,
                        size_bytes=stored.size_bytes,
                        page_count=stored.page_count,
                        sha256=stored.sha256,
                        relative_path=stored.relative_path.as_posix(),
                        created_at=now,
                    )
                    for document, stored in zip(document_rows, documents, strict=True)
                ]
            )
            self._session.add_all(
                [
                    AuditEventRow(
                        id=uuid4(),
                        actor_user_id=principal.user_id,
                        actor_username_snapshot=principal.username,
                        claim_id=claim_id,
                        sequence=1,
                        event_type="CLAIM_RECEIVED",
                        payload={"lifecycle_status": ClaimLifecycle.RECEIVED.value},
                        created_at=now,
                    ),
                    AuditEventRow(
                        id=uuid4(),
                        actor_user_id=principal.user_id,
                        actor_username_snapshot=principal.username,
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

        return ClaimCreationResult(claim=_to_domain(row), replayed=False)

    async def get_owned(self, claim_id: UUID, owner_user_id: UUID) -> Claim | None:
        result = await self._session.execute(
            select(ClaimRow).where(
                ClaimRow.id == claim_id,
                ClaimRow.owner_user_id == owner_user_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else _to_domain(row)


def _to_domain(row: ClaimRow) -> Claim:
    return Claim(
        id=row.id,
        owner_user_id=row.owner_user_id,
        owner_username_snapshot=row.owner_username_snapshot,
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
