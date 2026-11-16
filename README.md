# Aegis

Trust infrastructure for AI: what your AI knows, and what it is allowed to do.

| Product | What it does | Folder |
|---|---|---|
| **AegisMem** | Memory for AI. A free Chrome extension that searches all your AI chats, plus a memory server for agents. | [`AegisMem/`](AegisMem/) |
| **AegisTrace** | Safety and accountability for AI agents: permission checks, human approvals, signed audit log, dashboard. | [`AegisTrace/`](AegisTrace/) |
| **Shared** | Code both products use: encryption, signing, policies. | [`shared/`](shared/) |

## Run it

```bash
./aegis up      # AegisTrace + AegisMem + dashboard, connected (needs Docker, uv, Node 22)
./aegis demo    # demo activity: runs, a blocked action, governed memory, a pending approval
./aegis token   # sign-in token for the dashboard at http://localhost:3000
./aegis test    # every test suite against the running stack
./aegis down
```

Local development only: dev signing keys, AegisMem without auth on the internal network, mock embeddings
(set `EMBEDDING_BACKEND`/`EMBEDDING_API_KEY` for real ones).

## How they connect

AegisTrace exposes AegisMem as three governed tools: `memory.recall`, `memory.remember` and `memory.forget`.
Every memory access goes through the same rules, approvals and signed log as any other agent action.
Memories are scoped per organization, each records the run that wrote it, and erasing needs approval and
returns a signed receipt. The dashboard's **Memory** page shows the activity and, per subject, what is stored.

## Layout

```
AegisMem/      AegisMem: memory for AI
  extension/   Chrome extension (AegisMem Recall)       npm install && npm run build
  server/      Python memory server + benchmarks         pip install -e ".[dev]" && pytest
  site/        Marketing website (Next.js)               npm install && npm run build
AegisTrace/    AegisTrace (being brought in)
shared/        Shared libraries (planned)
docs/          Roadmaps and design notes
project_log.md Running log of decisions
```

Each folder is self-contained: run its commands from inside that folder.
