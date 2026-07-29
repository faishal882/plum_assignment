import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from openinference.semconv.trace import SpanAttributes
from sqlalchemy.engine import make_url

from claims_backend.application.processing import ClaimProcessor
from claims_backend.application.work import LeaseLostError
from claims_backend.application.workflow import WorkflowRepository, WorkflowRuntime
from claims_backend.domain.processing import (
    AffectedDocument,
    EarlyGateResult,
    IdentityConflictDetail,
    ProcessingRoute,
)
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import (
    ExecutionContract,
    NewWorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)
from claims_backend.observability import (
    EngineeringLogEvent,
    Observability,
    trace_identifiers,
)

type BeforeNodeHook = Callable[[str], Awaitable[None]]
type WorkflowNode = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class WorkflowRuntimeContext:
    """Ephemeral execution authority; never persisted in a LangGraph checkpoint."""

    lease: WorkLease
    workflow_run_id: UUID
    claim_id: UUID
    claim_version: int


_ACTIVE_RUNTIME_CONTEXT: ContextVar[WorkflowRuntimeContext] = ContextVar(
    "claims_workflow_runtime_context"
)

_NODE_COMPONENTS = {
    "load_claim": "persistence",
    "finalize": "persistence",
    "media_inspect": "document_intelligence",
    "freeze_casefile": "reconciliation",
    "adjudicate": "policy",
    "commit_decision": "persistence",
    "triage_documents": "identity",
    "render_documents": "document_intelligence",
    "discover_documents": "textract",
    "ocr_documents": "textract",
    "extract_evidence": "bedrock",
    "reconcile_casefile": "reconciliation",
    "commit_member_action": "persistence",
}
_TERMINAL_COMMIT_NODES = frozenset({"commit_decision", "commit_member_action"})


class WorkflowState(TypedDict):
    workflow_run_id: str
    claim_id: str
    claim_version: int
    work_item_id: str
    operation_key: str
    claim_loaded: bool
    finalized: bool
    route: str
    media_inspected: bool
    casefile_id: str
    casefile_hash: str
    proposal_hash: str
    action_required: bool
    action_code: str
    action_message: str
    observed_roles: list[str]
    required_roles: list[str]
    affected_documents: list[dict[str, str]]
    identity_conflict: list[dict[str, str]]
    rendered_page_count: int
    discovery_observation_count: int
    ocr_observation_count: int
    evidence_candidate_count: int
    extraction_completed: bool
    terminal_committed: bool
    effect_count: int


class WorkflowUpdate(TypedDict, total=False):
    claim_loaded: bool
    finalized: bool
    route: str
    media_inspected: bool
    casefile_id: str
    casefile_hash: str
    proposal_hash: str
    action_required: bool
    action_code: str
    action_message: str
    observed_roles: list[str]
    required_roles: list[str]
    affected_documents: list[dict[str, str]]
    identity_conflict: list[dict[str, str]]
    rendered_page_count: int
    discovery_observation_count: int
    ocr_observation_count: int
    evidence_candidate_count: int
    extraction_completed: bool
    terminal_committed: bool
    effect_count: int


class LangGraphClaimWorkflow(WorkflowRuntime):
    graph_name = "claim-processing"
    graph_version = "claim-processing-v7"

    def __init__(
        self,
        database_url: str,
        repository: WorkflowRepository,
        *,
        processor: ClaimProcessor | None = None,
        before_node: BeforeNodeHook | None = None,
        after_effect: BeforeNodeHook | None = None,
        observability: Observability | None = None,
        execution_profile: str = "UNSPECIFIED",
        execution_contract: ExecutionContract | None = None,
    ) -> None:
        self._checkpoint_url = _checkpoint_url(database_url)
        self._repository = repository
        self._processor = processor
        self._before_node = before_node or _no_op_hook
        self._after_effect = after_effect or _no_op_hook
        self._observability = observability
        self._execution_profile = execution_profile
        self.execution_contract = execution_contract or ExecutionContract.unspecified()

    async def setup(self) -> None:
        async with AsyncPostgresSaver.from_conn_string(self._checkpoint_url) as checkpointer:
            await checkpointer.setup()

    async def run(
        self,
        workflow_run: WorkflowRun,
        lease: WorkLease,
        *,
        resume: bool,
    ) -> bool:
        async with AsyncPostgresSaver.from_conn_string(self._checkpoint_url) as checkpointer:
            builder = StateGraph(WorkflowState, context_schema=WorkflowRuntimeContext)
            builder.add_node("load_claim", self._node("load_claim", self._load_claim))
            builder.add_node("finalize", self._node("finalize", self._finalize))
            if self._processor is None:
                builder.add_edge("load_claim", "finalize")
            else:
                builder.add_node(
                    "media_inspect",
                    self._node("media_inspect", self._media_inspect),
                )
                builder.add_node(
                    "freeze_casefile",
                    self._node("freeze_casefile", self._freeze_casefile),
                )
                builder.add_node(
                    "adjudicate",
                    self._node("adjudicate", self._adjudicate),
                )
                builder.add_node(
                    "commit_decision",
                    self._node("commit_decision", self._commit_decision),
                )
                builder.add_node(
                    "triage_documents",
                    self._node("triage_documents", self._triage_documents),
                )
                builder.add_node(
                    "render_documents",
                    self._node("render_documents", self._render_documents),
                )
                builder.add_node(
                    "discover_documents",
                    self._node("discover_documents", self._discover_documents),
                )
                builder.add_node(
                    "ocr_documents",
                    self._node("ocr_documents", self._ocr_documents),
                )
                builder.add_node(
                    "extract_evidence",
                    self._node("extract_evidence", self._extract_evidence),
                )
                builder.add_node(
                    "reconcile_casefile",
                    self._node("reconcile_casefile", self._reconcile_casefile),
                )
                builder.add_node(
                    "commit_member_action",
                    self._node("commit_member_action", self._commit_member_action),
                )
                builder.add_edge("load_claim", "media_inspect")
                builder.add_conditional_edges(
                    "media_inspect",
                    _after_media_inspection,
                    {
                        "freeze_casefile": "freeze_casefile",
                        "triage_documents": "triage_documents",
                        "render_documents": "render_documents",
                        "finalize": "finalize",
                    },
                )
                builder.add_edge("freeze_casefile", "adjudicate")
                builder.add_edge("adjudicate", "commit_decision")
                builder.add_edge("commit_decision", END)
                builder.add_conditional_edges(
                    "triage_documents",
                    _after_triage,
                    {
                        "commit_member_action": "commit_member_action",
                        "render_documents": "render_documents",
                    },
                )
                builder.add_conditional_edges(
                    "render_documents",
                    _after_rendering,
                    {
                        "commit_member_action": "commit_member_action",
                        "ocr_documents": "ocr_documents",
                        "discover_documents": "discover_documents",
                    },
                )
                builder.add_edge("discover_documents", "triage_documents")
                builder.add_edge("ocr_documents", "extract_evidence")
                builder.add_conditional_edges(
                    "extract_evidence",
                    _after_extraction,
                    {
                        "reconcile_casefile": "reconcile_casefile",
                        "finalize": "finalize",
                    },
                )
                builder.add_conditional_edges(
                    "reconcile_casefile",
                    _after_reconciliation,
                    {
                        "commit_member_action": "commit_member_action",
                        "adjudicate": "adjudicate",
                    },
                )
                builder.add_edge("commit_member_action", END)
            builder.add_edge(START, "load_claim")
            builder.add_edge("finalize", END)
            graph = builder.compile(
                checkpointer=checkpointer,
                name=self.graph_name,
            )
            config: RunnableConfig = {
                "configurable": {
                    "thread_id": str(workflow_run.id),
                }
            }
            runtime_context = WorkflowRuntimeContext(
                lease=lease,
                workflow_run_id=workflow_run.id,
                claim_id=workflow_run.claim_id,
                claim_version=workflow_run.claim_version,
            )
            initial_state: WorkflowState | None = None
            if not resume:
                initial_state = {
                    "workflow_run_id": str(workflow_run.id),
                    "claim_id": str(workflow_run.claim_id),
                    "claim_version": workflow_run.claim_version,
                    "work_item_id": str(workflow_run.work_item_id),
                    "operation_key": workflow_run.operation_key,
                    "claim_loaded": False,
                    "finalized": False,
                    "route": ProcessingRoute.NONE.value,
                    "media_inspected": False,
                    "casefile_id": "",
                    "casefile_hash": "",
                    "proposal_hash": "",
                    "action_required": False,
                    "action_code": "",
                    "action_message": "",
                    "observed_roles": [],
                    "required_roles": [],
                    "affected_documents": [],
                    "identity_conflict": [],
                    "rendered_page_count": 0,
                    "discovery_observation_count": 0,
                    "ocr_observation_count": 0,
                    "evidence_candidate_count": 0,
                    "extraction_completed": False,
                    "terminal_committed": False,
                    "effect_count": 0,
                }
            if self._observability is None:
                result = await graph.ainvoke(initial_state, config=config, context=runtime_context)
            else:
                started = monotonic()
                root_attributes: dict[str, str | int] = {
                    "session.id": str(workflow_run.claim_id),
                    "claim.id": str(workflow_run.claim_id),
                    "claim.version": workflow_run.claim_version,
                    "workflow.run_id": str(workflow_run.id),
                    "workflow.graph_name": self.graph_name,
                    "workflow.graph_version": self.graph_version,
                    "workflow.execution_profile": self._execution_profile,
                    "work.attempt": lease.attempt_number,
                    "work.lease_id.sha256": _lease_id_sha256(lease),
                    "lease.validation.outcome": "NOT_EVALUATED",
                    "terminal.commit.outcome": "NOT_COMMITTED",
                    "workflow.queue_wait_ms": max(
                        0,
                        round((lease.leased_at - lease.available_at).total_seconds() * 1000),
                    ),
                    SpanAttributes.INPUT_VALUE: _json(
                        initial_state
                        if initial_state is not None
                        else {
                            "resume": True,
                            "claim_id": str(workflow_run.claim_id),
                            "workflow_run_id": str(workflow_run.id),
                        }
                    ),
                    SpanAttributes.INPUT_MIME_TYPE: "application/json",
                }
                with self._observability.span(
                    "claim.workflow",
                    component="workflow",
                    attributes=root_attributes,
                ) as root_span:
                    self._observability.log(
                        EngineeringLogEvent(
                            event_name="workflow_started",
                            component="workflow",
                            claim_id=str(workflow_run.claim_id),
                            workflow_run_id=str(workflow_run.id),
                            attempt=lease.attempt_number,
                            duration_ms=0,
                            outcome="RUNNING",
                            lease_id_sha256=_lease_id_sha256(lease),
                            lease_validation_outcome="NOT_EVALUATED",
                            terminal_commit_outcome="NOT_COMMITTED",
                        )
                    )
                    try:
                        result = await graph.ainvoke(
                            initial_state, config=config, context=runtime_context
                        )
                    except Exception as error:
                        self._observability.set_attributes(
                            root_span,
                            _terminal_outcome_attributes(
                                node_name=None,
                                error=error,
                            ),
                        )
                        self._observability.log(
                            EngineeringLogEvent(
                                event_name="workflow_failed",
                                component="workflow",
                                claim_id=str(workflow_run.claim_id),
                                workflow_run_id=str(workflow_run.id),
                                attempt=lease.attempt_number,
                                duration_ms=max(
                                    0,
                                    round((monotonic() - started) * 1000),
                                ),
                                outcome="ERROR",
                                error_type=type(error).__name__,
                                lease_id_sha256=_lease_id_sha256(lease),
                                lease_validation_outcome=(
                                    "REJECTED_STALE"
                                    if isinstance(error, LeaseLostError)
                                    else "NOT_EVALUATED"
                                ),
                                terminal_commit_outcome="NOT_COMMITTED",
                            )
                        )
                        raise
                    self._observability.log(
                        EngineeringLogEvent(
                            event_name="workflow_finished",
                            component="workflow",
                            claim_id=str(workflow_run.claim_id),
                            workflow_run_id=str(workflow_run.id),
                            attempt=lease.attempt_number,
                            duration_ms=max(
                                0,
                                round((monotonic() - started) * 1000),
                            ),
                            outcome="OK",
                            lease_id_sha256=_lease_id_sha256(lease),
                            lease_validation_outcome=(
                                "ACCEPTED" if result["terminal_committed"] else "NOT_EVALUATED"
                            ),
                            terminal_commit_outcome=(
                                "COMMITTED" if result["terminal_committed"] else "NOT_COMMITTED"
                            ),
                        )
                    )
                    self._observability.set_attributes(
                        root_span,
                        {
                            "workflow.terminal_outcome": (
                                "COMMITTED" if result["terminal_committed"] else "FINALIZED"
                            ),
                            "lease.validation.outcome": (
                                "ACCEPTED" if result["terminal_committed"] else "NOT_EVALUATED"
                            ),
                            "terminal.commit.outcome": (
                                "COMMITTED" if result["terminal_committed"] else "NOT_COMMITTED"
                            ),
                            SpanAttributes.OUTPUT_VALUE: _json(result),
                            SpanAttributes.OUTPUT_MIME_TYPE: "application/json",
                        },
                    )
            if not result["finalized"] and not result["terminal_committed"]:
                raise WorkflowIncompleteError
            return bool(result["terminal_committed"])

    def _node(self, node_name: str, handler: WorkflowNode) -> WorkflowNode:
        async def observed(
            state: WorkflowState, runtime: Runtime[WorkflowRuntimeContext]
        ) -> WorkflowUpdate:
            context_token = _ACTIVE_RUNTIME_CONTEXT.set(runtime.context)
            started = monotonic()
            run_id = _workflow_run_id(state)
            try:
                if self._observability is None:
                    await self._repository.record_event(
                        run_id,
                        NewWorkflowEvent(
                            node_name=node_name,
                            event_type="ENTRY",
                            attempt_number=runtime.context.lease.attempt_number,
                            duration_ms=0,
                            outcome="RUNNING",
                            trace_id=None,
                            span_id=None,
                        ),
                    )
                    try:
                        result = cast(WorkflowUpdate, await handler(state))
                    except Exception as error:
                        await self._record_node_event(
                            state,
                            node_name=node_name,
                            event_type="ERROR",
                            started=started,
                            outcome="ERROR",
                            error_type=type(error).__name__,
                        )
                        raise
                    await self._record_node_event(
                        state,
                        node_name=node_name,
                        event_type="EXIT",
                        started=started,
                        outcome="OK",
                    )
                    return result

                with self._observability.span(
                    f"claim.workflow.{node_name}",
                    component=_NODE_COMPONENTS[node_name],
                    attributes={
                        "session.id": state["claim_id"],
                        "claim.id": state["claim_id"],
                        "claim.version": state["claim_version"],
                        "workflow.run_id": state["workflow_run_id"],
                        "node.name": node_name,
                        "work.attempt": runtime.context.lease.attempt_number,
                        "work.lease_id.sha256": _lease_id_sha256(runtime.context.lease),
                        **_terminal_outcome_attributes(node_name=node_name),
                        SpanAttributes.INPUT_VALUE: _json(state),
                        SpanAttributes.INPUT_MIME_TYPE: "application/json",
                    },
                ) as node_span:
                    trace_id, span_id = trace_identifiers()
                    (
                        await self._repository.record_event(
                            run_id,
                            NewWorkflowEvent(
                                node_name=node_name,
                                event_type="ENTRY",
                                attempt_number=runtime.context.lease.attempt_number,
                                duration_ms=0,
                                outcome="RUNNING",
                                trace_id=trace_id,
                                span_id=span_id,
                            ),
                        ),
                    )
                    self._log_node(state, node_name, "node_entered", 0, "RUNNING")
                    try:
                        result = cast(WorkflowUpdate, await handler(state))
                    except Exception as error:
                        duration_ms = max(0, round((monotonic() - started) * 1000))
                        await self._record_node_event(
                            state,
                            node_name=node_name,
                            event_type="ERROR",
                            started=started,
                            outcome="ERROR",
                            error_type=type(error).__name__,
                        )
                        self._log_node(
                            state,
                            node_name,
                            "node_failed",
                            duration_ms,
                            "ERROR",
                            error_type=type(error).__name__,
                            error=error,
                        )
                        self._observability.set_attributes(
                            node_span,
                            _terminal_outcome_attributes(node_name=node_name, error=error),
                        )
                        raise
                    duration_ms = max(0, round((monotonic() - started) * 1000))
                    await self._record_node_event(
                        state, node_name=node_name, event_type="EXIT", started=started, outcome="OK"
                    )
                    self._log_node(state, node_name, "node_finished", duration_ms, "OK")
                    self._observability.set_attributes(
                        node_span,
                        {
                            **_terminal_outcome_attributes(node_name=node_name, committed=True),
                            SpanAttributes.OUTPUT_VALUE: _json(result),
                            SpanAttributes.OUTPUT_MIME_TYPE: "application/json",
                        },
                    )
                    return result
            finally:
                _ACTIVE_RUNTIME_CONTEXT.reset(context_token)

        return observed

    async def _record_node_event(
        self,
        state: WorkflowState,
        *,
        node_name: str,
        event_type: str,
        started: float,
        outcome: str,
        error_type: str | None = None,
    ) -> None:
        trace_id, span_id = trace_identifiers()
        await self._repository.record_event(
            _workflow_run_id(state),
            NewWorkflowEvent(
                node_name=node_name,
                event_type=event_type,
                attempt_number=_active_lease().attempt_number,
                duration_ms=max(0, round((monotonic() - started) * 1000)),
                outcome=outcome,
                trace_id=trace_id,
                span_id=span_id,
                error_type=error_type,
            ),
        )

    def _log_node(
        self,
        state: WorkflowState,
        node_name: str,
        event_name: str,
        duration_ms: int,
        outcome: str,
        *,
        error_type: str | None = None,
        error: Exception | None = None,
    ) -> None:
        if self._observability is None:
            return
        self._observability.log(
            EngineeringLogEvent(
                event_name=event_name,
                component=f"workflow.{node_name}",
                claim_id=state["claim_id"],
                workflow_run_id=state["workflow_run_id"],
                attempt=_active_lease().attempt_number,
                duration_ms=duration_ms,
                outcome=outcome,
                error_type=error_type,
                lease_id_sha256=_lease_id_sha256(_active_lease()),
                lease_validation_outcome=_terminal_outcome_attributes(
                    node_name=node_name,
                    error=error,
                )["lease.validation.outcome"],
                terminal_commit_outcome=_terminal_outcome_attributes(
                    node_name=node_name,
                    error=error,
                    committed=(event_name == "node_finished"),
                )["terminal.commit.outcome"],
            )
        )

    async def _load_claim(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("load_claim")
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"claim-loaded:v{state['claim_version']}",
            "CLAIM_VERSION_LOADED",
            {
                "claim_id": state["claim_id"],
                "claim_version": state["claim_version"],
                "work_item_id": state["work_item_id"],
            },
        )
        await self._after_effect("load_claim")
        return {
            "claim_loaded": True,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _finalize(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("finalize")
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"skeleton-completed:v{state['claim_version']}",
            "WORKFLOW_SKELETON_COMPLETED",
            {
                "claim_id": state["claim_id"],
                "claim_version": state["claim_version"],
                "operation_key": state["operation_key"],
            },
        )
        await self._after_effect("finalize")
        return {
            "finalized": True,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _media_inspect(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("media_inspect")
        processor = self._required_processor()
        run = _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        inspection = await processor.inspect_media(run)
        route = await processor.route(run)
        created = await self._repository.record_effect(
            run.id,
            f"media-inspected:v{state['claim_version']}",
            "LOCAL_MEDIA_INSPECTED",
            {**inspection, "route": route.value},
        )
        await self._after_effect("media_inspect")
        return {
            "media_inspected": True,
            "route": route.value,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _freeze_casefile(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("freeze_casefile")
        processor = self._required_processor()
        reference = await processor.freeze_casefile(
            _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        )
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"casefile-frozen:v{state['claim_version']}",
            "CASEFILE_FROZEN",
            {
                "casefile_id": str(reference.id),
                "content_hash": reference.content_hash,
            },
        )
        await self._after_effect("freeze_casefile")
        return {
            "casefile_id": str(reference.id),
            "casefile_hash": reference.content_hash,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _adjudicate(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("adjudicate")
        proposal_hash = await self._required_processor().evaluate_casefile(
            UUID(state["casefile_id"])
        )
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"adjudication-proposed:v{state['claim_version']}",
            "ADJUDICATION_PROPOSED",
            {
                "casefile_id": state["casefile_id"],
                "proposal_hash": proposal_hash,
            },
        )
        await self._after_effect("adjudicate")
        return {
            "proposal_hash": proposal_hash,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _commit_decision(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("commit_decision")
        run = _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        await self._required_processor().commit_decision(
            run,
            _work_lease(state),
            UUID(state["casefile_id"]),
        )
        await self._after_effect("commit_decision")
        return {"terminal_committed": True}

    async def _triage_documents(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("triage_documents")
        result = await self._required_processor().triage_documents(
            _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        )
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"document-triage-completed:v{state['claim_version']}",
            "DOCUMENT_TRIAGE_COMPLETED",
            {
                "action_required": result.action_required,
                "observed_document_roles": list(result.observed_roles),
                "required_document_roles": list(result.required_roles),
            },
        )
        await self._after_effect("triage_documents")
        return {
            "action_required": result.action_required,
            "action_code": result.code or "",
            "action_message": result.message or "",
            "observed_roles": list(result.observed_roles),
            "required_roles": list(result.required_roles),
            "affected_documents": [
                {
                    "client_document_id": document.client_document_id,
                    "observed_role": document.observed_role,
                    "requested_action": document.requested_action,
                }
                for document in result.affected_documents
            ],
            "identity_conflict": [
                {
                    "client_document_id": item.client_document_id,
                    "patient_name": item.patient_name,
                }
                for item in result.identity_conflict
            ],
            "effect_count": state["effect_count"] + int(created),
        }

    async def _commit_member_action(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("commit_member_action")
        run = _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        await self._required_processor().commit_member_action(
            run,
            _work_lease(state),
            EarlyGateResult(
                action_required=state["action_required"],
                code=state["action_code"],
                message=state["action_message"],
                observed_roles=tuple(state["observed_roles"]),
                required_roles=tuple(state["required_roles"]),
                affected_documents=tuple(
                    AffectedDocument(
                        client_document_id=document["client_document_id"],
                        observed_role=document["observed_role"],
                        requested_action=document["requested_action"],
                    )
                    for document in state["affected_documents"]
                ),
                identity_conflict=tuple(
                    IdentityConflictDetail(
                        client_document_id=item["client_document_id"],
                        patient_name=item["patient_name"],
                    )
                    for item in state["identity_conflict"]
                ),
            ),
        )
        await self._after_effect("commit_member_action")
        return {"terminal_committed": True}

    async def _render_documents(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("render_documents")
        result = await self._required_processor().render_documents(
            _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        )
        action = result.action
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"document-pages-prepared:v{state['claim_version']}",
            ("DOCUMENT_RENDERING_BLOCKED" if action is not None else "DOCUMENT_PAGES_RENDERED"),
            {
                "rendered_page_count": result.rendered_page_count,
                "action_required": action is not None,
                "action_code": None if action is None else action.code,
            },
        )
        await self._after_effect("render_documents")
        if action is None:
            return {
                "rendered_page_count": result.rendered_page_count,
                "effect_count": state["effect_count"] + int(created),
            }
        return {
            "rendered_page_count": result.rendered_page_count,
            "action_required": True,
            "action_code": action.code or "",
            "action_message": action.message or "",
            "observed_roles": list(action.observed_roles),
            "required_roles": list(action.required_roles),
            "affected_documents": [
                {
                    "client_document_id": document.client_document_id,
                    "observed_role": document.observed_role,
                    "requested_action": document.requested_action,
                }
                for document in action.affected_documents
            ],
            "identity_conflict": [],
            "effect_count": state["effect_count"] + int(created),
        }

    async def _ocr_documents(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("ocr_documents")
        observation_count = await self._required_processor().ocr_documents(
            _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        )
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"page-ocr-completed:v{state['claim_version']}",
            "PAGE_OCR_COMPLETED",
            {
                "rendered_page_count": state["rendered_page_count"],
                "observation_count": observation_count,
            },
        )
        await self._after_effect("ocr_documents")
        return {
            "ocr_observation_count": observation_count,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _discover_documents(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("discover_documents")
        observation_count = await self._required_processor().discover_documents(
            _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        )
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"discovery-ocr-completed:v{state['claim_version']}",
            "DISCOVERY_OCR_COMPLETED",
            {
                "rendered_page_count": state["rendered_page_count"],
                "observation_count": observation_count,
            },
        )
        await self._after_effect("discover_documents")
        return {
            "discovery_observation_count": observation_count,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _extract_evidence(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("extract_evidence")
        candidate_count = await self._required_processor().extract_evidence(
            _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        )
        if candidate_count is None:
            return {}
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"structured-extraction-completed:v{state['claim_version']}",
            "STRUCTURED_EXTRACTION_COMPLETED",
            {
                "ocr_observation_count": state["ocr_observation_count"],
                "evidence_candidate_count": candidate_count,
            },
        )
        await self._after_effect("extract_evidence")
        return {
            "evidence_candidate_count": candidate_count,
            "extraction_completed": True,
            "effect_count": state["effect_count"] + int(created),
        }

    async def _reconcile_casefile(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("reconcile_casefile")
        result = await self._required_processor().reconcile_casefile(
            _workflow_run(state, self.graph_name, self.graph_version, self.execution_contract)
        )
        if result.reference is not None:
            reconciled = await self._repository.record_effect(
                _workflow_run_id(state),
                f"evidence-reconciled:v{state['claim_version']}",
                "EVIDENCE_RECONCILED",
                {
                    "evidence_candidate_count": state["evidence_candidate_count"],
                    "sufficient": True,
                },
            )
            frozen = await self._repository.record_effect(
                _workflow_run_id(state),
                f"casefile-frozen:v{state['claim_version']}",
                "CASEFILE_FROZEN",
                {
                    "casefile_id": str(result.reference.id),
                    "content_hash": result.reference.content_hash,
                },
            )
            await self._after_effect("reconcile_casefile")
            return {
                "casefile_id": str(result.reference.id),
                "casefile_hash": result.reference.content_hash,
                "effect_count": state["effect_count"] + int(reconciled) + int(frozen),
            }
        action = result.action
        if action is None:
            raise WorkflowIncompleteError("Reconciliation produced no terminal result.")
        created = await self._repository.record_effect(
            _workflow_run_id(state),
            f"evidence-reconciliation-required:v{state['claim_version']}",
            "EVIDENCE_RECONCILIATION_REQUIRED",
            {
                "evidence_candidate_count": state["evidence_candidate_count"],
                "sufficient": False,
                "action_code": action.code,
            },
        )
        await self._after_effect("reconcile_casefile")
        return {
            "action_required": True,
            "action_code": action.code or "",
            "action_message": action.message or "",
            "observed_roles": list(action.observed_roles),
            "required_roles": list(action.required_roles),
            "affected_documents": [],
            "identity_conflict": [],
            "effect_count": state["effect_count"] + int(created),
        }

    def _required_processor(self) -> ClaimProcessor:
        if self._processor is None:
            raise WorkflowIncompleteError
        return self._processor


class WorkflowIncompleteError(Exception):
    pass


async def _no_op_hook(_: str) -> None:
    return None


def _workflow_run_id(state: WorkflowState) -> UUID:
    return UUID(state["workflow_run_id"])


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _workflow_run(
    state: WorkflowState,
    graph_name: str,
    graph_version: str,
    execution_contract: ExecutionContract,
) -> WorkflowRun:
    return WorkflowRun(
        id=_workflow_run_id(state),
        work_item_id=UUID(state["work_item_id"]),
        claim_id=UUID(state["claim_id"]),
        claim_version=state["claim_version"],
        operation_key=state["operation_key"],
        graph_name=graph_name,
        graph_version=graph_version,
        execution_contract=execution_contract,
        status=WorkflowRunStatus.RUNNING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        completed_at=None,
    )


def _work_lease(_: WorkflowState) -> WorkLease:
    return _active_lease()


def _active_lease() -> WorkLease:
    return _ACTIVE_RUNTIME_CONTEXT.get().lease


def _lease_id_sha256(lease: WorkLease) -> str:
    return sha256(str(lease.lease_token).encode("ascii")).hexdigest()


def _terminal_outcome_attributes(
    *,
    node_name: str | None,
    error: Exception | None = None,
    committed: bool = False,
) -> dict[str, str]:
    if isinstance(error, LeaseLostError):
        return {
            "lease.validation.outcome": "REJECTED_STALE",
            "terminal.commit.outcome": "NOT_COMMITTED",
        }
    if node_name in _TERMINAL_COMMIT_NODES:
        return {
            "lease.validation.outcome": "ACCEPTED" if committed else "NOT_EVALUATED",
            "terminal.commit.outcome": "COMMITTED" if committed else "NOT_COMMITTED",
        }
    return {
        "lease.validation.outcome": "NOT_EVALUATED",
        "terminal.commit.outcome": "NOT_COMMITTED",
    }


def _after_media_inspection(
    state: WorkflowState,
) -> Literal["freeze_casefile", "triage_documents", "render_documents", "finalize"]:
    if state["route"] == ProcessingRoute.STRUCTURED_ADJUDICATION.value:
        return "freeze_casefile"
    if state["route"] == ProcessingRoute.EARLY_TRIAGE.value:
        return "triage_documents"
    if state["route"] == ProcessingRoute.DOCUMENT_INTELLIGENCE.value:
        return "render_documents"
    return "finalize"


def _after_triage(
    state: WorkflowState,
) -> Literal["commit_member_action", "render_documents"]:
    return "commit_member_action" if state["action_required"] else "render_documents"


def _after_rendering(
    state: WorkflowState,
) -> Literal["commit_member_action", "discover_documents", "ocr_documents"]:
    if state["action_required"]:
        return "commit_member_action"
    if state["route"] == ProcessingRoute.DOCUMENT_INTELLIGENCE.value and (
        state["discovery_observation_count"] == 0
    ):
        return "discover_documents"
    return "ocr_documents"


def _after_extraction(
    state: WorkflowState,
) -> Literal["reconcile_casefile", "finalize"]:
    return "reconcile_casefile" if state["extraction_completed"] else "finalize"


def _after_reconciliation(
    state: WorkflowState,
) -> Literal["commit_member_action", "adjudicate"]:
    return "commit_member_action" if state["action_required"] else "adjudicate"


def _checkpoint_url(database_url: str) -> str:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("LangGraph checkpoints require PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)
