from time import monotonic
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from openinference.semconv.trace import SpanAttributes

from claims_backend.application.processing import ClaimProcessor
from claims_backend.application.work import LeaseLostError
from claims_backend.application.workflow import WorkflowRepository, WorkflowRuntime
from claims_backend.domain.processing import ProcessingRoute
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import (
    ExecutionContract,
    NewWorkflowEvent,
    WorkflowRun,
)
from claims_backend.infrastructure.langgraph_workflow.edges import (
    _after_extraction,
    _after_media_inspection,
    _after_reconciliation,
    _after_rendering,
    _after_triage,
)
from claims_backend.infrastructure.langgraph_workflow.errors import (
    BeforeNodeHook,
    WorkflowIncompleteError,
    WorkflowNode,
    _no_op_hook,
)
from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _checkpoint_url,
    _json,
    _lease_id_sha256,
    _terminal_outcome_attributes,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.nodes import (
    adjudicate_node,
    commit_decision_node,
    commit_member_action_node,
    discover_documents_node,
    extract_evidence_node,
    finalize_node,
    freeze_casefile_node,
    load_claim_node,
    media_inspect_node,
    ocr_documents_node,
    reconcile_casefile_node,
    render_documents_node,
    triage_documents_node,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    _ACTIVE_RUNTIME_CONTEXT,
    _NODE_COMPONENTS,
    WorkflowRuntimeContext,
    WorkflowState,
    WorkflowUpdate,
    _active_lease,
)
from claims_backend.observability import (
    EngineeringLogEvent,
    Observability,
    trace_identifiers,
)


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
            builder.add_node("load_claim", self._node("load_claim", load_claim_node))
            builder.add_node("finalize", self._node("finalize", finalize_node))
            if self._processor is None:
                builder.add_edge("load_claim", "finalize")
            else:
                builder.add_node(
                    "media_inspect",
                    self._node("media_inspect", media_inspect_node),
                )
                builder.add_node(
                    "freeze_casefile",
                    self._node("freeze_casefile", freeze_casefile_node),
                )
                builder.add_node(
                    "adjudicate",
                    self._node("adjudicate", adjudicate_node),
                )
                builder.add_node(
                    "commit_decision",
                    self._node("commit_decision", commit_decision_node),
                )
                builder.add_node(
                    "triage_documents",
                    self._node("triage_documents", triage_documents_node),
                )
                builder.add_node(
                    "render_documents",
                    self._node("render_documents", render_documents_node),
                )
                builder.add_node(
                    "discover_documents",
                    self._node("discover_documents", discover_documents_node),
                )
                builder.add_node(
                    "ocr_documents",
                    self._node("ocr_documents", ocr_documents_node),
                )
                builder.add_node(
                    "extract_evidence",
                    self._node("extract_evidence", extract_evidence_node),
                )
                builder.add_node(
                    "reconcile_casefile",
                    self._node("reconcile_casefile", reconcile_casefile_node),
                )
                builder.add_node(
                    "commit_member_action",
                    self._node("commit_member_action", commit_member_action_node),
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
                        result = cast(WorkflowUpdate, await handler(state, self))
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
                        result = cast(WorkflowUpdate, await handler(state, self))
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

    def _required_processor(self) -> ClaimProcessor:
        if self._processor is None:
            raise WorkflowIncompleteError
        return self._processor
