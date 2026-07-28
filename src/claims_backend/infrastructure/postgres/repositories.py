from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from claims_backend.application.claims import (
    ActionIdempotencyConflictError,
    ClaimActionNotAllowedError,
    ClaimCreationResult,
    ClaimDocumentNotFoundError,
    ClaimNotFoundError,
    IdempotencyConflictError,
    StaleClaimVersionError,
)
from claims_backend.application.documents import StoredDocument
from claims_backend.domain.claims import (
    Claim,
    ClaimCategory,
    ClaimLifecycle,
    DocumentReplacementResult,
    ReplaceDocument,
    SubmitClaim,
)
from claims_backend.domain.identity import Principal
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    ClaimActionRow,
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
            document_version_rows = [
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
            self._session.add_all(document_version_rows)
            self._session.add(
                ClaimVersionRow(
                    id=uuid4(),
                    claim_id=claim_id,
                    version=version,
                    submission=_claim_version_snapshot(
                        row,
                        list(
                            zip(
                                document_rows,
                                document_version_rows,
                                strict=True,
                            )
                        ),
                        source="SUBMISSION",
                    ),
                    created_at=now,
                )
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

    async def replace_document(
        self,
        claim_id: UUID,
        action: ReplaceDocument,
        principal: Principal,
        document: StoredDocument,
        idempotency_key: str,
        request_hash: str,
    ) -> DocumentReplacementResult:
        now = datetime.now(UTC)
        async with self._session.begin():
            claim_row = (
                await self._session.execute(
                    select(ClaimRow)
                    .where(
                        ClaimRow.id == claim_id,
                        ClaimRow.owner_user_id == principal.user_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if claim_row is None:
                raise ClaimNotFoundError(claim_id)

            existing_action = (
                await self._session.execute(
                    select(ClaimActionRow).where(
                        ClaimActionRow.scope_user_id == principal.user_id,
                        ClaimActionRow.claim_id == claim_id,
                        ClaimActionRow.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            if existing_action is not None:
                if existing_action.request_hash != request_hash:
                    raise ActionIdempotencyConflictError
                replay_target = (
                    await self._session.execute(
                        select(DocumentRow).where(
                            DocumentRow.id == existing_action.replacement_document_id
                        )
                    )
                ).scalar_one()
                return DocumentReplacementResult(
                    action_id=existing_action.id,
                    claim=_to_domain(claim_row),
                    previous_version=existing_action.previous_version,
                    result_version=existing_action.result_version,
                    result_lifecycle=ClaimLifecycle(existing_action.result_lifecycle_status),
                    client_document_id=replay_target.client_document_id,
                    document_version=existing_action.replacement_document_version,
                    replayed=True,
                )

            if claim_row.current_version != action.expected_version:
                raise StaleClaimVersionError(claim_row.current_version)
            if claim_row.lifecycle_status not in {
                ClaimLifecycle.QUEUED.value,
                ClaimLifecycle.ACTION_REQUIRED.value,
            }:
                raise ClaimActionNotAllowedError

            target = (
                await self._session.execute(
                    select(DocumentRow).where(
                        DocumentRow.claim_id == claim_id,
                        DocumentRow.client_document_id == action.client_document_id,
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                raise ClaimDocumentNotFoundError

            previous_document_version = (
                await self._session.scalar(
                    select(func.max(DocumentVersionRow.version)).where(
                        DocumentVersionRow.document_id == target.id
                    )
                )
                or 0
            )
            new_document_version = previous_document_version + 1
            new_claim_version = claim_row.current_version + 1
            action_id = uuid4()
            previous_lifecycle = claim_row.lifecycle_status

            document_version_row = DocumentVersionRow(
                id=document.storage_id,
                document_id=target.id,
                version=new_document_version,
                original_filename=document.original_filename,
                media_type=document.media_type,
                size_bytes=document.size_bytes,
                page_count=document.page_count,
                sha256=document.sha256,
                relative_path=document.relative_path.as_posix(),
                created_at=now,
            )
            self._session.add(document_version_row)
            await self._session.flush((document_version_row,))

            claim_row.current_version = new_claim_version
            claim_row.lifecycle_status = ClaimLifecycle.QUEUED.value
            claim_row.updated_at = now
            claim_documents = (
                await self._session.scalars(
                    select(DocumentRow)
                    .where(DocumentRow.claim_id == claim_id)
                    .order_by(DocumentRow.upload_index)
                )
            ).all()
            document_snapshot: list[tuple[DocumentRow, DocumentVersionRow]] = []
            for claim_document in claim_documents:
                latest_version = (
                    await self._session.scalars(
                        select(DocumentVersionRow)
                        .where(DocumentVersionRow.document_id == claim_document.id)
                        .order_by(DocumentVersionRow.version.desc())
                        .limit(1)
                    )
                ).one()
                document_snapshot.append((claim_document, latest_version))
            self._session.add(
                ClaimVersionRow(
                    id=uuid4(),
                    claim_id=claim_id,
                    version=new_claim_version,
                    submission=_claim_version_snapshot(
                        claim_row,
                        document_snapshot,
                        source="DOCUMENT_REPLACEMENT",
                        action_id=action_id,
                        previous_version=action.expected_version,
                    ),
                    created_at=now,
                )
            )
            self._session.add(
                ClaimActionRow(
                    id=action_id,
                    scope_user_id=principal.user_id,
                    claim_id=claim_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    action_type="REPLACE_DOCUMENT",
                    previous_version=action.expected_version,
                    result_version=new_claim_version,
                    result_lifecycle_status=claim_row.lifecycle_status,
                    replacement_document_id=target.id,
                    replacement_document_version_id=document.storage_id,
                    replacement_document_version=new_document_version,
                    response_status=200,
                    created_at=now,
                )
            )
            audit_sequence = (
                await self._session.scalar(
                    select(func.max(AuditEventRow.sequence)).where(
                        AuditEventRow.claim_id == claim_id
                    )
                )
                or 0
            ) + 1
            self._session.add(
                AuditEventRow(
                    id=uuid4(),
                    actor_user_id=principal.user_id,
                    actor_username_snapshot=principal.username,
                    claim_id=claim_id,
                    sequence=audit_sequence,
                    event_type="DOCUMENT_REPLACED",
                    payload={
                        "action_id": str(action_id),
                        "previous_claim_version": action.expected_version,
                        "new_claim_version": new_claim_version,
                        "previous_lifecycle_status": previous_lifecycle,
                        "new_lifecycle_status": claim_row.lifecycle_status,
                        "client_document_id": target.client_document_id,
                        "document_id": str(target.id),
                        "document_version_id": str(document.storage_id),
                        "previous_document_version": previous_document_version,
                        "new_document_version": new_document_version,
                        "sha256": document.sha256,
                    },
                    created_at=now,
                )
            )
            await self._session.execute(
                update(ClaimWorkItemRow)
                .where(
                    ClaimWorkItemRow.claim_id == claim_id,
                    ClaimWorkItemRow.status == "AVAILABLE",
                )
                .values(status="SUPERSEDED", updated_at=now)
            )
            self._session.add(
                ClaimWorkItemRow(
                    id=uuid4(),
                    claim_id=claim_id,
                    operation_key=f"claim:{claim_id}:process:v{new_claim_version}",
                    status="AVAILABLE",
                    available_at=now,
                    attempt_count=0,
                    max_attempts=3,
                    created_at=now,
                    updated_at=now,
                )
            )

        return DocumentReplacementResult(
            action_id=action_id,
            claim=_to_domain(claim_row),
            previous_version=action.expected_version,
            result_version=new_claim_version,
            result_lifecycle=ClaimLifecycle(claim_row.lifecycle_status),
            client_document_id=target.client_document_id,
            document_version=new_document_version,
            replayed=False,
        )


def _claim_version_snapshot(
    claim: ClaimRow,
    documents: list[tuple[DocumentRow, DocumentVersionRow]],
    *,
    source: str,
    action_id: UUID | None = None,
    previous_version: int | None = None,
) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "source": source,
        "member_id": claim.member_id,
        "policy_id": claim.policy_id,
        "category": claim.category,
        "treatment_date": claim.treatment_date.isoformat(),
        "claimed_paise": claim.claimed_paise,
        "currency": claim.currency,
        "documents": [
            {
                "upload_index": document.upload_index,
                "client_document_id": document.client_document_id,
                "document_id": str(document.id),
                "document_version_id": str(document_version.id),
                "document_version": document_version.version,
                "sha256": document_version.sha256,
                "media_type": document_version.media_type,
                "size_bytes": document_version.size_bytes,
                "page_count": document_version.page_count,
            }
            for document, document_version in documents
        ],
    }
    if action_id is not None:
        snapshot["action_id"] = str(action_id)
    if previous_version is not None:
        snapshot["previous_version"] = previous_version
    return snapshot


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
