"""LangChain / LangGraph integration.

    from aegismem_client import AegisMem
    from aegismem_agents.langchain import aegismem_tools, handoff_node
    from langgraph.prebuilt import create_react_agent

    mem = AegisMem()                                    # AEGISMEM_BASE_URL / AEGISMEM_API_KEY
    agent = create_react_agent(model, tools=aegismem_tools(mem, user_id="u1"))

    graph.add_node("load_memory", handoff_node(mem))   # writes state["memory_context"]
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Iterable

from langchain_core.tools import StructuredTool

from aegismem_client import AegisMem
from aegismem_client.tools import TOOLS, ToolExecutor


def aegismem_tools(
    client: AegisMem, user_id: str | None = None, include: Iterable[str] | None = None,
) -> list[StructuredTool]:
    """LangChain tools for the AegisMem catalogue. ``include`` limits the set (e.g. omit "forget")."""
    executor = ToolExecutor(client, default_user=user_id)
    wanted = set(include) if include is not None else None
    tools = []
    for spec in TOOLS:
        if wanted is not None and spec["name"] not in wanted:
            continue

        async def run(_name: str = spec["name"], **kwargs: Any) -> str:
            return await executor.call_tool(_name, kwargs)

        tools.append(StructuredTool(
            name=f"aegismem_{spec['name']}",
            description=spec["description"],
            args_schema=spec["inputSchema"],
            coroutine=run,
            handle_tool_error=True,
        ))
    return tools


def handoff_node(
    client: AegisMem, user_key: str = "user_id", task_key: str = "task", output_key: str = "memory_context",
    token_budget: int = 1200,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """LangGraph node that loads a cited, budgeted memory briefing into the graph state."""
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        packet = await client.handoff(state[user_key], task=str(state.get(task_key, "")),
                                      token_budget=token_budget)
        return {output_key: packet.markdown}
    return node
