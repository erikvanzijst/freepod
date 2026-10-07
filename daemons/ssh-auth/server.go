package main

import (
	"context"
	"log/slog"
	"os"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"

	pb "github.com/erikvanzijst/caelus/ssh-auth/internal/libplugin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// The names sshpiperd switches on. An unrecognized one is a startup error on
// its side, so this list is the contract, not a hint.
//
// Advertising only PublicKeyAuth is what removes password authentication from
// the edge: sshpiperd installs handlers for exactly the callbacks named here,
// so the weaker credential is absent rather than merely unconfigured.
//
// `Logs` is deliberately not here: it is not one of the callback names
// sshpiperd accepts, yet it opens that stream anyway on connect. It is
// implemented below and not advertised.
var callbacks = []string{"PublicKeyAuth"}

// What every refusal says, whatever the cause. The cause goes to the log.
var errDenied = status.Error(codes.PermissionDenied, "denied")

type resolver struct {
	pb.UnimplementedSshPiperPluginServer

	db          *pgxpool.Pool
	upstreamKey []byte
	sidecarPort int
	log         *slog.Logger
}

func (r *resolver) ListCallbacks(ctx context.Context, _ *pb.ListCallbackRequest) (*pb.ListCallbackResponse, error) {
	r.log.Info("sshpiperd connected", "callbacks", callbacks)
	return &pb.ListCallbackResponse{Callbacks: callbacks}, nil
}

// Logs is a stream sshpiperd opens on connect and this side never writes to.
// Implemented because leaving it out makes sshpiperd log an error on every
// start, which buries the errors that mean something.
func (r *resolver) Logs(_ *pb.StartLogRequest, stream pb.SshPiperPlugin_LogsServer) error {
	<-stream.Context().Done()
	return nil
}

func (r *resolver) PublicKeyAuth(ctx context.Context, req *pb.PublicKeyAuthRequest) (*pb.PublicKeyAuthResponse, error) {
	meta := req.GetMeta()
	username := meta.GetUserName()

	d, err := resolve(ctx, r.db, username, req.GetPublicKey(), r.sidecarPort)
	if err != nil {
		// Fail closed. An unreachable database, a timed-out query, a bug --
		// all of them refuse. Nothing here falls back to a previous answer,
		// because there is no previous answer to fall back to.
		r.log.Error("resolution failed",
			"username", username, "from", meta.GetFromAddr(),
			"uniq_id", meta.GetUniqId(), "err", err)
		return nil, errDenied
	}

	if !d.admitted() {
		// The one place the causes are distinguishable. The client is told
		// only that it was refused; an operator reading this can tell an
		// unknown username from an unregistered key.
		r.log.Info("refused",
			"username", username, "cause", string(d.cause),
			"fingerprint", d.fingerprint, "status", d.status,
			"from", meta.GetFromAddr(), "uniq_id", meta.GetUniqId())
		return nil, errDenied
	}

	r.log.Info("admitted",
		"username", username, "fingerprint", d.fingerprint,
		"upstream", d.uri(), "from", meta.GetFromAddr(), "uniq_id", meta.GetUniqId())

	return &pb.PublicKeyAuthResponse{
		Upstream: &pb.Upstream{
			UserName: d.username,
			Uri:      d.uri(),
			// The sidecars regenerate their host keys on every start, so there
			// is no stable key to pin -- the same reason the chart's Pipe sets
			// ignore_hostkey today. The alternative is not "verify" but
			// "fail": with this false, sshpiperd calls VerifyHostKey, and a
			// plugin that does not implement it fails the handshake outright.
			IgnoreHostKey: true,
			// The platform's own credential, never anything the client
			// supplied. The downstream connection is terminated here and the
			// upstream one originated, so nothing could be replayed even if we
			// wanted to.
			Auth: &pb.Upstream_PrivateKey{
				PrivateKey: &pb.UpstreamPrivateKeyAuth{PrivateKey: r.upstreamKey},
			},
		},
	}, nil
}

// health answers grpc.health.v1 from a real query rather than from being alive.
//
// Kubernetes' native gRPC probe calls this. A resolver that is running but
// cannot read the store admits nobody, so reporting SERVING then would say the
// SSH edge is fine while every connection to it fails -- which is exactly the
// outage this is supposed to make visible, and the one thing a client
// presenting a bad key never causes.
type health struct {
	grpc_health_v1.UnimplementedHealthServer

	db  *pgxpool.Pool
	log *slog.Logger
}

func (h *health) Check(ctx context.Context, _ *grpc_health_v1.HealthCheckRequest) (*grpc_health_v1.HealthCheckResponse, error) {
	if err := h.db.Ping(ctx); err != nil {
		h.log.Warn("health check: the platform database is unreachable", "err", err)
		return &grpc_health_v1.HealthCheckResponse{
			Status: grpc_health_v1.HealthCheckResponse_NOT_SERVING,
		}, nil
	}
	return &grpc_health_v1.HealthCheckResponse{
		Status: grpc_health_v1.HealthCheckResponse_SERVING,
	}, nil
}

func newLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, nil))
}

func register(s *grpc.Server, r *resolver, h *health) {
	pb.RegisterSshPiperPluginServer(s, r)
	grpc_health_v1.RegisterHealthServer(s, h)
}
