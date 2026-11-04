# aegismem-agents

Governed memory tools for agent frameworks. All tools share one catalogue and executor
(`aegismem_client.tools`) with the MCP server, so behaviour is identical everywhere.

| Framework | Usage |
|---|---|
| LangChain / LangGraph | `aegismem_tools(AegisMem(), user_id="u1")` → `create_react_agent(model, tools=...)`; `handoff_node(mem)` loads a memory briefing into graph state |
| OpenAI Agents SDK | `Agent(tools=aegismem_function_tools(AegisMem(), user_id="u1"))` |

Tools: `remember`, `recall`, `handoff`, `correct`, `used`, `forget`. Pass `include=[...]` to omit
`forget` for agents that should never erase. Errors are returned to the model as text, not raised.
