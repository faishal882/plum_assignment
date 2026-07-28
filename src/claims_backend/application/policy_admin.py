from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from claims_backend.domain.policy import PolicyVersionInspection
from claims_backend.policy.compiler import PolicyCompilation, PolicyCompiler


class PolicySourceNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class PolicySourceArtifact:
    id: UUID
    policy_id: str
    source_sha256: str
    source_bytes: bytes


class PolicyRepository(Protocol):
    async def get_source_by_hash(
        self,
        source_sha256: str,
    ) -> PolicySourceArtifact | None: ...

    async def save_compilation(
        self,
        source: PolicySourceArtifact,
        compilation: PolicyCompilation,
        overlay_bytes: bytes,
        overlay_source_name: str,
    ) -> PolicyVersionInspection: ...

    async def inspect_version(
        self,
        policy_version_id: UUID,
    ) -> PolicyVersionInspection | None: ...


class PolicyAdministrationApplication:
    def __init__(
        self,
        repository: PolicyRepository,
        compiler: PolicyCompiler,
    ) -> None:
        self._repository = repository
        self._compiler = compiler

    async def compile(
        self,
        source_sha256: str,
        overlay_bytes: bytes,
        *,
        overlay_source_name: str,
    ) -> PolicyVersionInspection:
        source = await self._repository.get_source_by_hash(source_sha256)
        if source is None:
            raise PolicySourceNotFoundError(source_sha256)
        compilation = self._compiler.compile(source.source_bytes, overlay_bytes)
        return await self._repository.save_compilation(
            source,
            compilation,
            overlay_bytes,
            overlay_source_name,
        )

    async def inspect_version(
        self,
        policy_version_id: UUID,
    ) -> PolicyVersionInspection | None:
        return await self._repository.inspect_version(policy_version_id)
