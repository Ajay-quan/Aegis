"""AegisMem operator CLI.

Bootstrap the first admin key for a tenant (subsequent keys can be managed via
/api/v1/admin/keys):

    python scripts/aegisctl.py create-key --tenant acme --name bootstrap --scopes admin
    python scripts/aegisctl.py list-keys --tenant acme
    python scripts/aegisctl.py revoke-key --tenant acme --key-id <uuid>
    python scripts/aegisctl.py rebuild --tenant acme --component trust   # replay from event log

Uses the same control-plane database as the API (CONTROL_DATABASE_URL / settings).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.api.auth import SCOPES, issue_key  # noqa: E402
from apps.api.control import get_control_store  # noqa: E402
from core.config.settings import settings  # noqa: E402


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="aegisctl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-key")
    c.add_argument("--tenant", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--scopes", nargs="+", required=True, choices=SCOPES)
    lk = sub.add_parser("list-keys")
    lk.add_argument("--tenant", required=True)
    rk = sub.add_parser("revoke-key")
    rk.add_argument("--tenant", required=True)
    rk.add_argument("--key-id", required=True)
    rb = sub.add_parser("rebuild")
    rb.add_argument("--tenant", required=True)
    rb.add_argument("--component", required=True, choices=["trust", "risk"])
    sub.add_parser("drain-outbox", help="replay queued vector-index repairs once")
    sub.add_parser("outbox-status")
    bf = sub.add_parser("backfill-tenant", help="stamp tenant_id on pre-tenancy Qdrant points")
    bf.add_argument("--tenant", default="default")
    sub.add_parser("prune", help="prune expired retrieval-ledger and idempotency records now")
    args = ap.parse_args(argv)

    store = await get_control_store()
    try:
        if args.cmd == "create-key":
            record, raw = await issue_key(store, args.tenant, args.scopes, args.name)
            print(f"key_id:  {record.key_id}\ntenant:  {record.tenant_id}\nscopes:  {record.scopes}")
            print(f"api_key: {raw}\n\nStore this key now; it cannot be shown again.")
        elif args.cmd == "list-keys":
            for r in await store.list_api_keys(args.tenant):
                state = "revoked" if r.revoked_at else "active"
                print(f"{r.key_id}  {r.key_prefix}…  {state:8} {','.join(r.scopes):40} {r.name}")
        elif args.cmd == "revoke-key":
            ok = await store.revoke_api_key(args.tenant, args.key_id)
            print("revoked" if ok else "not found or already revoked")
            return 0 if ok else 1
        elif args.cmd == "backfill-tenant":
            from apps.api.dependencies import get_raw_vector_store
            vs = await get_raw_vector_store()
            if not hasattr(vs, "backfill_tenant"):
                print("backfill only applies to Qdrant (pgvector rows already carry tenant_id)")
                return 1
            print(f"stamped tenant_id={args.tenant} on {await vs.backfill_tenant(args.tenant)} points")
        elif args.cmd == "prune":
            from datetime import timedelta
            print({"ledger": await store.prune_ledger(timedelta(hours=settings.ledger_retention_hours)),
                   "idempotency": await store.prune_idempotency(
                       timedelta(hours=settings.idempotency_retention_hours))})
        elif args.cmd == "outbox-status":
            print(await store.outbox_counts() or "empty")
        elif args.cmd == "drain-outbox":
            from apps.api.dependencies import get_embedding, get_raw_db_store, get_raw_vector_store
            from services.vector_sync import OutboxWorker
            worker = OutboxWorker(store, await get_raw_db_store(), await get_raw_vector_store(),
                                  get_embedding(), max_attempts=settings.outbox_max_attempts)
            print(await worker.drain_once())
        elif args.cmd == "rebuild":
            from services.learning_runtime import LearningRuntime
            from domain.learning.risk_model import OnlineRiskModel
            from domain.learning.trust_calibrator import TrustCalibrator
            rt = LearningRuntime(store, hash_secret=settings.app_secret_key)
            if args.component == "trust":
                comp = await rt.rebuild(args.tenant, "trust",
                                        lambda st, j: TrustCalibrator.from_state(st, journal=j))
                print(f"rebuilt trust: {len(comp.to_state()['stats'])} source/origin stats")
            else:
                key = rt._tenant_key(args.tenant)
                comp = await rt.rebuild(args.tenant, "risk",
                                        lambda st, j: OnlineRiskModel.from_state(st, hash_key=key, journal=j))
                print(f"rebuilt risk model: {comp.examples} feedback examples")
        return 0
    finally:
        await store.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
