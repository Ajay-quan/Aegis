# aegis-audit

An open-source integrity audit for AI agent memory. It answers the questions security reviewers
ask before long-term memory goes to production:

| Check | Question |
|---|---|
| REV-1 | After a fact is updated, is the old version still served? |
| DEL-1 | After a memory is deleted, can it still be retrieved? |
| DEL-2 | Does deleting a fact remove its duplicate copies? |
| DEL-3 | Does erasing a user remove everything about them? |
| POI-1 | Is a prompt injection inside a tool result stored and served as memory? |
| POI-2 | Do covert behavioural instructions persist? |
| ISO-1 | Can one user's memories leak to another? |

```bash
pip install ./audit
aegis-audit --target naive                                       # calibration run
aegis-audit --target aegismem --url http://localhost:8000 --api-key aem_...
aegis-audit --target mem0 --url http://localhost:8888 --out report --fail-on critical
```

Verdicts are judged on the **text** a system returns, so any vendor can be audited. Each check uses
run-scoped user ids and cleans up afterwards. Unsupported operations are reported as SKIP, never as PASS.

To add a system, implement the `Target` protocol in `aegis_audit/targets.py` (add, search, update,
delete, delete_user). The Mem0 adapter follows Mem0's documented REST API. Verify it against your
server version before publishing results, and disclose findings to vendors responsibly.
