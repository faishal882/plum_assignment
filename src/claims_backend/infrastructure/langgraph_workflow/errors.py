from collections.abc import Awaitable, Callable
from typing import Any

type BeforeNodeHook = Callable[[str], Awaitable[None]]
type WorkflowNode = Callable[..., Any]


class WorkflowIncompleteError(Exception):
    pass


async def _no_op_hook(_: str) -> None:
    return None
