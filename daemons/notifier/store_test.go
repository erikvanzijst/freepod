package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Like app-auth's, these run against the real migrated schema -- the database
// `api/tests/conftest.py` migrates with the Alembic chain -- and as the real
// role, created by the SQL Terraform ships.
const noDatabase = `
CAELUS_TEST_DATABASE_URL is not set, or names a database without the outbox.
Inside the devcontainer the variable is set; migrate the database with:

    cd api && CAELUS_DATABASE_URL=$CAELUS_TEST_DATABASE_URL uv run alembic upgrade head
`

const (
	roleBootstrap = "../../tf/app/caelus/notifier-bootstrap.sql"
	roleName      = "caelus_notifier"
	rolePassword  = "notifier-test-password"
)

func testDSN(t *testing.T) string {
	t.Helper()
	raw := os.Getenv("CAELUS_TEST_DATABASE_URL")
	if raw == "" {
		t.Fatal(noDatabase)
	}
	return strings.Replace(raw, "postgresql+psycopg://", "postgresql://", 1)
}

func roleDSN(t *testing.T) string {
	admin := testDSN(t)
	at := strings.LastIndex(admin, "@")
	scheme := strings.Index(admin, "://")
	return admin[:scheme+3] + roleName + ":" + rolePassword + admin[at:]
}

var roleOnce sync.Once
var roleErr error

// fixture holds an admin pool for arranging rows and a pool as the notifier's
// role for the code under test. The outbox is emptied first: the sweep takes
// every pending row, and tests in this package run one at a time.
type fixture struct {
	t      *testing.T
	admin  *pgxpool.Pool
	role   *pgxpool.Pool
	unique string
	users  []int
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	ctx := context.Background()
	admin, err := pgxpool.New(ctx, testDSN(t))
	if err != nil {
		t.Fatalf("%s\n(%v)", noDatabase, err)
	}
	t.Cleanup(admin.Close)
	var n int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM information_schema.tables
		WHERE table_schema = 'public' AND table_name = 'notification_outbox'`).Scan(&n); err != nil || n != 1 {
		t.Fatal(noDatabase)
	}
	roleOnce.Do(func() {
		if _, err := exec.LookPath("psql"); err != nil {
			roleErr = fmt.Errorf("psql is not installed; it is how the cluster applies the bootstrap")
			return
		}
		out, err := exec.Command("psql", testDSN(t), "-q", "-v", "ON_ERROR_STOP=1",
			"-v", "notifier_password="+rolePassword, "-f", roleBootstrap).CombinedOutput()
		if err != nil {
			roleErr = fmt.Errorf("bootstrap: %v\n%s", err, out)
		}
	})
	if roleErr != nil {
		t.Fatal(roleErr)
	}
	role, err := openPool(ctx, roleDSN(t))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(role.Close)
	f := &fixture{t: t, admin: admin, role: role, unique: fmt.Sprintf("%d", time.Now().UnixNano())}
	f.exec(`DELETE FROM notification_outbox`)
	t.Cleanup(func() {
		f.exec(`DELETE FROM notification_outbox`)
		for _, id := range f.users {
			f.exec(`DELETE FROM "user" WHERE id = $1`, id)
		}
	})
	return f
}

func (f *fixture) exec(sql string, args ...any) {
	f.t.Helper()
	if _, err := f.admin.Exec(context.Background(), sql, args...); err != nil {
		f.t.Fatalf("fixture: %v\n%s", err, sql)
	}
}

func (f *fixture) user(email string) int {
	f.t.Helper()
	var id int
	if err := f.admin.QueryRow(context.Background(),
		`INSERT INTO "user" (email, is_admin, created_at) VALUES ($1, false, now()) RETURNING id`, email,
	).Scan(&id); err != nil {
		f.t.Fatal(err)
	}
	f.users = append(f.users, id)
	return id
}

// queue inserts a pending notification, to an address or to a user, and
// returns its id.
func (f *fixture) queue(recipient any) string {
	f.t.Helper()
	column := "recipient_email"
	if _, ok := recipient.(int); ok {
		column = "recipient_user_id"
	}
	var id string
	if err := f.admin.QueryRow(context.Background(), `
		INSERT INTO notification_outbox (kind, `+column+`, subject, body, reason)
		VALUES ('access.invitation', $1, 'Subject', 'Body', 'Reason') RETURNING id::text`, recipient,
	).Scan(&id); err != nil {
		f.t.Fatal(err)
	}
	return id
}

type outcome struct {
	state, err string
	attempts   int
	sent       bool
}

func (f *fixture) outcome(id string) outcome {
	f.t.Helper()
	var o outcome
	if err := f.admin.QueryRow(context.Background(), `
		SELECT state::text, coalesce(error, ''), attempts, sent_at IS NOT NULL
		  FROM notification_outbox WHERE id = $1::uuid`, id,
	).Scan(&o.state, &o.err, &o.attempts, &o.sent); err != nil {
		f.t.Fatal(err)
	}
	return o
}

func (f *fixture) sender(transport deliverer) *sender {
	s := &sender{pool: f.role, retryPause: time.Millisecond, log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if transport != nil {
		s.transport = transport
	}
	return s
}

// fakeTransport fails its first `fail` deliveries and records the rest.
type fakeTransport struct {
	mu        sync.Mutex
	fail      int
	calls     int
	delivered []string
	block     chan struct{}
}

func (f *fakeTransport) deliver(id, to string, m message) error {
	if f.block != nil {
		<-f.block
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	if f.fail > 0 {
		f.fail--
		return errors.New("451 try again later")
	}
	f.delivered = append(f.delivered, to)
	return nil
}

func TestSweepSendsToTheUsersCurrentAddress(t *testing.T) {
	f := newFixture(t)
	user := f.user("ana-" + f.unique + "@notifier.test")
	id := f.queue(user)
	f.exec(`UPDATE "user" SET email = $2 WHERE id = $1`, user, "ana-new-"+f.unique+"@notifier.test")
	tr := &fakeTransport{}
	if err := f.sender(tr).sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	if o := f.outcome(id); o != (outcome{state: "sent", attempts: 1, sent: true}) {
		t.Fatalf("outcome %+v", o)
	}
	if len(tr.delivered) != 1 || tr.delivered[0] != "ana-new-"+f.unique+"@notifier.test" {
		t.Fatalf("delivered %v", tr.delivered)
	}
}

func TestSweepTakesEveryPendingRowOnce(t *testing.T) {
	f := newFixture(t)
	ids := []string{f.queue("a@notifier.test"), f.queue("b@notifier.test"), f.queue("c@notifier.test")}
	tr := &fakeTransport{}
	s := f.sender(tr)
	for range 2 {
		if err := s.sweep(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if strings.Join(tr.delivered, ",") != "a@notifier.test,b@notifier.test,c@notifier.test" {
		t.Fatalf("delivered %v", tr.delivered)
	}
	for _, id := range ids {
		if o := f.outcome(id); o.state != "sent" {
			t.Fatalf("%s: %+v", id, o)
		}
	}
}

func TestARetrySucceeds(t *testing.T) {
	f := newFixture(t)
	id := f.queue("a@notifier.test")
	if err := f.sender(&fakeTransport{fail: 1}).sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	if o := f.outcome(id); o != (outcome{state: "sent", attempts: 2, sent: true}) {
		t.Fatalf("outcome %+v", o)
	}
}

func TestThreeFailuresFail(t *testing.T) {
	f := newFixture(t)
	id := f.queue("a@notifier.test")
	tr := &fakeTransport{fail: 5}
	s := f.sender(tr)
	for range 2 {
		if err := s.sweep(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if o := f.outcome(id); o != (outcome{state: "failed", err: "451 try again later", attempts: 3}) {
		t.Fatalf("outcome %+v", o)
	}
	if tr.calls != 3 {
		t.Fatalf("a failed notification was attempted again: %d calls", tr.calls)
	}
}

func TestNoRelaySuppresses(t *testing.T) {
	f := newFixture(t)
	id := f.queue("a@notifier.test")
	if err := f.sender(nil).sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	if o := f.outcome(id); o != (outcome{state: "suppressed"}) {
		t.Fatalf("outcome %+v", o)
	}
}

func TestAUserWithoutAnAddressFails(t *testing.T) {
	f := newFixture(t)
	user := f.user("")
	id := f.queue(user)
	tr := &fakeTransport{}
	if err := f.sender(tr).sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	o := f.outcome(id)
	if o.state != "failed" || o.attempts != 0 || !strings.Contains(o.err, "no email address") || tr.calls != 0 {
		t.Fatalf("outcome %+v, calls %d", o, tr.calls)
	}
}

func TestTwoSendersDeliverARowOnce(t *testing.T) {
	f := newFixture(t)
	id := f.queue("a@notifier.test")
	tr := &fakeTransport{block: make(chan struct{})}
	first, second := f.sender(tr), f.sender(tr)
	done := make(chan error)
	go func() { done <- first.sweep(context.Background()) }()
	time.Sleep(200 * time.Millisecond) // first holds the row's lock, blocked in delivery
	if err := second.sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	close(tr.block)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if tr.calls != 1 || f.outcome(id).state != "sent" {
		t.Fatalf("calls %d, outcome %+v", tr.calls, f.outcome(id))
	}
}

func TestShutdownBeforeRecordingLeavesTheRowPending(t *testing.T) {
	f := newFixture(t)
	id := f.queue("a@notifier.test")
	ctx, cancel := context.WithCancel(context.Background())
	tr := &fakeTransport{fail: 5}
	s := f.sender(tr)
	s.retryPause = time.Hour
	done := make(chan error)
	go func() { done <- s.sweep(ctx) }()
	time.Sleep(200 * time.Millisecond) // first attempt failed, now pausing
	cancel()
	<-done
	if o := f.outcome(id); o != (outcome{state: "pending"}) {
		t.Fatalf("outcome %+v", o)
	}
}
