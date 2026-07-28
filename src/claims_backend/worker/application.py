from dataclasses import dataclass
from datetime import timedelta

from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.observability import EngineeringLogEvent
from claims_backend.runtime.composition import ProcessRuntime, create_claim_processor


@dataclass(slots=True)
class ClaimWorker:
    """Owns one durable-claim worker process and its local resources."""

    runtime: ProcessRuntime
    service: WorkerService
    processor: ClaimWorkflowProcessor

    async def setup(self) -> None:
        await self.processor.setup()

    async def run_once(self) -> bool:
        settings = self.runtime.settings
        observability = self.runtime.observability
        if observability is not None:
            observability.log(
                EngineeringLogEvent(
                    event_name="worker_poll_started",
                    component="worker",
                    outcome="RUNNING",
                    duration_ms=0,
                )
            )
        processed = await self.service.run_once(settings.worker_id, self.processor.process)
        if observability is not None:
            observability.log(
                EngineeringLogEvent(
                    event_name="worker_poll_finished",
                    component="worker",
                    outcome="OK",
                    duration_ms=0,
                )
            )
        return processed

    async def close(self) -> None:
        await self.runtime.close()


def create_claim_worker(runtime: ProcessRuntime) -> ClaimWorker:
    """Build the complete durable-work dependency set outside FastAPI state."""
    settings = runtime.settings
    repository = PostgresWorkflowRepository(runtime.session_factory)
    workflow = LangGraphClaimWorkflow(
        settings.database_url,
        repository,
        processor=create_claim_processor(runtime),
        observability=runtime.observability,
    )
    processor = ClaimWorkflowProcessor(repository, workflow)
    service = WorkerService(
        PostgresWorkScheduler(runtime.session_factory),
        lease_ttl=timedelta(seconds=settings.worker_lease_seconds),
    )
    return ClaimWorker(runtime=runtime, service=service, processor=processor)
