package main

import (
	"context"
	"encoding/base64"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// The suite runs against the real migrated schema -- the same database
// `api/tests/conftest.py` creates and migrates with the Alembic chain. There is
// no in-memory mode and no skip path, for the reason that suite gives: a test
// that invents its own two tables would prove nothing about the query this
// component hardwires against the platform's.
//
// The coupling is deliberate (see README.md), so drift has to be a failure here
// rather than a surprise on the SSH path.
const noDatabase = `
CAELUS_TEST_DATABASE_URL is not set, or names a database with no schema.

These tests read the platform's real tables, so they need the migrated test
database. Inside the devcontainer the variable is already set and
.devcontainer/post-create.sh creates and migrates the database when the
container is built, so an empty one means it was dropped since. Rebuild it --
the script is idempotent and safe to re-run:

    .devcontainer/post-create.sh

`

// Two real ed25519 public keys. Real ones rather than random bytes because the
// resolver fingerprints the wire blob, and a fingerprint of nonsense would let
// a bug in that step pass unnoticed.
const (
	ownerKey    = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBZO/CpZb1FS9RnxIaTPPPAIrDvHCcynnYjhA7Jkvgw/"
	strangerKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR"
)

var upstreamKey = []byte("-----BEGIN OPENSSH PRIVATE KEY-----\nspike-platform-key\n-----END OPENSSH PRIVATE KEY-----\n")

// blob is the wire format sshpiperd sends: `ssh.PublicKey.Marshal()`.
func blob(t *testing.T, line string) []byte {
	t.Helper()
	b, err := base64.StdEncoding.DecodeString(strings.Fields(line)[1])
	if err != nil {
		t.Fatalf("decoding %q: %v", line, err)
	}
	return b
}

// testDSN is the migrated test database, as libpq expects it. The API's own
// variable is SQLAlchemy's `postgresql+psycopg://` form, which pgx rejects.
func testDSN(t *testing.T) string {
	t.Helper()
	raw := os.Getenv("CAELUS_TEST_DATABASE_URL")
	if raw == "" {
		t.Fatal(noDatabase)
	}
	return strings.Replace(raw, "postgresql+psycopg://", "postgresql://", 1)
}

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	pool, err := openPool(context.Background(), testDSN(t), 4, 2000)
	if err != nil {
		t.Fatalf("%s\n(%v)", noDatabase, err)
	}
	t.Cleanup(pool.Close)

	var n int
	if err := pool.QueryRow(context.Background(),
		`SELECT count(*) FROM information_schema.tables
		  WHERE table_schema = 'public' AND table_name IN ('deployment', 'user_ssh_key')`,
	).Scan(&n); err != nil || n != 2 {
		t.Fatal(noDatabase)
	}
	return pool
}

// fixture builds one owner, one deployment and whatever keys a test registers,
// and removes all of it afterwards. Names are unique per test, so tests can run
// against a database the API suite also uses without either disturbing the
// other.
type fixture struct {
	t         *testing.T
	pool      *pgxpool.Pool
	unique    string
	userIDs   []int
	productID int
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	pool := testPool(t)
	f := &fixture{t: t, pool: pool, unique: fmt.Sprintf("%d", time.Now().UnixNano())}
	t.Cleanup(f.cleanup)
	return f
}

func (f *fixture) exec(sql string, args ...any) {
	f.t.Helper()
	if _, err := f.pool.Exec(context.Background(), sql, args...); err != nil {
		f.t.Fatalf("fixture: %v\n%s", err, sql)
	}
}

func (f *fixture) queryInt(sql string, args ...any) int {
	f.t.Helper()
	var id int
	if err := f.pool.QueryRow(context.Background(), sql, args...).Scan(&id); err != nil {
		f.t.Fatalf("fixture: %v\n%s", err, sql)
	}
	return id
}

func (f *fixture) user(label string) int {
	f.t.Helper()
	id := f.queryInt(
		`INSERT INTO "user" (email, is_admin, created_at) VALUES ($1, false, now()) RETURNING id`,
		fmt.Sprintf("%s-%s@ssh-auth.test", label, f.unique))
	f.userIDs = append(f.userIDs, id)
	return id
}

// product creates the product/template/plan scaffolding a deployment needs.
// `deployment` has NOT NULL foreign keys to a template and a subscription, so
// there is no shorter path to one row in the table under test.
func (f *fixture) template(userID int) (templateID, subscriptionID int) {
	f.t.Helper()
	if f.productID == 0 {
		f.productID = f.queryInt(
			`INSERT INTO product (name, description, created_at) VALUES ($1, 'ssh-auth test', now()) RETURNING id`,
			fmt.Sprintf("ssh-auth-%s", f.unique))
	}
	templateID = f.queryInt(
		`INSERT INTO product_template_version (product_id, chart_ref, chart_version, created_at)
		 VALUES ($1, 'registry.home/test/', '1.0.0', now()) RETURNING id`, f.productID)
	planID := f.queryInt(
		`INSERT INTO plan (name, product_id, created_at) VALUES ($1, $2, now()) RETURNING id`,
		fmt.Sprintf("free-%s-%d", f.unique, templateID), f.productID)
	planTemplateID := f.queryInt(
		`INSERT INTO plan_template_version (plan_id, price_cents, billing_interval, created_at)
		 VALUES ($1, 0, 'monthly', now()) RETURNING id`, planID)
	subscriptionID = f.queryInt(
		`INSERT INTO subscription (plan_template_id, user_id, status, payment_status, created_at)
		 VALUES ($1, $2, 'active', 'current', now()) RETURNING id`, planTemplateID, userID)
	return templateID, subscriptionID
}

// deployment inserts a deployment and the release it names. The FK between them
// is mutual and DEFERRABLE INITIALLY DEFERRED, which is why both go in one
// transaction and why this suite needs PostgreSQL.
func (f *fixture) deployment(userID int, name, status string) (id string, namespace string) {
	f.t.Helper()
	templateID, subscriptionID := f.template(userID)
	namespace = name + "-ns"

	ctx := context.Background()
	tx, err := f.pool.Begin(ctx)
	if err != nil {
		f.t.Fatal(err)
	}
	defer tx.Rollback(ctx)

	if err := tx.QueryRow(ctx, `SELECT gen_random_uuid()`).Scan(&id); err != nil {
		f.t.Fatal(err)
	}
	var releaseID string
	if err := tx.QueryRow(ctx, `SELECT gen_random_uuid()`).Scan(&releaseID); err != nil {
		f.t.Fatal(err)
	}
	if _, err := tx.Exec(ctx, `SET CONSTRAINTS ALL DEFERRED`); err != nil {
		f.t.Fatal(err)
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO deployment
		   (id, user_id, desired_template_id, desired_release_id, name, namespace,
		    status, generation, subscription_id, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, 1, $8, now())`,
		id, userID, templateID, releaseID, name, namespace, status, subscriptionID); err != nil {
		f.t.Fatal(err)
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO deployment_release (id, number, deployment_id, template_id, created_at)
		 VALUES ($1, 1, $2, $3, now())`, releaseID, id, templateID); err != nil {
		f.t.Fatal(err)
	}
	if err := tx.Commit(ctx); err != nil {
		f.t.Fatal(err)
	}
	return id, namespace
}

func (f *fixture) registerKey(userID int, line string) {
	f.t.Helper()
	fields := strings.Fields(line)
	f.exec(
		`INSERT INTO user_ssh_key (user_id, key_type, public_key, fingerprint, bits, label, created_at)
		 VALUES ($1, $2, $3, $4, 256, 'ssh-auth test', now())`,
		userID, fields[0], fields[0]+" "+fields[1], fingerprint(blob(f.t, line)))
}

func (f *fixture) revokeKey(userID int, line string) {
	f.t.Helper()
	f.exec(`DELETE FROM user_ssh_key WHERE user_id = $1 AND fingerprint = $2`,
		userID, fingerprint(blob(f.t, line)))
}

func (f *fixture) setStatus(deploymentID, status string) {
	f.t.Helper()
	f.exec(`UPDATE deployment SET status = $2 WHERE id = $1`, deploymentID, status)
}

func (f *fixture) setOwner(deploymentID string, userID int) {
	f.t.Helper()
	f.exec(`UPDATE deployment SET user_id = $2 WHERE id = $1`, deploymentID, userID)
}

// cleanup removes exactly what this fixture created, in FK order, so a failed
// test leaves the shared database as it found it.
func (f *fixture) cleanup() {
	if len(f.userIDs) == 0 {
		return
	}
	ctx := context.Background()
	for _, sql := range []string{
		`DELETE FROM deployment_release WHERE deployment_id IN (SELECT id FROM deployment WHERE user_id = ANY($1))`,
		`DELETE FROM deployment WHERE user_id = ANY($1)`,
		`DELETE FROM user_ssh_key WHERE user_id = ANY($1)`,
		`DELETE FROM subscription WHERE user_id = ANY($1)`,
		`DELETE FROM "user" WHERE id = ANY($1)`,
	} {
		if _, err := f.pool.Exec(ctx, sql, f.userIDs); err != nil {
			f.t.Logf("cleanup: %v", err)
		}
	}
	if f.productID != 0 {
		f.pool.Exec(ctx, `DELETE FROM plan_template_version WHERE plan_id IN (SELECT id FROM plan WHERE product_id = $1)`, f.productID)
		f.pool.Exec(ctx, `DELETE FROM plan WHERE product_id = $1`, f.productID)
		f.pool.Exec(ctx, `DELETE FROM product_template_version WHERE product_id = $1`, f.productID)
		f.pool.Exec(ctx, `DELETE FROM product WHERE id = $1`, f.productID)
	}
}

// newBrokenPool points at an address that answers nothing, so a test exercising
// the unavailable-dependency path gets the real failure -- a connection that
// cannot be made -- rather than a patched error.
func newBrokenPool() (*pgxpool.Pool, error) {
	return pgxpool.New(context.Background(), "postgresql://nobody:nobody@127.0.0.1:1/nothing")
}
