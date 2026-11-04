#!/bin/sh
# Runs once on first database init (as the postgres superuser).
#   aegis_owner: owns the schema, runs migrations.
#   aegis_app:   what the API connects as. NOSUPERUSER NOBYPASSRLS so row-level security applies.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE aegis_owner LOGIN PASSWORD '${AEGIS_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE aegis_app   LOGIN PASSWORD '${AEGIS_APP_PASSWORD}'   NOSUPERUSER NOBYPASSRLS;
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO aegis_owner;
GRANT USAGE ON SCHEMA public TO aegis_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aegis_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aegis_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aegis_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO aegis_app;
SQL
