package main

import (
	"context"
	"os/exec"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

// The role the resolver connects as in the cluster, created by the SQL
// Terraform ships and applies from an init container. These tests run that
// exact file: a test that asserted grants it had written itself would prove
// nothing about what the cluster does.
const (
	roleBootstrap = "../../tf/app/caelus/ssh-resolver-bootstrap.sql"
	roleName      = "caelus_ssh_resolver"
	rolePassword  = "resolver-test-password"
)

// resolverRole applies the bootstrap and returns a DSN that connects as the
// role, dropping it afterwards.
func resolverRole(t *testing.T) string {
	t.Helper()
	admin := testDSN(t)

	psql := func(args ...string) ([]byte, error) {
		return exec.Command("psql", append([]string{admin, "-q", "-v", "ON_ERROR_STOP=1"}, args...)...).CombinedOutput()
	}
	if _, err := exec.LookPath("psql"); err != nil {
		t.Skip("psql is not installed; it is how the cluster applies this file")
	}
	if out, err := psql("-v", "ssh_resolver_password="+rolePassword, "-f", roleBootstrap); err != nil {
		t.Fatalf("bootstrap: %v\n%s", err, out)
	}
	t.Cleanup(func() {
		psql(
			"-c", "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "+roleName,
			"-c", "REVOKE ALL PRIVILEGES ON SCHEMA public FROM "+roleName,
			"-c", "DROP ROLE IF EXISTS "+roleName,
		)
	})

	// Swap the credential in the admin DSN rather than assembling a new one, so
	// host, port and database keep coming from one place.
	at := strings.LastIndex(admin, "@")
	scheme := strings.Index(admin, "://")
	return admin[:scheme+3] + roleName + ":" + rolePassword + admin[at:]
}

func rolePool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	pool, err := openPool(context.Background(), resolverRole(t), 4, 2000)
	if err != nil {
		t.Fatalf("connecting as %s: %v", roleName, err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func TestTheRoleReadsTheTwoTablesItNeeds(t *testing.T) {
	pool := rolePool(t)
	for _, q := range []string{
		"SELECT id, name, namespace, status, user_id FROM deployment LIMIT 1",
		"SELECT user_id, fingerprint FROM user_ssh_key LIMIT 1",
	} {
		if _, err := pool.Exec(context.Background(), q); err != nil {
			t.Errorf("%s: %v", q, err)
		}
	}
}

func TestTheRoleCannotWrite(t *testing.T) {
	pool := rolePool(t)
	for _, q := range []string{
		"UPDATE deployment SET status = 'ready'",
		"DELETE FROM deployment",
		`INSERT INTO user_ssh_key (user_id, key_type, public_key, fingerprint, bits, created_at)
		 VALUES (1, 'ssh-ed25519', 'x', 'SHA256:x', 256, now())`,
		"DELETE FROM user_ssh_key",
	} {
		_, err := pool.Exec(context.Background(), q)
		if err == nil {
			t.Errorf("%s succeeded; the role is not read-only", q)
		} else if !strings.Contains(strings.ToLower(err.Error()), "permission denied") {
			t.Errorf("%s: expected permission denied, got %v", q, err)
		}
	}
}

// `user` is in this list on purpose: the resolver joins on `user_id` and never
// needs the row, so it never gets to see an email address. Reaching it through
// `user` -- which the obvious version of this query does -- would have put that
// table in the grant for nothing.
func TestTheRoleCannotReadOutsideItsGrant(t *testing.T) {
	pool := rolePool(t)
	for _, table := range []string{`"user"`, "deployment_var", "deployment_release", "build"} {
		_, err := pool.Exec(context.Background(), "SELECT * FROM "+table+" LIMIT 1")
		if err == nil {
			t.Errorf("the role can read %s", table)
		} else if !strings.Contains(strings.ToLower(err.Error()), "permission denied") {
			t.Errorf("%s: expected permission denied, got %v", table, err)
		}
	}
}

// The grant is sufficient as well as minimal: a real admission over it.
func TestTheResolverWorksEndToEndAsTheReadOnlyRole(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, namespace := f.deployment(owner, "scoped-sss000", "ready")
	f.registerKey(owner, ownerKey)

	up := newHarness(t, rolePool(t)).mustAdmit(t, id, ownerKey)
	want := "tcp://scoped-sss000-ssh." + namespace + ".svc:2222"
	if up.GetUri() != want {
		t.Errorf("uri = %q, want %q", up.GetUri(), want)
	}
}

// ── the database dependency is bounded ────────────────────────────────────

// Asked of the server, not of the pool's configuration: a runtime parameter
// that never reached PostgreSQL would still be set on the config object.
func TestTheStatementTimeoutIsInForce(t *testing.T) {
	pool, err := openPool(context.Background(), testDSN(t), 4, 2000)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	var configured string
	if err := pool.QueryRow(context.Background(), "SHOW statement_timeout").Scan(&configured); err != nil {
		t.Fatal(err)
	}
	// PostgreSQL normalizes the unit it echoes back ("2000ms" becomes "2s").
	if configured == "0" {
		t.Fatal("no statement timeout; the resolver would wait forever on a slow query")
	}
	if configured != "2s" && configured != "2000ms" {
		t.Errorf("statement_timeout = %q, want 2s", configured)
	}
}

// A query that outlives the budget is cancelled, so the edge is not hung.
func TestASlowQueryRefusesRatherThanHangs(t *testing.T) {
	pool, err := openPool(context.Background(), testDSN(t), 1, 250)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	_, err = pool.Exec(context.Background(), "SELECT pg_sleep(5)")
	if err == nil {
		t.Fatal("the slow query completed; the timeout is not enforced")
	}
	if !strings.Contains(strings.ToLower(err.Error()), "statement timeout") {
		t.Errorf("expected a statement timeout, got %v", err)
	}
}

func TestThePoolIsBounded(t *testing.T) {
	pool, err := openPool(context.Background(), testDSN(t), 3, 2000)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	if got := pool.Config().MaxConns; got != 3 {
		t.Errorf("MaxConns = %d, want 3", got)
	}
}
