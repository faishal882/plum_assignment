from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from claims_backend.config import Settings
from claims_backend.observability import (
    Observability,
    ObservabilityConfig,
    create_observability,
)
from claims_backend.runtime.profiles import ExecutionProfile


@dataclass(slots=True)
class ProcessRuntime:
    settings: Settings
    profile: ExecutionProfile
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    observability: Observability | None
    _owns_observability: bool

    async def close(self) -> None:
        await self.engine.dispose()
        if self._owns_observability and self.observability is not None:
            self.observability.shutdown()


def create_process_runtime(
    settings: Settings,
    *,
    process_name: str,
    observability: Observability | None = None,
) -> ProcessRuntime:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    owned_observability = observability is None and settings.observability_enabled
    resolved_observability = observability
    if owned_observability:
        resolved_observability = create_observability(
            ObservabilityConfig(
                log_root=settings.log_root,
                enabled=settings.observability_enabled,
                phoenix_endpoint=settings.phoenix_endpoint,
                project_name=settings.phoenix_project,
                log_max_bytes=settings.log_max_bytes,
                log_backup_count=settings.log_backup_count,
                execution_profile=settings.execution_profile,
                capture_content=settings.observability_capture_content,
                synthetic_only=settings.observability_synthetic_only,
            ),
            process_name=process_name,
        )
    return ProcessRuntime(
        settings=settings,
        profile=settings.execution_profile,
        engine=engine,
        session_factory=session_factory,
        observability=resolved_observability,
        _owns_observability=owned_observability,
    )
