# Integration plan

Vertical slices, smallest first. Each ends with tests against the real local stack.

1. **API keys (Settings → API keys)**: done 2026-11-16. Keys for the AegisTrace API (SDKs, CLI, CI, agents) with
   the same design as AegisMem's (`aet_` prefix, peppered HMAC, shown once, scoped, revocable, audited).
   Accepted by the API alongside OIDC JWTs. Studio page to create, list and revoke them.
2. **Audit viewer (Settings → Audit)**: page done; next, record rules, grant and erasure changes as audit events too.
3. **AegisMem service credential**: Studio's memory calls authenticate with an `aem_` key instead of auth-off.
4. **Members and roles**: Owner/Admin/Developer/Viewer mapped to scopes; enforced server-side.
5. **Memory Explorer**: search via AegisMem `/retrieve`, versions, contradictions, quarantine review.
6. **Agent Builder (form view)**: create and edit agents, grants and model choice; validated and persisted.
7. **Token and cost capture** in model adapters, which unlocks the Overview additions and AegisOptimize.
