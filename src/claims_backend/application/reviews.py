from typing import Protocol
from uuid import UUID

from claims_backend.domain.identity import Principal, Role
from claims_backend.domain.reviews import (
    ReviewCommand,
    ReviewResolution,
    ReviewTaskDetail,
    ReviewTaskSummary,
)


class ReviewForbiddenError(PermissionError):
    pass


class ReviewTaskNotFoundError(LookupError):
    pass


class ReviewTaskNotOpenError(RuntimeError):
    pass


class ReviewStaleClaimVersionError(RuntimeError):
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__("The claim version changed before review resolution.")


class ReviewCommandIdempotencyConflictError(RuntimeError):
    pass


class ReviewCommandInvalidError(ValueError):
    pass


class ReviewRepository(Protocol):
    async def list_tasks(self) -> tuple[ReviewTaskSummary, ...]: ...

    async def get_task(self, task_id: UUID) -> ReviewTaskDetail | None: ...

    async def resolve(
        self,
        task_id: UUID,
        command: ReviewCommand,
        principal: Principal,
        idempotency_key: str,
    ) -> ReviewResolution: ...


class ReviewApplication:
    def __init__(self, repository: ReviewRepository) -> None:
        self._repository = repository

    async def list_tasks(
        self,
        principal: Principal,
    ) -> tuple[ReviewTaskSummary, ...]:
        _require_reviewer(principal)
        return await self._repository.list_tasks()

    async def get_task(
        self,
        task_id: UUID,
        principal: Principal,
    ) -> ReviewTaskDetail:
        _require_reviewer(principal)
        task = await self._repository.get_task(task_id)
        if task is None:
            raise ReviewTaskNotFoundError
        return task

    async def resolve(
        self,
        task_id: UUID,
        command: ReviewCommand,
        principal: Principal,
        idempotency_key: str,
    ) -> ReviewResolution:
        _require_reviewer(principal)
        return await self._repository.resolve(
            task_id,
            command,
            principal,
            idempotency_key,
        )


def _require_reviewer(principal: Principal) -> None:
    if Role.REVIEWER not in principal.roles:
        raise ReviewForbiddenError
