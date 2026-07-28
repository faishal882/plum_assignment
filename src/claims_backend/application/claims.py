from typing import Protocol
from uuid import UUID

from claims_backend.domain.claims import Claim, SubmitClaim


class ClaimNotFoundError(Exception):
    def __init__(self, claim_id: UUID) -> None:
        self.claim_id = claim_id
        super().__init__(f"Claim {claim_id} was not found")


class ClaimsRepository(Protocol):
    async def create(self, submission: SubmitClaim) -> Claim: ...

    async def get(self, claim_id: UUID) -> Claim | None: ...


class ClaimsApplication:
    def __init__(self, repository: ClaimsRepository) -> None:
        self._repository = repository

    async def submit(self, submission: SubmitClaim) -> Claim:
        return await self._repository.create(submission)

    async def get(self, claim_id: UUID) -> Claim:
        claim = await self._repository.get(claim_id)
        if claim is None:
            raise ClaimNotFoundError(claim_id)
        return claim
