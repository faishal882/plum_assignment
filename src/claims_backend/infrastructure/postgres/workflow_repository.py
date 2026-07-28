from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.workflow import WorkflowRepository
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import (
    NewWorkflowEvent,
    WorkflowEffect,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)
from claims_backend.infrastructure.postgres.models import (
    WorkflowEffectRow,
    WorkflowEventRow,
    WorkflowRunRow,
)


class PostgresWorkflowRepository(WorkflowRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_or_create(
        self,
        lease: WorkLease,
        graph_name: str,
        graph_version: str,
    ) -> WorkflowRun:
        now = datetime.now(UTC)
        workflow_run_id = uuid4()
        async with self._session_factory.begin() as session:
            inserted_id = await session.scalar(
                insert(WorkflowRunRow)
                .values(
                    id=workflow_run_id,
                    work_item_id=lease.work_item_id,
                    claim_id=lease.claim_id,
                    claim_version=lease.claim_version,
                    operation_key=lease.operation_key,
                    graph_name=graph_name,
                    graph_version=graph_version,
                    status=WorkflowRunStatus.PENDING.value,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[WorkflowRunRow.work_item_id])
                .returning(WorkflowRunRow.id)
            )
            row = (
                await session.scalars(
                    select(WorkflowRunRow).where(
                        WorkflowRunRow.id
                        == (inserted_id if inserted_id is not None else workflow_run_id)
                    )
                )
            ).one_or_none()
            if row is None:
                row = (
                    await session.scalars(
                        select(WorkflowRunRow).where(
                            WorkflowRunRow.work_item_id == lease.work_item_id
                        )
                    )
                ).one()
            if (
                row.claim_id != lease.claim_id
                or row.claim_version != lease.claim_version
                or row.operation_key != lease.operation_key
                or row.graph_name != graph_name
                or row.graph_version != graph_version
            ):
                raise WorkflowRunConflictError
            return _to_run(row)

    async def get_by_work_item(self, work_item_id: UUID) -> WorkflowRun | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(WorkflowRunRow).where(WorkflowRunRow.work_item_id == work_item_id)
            )
        return None if row is None else _to_run(row)

    async def mark_running(self, workflow_run_id: UUID) -> WorkflowRun:
        return await self._transition(
            workflow_run_id,
            allowed=(
                WorkflowRunStatus.PENDING,
                WorkflowRunStatus.RUNNING,
            ),
            target=WorkflowRunStatus.RUNNING,
        )

    async def mark_completed(self, workflow_run_id: UUID) -> WorkflowRun:
        return await self._transition(
            workflow_run_id,
            allowed=(
                WorkflowRunStatus.RUNNING,
                WorkflowRunStatus.COMPLETED,
            ),
            target=WorkflowRunStatus.COMPLETED,
        )

    async def record_effect(
        self,
        workflow_run_id: UUID,
        effect_key: str,
        effect_type: str,
        payload: dict[str, object],
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            effect_id = await session.scalar(
                insert(WorkflowEffectRow)
                .values(
                    id=uuid4(),
                    workflow_run_id=workflow_run_id,
                    effect_key=effect_key,
                    effect_type=effect_type,
                    payload=payload,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="workflow_effects_run_key_uq")
                .returning(WorkflowEffectRow.id)
            )
        return effect_id is not None

    async def list_effects(
        self,
        workflow_run_id: UUID,
    ) -> tuple[WorkflowEffect, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(WorkflowEffectRow)
                    .where(WorkflowEffectRow.workflow_run_id == workflow_run_id)
                    .order_by(WorkflowEffectRow.created_at, WorkflowEffectRow.id)
                )
            ).all()
        return tuple(_to_effect(row) for row in rows)

    async def record_event(
        self,
        workflow_run_id: UUID,
        event: NewWorkflowEvent,
    ) -> WorkflowEvent:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            run = await session.scalar(
                select(WorkflowRunRow)
                .where(WorkflowRunRow.id == workflow_run_id)
                .with_for_update()
            )
            if run is None:
                raise WorkflowTransitionError
            sequence = (
                await session.scalar(
                    select(func.max(WorkflowEventRow.sequence)).where(
                        WorkflowEventRow.workflow_run_id == workflow_run_id
                    )
                )
                or 0
            ) + 1
            row = WorkflowEventRow(
                id=uuid4(),
                workflow_run_id=workflow_run_id,
                sequence=sequence,
                node_name=event.node_name,
                event_type=event.event_type,
                attempt_number=event.attempt_number,
                duration_ms=event.duration_ms,
                outcome=event.outcome,
                trace_id=event.trace_id,
                span_id=event.span_id,
                error_type=event.error_type,
                created_at=now,
            )
            session.add(row)
            await session.flush((row,))
            return _to_event(row)

    async def list_events(
        self,
        workflow_run_id: UUID,
    ) -> tuple[WorkflowEvent, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(WorkflowEventRow)
                    .where(WorkflowEventRow.workflow_run_id == workflow_run_id)
                    .order_by(WorkflowEventRow.sequence)
                )
            ).all()
        return tuple(_to_event(row) for row in rows)

    async def _transition(
        self,
        workflow_run_id: UUID,
        *,
        allowed: tuple[WorkflowRunStatus, ...],
        target: WorkflowRunStatus,
    ) -> WorkflowRun:
        now = datetime.now(UTC)
        values: dict[str, object] = {
            "status": target.value,
            "updated_at": now,
        }
        if target is WorkflowRunStatus.COMPLETED:
            values["completed_at"] = now
        async with self._session_factory.begin() as session:
            row = (
                await session.scalars(
                    update(WorkflowRunRow)
                    .where(
                        WorkflowRunRow.id == workflow_run_id,
                        WorkflowRunRow.status.in_(status.value for status in allowed),
                    )
                    .values(**values)
                    .returning(WorkflowRunRow)
                )
            ).one_or_none()
            if row is None:
                raise WorkflowTransitionError
            return _to_run(row)


class WorkflowRunConflictError(Exception):
    pass


class WorkflowTransitionError(Exception):
    pass


def _to_run(row: WorkflowRunRow) -> WorkflowRun:
    return WorkflowRun(
        id=row.id,
        work_item_id=row.work_item_id,
        claim_id=row.claim_id,
        claim_version=row.claim_version,
        operation_key=row.operation_key,
        graph_name=row.graph_name,
        graph_version=row.graph_version,
        status=WorkflowRunStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _to_effect(row: WorkflowEffectRow) -> WorkflowEffect:
    return WorkflowEffect(
        id=row.id,
        workflow_run_id=row.workflow_run_id,
        effect_key=row.effect_key,
        effect_type=row.effect_type,
        payload=row.payload,
        created_at=row.created_at,
    )


def _to_event(row: WorkflowEventRow) -> WorkflowEvent:
    return WorkflowEvent(
        id=row.id,
        workflow_run_id=row.workflow_run_id,
        sequence=row.sequence,
        node_name=row.node_name,
        event_type=row.event_type,
        attempt_number=row.attempt_number,
        duration_ms=row.duration_ms,
        outcome=row.outcome,
        trace_id=row.trace_id,
        span_id=row.span_id,
        error_type=row.error_type,
        created_at=row.created_at,
    )
