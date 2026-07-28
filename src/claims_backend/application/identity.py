from typing import Protocol

from claims_backend.domain.identity import Principal


class IdentityProvider(Protocol):
    async def resolve(self, username: str) -> Principal | None: ...
