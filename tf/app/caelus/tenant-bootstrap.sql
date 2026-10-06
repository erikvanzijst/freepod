-- One-time setup for the tenant PostgreSQL cluster, applied on every rollout.
--
-- Idempotent by construction, because it runs again on every rollout.
--
-- Required psql variables:
--   caelus_admin_password       password for the platform's admin role
--   pgbouncer_auth_password     password for the pooler's auth_query role
--   postgres_exporter_password  password for the metrics sidecar's role

\set ON_ERROR_STOP on

SET client_min_messages = warning;

-- PostgreSQL grants CONNECT to PUBLIC on every database, these two included, so
-- database-per-tenant is not isolation until this runs (design D1).
--
-- ALL rather than CONNECT: revoking only CONNECT leaves PUBLIC holding TEMPORARY
-- (`datacl` reads `=T/postgres`), which is inert without CONNECT but is one more
-- thing to reason about every time someone reads this ACL. The roles that do
-- connect here hold their grants explicitly below.
REVOKE ALL ON DATABASE postgres FROM PUBLIC;
REVOKE ALL ON DATABASE template1 FROM PUBLIC;


-- ---------------------------------------------------------------------------
-- Provision the caelus_admin role (used by the api and worker processes)
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'caelus_admin') THEN
        CREATE ROLE caelus_admin;
    END IF;
END
$$;

ALTER ROLE caelus_admin WITH LOGIN CREATEDB CREATEROLE
    NOSUPERUSER NOREPLICATION NOBYPASSRLS;
ALTER ROLE caelus_admin WITH PASSWORD :'caelus_admin_password';

-- pg_database_size on a database whose CONNECT it does not hold:
GRANT pg_read_all_stats TO caelus_admin;
-- pg_terminate_backend on a tenant's backends:
GRANT pg_signal_backend TO caelus_admin;

GRANT CONNECT ON DATABASE postgres TO caelus_admin;

-- temp_file_limit is superuser-only to set, which is exactly what makes it real
-- enforcement rather than advice -- and is also why a non-superuser admin
-- cannot apply it to a tenant role without this (PG15+).
GRANT SET ON PARAMETER temp_file_limit TO caelus_admin;


-- ---------------------------------------------------------------------------
-- pgbouncer_auth -- the pooler's credential lookup
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pgbouncer_auth') THEN
        CREATE ROLE pgbouncer_auth;
    END IF;
END
$$;

ALTER ROLE pgbouncer_auth WITH LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE pgbouncer_auth WITH PASSWORD :'pgbouncer_auth_password';

GRANT CONNECT ON DATABASE postgres TO pgbouncer_auth;

-- Authentication keeps a connection slot when tenants have taken every other
-- one: PG16+ reserved_connections, held open for exactly this role (design D9).
GRANT pg_use_reserved_connections TO pgbouncer_auth;

-- SECURITY DEFINER because pg_shadow is superuser-only. Owned by the superuser running
-- this script.
CREATE SCHEMA IF NOT EXISTS pgbouncer;
REVOKE ALL ON SCHEMA pgbouncer FROM PUBLIC;
GRANT USAGE ON SCHEMA pgbouncer TO pgbouncer_auth;

CREATE OR REPLACE FUNCTION pgbouncer.user_lookup(
    IN i_username TEXT,
    OUT uname TEXT,
    OUT phash TEXT
) RETURNS RECORD AS $$
BEGIN
    SELECT usename, passwd FROM pg_catalog.pg_shadow
     WHERE usename = i_username
      INTO uname, phash;
    RETURN;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

REVOKE ALL ON FUNCTION pgbouncer.user_lookup(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pgbouncer.user_lookup(TEXT) TO pgbouncer_auth;


-- ---------------------------------------------------------------------------
-- postgres_exporter -- the metrics sidecar (tenant-db.tf)
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'postgres_exporter') THEN
        CREATE ROLE postgres_exporter;
    END IF;
END
$$;

-- The exporter holds one connection; the limit keeps a misbehaving one from
-- taking tenants' slots.
ALTER ROLE postgres_exporter WITH LOGIN CONNECTION LIMIT 2
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE postgres_exporter WITH PASSWORD :'postgres_exporter_password';

-- Read-only statistics, including pg_database_size of every tenant database
-- without CONNECT on any of them.
GRANT pg_monitor TO postgres_exporter;

GRANT CONNECT ON DATABASE postgres TO postgres_exporter;
