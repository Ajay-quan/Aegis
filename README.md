# Aegis

Trust infrastructure for AI: what your AI knows, and what it is allowed to do.

| Product | What it does | Folder |
|---|---|---|
| **AegisMem** | Memory for AI. A free Chrome extension that searches all your AI chats, plus a memory server for agents. | [`AegisMem/`](AegisMem/) |
| **AegisTrace** | Safety and accountability for AI agents: permission checks, human approvals, signed audit log, dashboard. | [`AegisTrace/`](AegisTrace/) |
| **Shared** | Code both products use: encryption, signing, policies. | [`shared/`](shared/) |

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
