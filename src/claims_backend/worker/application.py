import asyncio
from dataclasses import dataclass
from datetime import timedelta

from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.domain.workflow import ExecutionContract, WorkflowRun
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.observability import EngineeringLogEvent
from claims_backend.runtime.composition import (
    ProcessRuntime,
    create_claim_processor,
    create_execution_contract,
)


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

    async def run_loop(self, stop_event: asyncio.Event) -> None:
        """Poll durable work without retaining a transaction while idle."""
        while not stop_event.is_set():
            active = asyncio.create_task(self.run_once())
            stopping = asyncio.create_task(stop_event.wait())
            done, _ = await asyncio.wait(
                {active, stopping},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stopping in done:
                if not active.done():
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(active),
                            timeout=self.runtime.settings.worker_shutdown_seconds,
                        )
                    except TimeoutError:
                        active.cancel()
                        await asyncio.gather(active, return_exceptions=True)
                else:
                    await active
                return
            stopping.cancel()
            await asyncio.gather(stopping, return_exceptions=True)
            processed = await active
            if processed:
                continue
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.runtime.settings.worker_poll_seconds,
                )
            except TimeoutError:
                continue

    async def close(self) -> None:
        await self.runtime.close()


def create_claim_worker(runtime: ProcessRuntime) -> ClaimWorker:
    """Build the complete durable-work dependency set outside FastAPI state."""
    settings = runtime.settings
    repository = PostgresWorkflowRepository(runtime.session_factory)
    workflows: dict[ExecutionContract, LangGraphClaimWorkflow] = {}

    async def resolve_workflow(existing: WorkflowRun | None) -> LangGraphClaimWorkflow:
        contract = (
            create_execution_contract(settings) if existing is None else existing.execution_contract
        )
        workflow = workflows.get(contract)
        if workflow is None:
            workflow = LangGraphClaimWorkflow(
                settings.database_url,
                repository,
                processor=create_claim_processor(runtime, execution_contract=contract),
                observability=runtime.observability,
                execution_profile=contract.execution_profile,
                execution_contract=contract,
            )
            await workflow.setup()
            workflows[contract] = workflow
        return workflow

    default_contract = create_execution_contract(settings)
    default_workflow = LangGraphClaimWorkflow(
        settings.database_url,
        repository,
        processor=create_claim_processor(runtime, execution_contract=default_contract),
        observability=runtime.observability,
        execution_profile=default_contract.execution_profile,
        execution_contract=default_contract,
    )
    workflows[default_contract] = default_workflow
    processor = ClaimWorkflowProcessor(
        repository,
        default_workflow,
        runtime_resolver=resolve_workflow,
    )
    service = WorkerService(
        PostgresWorkScheduler(runtime.session_factory),
        lease_ttl=timedelta(seconds=settings.worker_lease_seconds),
    )
    return ClaimWorker(runtime=runtime, service=service, processor=processor)
