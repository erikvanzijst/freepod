-- The app authentication service's database role, applied on every rollout.
--
-- app-auth sits on an internet-facing authentication path: its broker decides
-- which hosts may receive a sign-in code, and its verifier redeems those codes.
-- It connects as this role rather than the platform's own, so a bug in it can
-- read only what the eligibility query names and write only its own two tables.
--
-- Idempotent by construction, because it runs again on every rollout. It runs
-- *after* `alembic upgrade head`, since a grant needs the table to exist.
--
-- Required psql variables:
--   app_auth_password    password for the caelus_app_auth role

\set ON_ERROR_STOP on

SET client_min_messages = warning;

-- One transaction, so the converge below is atomic. Privileges are
-- transactional in PostgreSQL: until COMMIT, the running service keeps seeing
-- its old grants, rather than a gap between the REVOKEs and the GRANTs in which
-- every sign-in would fail with permission denied.
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'caelus_app_auth') THEN
        CREATE ROLE caelus_app_auth LOGIN;
    END IF;
END
$$;

ALTER ROLE caelus_app_auth WITH
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS
    PASSWORD :'app_auth_password';

-- Converge rather than accumulate, as for caelus_ssh_resolver. Column grants
-- are revoked by the table-level REVOKE ALL, so re-granting below is exact.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM caelus_app_auth;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM caelus_app_auth;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM caelus_app_auth;

GRANT USAGE ON SCHEMA public TO caelus_app_auth;

-- Eligibility: is this host a live `custom` deployment whose *applied* release
-- enabled authentication? Column grants, not table grants: `deployment` also
-- carries the owner, and `deployment_release` build and error detail, none of
-- which the broker has any use for. Vars and database passwords live in tables
-- this role is never granted.
GRANT SELECT (id, hostname, status, applied_release_id) ON TABLE deployment TO caelus_app_auth;
GRANT SELECT (id, template_id, values_json) ON TABLE deployment_release TO caelus_app_auth;
GRANT SELECT (id, product_id) ON TABLE product_template_version TO caelus_app_auth;
GRANT SELECT (id, slug) ON TABLE product TO caelus_app_auth;

-- Its own records. No UPDATE: consent is inserted once, codes are inserted and
-- then deleted on redemption or expiry.
GRANT SELECT, INSERT, DELETE ON TABLE app_auth_consent TO caelus_app_auth;
GRANT SELECT, INSERT, DELETE ON TABLE app_auth_code TO caelus_app_auth;

COMMIT;
