package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Like ssh-auth, these run against the real migrated schema -- the database
// `api/tests/conftest.py` migrates with the Alembic chain -- and as the real
// role, created by the SQL Terraform ships. A test that invented its own tables
// would prove nothing about queries hardwired against the platform's.
const noDatabase = `
CAELUS_TEST_DATABASE_URL is not set, or names a database without the app-auth
tables. Inside the devcontainer the variable is set; migrate the database with:

    cd api && CAELUS_DATABASE_URL=$CAELUS_TEST_DATABASE_URL uv run alembic upgrade head
`

const (
	roleBootstrap = "../../tf/app/caelus/app-auth-bootstrap.sql"
	roleName      = "caelus_app_auth"
	rolePassword  = "app-auth-test-password"
)

func testDSN(t *testing.T) string {
	t.Helper()
	raw := os.Getenv("CAELUS_TEST_DATABASE_URL")
	if raw == "" {
		t.Fatal(noDatabase)
	}
	return strings.Replace(raw, "postgresql+psycopg://", "postgresql://", 1)
}

func adminPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	pool, err := openPool(context.Background(), testDSN(t), 4)
	if err != nil {
		t.Fatalf("%s\n(%v)", noDatabase, err)
	}
	t.Cleanup(pool.Close)
	var n int
	if err := pool.QueryRow(context.Background(),
		`SELECT count(*) FROM information_schema.tables
		  WHERE table_schema = 'public' AND table_name IN ('app_auth_consent', 'app_auth_code')`,
	).Scan(&n); err != nil || n != 2 {
		t.Fatal(noDatabase)
	}
	return pool
}

// The role is shared by every test in the run and dropped at the end of none:
// grants are re-applied idempotently, exactly as each rollout does.
var roleOnce sync.Once
var roleErr error

func rolePool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	admin := testDSN(t)
	roleOnce.Do(func() {
		if _, err := exec.LookPath("psql"); err != nil {
			roleErr = fmt.Errorf("psql is not installed; it is how the cluster applies the bootstrap")
			return
		}
		out, err := exec.Command("psql", admin, "-q", "-v", "ON_ERROR_STOP=1",
			"-v", "app_auth_password="+rolePassword, "-f", roleBootstrap).CombinedOutput()
		if err != nil {
			roleErr = fmt.Errorf("bootstrap: %v\n%s", err, out)
		}
	})
	if roleErr != nil {
		t.Fatal(roleErr)
	}
	at := strings.LastIndex(admin, "@")
	scheme := strings.Index(admin, "://")
	pool, err := openPool(context.Background(), admin[:scheme+3]+roleName+":"+rolePassword+admin[at:], 4)
	if err != nil {
		t.Fatalf("connecting as %s: %v", roleName, err)
	}
	t.Cleanup(pool.Close)
	return pool
}

// fixture creates one owner, one product with a slug unique to the test, and
// deployments under it, and removes all of it afterwards.
type fixture struct {
	t         *testing.T
	admin     *pgxpool.Pool
	unique    string
	slug      string
	userID    int
	productID int
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	f := &fixture{t: t, admin: adminPool(t), unique: fmt.Sprintf("%d", time.Now().UnixNano())}
	f.slug = "custom-test-" + f.unique
	f.userID = f.queryInt(`INSERT INTO "user" (email, is_admin, created_at) VALUES ($1, false, now()) RETURNING id`,
		"owner-"+f.unique+"@app-auth.test")
	f.productID = f.queryInt(`INSERT INTO product (name, slug, description, created_at) VALUES ($1, $1, 'app-auth test', now()) RETURNING id`, f.slug)
	t.Cleanup(f.cleanup)
	return f
}

func (f *fixture) queryInt(sql string, args ...any) int {
	f.t.Helper()
	var id int
	if err := f.admin.QueryRow(context.Background(), sql, args...).Scan(&id); err != nil {
		f.t.Fatalf("fixture: %v\n%s", err, sql)
	}
	return id
}

func (f *fixture) exec(sql string, args ...any) {
	f.t.Helper()
	if _, err := f.admin.Exec(context.Background(), sql, args...); err != nil {
		f.t.Fatalf("fixture: %v\n%s", err, sql)
	}
}

func (f *fixture) store(pool *pgxpool.Pool) *pgStore {
	return &pgStore{pool: pool, productSlug: f.slug}
}

// deployment inserts a deployment whose applied release carries `values`, the
// way the reconciler leaves one it has rolled out.
func (f *fixture) deployment(hostname, status, values string) string {
	f.t.Helper()
	templateID := f.queryInt(`INSERT INTO product_template_version (product_id, chart_ref, chart_version, created_at)
		VALUES ($1, 'oci://test/', '1.0.0', now()) RETURNING id`, f.productID)
	planID := f.queryInt(`INSERT INTO plan (name, product_id, created_at) VALUES ($1, $2, now()) RETURNING id`,
		fmt.Sprintf("free-%s-%d", f.unique, templateID), f.productID)
	ptID := f.queryInt(`INSERT INTO plan_template_version (plan_id, price_cents, billing_interval, created_at)
		VALUES ($1, 0, 'monthly', now()) RETURNING id`, planID)
	subID := f.queryInt(`INSERT INTO subscription (plan_template_id, user_id, status, payment_status, created_at)
		VALUES ($1, $2, 'active', 'current', now()) RETURNING id`, ptID, f.userID)

	ctx := context.Background()
	tx, err := f.admin.Begin(ctx)
	if err != nil {
		f.t.Fatal(err)
	}
	defer tx.Rollback(ctx)
	var id, releaseID string
	tx.QueryRow(ctx, `SELECT gen_random_uuid()::text, gen_random_uuid()::text`).Scan(&id, &releaseID)
	tx.Exec(ctx, `SET CONSTRAINTS ALL DEFERRED`)
	name := fmt.Sprintf("d%d", time.Now().UnixNano())
	if _, err := tx.Exec(ctx, `INSERT INTO deployment
		  (id, user_id, desired_template_id, desired_release_id, applied_release_id, name, namespace,
		   status, generation, subscription_id, hostname, created_at)
		VALUES ($1, $2, $3, $4, $4, $5, $5, $6, 1, $7, $8, now())`,
		id, f.userID, templateID, releaseID, name, status, subID, hostname); err != nil {
		f.t.Fatal(err)
	}
	if _, err := tx.Exec(ctx, `INSERT INTO deployment_release (id, number, deployment_id, template_id, values_json, created_at)
		VALUES ($1, 1, $2, $3, $4::json, now())`, releaseID, id, templateID, values); err != nil {
		f.t.Fatal(err)
	}
	if err := tx.Commit(ctx); err != nil {
		f.t.Fatal(err)
	}
	return id
}

// release records a newer desired release without applying it, as a deploy in
// flight does.
func (f *fixture) desire(deploymentID, values string) {
	f.t.Helper()
	ctx := context.Background()
	tx, _ := f.admin.Begin(ctx)
	defer tx.Rollback(ctx)
	var releaseID string
	tx.QueryRow(ctx, `SELECT gen_random_uuid()::text`).Scan(&releaseID)
	if _, err := tx.Exec(ctx, `INSERT INTO deployment_release (id, number, deployment_id, template_id, values_json, created_at)
		SELECT $1, 2, id, desired_template_id, $2::json, now() FROM deployment WHERE id = $3`, releaseID, values, deploymentID); err != nil {
		f.t.Fatal(err)
	}
	tx.Exec(ctx, `UPDATE deployment SET desired_release_id = $1, user_values_json = $2::json WHERE id = $3`, releaseID, values, deploymentID)
	tx.Commit(ctx)
}

func (f *fixture) cleanup() {
	ctx := context.Background()
	for _, sql := range []string{
		`DELETE FROM app_auth_consent WHERE deployment_id IN (SELECT id FROM deployment WHERE user_id = $1)`,
		`UPDATE deployment SET applied_release_id = NULL WHERE user_id = $1`,
		`DELETE FROM deployment_release WHERE deployment_id IN (SELECT id FROM deployment WHERE user_id = $1)`,
		`DELETE FROM deployment WHERE user_id = $1`,
		`DELETE FROM subscription WHERE user_id = $1`,
		`DELETE FROM "user" WHERE id = $1`,
	} {
		if _, err := f.admin.Exec(ctx, sql, f.userID); err != nil {
			f.t.Logf("cleanup: %v", err)
		}
	}
	f.admin.Exec(ctx, `DELETE FROM plan_template_version WHERE plan_id IN (SELECT id FROM plan WHERE product_id = $1)`, f.productID)
	f.admin.Exec(ctx, `DELETE FROM plan WHERE product_id = $1`, f.productID)
	f.admin.Exec(ctx, `DELETE FROM product_template_version WHERE product_id = $1`, f.productID)
	f.admin.Exec(ctx, `DELETE FROM product WHERE id = $1`, f.productID)
}

const authOn = `{"hostname":"x","auth":{"enabled":true}}`

func TestEligibility(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	u := f.unique

	enabled := f.deployment("milk-"+u+".erik.freepod.eu", "provisioned", authOn)
	custom := f.deployment("shop-"+u+".example.com", "provisioned", authOn)
	f.deployment("plain-"+u+".erik.freepod.eu", "provisioned", `{"hostname":"x"}`)
	f.deployment("off-"+u+".erik.freepod.eu", "provisioned", `{"hostname":"x","auth":{"enabled":false}}`)
	f.deployment("gone-"+u+".erik.freepod.eu", "deleted", authOn)
	rolling := f.deployment("rolling-"+u+".erik.freepod.eu", "provisioned", `{"hostname":"x"}`)
	f.desire(rolling, authOn)
	disabling := f.deployment("disabling-"+u+".erik.freepod.eu", "provisioned", authOn)
	f.desire(disabling, `{"hostname":"x"}`)

	cases := []struct {
		host string
		want string
	}{
		{"milk-" + u + ".erik.freepod.eu", enabled},
		{"MILK-" + u + ".Erik.Freepod.EU", enabled},
		{"shop-" + u + ".example.com", custom},
		{"plain-" + u + ".erik.freepod.eu", ""},
		{"off-" + u + ".erik.freepod.eu", ""},
		{"gone-" + u + ".erik.freepod.eu", ""},
		{"evil.example", ""},
		// The edge enforces what the applied release rendered, so the broker
		// agrees with it until the new release is live.
		{"rolling-" + u + ".erik.freepod.eu", ""},
		{"disabling-" + u + ".erik.freepod.eu", disabling},
	}
	for _, c := range cases {
		id, ok, err := st.eligible(ctx, c.host)
		if err != nil {
			t.Fatal(err)
		}
		if ok != (c.want != "") || id != c.want {
			t.Errorf("eligible(%q) = %q, %v; want %q", c.host, id, ok, c.want)
		}
	}
	if _, ok, _ := (&pgStore{pool: st.pool, productSlug: "someone-else"}).eligible(ctx, "milk-"+u+".erik.freepod.eu"); ok {
		t.Error("a deployment of another product was eligible")
	}
}

func TestConsent(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	dep := f.deployment("c-"+f.unique+".erik.freepod.eu", "provisioned", authOn)

	if ok, _ := st.hasConsent(ctx, "3f2a", dep, disclosedClaims); ok {
		t.Fatal("consent before any was given")
	}
	for i := 0; i < 2; i++ {
		if err := st.recordConsent(ctx, "3f2a", dep, disclosedClaims); err != nil {
			t.Fatal(err)
		}
	}
	var n int
	f.admin.QueryRow(ctx, `SELECT count(*) FROM app_auth_consent WHERE deployment_id = $1::uuid`, dep).Scan(&n)
	if n != 1 {
		t.Fatalf("%d consent rows, want exactly one", n)
	}
	if ok, _ := st.hasConsent(ctx, "3f2a", dep, disclosedClaims); !ok {
		t.Fatal("recorded consent not found")
	}
	if ok, _ := st.hasConsent(ctx, "3f2a", dep, append([]string{"picture"}, disclosedClaims...)); ok {
		t.Fatal("consent covered a claim it was never given for")
	}
	other := f.deployment("c2-"+f.unique+".erik.freepod.eu", "provisioned", authOn)
	if ok, _ := st.hasConsent(ctx, "3f2a", other, disclosedClaims); ok {
		t.Fatal("consent for one deployment counted for another")
	}
}

func TestCodes(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	rec := codeRecord{Host: "milk.example", Subject: "3f2a", Email: "a@x", Name: "A", ReturnPath: "/", NonceHash: sha256Bytes("n")}

	code := randomToken()
	if err := st.insertCode(ctx, sha256Bytes(code), rec); err != nil {
		t.Fatal(err)
	}
	var stored []byte
	f.admin.QueryRow(ctx, `SELECT code_hash FROM app_auth_code WHERE code_hash = $1`, sha256Bytes(code)).Scan(&stored)
	if _, _, found, _ := st.redeemCode(ctx, sha256Bytes(string(stored))); found {
		t.Fatal("the stored hash was redeemable as a code")
	}

	t.Run("concurrent redemption succeeds once", func(t *testing.T) {
		code := randomToken()
		st.insertCode(ctx, sha256Bytes(code), rec)
		var wg sync.WaitGroup
		var mu sync.Mutex
		wins := 0
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if _, fresh, found, err := st.redeemCode(ctx, sha256Bytes(code)); err == nil && found && fresh {
					mu.Lock()
					wins++
					mu.Unlock()
				}
			}()
		}
		wg.Wait()
		if wins != 1 {
			t.Fatalf("%d redemptions succeeded", wins)
		}
	})

	t.Run("expiry", func(t *testing.T) {
		code := randomToken()
		st.insertCode(ctx, sha256Bytes(code), rec)
		f.exec(`UPDATE app_auth_code SET expires_at = expires_at - interval '61 seconds' WHERE code_hash = $1`, sha256Bytes(code))
		got, fresh, found, err := st.redeemCode(ctx, sha256Bytes(code))
		if err != nil || !found || fresh {
			t.Fatalf("found=%v fresh=%v err=%v", found, fresh, err)
		}
		if got.Host != rec.Host || string(got.NonceHash) != string(rec.NonceHash) {
			t.Fatalf("record %+v", got)
		}
	})

	t.Run("purge", func(t *testing.T) {
		expired, live := randomToken(), randomToken()
		st.insertCode(ctx, sha256Bytes(expired), rec)
		st.insertCode(ctx, sha256Bytes(live), rec)
		f.exec(`UPDATE app_auth_code SET expires_at = expires_at - interval '2 hours' WHERE code_hash = $1`, sha256Bytes(expired))
		if _, err := st.purgeExpiredCodes(ctx); err != nil {
			t.Fatal(err)
		}
		var n int
		f.admin.QueryRow(ctx, `SELECT count(*) FROM app_auth_code WHERE code_hash = ANY($1)`,
			[][]byte{sha256Bytes(expired), sha256Bytes(live)}).Scan(&n)
		if n != 1 {
			t.Fatalf("%d codes left, want only the live one", n)
		}
		st.redeemCode(ctx, sha256Bytes(live))
	})
}

func TestRoleIsLeastPrivilege(t *testing.T) {
	f := newFixture(t)
	pool := rolePool(t)
	ctx := context.Background()
	dep := f.deployment("r-"+f.unique+".erik.freepod.eu", "provisioned", authOn)

	denied := map[string]string{
		"write deployments":        `UPDATE deployment SET hostname = hostname WHERE id = '` + dep + `'`,
		"read the owner":           `SELECT user_id FROM deployment LIMIT 1`,
		"read var values":          `SELECT * FROM deployment_var LIMIT 1`,
		"read database passwords":  `SELECT * FROM deployment_database LIMIT 1`,
		"read accounts":            `SELECT email FROM "user" LIMIT 1`,
		"update consent":           `UPDATE app_auth_consent SET claims = '{}'`,
		"read release build ids":   `SELECT build_id FROM deployment_release LIMIT 1`,
		"read template chart refs": `SELECT chart_ref FROM product_template_version LIMIT 1`,
	}
	for name, sql := range denied {
		t.Run(name, func(t *testing.T) {
			_, err := pool.Exec(ctx, sql)
			if err == nil || !strings.Contains(err.Error(), "permission denied") {
				t.Fatalf("got %v, want permission denied", err)
			}
		})
	}
}
