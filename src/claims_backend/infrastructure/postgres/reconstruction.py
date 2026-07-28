from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.domain.reconstruction import ClaimReconstruction
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    CasefileRow,
    ClaimRow,
    ClaimVersionRow,
    ClaimWorkItemRow,
    ComponentFailureRow,
    DecisionRecordRow,
    DocumentRow,
    DocumentVersionRow,
    MemberActionRow,
    ModelExtractionRow,
    PolicyOverlayRow,
    PolicySourceRow,
    PolicyVersionRow,
    ReviewResolutionRow,
    ReviewTaskRow,
    RuleResultRow,
    WorkflowEffectRow,
    WorkflowEventRow,
    WorkflowRunRow,
)


class PostgresClaimReconstructor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def reconstruct(self, claim_id: UUID) -> ClaimReconstruction | None:
        async with self._session_factory() as session:
            claim = await session.get(ClaimRow, claim_id)
            if claim is None:
                return None
            version = (
                await session.scalars(
                    select(ClaimVersionRow).where(
                        ClaimVersionRow.claim_id == claim.id,
                        ClaimVersionRow.version == claim.current_version,
                    )
                )
            ).one()
            work = await session.scalar(
                select(ClaimWorkItemRow).where(
                    ClaimWorkItemRow.claim_id == claim.id,
                    ClaimWorkItemRow.claim_version == claim.current_version,
                )
            )
            workflow = (
                None
                if work is None
                else await session.scalar(
                    select(WorkflowRunRow).where(WorkflowRunRow.work_item_id == work.id)
                )
            )
            workflow_events = (
                []
                if workflow is None
                else (
                    await session.scalars(
                        select(WorkflowEventRow)
                        .where(WorkflowEventRow.workflow_run_id == workflow.id)
                        .order_by(WorkflowEventRow.sequence)
                    )
                ).all()
            )
            workflow_effects = (
                []
                if workflow is None
                else (
                    await session.scalars(
                        select(WorkflowEffectRow)
                        .where(WorkflowEffectRow.workflow_run_id == workflow.id)
                        .order_by(
                            WorkflowEffectRow.created_at,
                            WorkflowEffectRow.id,
                        )
                    )
                ).all()
            )
            audits = (
                await session.scalars(
                    select(AuditEventRow)
                    .where(AuditEventRow.claim_id == claim.id)
                    .order_by(AuditEventRow.sequence)
                )
            ).all()
            casefile = await session.scalar(
                select(CasefileRow).where(
                    CasefileRow.claim_id == claim.id,
                    CasefileRow.claim_version == claim.current_version,
                )
            )
            policy = (
                None
                if claim.policy_version_id is None
                else await session.get(PolicyVersionRow, claim.policy_version_id)
            )
            policy_source = (
                None
                if policy is None
                else await session.get(PolicySourceRow, policy.policy_source_id)
            )
            policy_overlay = (
                None
                if policy is None
                else await session.get(PolicyOverlayRow, policy.policy_overlay_id)
            )
            decision = await session.scalar(
                select(DecisionRecordRow).where(
                    DecisionRecordRow.claim_id == claim.id,
                    DecisionRecordRow.claim_version == claim.current_version,
                )
            )
            rules = (
                []
                if decision is None
                else (
                    await session.scalars(
                        select(RuleResultRow)
                        .where(RuleResultRow.decision_record_id == decision.id)
                        .order_by(RuleResultRow.sequence)
                    )
                ).all()
            )
            failures = (
                []
                if decision is None
                else (
                    await session.scalars(
                        select(ComponentFailureRow)
                        .where(ComponentFailureRow.decision_record_id == decision.id)
                        .order_by(ComponentFailureRow.created_at, ComponentFailureRow.id)
                    )
                ).all()
            )
            actions = (
                await session.scalars(
                    select(MemberActionRow)
                    .where(MemberActionRow.claim_id == claim.id)
                    .order_by(MemberActionRow.claim_version, MemberActionRow.created_at)
                )
            ).all()
            review_task = await session.scalar(
                select(ReviewTaskRow).where(
                    ReviewTaskRow.claim_id == claim.id,
                    ReviewTaskRow.claim_version == claim.current_version,
                )
            )
            resolutions = (
                []
                if review_task is None
                else (
                    await session.scalars(
                        select(ReviewResolutionRow)
                        .where(ReviewResolutionRow.task_id == review_task.id)
                        .order_by(ReviewResolutionRow.created_at)
                    )
                ).all()
            )
            model_extractions = (
                await session.scalars(
                    select(ModelExtractionRow)
                    .join(
                        DocumentVersionRow,
                        DocumentVersionRow.id == ModelExtractionRow.document_version_id,
                    )
                    .join(DocumentRow, DocumentRow.id == DocumentVersionRow.document_id)
                    .where(DocumentRow.claim_id == claim.id)
                    .order_by(
                        ModelExtractionRow.created_at,
                        ModelExtractionRow.id,
                    )
                )
            ).all()

        casefile_value: dict[str, object] | None = (
            None
            if casefile is None
            else {
                "id": str(casefile.id),
                "content_hash": casefile.content_hash,
                "policy_version_id": str(casefile.policy_version_id),
                "member_version_id": str(casefile.member_version_id),
                "content": casefile.content,
                "created_at": casefile.created_at.isoformat(),
            }
        )
        evidence_references: set[str] = set()
        if casefile_value is not None:
            _collect_evidence_references(casefile_value, evidence_references)
        for rule in rules:
            evidence_references.update(rule.evidence_refs)
        return ClaimReconstruction(
            claim_id=claim.id,
            claim_version=claim.current_version,
            claim=_claim_value(claim),
            submission=version.submission,
            policy=(
                None if policy is None else _policy_value(policy, policy_source, policy_overlay)
            ),
            work_item=(None if work is None else _work_value(work)),
            workflow=(None if workflow is None else _workflow_value(workflow)),
            workflow_events=tuple(_workflow_event_value(row) for row in workflow_events),
            workflow_effects=tuple(_workflow_effect_value(row) for row in workflow_effects),
            audit_events=tuple(_audit_value(row) for row in audits),
            casefile=casefile_value,
            evidence_references=tuple(sorted(evidence_references)),
            model_extractions=tuple(_model_value(row) for row in model_extractions),
            decision=(None if decision is None else _decision_value(decision)),
            rule_results=tuple(_rule_value(row) for row in rules),
            component_failures=tuple(_failure_value(row) for row in failures),
            member_actions=tuple(_action_value(row) for row in actions),
            review_task=(None if review_task is None else _review_task_value(review_task)),
            review_resolutions=tuple(_resolution_value(row) for row in resolutions),
        )


def _claim_value(row: ClaimRow) -> dict[str, object]:
    return {
        "member_id": row.member_id,
        "policy_id": row.policy_id,
        "policy_version_id": _uuid(row.policy_version_id),
        "member_version_id": _uuid(row.member_version_id),
        "category": row.category,
        "treatment_date": row.treatment_date.isoformat(),
        "claimed_paise": row.claimed_paise,
        "currency": row.currency,
        "lifecycle_status": row.lifecycle_status,
        "adjudication_recommendation": row.adjudication_recommendation,
        "approved_paise": row.approved_paise,
        "handling_status": row.handling_status,
        "processing_quality": row.processing_quality,
        "review_task_id": _uuid(row.review_task_id),
    }


def _policy_value(
    row: PolicyVersionRow,
    source: PolicySourceRow | None,
    overlay: PolicyOverlayRow | None,
) -> dict[str, object]:
    engine_contract_version = (
        row.ir.get("engine_contract_version") if isinstance(row.ir, dict) else None
    )
    return {
        "id": str(row.id),
        "policy_id": row.policy_id,
        "version": row.version,
        "status": row.status,
        "policy_source_id": str(row.policy_source_id),
        "policy_overlay_id": str(row.policy_overlay_id),
        "source_sha256": None if source is None else source.source_sha256,
        "overlay_sha256": None if overlay is None else overlay.source_sha256,
        "compiler_version": row.compiler_version,
        "ir_sha256": row.ir_sha256,
        "engine_contract_version": engine_contract_version,
    }


def _work_value(row: ClaimWorkItemRow) -> dict[str, object]:
    return {
        "id": str(row.id),
        "operation_key": row.operation_key,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "last_failure_code": row.last_failure_code,
    }


def _workflow_value(row: WorkflowRunRow) -> dict[str, object]:
    return {
        "id": str(row.id),
        "graph_name": row.graph_name,
        "graph_version": row.graph_version,
        "execution_contract": row.execution_contract,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "completed_at": _datetime(row.completed_at),
    }


def _workflow_event_value(row: WorkflowEventRow) -> dict[str, object]:
    return {
        "sequence": row.sequence,
        "node_name": row.node_name,
        "event_type": row.event_type,
        "attempt_number": row.attempt_number,
        "duration_ms": row.duration_ms,
        "outcome": row.outcome,
        "trace_id": row.trace_id,
        "span_id": row.span_id,
        "error_type": row.error_type,
        "created_at": row.created_at.isoformat(),
    }


def _workflow_effect_value(row: WorkflowEffectRow) -> dict[str, object]:
    return {
        "effect_key": row.effect_key,
        "effect_type": row.effect_type,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
    }


def _audit_value(row: AuditEventRow) -> dict[str, object]:
    return {
        "sequence": row.sequence,
        "event_type": row.event_type,
        "actor_user_id": str(row.actor_user_id),
        "actor_username": row.actor_username_snapshot,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
    }


def _decision_value(row: DecisionRecordRow) -> dict[str, object]:
    return {
        "id": str(row.id),
        "recommendation": row.recommendation,
        "lifecycle_status": row.lifecycle_status,
        "approved_paise": row.approved_paise,
        "currency": row.currency,
        "engine_version": row.engine_version,
        "canonical_hash": row.canonical_hash,
        "created_at": row.created_at.isoformat(),
    }


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


def _failure_value(row: ComponentFailureRow) -> dict[str, object]:
    return {
        "component": row.component,
        "criticality": row.criticality,
        "attempts": row.attempts,
        "failure_code": row.failure_code,
        "retryable": row.retryable,
        "completeness": row.completeness,
        "confidence": row.confidence,
        "effect_on_handling": row.effect_on_handling,
        "created_at": row.created_at.isoformat(),
    }


def _action_value(row: MemberActionRow) -> dict[str, object]:
    return {
        "claim_version": row.claim_version,
        "code": row.code,
        "message": row.message,
        "observed_document_roles": row.observed_document_roles,
        "required_document_roles": row.required_document_roles,
        "details": row.details,
        "created_at": row.created_at.isoformat(),
    }


def _review_task_value(row: ReviewTaskRow) -> dict[str, object]:
    return {
        "id": str(row.id),
        "status": row.status,
        "signal_codes": row.signal_codes,
        "allowed_actions": row.allowed_actions,
        "machine_recommendation": row.machine_recommendation,
        "machine_approved_paise": row.machine_approved_paise,
        "currency": row.currency,
        "created_at": row.created_at.isoformat(),
        "resolved_at": _datetime(row.resolved_at),
    }


def _resolution_value(row: ReviewResolutionRow) -> dict[str, object]:
    return {
        "id": str(row.id),
        "action": row.action,
        "reason_code": row.reason_code,
        "reason_note": row.reason_note,
        "before": row.before,
        "after": row.after,
        "actor_user_id": str(row.actor_user_id),
        "actor_username": row.actor_username_snapshot,
        "created_at": row.created_at.isoformat(),
    }


def _model_value(row: ModelExtractionRow) -> dict[str, object]:
    return {
        "route": row.route,
        "model_id": row.model_id,
        "region": row.region,
        "prompt_version": row.prompt_version,
        "schema_version": row.schema_version,
        "input_sha256": row.input_sha256,
        "provider_request_id": row.provider_request_id,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "latency_ms": row.latency_ms,
        "stop_reason": row.stop_reason,
    }


def _collect_evidence_references(value: object, target: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "evidence_refs" and isinstance(child, Sequence):
                target.update(str(item) for item in child if isinstance(item, str))
            else:
                _collect_evidence_references(child, target)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for child in value:
            _collect_evidence_references(child, target)


def _uuid(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
