from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from claims_backend.application.intelligence import (
    OcrApplication,
    OcrProvider,
    PageArtifactApplication,
)
from claims_backend.config import Settings
from claims_backend.infrastructure.aws.bedrock import ChatBedrockConverseTransport
from claims_backend.infrastructure.aws.textract import TextractAdapter, create_textract_client
from claims_backend.infrastructure.fixtures.recorded_intelligence import (
    RecordedDiscoveryOcrProvider,
    RecordedDocumentModelTransport,
)
from claims_backend.infrastructure.page_artifacts import (
    LocalPageArtifactReader,
    LocalPageArtifactStore,
)
from claims_backend.infrastructure.page_renderer import LocalPageRenderer
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.infrastructure.postgres.ocr import PostgresOcrRepository
from claims_backend.infrastructure.postgres.page_artifacts import PostgresPageArtifactRepository
from claims_backend.infrastructure.postgres.structured_model import (
    PostgresStructuredModelRepository,
)
from claims_backend.model.application import StructuredModelApplication
from claims_backend.model.routing import ModelRouter
from claims_backend.model.transport import StructuredModelTransport
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


def create_claim_processor(runtime: ProcessRuntime) -> PostgresClaimProcessor:
    """Construct the complete profile-selected intelligence pipeline.

    The local profile has no AWS construction path; the live profile can only
    exist after the authorization check performed by ``Settings``.
    """
    settings = runtime.settings
    settings.data_root.mkdir(parents=True, exist_ok=True)
    pages = PostgresPageArtifactRepository(runtime.session_factory)
    ocr_repository = PostgresOcrRepository(runtime.session_factory)
    evidence = PostgresStructuredModelRepository(runtime.session_factory)
    if runtime.profile is ExecutionProfile.LIVE_INTELLIGENCE:
        ocr_provider: OcrProvider = TextractAdapter(
            create_textract_client(
                region=settings.aws_region,
                read_timeout_seconds=settings.textract_timeout_seconds,
            ),
            concurrency_limit=settings.textract_concurrency_limit,
            observability=runtime.observability,
        )
        model_transport: StructuredModelTransport = ChatBedrockConverseTransport.from_settings(
            settings,
            observability=runtime.observability,
        )
    else:
        ocr_provider = RecordedDiscoveryOcrProvider()
        model_transport = RecordedDocumentModelTransport()
    return PostgresClaimProcessor(
        runtime.session_factory,
        page_artifacts=PageArtifactApplication(
            LocalPageRenderer(
                settings.data_root,
                max_page_bytes=settings.max_textract_page_bytes,
                render_dpi=settings.page_render_dpi,
            ),
            LocalPageArtifactStore(settings.data_root),
            pages,
        ),
        page_repository=pages,
        ocr=OcrApplication(
            LocalPageArtifactReader(settings.data_root),
            ocr_provider,
            ocr_repository,
        ),
        ocr_repository=ocr_repository,
        structured_model=StructuredModelApplication(
            ModelRouter.default(
                region=settings.bedrock_region,
                model_id=settings.bedrock_model_id,
            ),
            model_transport,
            evidence,
        ),
        evidence_repository=evidence,
    )
