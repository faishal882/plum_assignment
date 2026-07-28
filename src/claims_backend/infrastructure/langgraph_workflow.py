from collections.abc import Awaitable, Callable
from typing import TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.engine import make_url

from claims_backend.application.workflow import WorkflowRepository, WorkflowRuntime
from claims_backend.domain.workflow import WorkflowRun

type BeforeNodeHook = Callable[[str], Awaitable[None]]


class WorkflowState(TypedDict):
    workflow_run_id: str
    claim_id: str
    claim_version: int
    work_item_id: str
    operation_key: str
    claim_loaded: bool
    finalized: bool
    effect_count: int


class WorkflowUpdate(TypedDict, total=False):
    claim_loaded: bool
    finalized: bool
    effect_count: int


class LangGraphClaimWorkflow(WorkflowRuntime):
    graph_name = "claim-processing"
    graph_version = "skeleton-v1"

    def __init__(
        self,
        database_url: str,
        repository: WorkflowRepository,
        *,
        before_node: BeforeNodeHook | None = None,
        after_effect: BeforeNodeHook | None = None,
    ) -> None:
        self._checkpoint_url = _checkpoint_url(database_url)
        self._repository = repository
        self._before_node = before_node or _no_op_hook
        self._after_effect = after_effect or _no_op_hook

    async def setup(self) -> None:
        async with AsyncPostgresSaver.from_conn_string(self._checkpoint_url) as checkpointer:
            await checkpointer.setup()

    async def run(self, workflow_run: WorkflowRun, *, resume: bool) -> None:
        async with AsyncPostgresSaver.from_conn_string(self._checkpoint_url) as checkpointer:
            builder = StateGraph(WorkflowState)
            builder.add_node("load_claim", self._load_claim)
            builder.add_node("finalize", self._finalize)
            builder.add_edge(START, "load_claim")
            builder.add_edge("load_claim", "finalize")
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
                    "effect_count": 0,
                }
            result = await graph.ainvoke(initial_state, config=config)
            if not result["finalized"]:
                raise WorkflowIncompleteError

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


class WorkflowIncompleteError(Exception):
    pass


async def _no_op_hook(_: str) -> None:
    return None


def _workflow_run_id(state: WorkflowState) -> UUID:
    return UUID(state["workflow_run_id"])


def _checkpoint_url(database_url: str) -> str:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("LangGraph checkpoints require PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)
