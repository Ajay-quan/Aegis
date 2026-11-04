-- The application role is not the table owner and cannot bypass RLS.
CREATE ROLE aegis_app LOGIN PASSWORD 'dev-app-password' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE aegistrace TO aegis_app;
-- Outbox dispatcher: may read/update the outbox across tenants, nothing else.
CREATE ROLE aegis_dispatcher LOGIN PASSWORD 'dev-dispatcher-password' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE aegistrace TO aegis_dispatcher;
