from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from claims_backend.domain.identity import Principal, Role
from claims_backend.domain.policy import (
    PolicyActivationEvent,
    PolicyFindingSeverity,
    PolicyVersionInspection,
)
from claims_backend.policy.compiler import PolicyCompilation, PolicyCompiler


class PolicySourceNotFoundError(LookupError):
    pass


class PolicyVersionNotFoundError(LookupError):
    pass


class PolicyActivationBlockedError(RuntimeError):
    pass


class PolicyActivationForbiddenError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class PolicyActivationGate:
    blocking_severities: frozenset[PolicyFindingSeverity] = field(
        default_factory=lambda: frozenset({PolicyFindingSeverity.ERROR})
    )


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

    async def activate(
        self,
        policy_version_id: UUID,
        actor: str,
        gate: PolicyActivationGate,
    ) -> PolicyVersionInspection: ...

    async def list_activation_events(
        self,
        policy_version_id: UUID,
    ) -> tuple[PolicyActivationEvent, ...]: ...


class PolicyAdministrationApplication:
    def __init__(
        self,
        repository: PolicyRepository,
        compiler: PolicyCompiler,
        activation_gate: PolicyActivationGate | None = None,
    ) -> None:
        self._repository = repository
        self._compiler = compiler
        self._activation_gate = activation_gate or PolicyActivationGate()

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

    async def activate(
        self,
        policy_version_id: UUID,
        principal: Principal,
    ) -> PolicyVersionInspection:
        if Role.OPERATOR not in principal.roles:
            raise PolicyActivationForbiddenError
        return await self._repository.activate(
            policy_version_id,
            principal.username,
            self._activation_gate,
        )

    async def list_activation_events(
        self,
        policy_version_id: UUID,
    ) -> tuple[PolicyActivationEvent, ...]:
        return await self._repository.list_activation_events(policy_version_id)
