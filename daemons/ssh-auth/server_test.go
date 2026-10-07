package main

import (
	"bytes"
	"context"
	"log/slog"
	"net"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"

	pb "github.com/erikvanzijst/caelus/ssh-auth/internal/libplugin"
)

const sidecarPort = 2222

// harness runs the real servicer over a real loopback listener, because every
// interesting property here is an interaction: the callback list is what
// removes password authentication at the edge, a refusal is only useful if it
// looks like every other refusal, and failing closed is about what happens when
// the database is gone.
//
// What it cannot cover is sshpiperd's half. That was the spike --
// var/ssh_access.md, gRPC plugin spike results.
type harness struct {
	plugin pb.SshPiperPluginClient
	health grpc_health_v1.HealthClient
	logs   *bytes.Buffer
}

func newHarness(t *testing.T, pool *pgxpool.Pool) *harness {
	t.Helper()

	logs := &bytes.Buffer{}
	log := slog.New(slog.NewTextHandler(logs, nil))

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	s := grpc.NewServer()
	register(s,
		&resolver{db: pool, upstreamKey: upstreamKey, sidecarPort: sidecarPort, log: log},
		&health{db: pool, log: log},
	)
	go s.Serve(listener)

	conn, err := grpc.NewClient(listener.Addr().String(),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		conn.Close()
		s.Stop()
	})
	return &harness{
		plugin: pb.NewSshPiperPluginClient(conn),
		health: grpc_health_v1.NewHealthClient(conn),
		logs:   logs,
	}
}

func (h *harness) auth(t *testing.T, username, keyLine string) (*pb.PublicKeyAuthResponse, error) {
	t.Helper()
	return h.plugin.PublicKeyAuth(context.Background(), &pb.PublicKeyAuthRequest{
		Meta: &pb.ConnMeta{
			UserName: username,
			FromAddr: "203.0.113.7:51234",
			UniqId:   uuid.NewString(),
		},
		PublicKey: blob(t, keyLine),
	})
}

func (h *harness) mustAdmit(t *testing.T, username, keyLine string) *pb.Upstream {
	t.Helper()
	resp, err := h.auth(t, username, keyLine)
	if err != nil {
		t.Fatalf("expected %s to be admitted, got %v", username, err)
	}
	return resp.GetUpstream()
}

func (h *harness) mustRefuse(t *testing.T, username, keyLine string) {
	t.Helper()
	if _, err := h.auth(t, username, keyLine); err == nil {
		t.Fatalf("expected %s to be refused, it was admitted", username)
	} else if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("expected PermissionDenied, got %v", err)
	}
}

// ── only public-key authentication is offered ─────────────────────────────

func TestListCallbacksAdvertisesPublicKeyAuthAlone(t *testing.T) {
	h := newHarness(t, testPool(t))
	resp, err := h.plugin.ListCallbacks(context.Background(), &pb.ListCallbackRequest{})
	if err != nil {
		t.Fatal(err)
	}
	got := resp.GetCallbacks()
	if len(got) != 1 || got[0] != "PublicKeyAuth" {
		t.Fatalf("callbacks = %v, want [PublicKeyAuth]", got)
	}
}

// Password auth is absent at the edge because it is absent from this list.
// sshpiperd installs a handler for exactly the callbacks named here, so this
// assertion is the mechanism, not a proxy for it.
func TestNoOtherAuthenticationCallbackIsAdvertised(t *testing.T) {
	h := newHarness(t, testPool(t))
	resp, err := h.plugin.ListCallbacks(context.Background(), &pb.ListCallbackRequest{})
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range resp.GetCallbacks() {
		switch c {
		case "PasswordAuth", "KeyboardInteractiveAuth", "NoneAuth", "NextAuthMethods":
			t.Errorf("%s is advertised; password authentication would be reachable", c)
		}
	}
}

// sshpiperd opens this stream on connect whether or not it is advertised.
// Unimplemented it logs an error on every start; advertised it is a startup
// error, because `Logs` is not one of the callback names sshpiperd accepts.
func TestLogsIsImplementedButNotAdvertised(t *testing.T) {
	for _, c := range callbacks {
		if c == "Logs" {
			t.Fatal("Logs must not be advertised; sshpiperd rejects it as a callback name")
		}
	}
	h := newHarness(t, testPool(t))
	ctx, cancel := context.WithCancel(context.Background())
	stream, err := h.plugin.Logs(ctx, &pb.StartLogRequest{UniqId: "x", Level: "info"})
	if err != nil {
		t.Fatal(err)
	}
	cancel()
	if _, err := stream.Recv(); err == nil {
		t.Fatal("expected the stream to end, it yielded a message")
	}
}

// ── access requires a key registered on the owning account ────────────────

func TestOwnersRegisteredKeyIsAdmitted(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, namespace := f.deployment(owner, "hello-world-aaa111", "ready")
	f.registerKey(owner, ownerKey)

	up := newHarness(t, f.pool).mustAdmit(t, id, ownerKey)
	want := "tcp://hello-world-aaa111-ssh." + namespace + ".svc:2222"
	if up.GetUri() != want {
		t.Errorf("uri = %q, want %q", up.GetUri(), want)
	}
	if up.GetUserName() != "hello-world-aaa111" {
		t.Errorf("upstream user = %q, want the release name", up.GetUserName())
	}
}

func TestAnotherAccountsKeyIsRefused(t *testing.T) {
	f := newFixture(t)
	owner, stranger := f.user("owner"), f.user("stranger")
	id, _ := f.deployment(owner, "hello-world-bbb222", "ready")
	f.registerKey(owner, ownerKey)
	// Registered, valid, and on the wrong account -- the cross-tenant case.
	f.registerKey(stranger, strangerKey)

	newHarness(t, f.pool).mustRefuse(t, id, strangerKey)
}

func TestUnregisteredKeyIsRefused(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "hello-world-ccc333", "ready")

	newHarness(t, f.pool).mustRefuse(t, id, ownerKey)
}

func TestUnknownUsernameIsRefused(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	f.registerKey(owner, ownerKey)

	newHarness(t, f.pool).mustRefuse(t, "no-such-deployment", ownerKey)
}

// The account consulted is the deployment's current owner, so access follows
// ownership without anything having to be rewritten when it moves.
func TestOwnershipChangeMovesAccess(t *testing.T) {
	f := newFixture(t)
	owner, successor := f.user("owner"), f.user("successor")
	id, _ := f.deployment(owner, "hello-world-ddd444", "ready")
	f.registerKey(owner, ownerKey)
	f.registerKey(successor, strangerKey)
	h := newHarness(t, f.pool)

	h.mustAdmit(t, id, ownerKey)
	f.setOwner(id, successor)
	h.mustAdmit(t, id, strangerKey)
	h.mustRefuse(t, id, ownerKey)
}

// ── reachability is an allowlist that includes `error` ────────────────────

// The D17 defect, one layer up. This must never become a passing denial.
//
// File access matters most when the application is broken. The SFTP Service
// publishes not-ready addresses for exactly this reason; a resolver that
// refused `error` would take the access away again at the edge.
func TestACrashLoopingDeploymentIsStillReachable(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "broken-fff666", "error")
	f.registerKey(owner, ownerKey)

	up := newHarness(t, f.pool).mustAdmit(t, id, ownerKey)
	if !strings.HasSuffix(up.GetUri(), ":2222") {
		t.Errorf("uri = %q", up.GetUri())
	}
}

func TestUnreachableStatusesAreRefused(t *testing.T) {
	for _, st := range []string{"deleting", "deleted", "pending", "provisioning"} {
		t.Run(st, func(t *testing.T) {
			f := newFixture(t)
			owner := f.user("owner")
			id, _ := f.deployment(owner, "gated-ggg777", st)
			f.registerKey(owner, ownerKey)

			newHarness(t, f.pool).mustRefuse(t, id, ownerKey)
		})
	}
}

// Deletion is what stops a username resolving -- no cleanup step involved.
func TestADeletedDeploymentIsNotRoutable(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "reused-hhh888", "ready")
	f.registerKey(owner, ownerKey)
	h := newHarness(t, f.pool)

	h.mustAdmit(t, id, ownerKey)
	f.setStatus(id, "deleted")
	h.mustRefuse(t, id, ownerKey)
}

// ── the upstream is the platform's own credential ─────────────────────────

func TestUpstreamCarriesTheMountedPrivateKey(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "hello-world-iii999", "ready")
	f.registerKey(owner, ownerKey)

	up := newHarness(t, f.pool).mustAdmit(t, id, ownerKey)
	if !bytes.Equal(up.GetPrivateKey().GetPrivateKey(), upstreamKey) {
		t.Error("upstream does not carry the mounted key")
	}
	if up.GetPassword() != nil || up.GetNone() != nil {
		t.Error("upstream offers something other than the private key")
	}
}

// What the client presented is not replayed, in any field.
func TestNoClientSuppliedMaterialReachesTheUpstream(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "hello-world-jjj000", "ready")
	f.registerKey(owner, ownerKey)

	offered := blob(t, ownerKey)
	up := newHarness(t, f.pool).mustAdmit(t, id, ownerKey)
	if bytes.Contains(up.GetPrivateKey().GetPrivateKey(), offered) {
		t.Error("the offered key appears in the upstream credential")
	}
	if len(up.GetPrivateKey().GetCaPublicKey()) != 0 {
		t.Error("upstream carries a CA public key it was never given")
	}
}

// The sidecars regenerate host keys on every start; there is none to pin. With
// this false sshpiperd calls VerifyHostKey, which this plugin does not
// implement, and the handshake fails outright (spike result #12).
func TestUpstreamHostKeyIsNotVerified(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "hello-world-kkk111", "ready")
	f.registerKey(owner, ownerKey)

	if !newHarness(t, f.pool).mustAdmit(t, id, ownerKey).GetIgnoreHostKey() {
		t.Error("ignore_host_key is false; the handshake would fail on VerifyHostKey")
	}
}

// sshpiperd parses this with url.Parse and dials scheme://host.
func TestUpstreamUriCarriesAScheme(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, namespace := f.deployment(owner, "hello-world-lll222", "ready")
	f.registerKey(owner, ownerKey)

	uri := newHarness(t, f.pool).mustAdmit(t, id, ownerKey).GetUri()
	if !strings.HasPrefix(uri, "tcp://") || !strings.Contains(uri, namespace) {
		t.Errorf("uri = %q", uri)
	}
}

// ── refusals are uniform, and the log is where they differ ────────────────

func TestEveryRefusalLooksTheSameToTheClient(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	reachableID, _ := f.deployment(owner, "uniform-mmm333", "ready")
	gatedID, _ := f.deployment(owner, "gated-mmm444", "pending")
	f.registerKey(owner, ownerKey)
	h := newHarness(t, f.pool)

	seen := map[string]bool{}
	for _, tc := range []struct{ username, key string }{
		{"no-such-deployment", ownerKey}, // not a uuid at all
		{uuid.NewString(), ownerKey},     // a uuid naming nothing
		{reachableID, strangerKey},       // key registered nowhere
		{gatedID, ownerKey},              // not in a reachable state
	} {
		_, err := h.auth(t, tc.username, tc.key)
		if err == nil {
			t.Fatalf("%s was admitted", tc.username)
		}
		seen[status.Code(err).String()+"/"+status.Convert(err).Message()] = true
	}
	if len(seen) != 1 {
		t.Errorf("refusals are distinguishable to the client: %v", seen)
	}
	if !seen["PermissionDenied/denied"] {
		t.Errorf("unexpected refusal shape: %v", seen)
	}
}

func TestTheLogDistinguishesWhatTheClientCannot(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "logged-nnn555", "ready")
	h := newHarness(t, f.pool)

	h.mustRefuse(t, "no-such-deployment", ownerKey)
	h.mustRefuse(t, id, ownerKey)

	logged := h.logs.String()
	for _, want := range []string{
		"cause=" + string(causeUnknownUsername),
		"cause=" + string(causeKeyNotRegistered),
	} {
		if !strings.Contains(logged, want) {
			t.Errorf("log does not record %s:\n%s", want, logged)
		}
	}
}

// ── fail closed, and never reuse an answer ────────────────────────────────

// No cache, so no interval in which a removed key still authenticates.
func TestRevocationTakesEffectOnTheNextConnection(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "revoke-ooo666", "ready")
	f.registerKey(owner, ownerKey)
	h := newHarness(t, f.pool)

	h.mustAdmit(t, id, ownerKey)
	f.revokeKey(owner, ownerKey)
	h.mustRefuse(t, id, ownerKey)
}

func TestANewlyRegisteredKeyWorksOnTheNextConnection(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "fresh-ppp777", "ready")
	h := newHarness(t, f.pool)

	h.mustRefuse(t, id, ownerKey)
	f.registerKey(owner, ownerKey)
	h.mustAdmit(t, id, ownerKey)
}

// A resolver that cannot read the store closes the door. Built against an
// address that answers nothing, so the failure is the real one -- a connection
// that cannot be made -- rather than a patched error.
func TestAnUnreachableDatabaseRefusesRatherThanAdmits(t *testing.T) {
	pool, err := newBrokenPool()
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	// Well-formed on purpose: a username that is not a uuid is refused before
	// the store is consulted, which would prove the opposite of this test.
	h := newHarness(t, pool)
	h.mustRefuse(t, uuid.NewString(), ownerKey)
	if !strings.Contains(h.logs.String(), "resolution failed") {
		t.Error("the failure was not logged as one")
	}
}

// ── the resolver's health is the SSH edge's health ────────────────────────

func TestAHealthyResolverReportsServing(t *testing.T) {
	h := newHarness(t, testPool(t))
	resp, err := h.health.Check(context.Background(), &grpc_health_v1.HealthCheckRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if resp.GetStatus() != grpc_health_v1.HealthCheckResponse_SERVING {
		t.Errorf("status = %v, want SERVING", resp.GetStatus())
	}
}

// The outage a bad key can never cause. Readiness is what the platform alerts
// on, so a resolver that is alive and admitting nobody has to say so here --
// otherwise the SSH edge looks healthy while every connection to it is refused.
func TestAnUnreachableDatabaseReportsNotServing(t *testing.T) {
	pool, err := newBrokenPool()
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	h := newHarness(t, pool)
	resp, err := h.health.Check(context.Background(), &grpc_health_v1.HealthCheckRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if resp.GetStatus() != grpc_health_v1.HealthCheckResponse_NOT_SERVING {
		t.Errorf("status = %v, want NOT_SERVING", resp.GetStatus())
	}
}

// A client presenting an unregistered key is not an outage. This is the
// distinguishing property the platform's alerting rests on: refusals are
// routine and leave the resolver SERVING; only the resolver itself failing
// takes the edge down.
func TestRefusedConnectionsDoNotAffectHealth(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, _ := f.deployment(owner, "healthy-ttt111", "ready")
	h := newHarness(t, f.pool)

	for i := 0; i < 5; i++ {
		h.mustRefuse(t, id, ownerKey)
	}

	resp, err := h.health.Check(context.Background(), &grpc_health_v1.HealthCheckRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if resp.GetStatus() != grpc_health_v1.HealthCheckResponse_SERVING {
		t.Errorf("refusals moved the resolver to %v", resp.GetStatus())
	}
}

// ── the username is the deployment's id, and only that ────────────────────

// A primary key, so at most one row can match and the lookup needs no
// tie-break.
func TestTheDeploymentIdResolvesItsDeployment(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, namespace := f.deployment(owner, "addressed-uuu111", "ready")
	f.registerKey(owner, ownerKey)

	up := newHarness(t, f.pool).mustAdmit(t, id, ownerKey)
	if up.GetUri() != "tcp://addressed-uuu111-ssh."+namespace+".svc:2222" {
		t.Errorf("uri = %q", up.GetUri())
	}
}

// Neither of the deployment's internal names addresses it at the edge, though
// it carries both. Refused indistinguishably from anything else, by design.
func TestNeitherTheReleaseNameNorTheNamespaceIsAUsername(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	_, namespace := f.deployment(owner, "not-a-username-vvv222", "ready")
	f.registerKey(owner, ownerKey)
	h := newHarness(t, f.pool)

	h.mustRefuse(t, "not-a-username-vvv222", ownerKey)
	h.mustRefuse(t, namespace, ownerKey)

	if !strings.Contains(h.logs.String(), "cause="+string(causeUnknownUsername)) {
		t.Errorf("refused for some other reason:\n%s", h.logs.String())
	}
}

// A username that cannot be a deployment id is refused without a query. The
// database must never be handed something it would reject as a cast error,
// which an operator would then have to read as an outage rather than a
// refusal.
func TestAUsernameThatIsNotAUuidIsRefusedWithoutQuerying(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	f.registerKey(owner, ownerKey)

	pool, err := newBrokenPool()
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	// The pool answers nothing, so admitting or erroring would both mean the
	// username reached it.
	h := newHarness(t, pool)
	h.mustRefuse(t, "definitely-not-a-uuid", ownerKey)

	if !strings.Contains(h.logs.String(), "cause="+string(causeUnknownUsername)) {
		t.Errorf("a malformed username reached the store:\n%s", h.logs.String())
	}
}

// The other half: well-formed, and naming nothing.
func TestAWellFormedIdNamingNothingIsRefused(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	f.deployment(owner, "present-yyy555", "ready")
	f.registerKey(owner, ownerKey)

	newHarness(t, f.pool).mustRefuse(t, uuid.NewString(), ownerKey)
}

// The client-facing identifier and the account presented upstream are two
// different things: the first is the deployment's id, the second is whatever
// the chart rendered, which is the release name.
func TestTheUpstreamAccountIsStillTheReleaseName(t *testing.T) {
	f := newFixture(t)
	owner := f.user("owner")
	id, namespace := f.deployment(owner, "upstream-www333", "ready")
	f.registerKey(owner, ownerKey)

	up := newHarness(t, f.pool).mustAdmit(t, id, ownerKey)
	if up.GetUserName() != "upstream-www333" {
		t.Errorf("upstream user = %q, want the release name", up.GetUserName())
	}
	if up.GetUserName() == id || up.GetUserName() == namespace {
		t.Error("the upstream account followed an identifier that is not the release name")
	}
}
