-- The notifier's database role, applied on every rollout.
--
-- The notifier delivers what platform services queued in notification_outbox
-- (daemons/notifier). It reads queued rows and the address of a user
-- recipient, and records how each delivery ended; it cannot queue, delete or
-- read anything else.
--
-- Idempotent and run *after* `alembic upgrade head`, like app-auth-bootstrap.sql.
--
-- Required psql variables:
--   notifier_password    password for the caelus_notifier role

\set ON_ERROR_STOP on

SET client_min_messages = warning;

-- One transaction, so the running notifier never sees a gap between the
-- REVOKEs and the GRANTs.
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'caelus_notifier') THEN
        CREATE ROLE caelus_notifier LOGIN;
    END IF;
END
$$;

ALTER ROLE caelus_notifier WITH
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS
    PASSWORD :'notifier_password';

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM caelus_notifier;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM caelus_notifier;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM caelus_notifier;

GRANT USAGE ON SCHEMA public TO caelus_notifier;

GRANT SELECT ON TABLE notification_outbox TO caelus_notifier;
-- Also what lets it lock a row with FOR UPDATE.
GRANT UPDATE (state, attempts, last_attempt_at, sent_at, error) ON TABLE notification_outbox TO caelus_notifier;
GRANT SELECT (id, email) ON TABLE "user" TO caelus_notifier;

COMMIT;
