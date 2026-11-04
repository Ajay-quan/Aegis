"""OpenAI Agents SDK integration.

    from agents import Agent
    from aegismem_client import AegisMem
    from aegismem_agents.openai_agents import aegismem_function_tools

    agent = Agent(name="assistant", tools=aegismem_function_tools(AegisMem(), user_id="u1"))
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from agents import FunctionTool

from aegismem_client import AegisMem
from aegismem_client.errors import AegisMemError
from aegismem_client.tools import TOOLS, ToolExecutor


def aegismem_function_tools(
    client: AegisMem, user_id: str | None = None, include: Iterable[str] | None = None,
) -> list[FunctionTool]:
    executor = ToolExecutor(client, default_user=user_id)
    wanted = set(include) if include is not None else None
    tools = []
    for spec in TOOLS:
        if wanted is not None and spec["name"] not in wanted:
            continue

        async def invoke(ctx: Any, args_json: str, _name: str = spec["name"]) -> str:
            try:
                return await executor.call_tool(_name, json.loads(args_json or "{}"))
            except (AegisMemError, ValueError, KeyError) as e:  # visible to the model, recoverable
                return f"error: {type(e).__name__}: {e}"

        tools.append(FunctionTool(
            name=f"aegismem_{spec['name']}",
            description=spec["description"],
            params_json_schema=spec["inputSchema"],
            on_invoke_tool=invoke,
            strict_json_schema=False,  # optional parameters (user_id, top_k, ...) are allowed
        ))
    return tools
