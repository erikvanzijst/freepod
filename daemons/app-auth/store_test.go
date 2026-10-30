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

// fixture creates one owner, two products and deployments under them, and
// removes all of it afterwards. Hostnames carry a suffix unique to the test,
// which is what keeps tests apart in a database the API suite shares.
type fixture struct {
	t              *testing.T
	admin          *pgxpool.Pool
	unique         string
	userID         int
	productID      int
	otherProductID int
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	f := &fixture{t: t, admin: adminPool(t), unique: fmt.Sprintf("%d", time.Now().UnixNano())}
	f.userID = f.queryInt(`INSERT INTO "user" (email, is_admin, created_at) VALUES ($1, false, now()) RETURNING id`,
		"owner-"+f.unique+"@app-auth.test")
	f.productID = f.queryInt(`INSERT INTO product (name, slug, description, created_at) VALUES ($1, $1, 'app-auth test', now()) RETURNING id`,
		"app-auth-test-"+f.unique)
	f.otherProductID = f.queryInt(`INSERT INTO product (name, description, created_at) VALUES ($1, 'app-auth test', now()) RETURNING id`,
		"app-auth-other-"+f.unique)
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
	return &pgStore{pool: pool}
}

// deployment inserts a deployment whose applied release carries `values`, the
// way the reconciler leaves one it has rolled out.
func (f *fixture) deployment(hostname, status, values string) string {
	f.t.Helper()
	return f.deploymentOf(f.productID, hostname, status, values, "")
}

// deploymentOf is deployment for a given product, with `system` as its
// template's system values (empty for none).
func (f *fixture) deploymentOf(productID int, hostname, status, values, system string) string {
	f.t.Helper()
	var systemValues any
	if system != "" {
		systemValues = system
	}
	templateID := f.queryInt(`INSERT INTO product_template_version (product_id, chart_ref, chart_version, system_values_json, created_at)
		VALUES ($1, 'oci://test/', '1.0.0', $2::json, now()) RETURNING id`, productID, systemValues)
	planID := f.queryInt(`INSERT INTO plan (name, product_id, created_at) VALUES ($1, $2, now()) RETURNING id`,
		fmt.Sprintf("free-%s-%d", f.unique, templateID), productID)
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
		`DELETE FROM app_access_entry WHERE deployment_id IN (SELECT id FROM deployment WHERE user_id = $1)`,
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
	for _, product := range []int{f.productID, f.otherProductID} {
		f.admin.Exec(ctx, `DELETE FROM plan_template_version WHERE plan_id IN (SELECT id FROM plan WHERE product_id = $1)`, product)
		f.admin.Exec(ctx, `DELETE FROM plan WHERE product_id = $1`, product)
		f.admin.Exec(ctx, `DELETE FROM product_template_version WHERE product_id = $1`, product)
		f.admin.Exec(ctx, `DELETE FROM product WHERE id = $1`, product)
	}
}

const authOn = `{"hostname":"x","auth":{"enabled":true}}`

func TestEligibility(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	u := f.unique

	enabled := f.deployment("milk-"+u+"-erik.freepod.app", "provisioned", authOn)
	custom := f.deployment("shop-"+u+".example.com", "provisioned", authOn)
	f.deployment("plain-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x"}`)
	f.deployment("off-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x","auth":{"enabled":false}}`)
	f.deployment("gone-"+u+"-erik.freepod.app", "deleted", authOn)
	rolling := f.deployment("rolling-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x"}`)
	f.desire(rolling, authOn)
	disabling := f.deployment("disabling-"+u+"-erik.freepod.app", "provisioned", authOn)
	f.desire(disabling, `{"hostname":"x"}`)
	// Any product qualifies, and a template may turn authentication on itself.
	// Its system value is a default: a user value overrides it, as the
	// reconciler's Helm merge does.
	other := f.deploymentOf(f.otherProductID, "other-"+u+"-erik.freepod.app", "provisioned", authOn, "")
	templated := f.deploymentOf(f.otherProductID, "templated-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x"}`, `{"auth":{"enabled":true}}`)
	f.deploymentOf(f.otherProductID, "overridden-"+u+"-erik.freepod.app", "provisioned",
		`{"hostname":"x","auth":{"enabled":false}}`, `{"auth":{"enabled":true}}`)
	templateOff := f.deploymentOf(f.otherProductID, "templateoff-"+u+"-erik.freepod.app", "provisioned", authOn, `{"auth":{"enabled":false}}`)
	f.deploymentOf(f.otherProductID, "nosetting-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x"}`, `{"nodePool":"tenant"}`)
	// The store matches hostnames exactly; preview hostnames are the broker's.
	f.deployment("preview-milk-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x"}`)
	f.deployment("oidc-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x","auth":{"enabled":true,"protocol":"oidc"}}`)
	f.deployment("saml-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x","auth":{"enabled":true,"protocol":"saml"}}`)
	explicit := f.deployment("explicit-"+u+"-erik.freepod.app", "provisioned", `{"hostname":"x","auth":{"enabled":true,"protocol":"header"}}`)
	f.deploymentOf(f.otherProductID, "templateoidc-"+u+"-erik.freepod.app", "provisioned", authOn, `{"auth":{"protocol":"oidc"}}`)
	userHeader := f.deploymentOf(f.otherProductID, "userheader-"+u+"-erik.freepod.app", "provisioned",
		`{"hostname":"x","auth":{"enabled":true,"protocol":"header"}}`, `{"auth":{"protocol":"oidc"}}`)

	cases := []struct {
		host string
		want string
	}{
		{"milk-" + u + "-erik.freepod.app", enabled},
		{"MILK-" + u + "-Erik.Freepod.APP", enabled},
		{"shop-" + u + ".example.com", custom},
		{"plain-" + u + "-erik.freepod.app", ""},
		{"off-" + u + "-erik.freepod.app", ""},
		{"gone-" + u + "-erik.freepod.app", ""},
		{"evil.example", ""},
		// The edge enforces what the applied release rendered, so the broker
		// agrees with it until the new release is live.
		{"rolling-" + u + "-erik.freepod.app", ""},
		{"disabling-" + u + "-erik.freepod.app", disabling},
		{"other-" + u + "-erik.freepod.app", other},
		{"templated-" + u + "-erik.freepod.app", templated},
		{"overridden-" + u + "-erik.freepod.app", ""},
		{"templateoff-" + u + "-erik.freepod.app", templateOff},
		{"nosetting-" + u + "-erik.freepod.app", ""},
		{"preview-milk-" + u + "-erik.freepod.app", ""},
		// Header authentication needs `auth.protocol: header`, its default.
		{"oidc-" + u + "-erik.freepod.app", ""},
		{"saml-" + u + "-erik.freepod.app", ""},
		{"explicit-" + u + "-erik.freepod.app", explicit},
		{"templateoidc-" + u + "-erik.freepod.app", ""},
		{"userheader-" + u + "-erik.freepod.app", userHeader},
	}
	for _, c := range cases {
		app, ok, err := st.eligible(ctx, c.host)
		if err != nil {
			t.Fatal(err)
		}
		if ok != (c.want != "") || app.ID != c.want {
			t.Errorf("eligible(%q) = %q, %v; want %q", c.host, app.ID, ok, c.want)
		}
	}
}

func TestEligibleAccess(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	u := f.unique
	p := f.otherProductID

	for i, c := range []struct {
		name, values, system string
		listed               bool
	}{
		{"default", authOn, "", false},
		{"user lists", `{"hostname":"x","auth":{"enabled":true,"access":"listed"}}`, "", true},
		{"template lists", `{"hostname":"x"}`, `{"auth":{"enabled":true,"access":"listed"}}`, true},
		{"user value over template's", `{"hostname":"x","auth":{"access":"anyone"}}`, `{"auth":{"enabled":true,"access":"listed"}}`, false},
		{"unknown access fails closed", `{"hostname":"x","auth":{"enabled":true,"access":"friends"}}`, "", true},
		{"anyone, stated", `{"hostname":"x","auth":{"enabled":true,"access":"anyone"}}`, "", false},
	} {
		t.Run(c.name, func(t *testing.T) {
			host := fmt.Sprintf("access%d-%s.example.com", i, u)
			id := f.deploymentOf(p, host, "provisioned", c.values, c.system)
			app, ok, err := st.eligible(ctx, host)
			if err != nil || !ok || app.ID != id {
				t.Fatalf("eligible = %+v, %v, %v", app, ok, err)
			}
			if app.Listed != c.listed {
				t.Fatalf("listed = %v, want %v", app.Listed, c.listed)
			}
		})
	}
}

func TestAccessList(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	dep := f.deployment("list-"+f.unique+"-erik.freepod.app", "provisioned", authOn)
	other := f.deployment("list2-"+f.unique+"-erik.freepod.app", "provisioned", authOn)
	entry := func(dep, email string) string {
		var id string
		if err := f.admin.QueryRow(ctx, `INSERT INTO app_access_entry (id, deployment_id, email, created_at)
			VALUES (gen_random_uuid(), $1::uuid, $2, now()) RETURNING id::text`, dep, email).Scan(&id); err != nil {
			t.Fatal(err)
		}
		return id
	}
	jules := entry(dep, "jules@example.org")
	noor := entry(dep, "noor@example.org")
	entry(other, "sam@example.org")

	l, err := st.accessList(ctx, dep)
	if err != nil {
		t.Fatal(err)
	}
	if l.OwnerEmail != "owner-"+f.unique+"@app-auth.test" || len(l.Entries) != 2 {
		t.Fatalf("list %+v", l)
	}

	if bound, err := st.bindEntry(ctx, jules, "s-jules", "Jules"); err != nil || !bound {
		t.Fatalf("bind = %v, %v", bound, err)
	}
	if bound, err := st.bindEntry(ctx, jules, "s-other", "Other"); err != nil || bound {
		t.Fatalf("rebinding a bound entry = %v, %v", bound, err)
	}
	if bound, err := st.bindEntry(ctx, noor, "s-jules", "Jules"); err != nil || bound {
		t.Fatalf("binding a second entry to one subject = %v, %v", bound, err)
	}
	var sub, name string
	var boundAt *time.Time
	f.admin.QueryRow(ctx, `SELECT subject, name, bound_at FROM app_access_entry WHERE id = $1::uuid`, jules).Scan(&sub, &name, &boundAt)
	if sub != "s-jules" || name != "Jules" || boundAt == nil {
		t.Fatalf("entry holds %q %q %v", sub, name, boundAt)
	}

	t.Run("concurrent binds by one subject", func(t *testing.T) {
		id := entry(dep, "concurrent@example.org")
		var wg sync.WaitGroup
		var mu sync.Mutex
		wins := 0
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if bound, err := st.bindEntry(ctx, id, "s-concurrent", "C"); err == nil && bound {
					mu.Lock()
					wins++
					mu.Unlock()
				}
			}()
		}
		wg.Wait()
		if wins != 1 {
			t.Fatalf("%d binds succeeded", wins)
		}
	})
}

func TestConsent(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	dep := f.deployment("c-"+f.unique+"-erik.freepod.app", "provisioned", authOn)

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
	other := f.deployment("c2-"+f.unique+"-erik.freepod.app", "provisioned", authOn)
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
	dep := f.deployment("r-"+f.unique+"-erik.freepod.app", "provisioned", authOn)

	denied := map[string]string{
		"write deployments":          `UPDATE deployment SET hostname = hostname WHERE id = '` + dep + `'`,
		"read var values":            `SELECT * FROM deployment_var LIMIT 1`,
		"read database passwords":    `SELECT * FROM deployment_database LIMIT 1`,
		"read other account columns": `SELECT handle FROM "user" LIMIT 1`,
		"update consent":             `UPDATE app_auth_consent SET claims = '{}'`,
		"update OIDC codes":          `UPDATE app_auth_oidc_code SET subject = subject`,
		"read release build ids":     `SELECT build_id FROM deployment_release LIMIT 1`,
		"read template chart refs":   `SELECT chart_ref FROM product_template_version LIMIT 1`,
		"read products":              `SELECT name FROM product LIMIT 1`,
		"insert access entries":      `INSERT INTO app_access_entry (id, deployment_id, email, created_at) VALUES (gen_random_uuid(), '` + dep + `', 'x@example.com', now())`,
		"change an entry's email":    `UPDATE app_access_entry SET email = email`,
		"delete access entries":      `DELETE FROM app_access_entry`,
		"read invitations":           `SELECT * FROM app_access_invitation LIMIT 1`,
	}
	for name, sql := range denied {
		t.Run(name, func(t *testing.T) {
			_, err := pool.Exec(ctx, sql)
			if err == nil || !strings.Contains(err.Error(), "permission denied") {
				t.Fatalf("got %v, want permission denied", err)
			}
		})
	}

	allowed := map[string]string{
		"read the owner":       `SELECT d.user_id, u.email FROM deployment d JOIN "user" u ON u.id = d.user_id LIMIT 1`,
		"read access entries":  `SELECT id, email, subject, name, created_at, bound_at FROM app_access_entry LIMIT 1`,
		"bind an access entry": `UPDATE app_access_entry SET subject = subject, name = name, bound_at = bound_at WHERE false`,
	}
	for name, sql := range allowed {
		t.Run(name, func(t *testing.T) {
			if _, err := pool.Exec(ctx, sql); err != nil {
				t.Fatal(err)
			}
		})
	}
}

const (
	ssoOn          = `{"hostname":"x","auth":{"enabled":true,"protocol":"oidc"}}`
	declaresSSO    = `{"auth":{"oidc":{"redirectPaths":["/oidc/callback"],"nativeRedirectUris":["app.immich:///oauth-callback"]}}}`
	declaresNoPKCE = `{"auth":{"oidc":{"redirectPaths":["/oidc/callback"],"pkce":false}}}`
)

func TestSSOClient(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	u := f.unique
	p := f.otherProductID

	enabled := f.deploymentOf(p, "Wiki-"+u+"-alice.freepod.app", "provisioned", ssoOn, declaresSSO)
	templated := f.deploymentOf(p, "templated-"+u+"-alice.freepod.app", "provisioned", `{"hostname":"x"}`,
		`{"auth":{"enabled":true,"protocol":"oidc","oidc":{"redirectPaths":["/cb"]}}}`)
	noPKCE := f.deploymentOf(p, "nopkce-"+u+"-alice.freepod.app", "provisioned", ssoOn, declaresNoPKCE)
	undeclared := f.deploymentOf(p, "undeclared-"+u+"-alice.freepod.app", "provisioned",
		`{"hostname":"x","auth":{"enabled":true,"protocol":"oidc","oidc":{"redirectPaths":["/cb"]}}}`, "")
	allInvalid := f.deploymentOf(p, "invalid-"+u+"-alice.freepod.app", "provisioned", ssoOn,
		`{"auth":{"oidc":{"redirectPaths":["@evil.example/cb",".evil.example/cb","/cb?next=/"]}}}`)
	userOverrides := f.deploymentOf(p, "useron-"+u+"-alice.freepod.app", "provisioned", ssoOn,
		`{"auth":{"enabled":false,"oidc":{"redirectPaths":["/cb"]}}}`)
	userTurnsOff := f.deploymentOf(p, "useroff-"+u+"-alice.freepod.app", "provisioned",
		`{"hostname":"x","auth":{"enabled":false}}`, `{"auth":{"enabled":true,"protocol":"oidc","oidc":{"redirectPaths":["/cb"]}}}`)
	headersOnly := f.deploymentOf(p, "headers-"+u+"-alice.freepod.app", "provisioned", authOn, declaresSSO)
	templateProtocol := f.deploymentOf(p, "tproto-"+u+"-alice.freepod.app", "provisioned", authOn,
		`{"auth":{"protocol":"oidc","oidc":{"redirectPaths":["/cb"]}}}`)
	unknownProtocol := f.deploymentOf(p, "saml-"+u+"-alice.freepod.app", "provisioned",
		`{"hostname":"x","auth":{"enabled":true,"protocol":"saml"}}`, declaresSSO)
	userNative := f.deploymentOf(p, "usernative-"+u+"-alice.freepod.app", "provisioned",
		`{"hostname":"x","auth":{"enabled":true,"protocol":"oidc","oidc":{"nativeRedirectUris":["app.evil:///steal"],"pkce":false}}}`, declaresSSO)
	listed := f.deploymentOf(p, "listed-"+u+"-alice.freepod.app", "provisioned",
		`{"hostname":"x","auth":{"enabled":true,"protocol":"oidc","access":"listed"}}`, declaresSSO)
	off := f.deploymentOf(p, "off-"+u+"-alice.freepod.app", "provisioned", `{"hostname":"x"}`, declaresSSO)
	rolling := f.deploymentOf(p, "rolling-"+u+"-alice.freepod.app", "provisioned", `{"hostname":"x"}`, declaresSSO)
	f.desire(rolling, ssoOn)
	deleted := f.deploymentOf(p, "gone-"+u+"-alice.freepod.app", "deleted", ssoOn, declaresSSO)

	for name, c := range map[string]struct {
		id   string
		want bool
	}{
		"user value":                    {enabled, true},
		"template enables":              {templated, true},
		"template opts out of PKCE":     {noPKCE, true},
		"template declares no paths":    {undeclared, false},
		"template paths all invalid":    {allInvalid, false},
		"user value over template's":    {userOverrides, true},
		"user turns the template's off": {userTurnsOff, false},
		"header authentication alone":   {headersOnly, false},
		"template sets the protocol":    {templateProtocol, true},
		"unknown protocol":              {unknownProtocol, false},
		"not enabled":                   {off, false},
		"enabled but not yet applied":   {rolling, false},
		"deleted":                       {deleted, false},
		"unknown":                       {"00000000-0000-0000-0000-000000000000", false},
		"not a deployment id":           {"evil'; --", false},
		"upper-case form of a real id":  {strings.ToUpper(enabled), false},
	} {
		t.Run(name, func(t *testing.T) {
			got, ok, err := st.ssoClient(ctx, c.id)
			if err != nil {
				t.Fatal(err)
			}
			if ok != c.want || (ok && got.ID != c.id) {
				t.Fatalf("ssoClient(%q) = %+v, %v; want %v", c.id, got, ok, c.want)
			}
		})
	}

	got, _, _ := st.ssoClient(ctx, enabled)
	host := "wiki-" + u + "-alice.freepod.app"
	if got.Hostname != host || len(got.RedirectURIs) != 1 || got.RedirectURIs[0] != "https://"+host+"/oidc/callback" ||
		len(got.NativeURIs) != 1 || got.NativeURIs[0] != "app.immich:///oauth-callback" || !got.PKCE {
		t.Fatalf("client %+v", got)
	}
	if got, _, _ := st.ssoClient(ctx, noPKCE); got.PKCE {
		t.Fatal("the template's PKCE opt-out was not read")
	}
	if got.Listed {
		t.Fatal("a client listed by default")
	}
	if got, _, _ := st.ssoClient(ctx, listed); !got.Listed {
		t.Fatal("auth.access: listed was not read")
	}
	// auth.oidc is read from the template alone.
	if got, _, _ := st.ssoClient(ctx, userNative); len(got.NativeURIs) != 1 || got.NativeURIs[0] != "app.immich:///oauth-callback" || !got.PKCE {
		t.Fatalf("user values reached the client: %+v", got)
	}
}

func TestOIDCCodes(t *testing.T) {
	f := newFixture(t)
	st := f.store(rolePool(t))
	ctx := context.Background()
	dep := f.deploymentOf(f.otherProductID, "codes-"+f.unique+"-alice.freepod.app", "provisioned", ssoOn, declaresSSO)
	authTime := time.Date(2026, 10, 26, 9, 30, 0, 0, time.FixedZone("CET", 3600))
	rec := oidcCode{DeploymentID: dep, RedirectURI: "https://x/cb", Subject: "3f2a", Email: "a@x", Name: "A",
		Nonce: "n", CodeChallenge: "c", AuthTime: authTime}

	code := randomToken()
	if err := st.insertOIDCCode(ctx, sha256Bytes(code), rec); err != nil {
		t.Fatal(err)
	}
	if _, _, found, _ := st.redeemCode(ctx, sha256Bytes(code)); found {
		t.Fatal("an OIDC code was redeemable as a sign-in code")
	}
	got, fresh, found, err := st.redeemOIDCCode(ctx, sha256Bytes(code))
	if err != nil || !found || !fresh {
		t.Fatalf("found=%v fresh=%v err=%v", found, fresh, err)
	}
	if !got.AuthTime.Equal(authTime) {
		t.Fatalf("auth_time %v, want %v", got.AuthTime, authTime)
	}
	got.AuthTime = rec.AuthTime
	if got != rec {
		t.Fatalf("record %+v", got)
	}
	if _, _, found, _ := st.redeemOIDCCode(ctx, sha256Bytes(code)); found {
		t.Fatal("redeemed twice")
	}

	t.Run("optional fields", func(t *testing.T) {
		code := randomToken()
		bare := rec
		bare.Nonce, bare.CodeChallenge = "", ""
		st.insertOIDCCode(ctx, sha256Bytes(code), bare)
		if got, _, _, _ := st.redeemOIDCCode(ctx, sha256Bytes(code)); got.Nonce != "" || got.CodeChallenge != "" {
			t.Fatalf("record %+v", got)
		}
	})

	t.Run("sign-in codes do not redeem as OIDC codes", func(t *testing.T) {
		code := randomToken()
		st.insertCode(ctx, sha256Bytes(code), codeRecord{Host: "h", Subject: "s", Email: "e", Name: "n", ReturnPath: "/", NonceHash: sha256Bytes("n")})
		if _, _, found, _ := st.redeemOIDCCode(ctx, sha256Bytes(code)); found {
			t.Fatal("a sign-in code was redeemable as an OIDC code")
		}
		st.redeemCode(ctx, sha256Bytes(code))
	})

	t.Run("concurrent redemption succeeds once", func(t *testing.T) {
		code := randomToken()
		st.insertOIDCCode(ctx, sha256Bytes(code), rec)
		var wg sync.WaitGroup
		var mu sync.Mutex
		wins := 0
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if _, fresh, found, err := st.redeemOIDCCode(ctx, sha256Bytes(code)); err == nil && found && fresh {
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

	t.Run("expiry and purge", func(t *testing.T) {
		stale, expired, live := randomToken(), randomToken(), randomToken()
		for _, c := range []string{stale, expired, live} {
			st.insertOIDCCode(ctx, sha256Bytes(c), rec)
		}
		f.exec(`UPDATE app_auth_oidc_code SET expires_at = expires_at - interval '61 seconds' WHERE code_hash = $1`, sha256Bytes(stale))
		if _, fresh, found, _ := st.redeemOIDCCode(ctx, sha256Bytes(stale)); !found || fresh {
			t.Fatalf("found=%v fresh=%v", found, fresh)
		}
		f.exec(`UPDATE app_auth_oidc_code SET expires_at = expires_at - interval '2 hours' WHERE code_hash = $1`, sha256Bytes(expired))
		if _, err := st.purgeExpiredCodes(ctx); err != nil {
			t.Fatal(err)
		}
		var n int
		f.admin.QueryRow(ctx, `SELECT count(*) FROM app_auth_oidc_code WHERE code_hash = ANY($1)`,
			[][]byte{sha256Bytes(expired), sha256Bytes(live)}).Scan(&n)
		if n != 1 {
			t.Fatalf("%d codes left, want only the live one", n)
		}
		st.redeemOIDCCode(ctx, sha256Bytes(live))
	})
}
