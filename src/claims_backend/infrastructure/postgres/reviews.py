import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from opentelemetry.util.types import AttributeValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.reviews import (
    ReviewCommandIdempotencyConflictError,
    ReviewCommandInvalidError,
    ReviewStaleClaimVersionError,
    ReviewTaskNotFoundError,
    ReviewTaskNotOpenError,
)
from claims_backend.domain.identity import Principal
from claims_backend.domain.reviews import (
    ReviewAction,
    ReviewCommand,
    ReviewResolution,
    ReviewTaskDetail,
    ReviewTaskStatus,
    ReviewTaskSummary,
)
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    CasefileRow,
    ClaimRow,
    ClaimWorkItemRow,
    DecisionRecordRow,
    ReviewResolutionRow,
    ReviewTaskRow,
    RuleResultRow,
    WorkflowEventRow,
    WorkflowRunRow,
)
from claims_backend.observability import EngineeringLogEvent, Observability


class PostgresReviewRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        observability: Observability | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._observability = observability

    async def list_tasks(self) -> tuple[ReviewTaskSummary, ...]:
        with self._span("review.list", attributes={"review.operation": "LIST"}):
            async with self._session_factory() as session:
                rows = (
                    await session.scalars(
                        select(ReviewTaskRow).order_by(
                            ReviewTaskRow.created_at,
                            ReviewTaskRow.id,
                        )
                    )
                ).all()
        return tuple(_summary(row) for row in rows)

    async def get_task(self, task_id: UUID) -> ReviewTaskDetail | None:
        parent = await self._trace_parent(task_id)
        attributes: dict[str, AttributeValue] = {
            "review.operation": "INSPECT",
            "review.task_id": str(task_id),
        }
        if parent is not None:
            attributes["claim.id"] = str(parent.claim_id)
            attributes["workflow.run_id"] = str(parent.workflow_run_id)
        with self._span(
            "review.inspect",
            attributes=attributes,
            parent=parent,
        ):
            result = await self._get_task(task_id)
            self._log("review_task_inspected", parent, task_id, "OK")
            return result

    async def _get_task(self, task_id: UUID) -> ReviewTaskDetail | None:
        async with self._session_factory() as session:
            task = await session.scalar(select(ReviewTaskRow).where(ReviewTaskRow.id == task_id))
            if task is None:
                return None
            decision = await session.scalar(
                select(DecisionRecordRow).where(DecisionRecordRow.id == task.decision_record_id)
            )
            if decision is None:
                raise ReviewTaskNotFoundError
            casefile = await session.scalar(
                select(CasefileRow).where(CasefileRow.id == decision.casefile_id)
            )
            rules = (
                await session.scalars(
                    select(RuleResultRow)
                    .where(RuleResultRow.decision_record_id == decision.id)
                    .order_by(RuleResultRow.sequence)
                )
            ).all()
        content = {} if casefile is None else casefile.content
        evidence_value = content.get("evidence")
        evidence = evidence_value if isinstance(evidence_value, dict) else {}
        facts = evidence.get("facts")
        conflicts = (
            tuple(
                dict(item)
                for item in facts
                if isinstance(item, dict) and item.get("state") == "CONFLICT"
            )
            if isinstance(facts, list)
            else ()
        )
        rendered_rules = tuple(_rule_value(row) for row in rules)
        return ReviewTaskDetail(
            summary=_summary(task),
            evidence=evidence,
            conflicts=conflicts,
            rules=rendered_rules,
            calculations=tuple(
                item
                for item in rendered_rules
                if item["amount_before_paise"] != item["amount_after_paise"]
                or str(item["rule_id"]).startswith("amount.")
            ),
            failures=tuple(item for item in rendered_rules if item["status"] == "FAIL"),
        )

    async def resolve(
        self,
        task_id: UUID,
        command: ReviewCommand,
        principal: Principal,
        idempotency_key: str,
    ) -> ReviewResolution:
        parent = await self._trace_parent(task_id)
        attributes: dict[str, AttributeValue] = {
            "review.operation": "RESOLVE",
            "review.task_id": str(task_id),
            "review.action": command.action.value,
        }
        if parent is not None:
            attributes["claim.id"] = str(parent.claim_id)
            attributes["workflow.run_id"] = str(parent.workflow_run_id)
        with self._span(
            "review.resolve",
            attributes=attributes,
            parent=parent,
        ):
            result = await self._resolve(
                task_id,
                command,
                principal,
                idempotency_key,
            )
            self._log(
                "review_task_resolved",
                parent,
                task_id,
                "OK",
            )
            return result

    async def _resolve(
        self,
        task_id: UUID,
        command: ReviewCommand,
        principal: Principal,
        idempotency_key: str,
    ) -> ReviewResolution:
        request_hash = _request_hash(command)
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            task = await session.scalar(
                select(ReviewTaskRow).where(ReviewTaskRow.id == task_id).with_for_update()
            )
            if task is None:
                raise ReviewTaskNotFoundError
            existing = await session.scalar(
                select(ReviewResolutionRow).where(ReviewResolutionRow.task_id == task.id)
            )
            if existing is not None:
                if (
                    existing.actor_user_id == principal.user_id
                    and existing.idempotency_key == idempotency_key
                    and existing.request_hash != request_hash
                ):
                    raise ReviewCommandIdempotencyConflictError
                if (
                    existing.actor_user_id != principal.user_id
                    or existing.idempotency_key != idempotency_key
                ):
                    raise ReviewTaskNotOpenError
                return _resolution(existing, replayed=True)
            if task.status != ReviewTaskStatus.OPEN.value:
                raise ReviewTaskNotOpenError
            claim = await session.scalar(
                select(ClaimRow).where(ClaimRow.id == task.claim_id).with_for_update()
            )
            if claim is None:
                raise ReviewTaskNotFoundError
            if claim.current_version != command.expected_claim_version:
                raise ReviewStaleClaimVersionError(claim.current_version)
            allowed = {ReviewAction(value) for value in task.allowed_actions}
            if command.action not in allowed:
                raise ReviewTaskNotOpenError

            before = {
                "lifecycle_status": claim.lifecycle_status,
                "handling_status": claim.handling_status,
                "machine_recommendation": task.machine_recommendation,
                "machine_approved_paise": task.machine_approved_paise,
                "adjudication_recommendation": claim.adjudication_recommendation,
                "approved_paise": claim.approved_paise,
            }
            after = _resolved_values(command, task, claim)
            _apply_resolution(claim, command, after)
            task.status = ReviewTaskStatus.RESOLVED.value
            task.allowed_actions = []
            task.resolved_at = now
            row = ReviewResolutionRow(
                id=uuid4(),
                task_id=task.id,
                action=command.action.value,
                reason_code=command.reason_code,
                reason_note=command.reason_note,
                before=before,
                after=after,
                actor_user_id=principal.user_id,
                actor_username_snapshot=principal.username,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                created_at=now,
            )
            session.add(row)
            sequence = (
                await session.scalar(
                    select(func.max(AuditEventRow.sequence)).where(
                        AuditEventRow.claim_id == claim.id
                    )
                )
                or 0
            ) + 1
            session.add(
                AuditEventRow(
                    id=uuid4(),
                    actor_user_id=principal.user_id,
                    actor_username_snapshot=principal.username,
                    claim_id=claim.id,
                    sequence=sequence,
                    event_type="CLAIM_REVIEW_RESOLVED",
                    payload={
                        "review_task_id": str(task.id),
                        "resolution_id": str(row.id),
                        "action": command.action.value,
                        "reason_code": command.reason_code,
                        "before": before,
                        "after": after,
                    },
                    created_at=now,
                )
            )
            await session.flush((row,))
            return _resolution(row, replayed=False)

    async def _trace_parent(self, task_id: UUID) -> "_ReviewTraceParent | None":
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        ReviewTaskRow.claim_id,
                        WorkflowRunRow.id,
                        WorkflowEventRow.trace_id,
                        WorkflowEventRow.span_id,
                    )
                    .join(
                        ClaimWorkItemRow,
                        (ClaimWorkItemRow.claim_id == ReviewTaskRow.claim_id)
                        & (
                            ClaimWorkItemRow.claim_version
                            == ReviewTaskRow.claim_version
                        ),
                    )
                    .join(
                        WorkflowRunRow,
                        WorkflowRunRow.work_item_id == ClaimWorkItemRow.id,
                    )
                    .join(
                        WorkflowEventRow,
                        WorkflowEventRow.workflow_run_id == WorkflowRunRow.id,
                    )
                    .where(
                        ReviewTaskRow.id == task_id,
                        WorkflowEventRow.trace_id.is_not(None),
                        WorkflowEventRow.span_id.is_not(None),
                    )
                    .order_by(WorkflowEventRow.sequence)
                    .limit(1)
                )
            ).one_or_none()
        if row is None or row.trace_id is None or row.span_id is None:
            return None
        return _ReviewTraceParent(
            claim_id=row.claim_id,
            workflow_run_id=row.id,
            trace_id=row.trace_id,
            span_id=row.span_id,
        )

    @contextmanager
    def _span(
        self,
        name: str,
        *,
        attributes: Mapping[str, AttributeValue],
        parent: "_ReviewTraceParent | None" = None,
    ) -> Iterator[None]:
        if self._observability is None:
            yield
            return
        with self._observability.span(
            name,
            component="review",
            attributes=attributes,
            parent_trace_id=None if parent is None else parent.trace_id,
            parent_span_id=None if parent is None else parent.span_id,
        ):
            yield

    def _log(
        self,
        event_name: str,
        parent: "_ReviewTraceParent | None",
        task_id: UUID,
        outcome: str,
    ) -> None:
        if self._observability is None:
            return
        self._observability.log(
            EngineeringLogEvent(
                event_name=event_name,
                component="review",
                claim_id=None if parent is None else str(parent.claim_id),
                workflow_run_id=(
                    None if parent is None else str(parent.workflow_run_id)
                ),
                outcome=outcome,
            )
        )


class _ReviewTraceParent:
    def __init__(
        self,
        *,
        claim_id: UUID,
        workflow_run_id: UUID,
        trace_id: str,
        span_id: str,
    ) -> None:
        self.claim_id = claim_id
        self.workflow_run_id = workflow_run_id
        self.trace_id = trace_id
        self.span_id = span_id


def _resolved_values(
    command: ReviewCommand,
    task: ReviewTaskRow,
    claim: ClaimRow,
) -> dict[str, object]:
    if command.action is ReviewAction.ACCEPT:
        recommendation = task.machine_recommendation
        approved_paise = task.machine_approved_paise
        lifecycle = "DECIDED"
    elif command.action is ReviewAction.AMEND:
        if (
            command.amended_paise is None
            or command.amended_paise < 0
            or command.amended_paise > claim.claimed_paise
        ):
            raise ReviewCommandInvalidError
        approved_paise = command.amended_paise
        recommendation = (
            "REJECTED"
            if approved_paise == 0
            else "APPROVED"
            if approved_paise == claim.claimed_paise
            else "PARTIAL"
        )
        lifecycle = "DECIDED"
    elif command.action is ReviewAction.REJECT:
        recommendation = "REJECTED"
        approved_paise = 0
        lifecycle = "DECIDED"
    else:
        recommendation = None
        approved_paise = None
        lifecycle = "ACTION_REQUIRED"
    return {
        "lifecycle_status": lifecycle,
        "handling_status": "HUMAN_REVIEW_RESOLVED",
        "adjudication_recommendation": recommendation,
        "approved_paise": approved_paise,
    }


def _apply_resolution(
    claim: ClaimRow,
    command: ReviewCommand,
    after: dict[str, object],
) -> None:
    claim.lifecycle_status = str(after["lifecycle_status"])
    claim.handling_status = str(after["handling_status"])
    recommendation = after["adjudication_recommendation"]
    amount = after["approved_paise"]
    claim.adjudication_recommendation = None if recommendation is None else str(recommendation)
    claim.approved_paise = None if amount is None else int(str(amount))
    if command.action is ReviewAction.REQUEST_DOCUMENT:
        claim.current_action = {
            "code": "REVIEW_DOCUMENT_REQUIRED",
            "message": "A reviewer requested additional claim documentation.",
            "observed_document_roles": [],
            "required_document_roles": [],
        }
        claim.member_explanation = None
    else:
        claim.current_action = None
        claim.member_explanation = {
            "summary": "Human review of this claim is complete.",
            "deductions": [],
            "line_items": [],
        }
    claim.updated_at = datetime.now(UTC)


def _summary(row: ReviewTaskRow) -> ReviewTaskSummary:
    return ReviewTaskSummary(
        id=row.id,
        claim_id=row.claim_id,
        claim_version=row.claim_version,
        status=ReviewTaskStatus(row.status),
        signal_codes=tuple(row.signal_codes),
        machine_recommendation=row.machine_recommendation,
        machine_approved_paise=row.machine_approved_paise,
        currency=row.currency,
        allowed_actions=tuple(ReviewAction(value) for value in row.allowed_actions),
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _rule_value(row: RuleResultRow) -> dict[str, object]:
    return {
        "sequence": row.sequence,
        "rule_id": row.rule_id,
        "status": row.status,
        "reason_code": row.reason_code,
        "policy_path": row.policy_path,
        "evidence_refs": row.evidence_refs,
        "inputs": row.inputs,
        "amount_before_paise": row.amount_before_paise,
        "adjustment_paise": row.adjustment_paise,
        "amount_after_paise": row.amount_after_paise,
    }


def _request_hash(command: ReviewCommand) -> str:
    return sha256(
        json.dumps(
            {
                "action": command.action.value,
                "expected_claim_version": command.expected_claim_version,
                "reason_code": command.reason_code,
                "reason_note": command.reason_note,
                "amended_paise": command.amended_paise,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _resolution(
    row: ReviewResolutionRow,
    *,
    replayed: bool,
) -> ReviewResolution:
    return ReviewResolution(
        id=row.id,
        task_id=row.task_id,
        action=ReviewAction(row.action),
        reason_code=row.reason_code,
        reason_note=row.reason_note,
        before=row.before,
        after=row.after,
        actor_user_id=row.actor_user_id,
        actor_username=row.actor_username_snapshot,
        created_at=row.created_at,
        replayed=replayed,
    )
