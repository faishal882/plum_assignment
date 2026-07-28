from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.engine import make_url

from claims_backend.application.processing import ClaimProcessor
from claims_backend.application.workflow import WorkflowRepository, WorkflowRuntime
from claims_backend.domain.processing import (
    AffectedDocument,
    EarlyGateResult,
    IdentityConflictDetail,
    ProcessingRoute,
)
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import WorkflowRun, WorkflowRunStatus

type BeforeNodeHook = Callable[[str], Awaitable[None]]


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
    ocr_observation_count: int
    evidence_candidate_count: int
    extraction_completed: bool
    terminal_committed: bool
    worker_id: str
    lease_token: str
    leased_at: str
    lease_until: str
    available_at: str
    attempt_number: int
    max_attempts: int
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
    ocr_observation_count: int
    evidence_candidate_count: int
    extraction_completed: bool
    terminal_committed: bool
    effect_count: int


class LangGraphClaimWorkflow(WorkflowRuntime):
    graph_name = "claim-processing"
    graph_version = "claim-processing-v6"

    def __init__(
        self,
        database_url: str,
        repository: WorkflowRepository,
        *,
        processor: ClaimProcessor | None = None,
        before_node: BeforeNodeHook | None = None,
        after_effect: BeforeNodeHook | None = None,
    ) -> None:
        self._checkpoint_url = _checkpoint_url(database_url)
        self._repository = repository
        self._processor = processor
        self._before_node = before_node or _no_op_hook
        self._after_effect = after_effect or _no_op_hook

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
            builder = StateGraph(WorkflowState)
            builder.add_node("load_claim", self._load_claim)
            builder.add_node("finalize", self._finalize)
            if self._processor is None:
                builder.add_edge("load_claim", "finalize")
            else:
                builder.add_node("media_inspect", self._media_inspect)
                builder.add_node("freeze_casefile", self._freeze_casefile)
                builder.add_node("adjudicate", self._adjudicate)
                builder.add_node("commit_decision", self._commit_decision)
                builder.add_node("triage_documents", self._triage_documents)
                builder.add_node("render_documents", self._render_documents)
                builder.add_node("ocr_documents", self._ocr_documents)
                builder.add_node("extract_evidence", self._extract_evidence)
                builder.add_node("reconcile_casefile", self._reconcile_casefile)
                builder.add_node("commit_member_action", self._commit_member_action)
                builder.add_edge("load_claim", "media_inspect")
                builder.add_conditional_edges(
                    "media_inspect",
                    _after_media_inspection,
                    {
                        "freeze_casefile": "freeze_casefile",
                        "triage_documents": "triage_documents",
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
                    },
                )
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
                    "ocr_observation_count": 0,
                    "evidence_candidate_count": 0,
                    "extraction_completed": False,
                    "terminal_committed": False,
                    "worker_id": lease.worker_id,
                    "lease_token": str(lease.lease_token),
                    "leased_at": lease.leased_at.isoformat(),
                    "lease_until": lease.lease_until.isoformat(),
                    "available_at": lease.available_at.isoformat(),
                    "attempt_number": lease.attempt_number,
                    "max_attempts": lease.max_attempts,
                    "effect_count": 0,
                }
            result = await graph.ainvoke(initial_state, config=config)
            if not result["finalized"] and not result["terminal_committed"]:
                raise WorkflowIncompleteError
            return bool(result["terminal_committed"])

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
        run = _workflow_run(state, self.graph_name, self.graph_version)
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
            _workflow_run(state, self.graph_name, self.graph_version)
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
        run = _workflow_run(state, self.graph_name, self.graph_version)
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
            _workflow_run(state, self.graph_name, self.graph_version)
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
        run = _workflow_run(state, self.graph_name, self.graph_version)
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
            _workflow_run(state, self.graph_name, self.graph_version)
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
            _workflow_run(state, self.graph_name, self.graph_version)
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

    async def _extract_evidence(self, state: WorkflowState) -> WorkflowUpdate:
        await self._before_node("extract_evidence")
        candidate_count = await self._required_processor().extract_evidence(
            _workflow_run(state, self.graph_name, self.graph_version)
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
            _workflow_run(state, self.graph_name, self.graph_version)
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


def _workflow_run(
    state: WorkflowState,
    graph_name: str,
    graph_version: str,
) -> WorkflowRun:
    return WorkflowRun(
        id=_workflow_run_id(state),
        work_item_id=UUID(state["work_item_id"]),
        claim_id=UUID(state["claim_id"]),
        claim_version=state["claim_version"],
        operation_key=state["operation_key"],
        graph_name=graph_name,
        graph_version=graph_version,
        status=WorkflowRunStatus.RUNNING,
        created_at=datetime.fromisoformat(state["leased_at"]),
        updated_at=datetime.fromisoformat(state["leased_at"]),
        completed_at=None,
    )


def _work_lease(state: WorkflowState) -> WorkLease:
    return WorkLease(
        work_item_id=UUID(state["work_item_id"]),
        claim_id=UUID(state["claim_id"]),
        claim_version=state["claim_version"],
        operation_key=state["operation_key"],
        worker_id=state["worker_id"],
        lease_token=UUID(state["lease_token"]),
        leased_at=datetime.fromisoformat(state["leased_at"]),
        lease_until=datetime.fromisoformat(state["lease_until"]),
        available_at=datetime.fromisoformat(state["available_at"]),
        attempt_number=state["attempt_number"],
        max_attempts=state["max_attempts"],
    )


def _after_media_inspection(
    state: WorkflowState,
) -> Literal["freeze_casefile", "triage_documents", "finalize"]:
    if state["route"] == ProcessingRoute.STRUCTURED_ADJUDICATION.value:
        return "freeze_casefile"
    if state["route"] == ProcessingRoute.EARLY_TRIAGE.value:
        return "triage_documents"
    return "finalize"


def _after_triage(
    state: WorkflowState,
) -> Literal["commit_member_action", "render_documents"]:
    return "commit_member_action" if state["action_required"] else "render_documents"


def _after_rendering(
    state: WorkflowState,
) -> Literal["commit_member_action", "ocr_documents"]:
    return "commit_member_action" if state["action_required"] else "ocr_documents"


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
