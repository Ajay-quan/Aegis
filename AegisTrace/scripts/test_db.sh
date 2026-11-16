#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
# Create (if needed) and migrate the isolated test database `aegistrace_test`.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T postgres psql -U aegis_owner -d postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname='aegistrace_test'" | grep -q 1 || \
  docker compose exec -T postgres psql -U aegis_owner -d postgres -c "CREATE DATABASE aegistrace_test" \
  -c "GRANT CONNECT ON DATABASE aegistrace_test TO aegis_app, aegis_dispatcher"
AEGIS_OWNER_DATABASE_URL=postgresql+psycopg://aegis_owner:dev-owner-password@127.0.0.1:55432/aegistrace_test \
  uv run alembic upgrade head
