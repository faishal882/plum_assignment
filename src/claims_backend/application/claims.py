import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from claims_backend.application.documents import DocumentStore, StoredDocument, UploadSource
from claims_backend.domain.claims import Claim, SubmitClaim
from claims_backend.domain.identity import Principal, Role


class ClaimNotFoundError(Exception):
    def __init__(self, claim_id: UUID) -> None:
        self.claim_id = claim_id
        super().__init__(f"Claim {claim_id} was not found")


class ClaimSubmissionForbiddenError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ClaimCreationResult:
    claim: Claim
    replayed: bool


class ClaimsRepository(Protocol):
    async def create(
        self,
        submission: SubmitClaim,
        principal: Principal,
        documents: tuple[StoredDocument, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> ClaimCreationResult: ...

    async def get_owned(self, claim_id: UUID, owner_user_id: UUID) -> Claim | None: ...


class ClaimsApplication:
    def __init__(self, repository: ClaimsRepository, document_store: DocumentStore) -> None:
        self._repository = repository
        self._document_store = document_store

    async def submit(
        self,
        submission: SubmitClaim,
        principal: Principal,
        uploads: list[UploadSource],
        idempotency_key: str,
    ) -> Claim:
        if Role.MEMBER not in principal.roles or principal.member_id != submission.member_id:
            raise ClaimSubmissionForbiddenError
        documents = await self._document_store.store_all(uploads)
        try:
            result = await self._repository.create(
                submission,
                principal,
                documents,
                idempotency_key,
                _canonical_request_hash(submission, principal, documents),
            )
        except BaseException:
            await self._document_store.delete_all(documents)
            raise
        if result.replayed:
            await self._document_store.delete_all(documents)
        return result.claim

    async def get(self, claim_id: UUID, principal: Principal) -> Claim:
        claim = await self._repository.get_owned(claim_id, principal.user_id)
        if claim is None:
            raise ClaimNotFoundError(claim_id)
        return claim


def _canonical_request_hash(
    submission: SubmitClaim,
    principal: Principal,
    documents: tuple[StoredDocument, ...],
) -> str:
    canonical_documents = [
        {
            "upload_index": manifest.upload_index,
            "client_document_id": manifest.client_document_id,
            "sha256": document.sha256,
            "media_type": document.media_type,
            "size_bytes": document.size_bytes,
            "page_count": document.page_count,
        }
        for manifest, document in zip(submission.documents, documents, strict=True)
    ]
    payload = {
        "owner_user_id": str(principal.user_id),
        "member_id": submission.member_id,
        "policy_id": submission.policy_id,
        "category": submission.category.value,
        "treatment_date": submission.treatment_date.isoformat(),
        "claimed_paise": submission.claimed_paise,
        "currency": submission.currency,
        "documents": canonical_documents,
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()
