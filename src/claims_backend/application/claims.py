from typing import Protocol
from uuid import UUID

from claims_backend.domain.claims import Claim, SubmitClaim
from claims_backend.domain.identity import Principal, Role


class ClaimNotFoundError(Exception):
    def __init__(self, claim_id: UUID) -> None:
        self.claim_id = claim_id
        super().__init__(f"Claim {claim_id} was not found")


class ClaimSubmissionForbiddenError(Exception):
    pass


class ClaimsRepository(Protocol):
    async def create(self, submission: SubmitClaim, principal: Principal) -> Claim: ...

    async def get_owned(self, claim_id: UUID, owner_user_id: UUID) -> Claim | None: ...


class ClaimsApplication:
    def __init__(self, repository: ClaimsRepository) -> None:
        self._repository = repository

    async def submit(self, submission: SubmitClaim, principal: Principal) -> Claim:
        if Role.MEMBER not in principal.roles or principal.member_id != submission.member_id:
            raise ClaimSubmissionForbiddenError
        return await self._repository.create(submission, principal)

    async def get(self, claim_id: UUID, principal: Principal) -> Claim:
        claim = await self._repository.get_owned(claim_id, principal.user_id)
        if claim is None:
            raise ClaimNotFoundError(claim_id)
        return claim
