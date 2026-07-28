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


class ClaimsRepository(Protocol):
    async def create(
        self,
        submission: SubmitClaim,
        principal: Principal,
        documents: tuple[StoredDocument, ...],
    ) -> Claim: ...

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
    ) -> Claim:
        if Role.MEMBER not in principal.roles or principal.member_id != submission.member_id:
            raise ClaimSubmissionForbiddenError
        documents = await self._document_store.store_all(uploads)
        try:
            return await self._repository.create(submission, principal, documents)
        except BaseException:
            await self._document_store.delete_all(documents)
            raise

    async def get(self, claim_id: UUID, principal: Principal) -> Claim:
        claim = await self._repository.get_owned(claim_id, principal.user_id)
        if claim is None:
            raise ClaimNotFoundError(claim_id)
        return claim
