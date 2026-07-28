from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from claims_backend.application.claims import (
    ActionIdempotencyConflictError,
    ActivePolicyUnavailableError,
    ClaimActionNotAllowedError,
    ClaimCreationResult,
    ClaimDocumentNotFoundError,
    ClaimNotFoundError,
    IdempotencyConflictError,
    MemberSnapshotUnavailableError,
    StaleClaimVersionError,
)
from claims_backend.application.documents import StoredDocument
from claims_backend.domain.claims import (
    Claim,
    ClaimCategory,
    ClaimLifecycle,
    DocumentReplacementResult,
    MemberAction,
    MemberActionDocument,
    MemberAdjudication,
    MemberDeduction,
    MemberExplanation,
    MemberIdentityConflict,
    MemberLineItemExplanation,
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
    MemberRow,
    MemberVersionRow,
    PolicyOverlayRow,
    PolicySourceRow,
    PolicyVersionRow,
    SetupImportRow,
)


@dataclass(frozen=True, slots=True)
class _PinnedSnapshots:
    policy_source_id: UUID
    policy_overlay_id: UUID
    policy_version_id: UUID
    member_version_id: UUID
    policy: dict[str, object]
    member: dict[str, object]


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

            pins = await self._resolve_pins(submission)
            row = ClaimRow(
                id=claim_id,
                owner_user_id=principal.user_id,
                owner_username_snapshot=principal.username,
                member_id=submission.member_id,
                policy_id=submission.policy_id,
                policy_source_id=pins.policy_source_id,
                policy_overlay_id=pins.policy_overlay_id,
                policy_version_id=pins.policy_version_id,
                member_version_id=pins.member_version_id,
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
                        pinned_snapshots=pins,
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
                    claim_version=version,
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
            previous_claim_version = (
                await self._session.scalars(
                    select(ClaimVersionRow).where(
                        ClaimVersionRow.claim_id == claim_id,
                        ClaimVersionRow.version == action.expected_version,
                    )
                )
            ).one()

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
            claim_row.current_action = None
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
                        prior_submission=previous_claim_version.submission,
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
                    ClaimWorkItemRow.status.in_(("AVAILABLE", "LEASED")),
                )
                .values(
                    status="SUPERSEDED",
                    lease_owner=None,
                    lease_token=None,
                    lease_until=None,
                    updated_at=now,
                )
            )
            self._session.add(
                ClaimWorkItemRow(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=new_claim_version,
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

    async def _resolve_pins(self, submission: SubmitClaim) -> _PinnedSnapshots:
        row = (
            await self._session.execute(
                select(
                    PolicyVersionRow,
                    PolicySourceRow,
                    PolicyOverlayRow,
                    MemberRow,
                    MemberVersionRow,
                    SetupImportRow,
                )
                .join(
                    PolicySourceRow,
                    PolicySourceRow.id == PolicyVersionRow.policy_source_id,
                )
                .join(
                    PolicyOverlayRow,
                    PolicyOverlayRow.id == PolicyVersionRow.policy_overlay_id,
                )
                .join(
                    MemberRow,
                    (MemberRow.policy_id == PolicyVersionRow.policy_id)
                    & (MemberRow.external_member_id == submission.member_id),
                )
                .join(
                    MemberVersionRow,
                    MemberVersionRow.member_id == MemberRow.id,
                )
                .join(
                    SetupImportRow,
                    SetupImportRow.id == MemberVersionRow.setup_import_id,
                )
                .where(
                    PolicyVersionRow.policy_id == submission.policy_id,
                    PolicyVersionRow.status == "ACTIVE",
                    SetupImportRow.policy_source_id == PolicyVersionRow.policy_source_id,
                )
                .order_by(
                    SetupImportRow.imported_at.desc(),
                    MemberVersionRow.version.desc(),
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            active_exists = await self._session.scalar(
                select(PolicyVersionRow.id).where(
                    PolicyVersionRow.policy_id == submission.policy_id,
                    PolicyVersionRow.status == "ACTIVE",
                )
            )
            if active_exists is None:
                raise ActivePolicyUnavailableError(submission.policy_id)
            raise MemberSnapshotUnavailableError(submission.member_id)

        policy_version, source, overlay, member, member_version, setup_import = row
        if policy_version.ir_sha256 is None:
            raise ActivePolicyUnavailableError(submission.policy_id)
        return _PinnedSnapshots(
            policy_source_id=source.id,
            policy_overlay_id=overlay.id,
            policy_version_id=policy_version.id,
            member_version_id=member_version.id,
            policy={
                "policy_source_id": str(source.id),
                "policy_overlay_id": str(overlay.id),
                "policy_version_id": str(policy_version.id),
                "policy_version": policy_version.version,
                "source_sha256": source.source_sha256,
                "overlay_sha256": overlay.source_sha256,
                "ir_sha256": policy_version.ir_sha256,
            },
            member={
                "member_id": member.external_member_id,
                "member_record_id": str(member.id),
                "member_version_id": str(member_version.id),
                "member_version": member_version.version,
                "setup_import_id": str(setup_import.id),
            },
        )


def _claim_version_snapshot(
    claim: ClaimRow,
    documents: list[tuple[DocumentRow, DocumentVersionRow]],
    *,
    source: str,
    action_id: UUID | None = None,
    previous_version: int | None = None,
    pinned_snapshots: _PinnedSnapshots | None = None,
    prior_submission: dict[str, object] | None = None,
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
    if pinned_snapshots is not None:
        snapshot["policy_snapshot"] = pinned_snapshots.policy
        snapshot["member_snapshot"] = pinned_snapshots.member
    elif prior_submission is not None:
        snapshot["policy_snapshot"] = prior_submission["policy_snapshot"]
        snapshot["member_snapshot"] = prior_submission["member_snapshot"]
    if action_id is not None:
        snapshot["action_id"] = str(action_id)
    if previous_version is not None:
        snapshot["previous_version"] = previous_version
    return snapshot


def _to_domain(row: ClaimRow) -> Claim:
    explanation = row.member_explanation
    action = row.current_action
    deduction_values = None if explanation is None else explanation.get("deductions")
    line_item_values = None if explanation is None else explanation.get("line_items")
    deductions = (
        tuple(
            MemberDeduction(
                code=str(item["code"]),
                label=str(item["label"]),
                amount_paise=int(str(item["amount_paise"])),
            )
            for item in deduction_values
            if isinstance(item, dict)
        )
        if isinstance(deduction_values, list)
        else ()
    )
    line_items = (
        tuple(
            MemberLineItemExplanation(
                concept=str(item["concept"]),
                label=str(item["label"]),
                claimed_paise=int(str(item["claimed_paise"])),
                approved_paise=int(str(item["approved_paise"])),
                status=str(item["status"]),
                reason_code=str(item["reason_code"]),
            )
            for item in line_item_values
            if isinstance(item, dict)
        )
        if isinstance(line_item_values, list)
        else ()
    )
    observed_roles = None if action is None else action.get("observed_document_roles")
    required_roles = None if action is None else action.get("required_document_roles")
    action_documents = None if action is None else action.get("affected_documents")
    identity_conflict = None if action is None else action.get("identity_conflict")
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
        adjudication=(
            None
            if row.adjudication_recommendation is None or row.approved_paise is None
            else MemberAdjudication(
                recommendation=row.adjudication_recommendation,
                approved_paise=row.approved_paise,
                currency=row.currency,
            )
        ),
        explanation=(
            None
            if explanation is None
            else MemberExplanation(
                summary=str(explanation["summary"]),
                deductions=deductions,
                line_items=line_items,
            )
        ),
        action=(
            None
            if action is None
            else MemberAction(
                code=str(action["code"]),
                message=str(action["message"]),
                observed_document_roles=tuple(str(value) for value in observed_roles),
                required_document_roles=tuple(str(value) for value in required_roles),
                affected_documents=(
                    tuple(
                        MemberActionDocument(
                            client_document_id=str(item["client_document_id"]),
                            observed_role=str(item["observed_role"]),
                            requested_action=str(item["requested_action"]),
                        )
                        for item in action_documents
                        if isinstance(item, dict)
                    )
                    if isinstance(action_documents, list)
                    else ()
                ),
                identity_conflict=(
                    tuple(
                        MemberIdentityConflict(
                            client_document_id=str(item["client_document_id"]),
                            patient_name=str(item["patient_name"]),
                        )
                        for item in identity_conflict
                        if isinstance(item, dict)
                    )
                    if isinstance(identity_conflict, list)
                    else ()
                ),
            )
            if isinstance(observed_roles, list) and isinstance(required_roles, list)
            else None
        ),
        handling_status=row.handling_status,
        review_task_id=row.review_task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
