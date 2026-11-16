# ADR-001: AegisTrace is Studio's control plane; organization = tenant, workspace = project

Status: accepted (2026-11-16)

## Context
Studio needs organizations, workspaces, API keys, audit events and integration settings. AegisTrace already
has tenants with Postgres row-level security, projects, agents, OIDC sign-in, scopes and an append-only
evidence model. AegisMem has its own API keys and audit log for the memory API.

## Decision
- Studio-owned records live in the AegisTrace database, under the same tenant RLS. No third database.
- Organization = AegisTrace tenant; workspace = AegisTrace project.
- AegisMem stays the source of truth for memory and its own keys. Studio reaches it server-side with a
  service credential.
- AegisTrace API keys copy AegisMem's proven design: prefixed keys, peppered HMAC-SHA256 stored, plaintext
  shown once, scoped, revocable, audited.

## Alternatives considered
A separate Studio service and database: cleaner ownership, but a third auth model, a third migration stream
and cross-database consistency, with no requirement that needs it yet.

## Consequences
Reversible: Studio tables are self-contained (`api_keys`, `audit_events`) and can move behind a Studio service
later. The AegisTrace API grows a few admin endpoints.
