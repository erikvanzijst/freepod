-- The platform database's metrics sidecar role (postgres.tf), applied on every
-- rollout by the worker's init containers.
--
-- Required psql variables:
--   postgres_exporter_password    password for the postgres_exporter role

\set ON_ERROR_STOP on

SET client_min_messages = warning;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'postgres_exporter') THEN
        CREATE ROLE postgres_exporter;
    END IF;
END
$$;

ALTER ROLE postgres_exporter WITH LOGIN CONNECTION LIMIT 2
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE postgres_exporter WITH PASSWORD :'postgres_exporter_password';

-- Statistics only; no grant on any table's contents.
GRANT pg_monitor TO postgres_exporter;

SELECT format('GRANT CONNECT ON DATABASE %I TO postgres_exporter', current_database()) \gexec
