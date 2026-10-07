package main

import (
	"context"
	"fmt"
	"net"
	"os"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health/grpc_health_v1"
)

// Bounded well inside the probe's own timeout, so a hung dial reports "not
// serving" rather than letting the kubelet time the probe out -- the two look
// the same to Kubernetes but only one of them says why in the log.
const healthcheckTimeout = 2 * time.Second

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) (int, error) {
	v := os.Getenv(key)
	if v == "" {
		return fallback, nil
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return 0, fmt.Errorf("%s: %w", key, err)
	}
	return n, nil
}

func main() {
	// `ssh-auth -healthcheck` is the container's readiness probe. It has to be
	// this binary rather than a `grpc` probe on the pod spec, because the
	// kubelet dials those at the *pod IP* and this server binds loopback only
	// -- deliberately, see run(). An exec probe runs inside the container,
	// where 127.0.0.1 is the right address.
	if len(os.Args) > 1 && os.Args[1] == "-healthcheck" {
		if err := healthcheck(); err != nil {
			fmt.Fprintln(os.Stderr, "ssh-auth: not serving:", err)
			os.Exit(1)
		}
		return
	}
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "ssh-auth:", err)
		os.Exit(1)
	}
}

// healthcheck asks the running server the same question Kubernetes would, and
// reports it the only way an exec probe can: the exit status.
func healthcheck() error {
	ctx, cancel := context.WithTimeout(context.Background(), healthcheckTimeout)
	defer cancel()

	conn, err := grpc.NewClient(env("CAELUS_SSH_RESOLVER_LISTEN", "127.0.0.1:50051"),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return err
	}
	defer conn.Close()

	resp, err := grpc_health_v1.NewHealthClient(conn).Check(ctx, &grpc_health_v1.HealthCheckRequest{})
	if err != nil {
		return err
	}
	if resp.GetStatus() != grpc_health_v1.HealthCheckResponse_SERVING {
		return fmt.Errorf("status %s", resp.GetStatus())
	}
	return nil
}

func run() error {
	log := newLogger()

	// Loopback, and this is a security boundary rather than tidiness.
	// PublicKeyAuth returns the environment's upstream private key to whoever
	// calls it with a username and a public key registered on that
	// deployment's owner -- both public information. Reachable on the pod IP
	// and unauthenticated, this would hand the fleet-wide upstream credential
	// to anything in the cluster. Binding it anywhere else means mTLS first.
	listen := env("CAELUS_SSH_RESOLVER_LISTEN", "127.0.0.1:50051")
	keyPath := env("CAELUS_SSH_RESOLVER_UPSTREAM_KEY_PATH", "/upstreamkey/ssh_upstream_key")
	dsn := os.Getenv("CAELUS_SSH_RESOLVER_DATABASE_URL")
	if dsn == "" {
		return fmt.Errorf("CAELUS_SSH_RESOLVER_DATABASE_URL is not set")
	}
	sidecarPort, err := envInt("CAELUS_SFTP_SIDECAR_PORT", 2222)
	if err != nil {
		return err
	}
	poolSize, err := envInt("CAELUS_SSH_RESOLVER_POOL_SIZE", 4)
	if err != nil {
		return err
	}
	timeoutMs, err := envInt("CAELUS_SSH_RESOLVER_STATEMENT_TIMEOUT_MS", 2000)
	if err != nil {
		return err
	}

	// Read once at startup, so a missing or unreadable key stops the process
	// instead of turning every SSH connection into a puzzle.
	upstreamKey, err := os.ReadFile(keyPath)
	if err != nil {
		return fmt.Errorf("upstream key: %w", err)
	}
	if len(upstreamKey) == 0 {
		return fmt.Errorf("upstream key %s is empty", keyPath)
	}

	db, err := openPool(context.Background(), dsn, poolSize, timeoutMs)
	if err != nil {
		return err
	}
	defer db.Close()

	listener, err := net.Listen("tcp", listen)
	if err != nil {
		return err
	}

	s := grpc.NewServer()
	register(s,
		&resolver{db: db, upstreamKey: upstreamKey, sidecarPort: sidecarPort, log: log},
		&health{db: db, log: log},
	)

	log.Info("ssh resolver listening",
		"addr", listen, "upstream_key", keyPath, "sidecar_port", sidecarPort)
	return s.Serve(listener)
}

// openPool bounds the database dependency: a small pool and a short statement
// timeout, so a slow database refuses connections quickly rather than hanging
// the edge. The client retries; the edge does not.
func openPool(ctx context.Context, dsn string, poolSize, timeoutMs int) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("database url: %w", err)
	}
	cfg.MaxConns = int32(poolSize)
	cfg.ConnConfig.RuntimeParams["statement_timeout"] = strconv.Itoa(timeoutMs)

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := pool.Ping(pingCtx); err != nil {
		// Not fatal in principle -- the resolver fails closed and would
		// recover -- but a resolver that cannot reach the database at startup
		// is a misconfiguration far more often than an outage, and saying so
		// here beats discovering it as refused logins.
		return nil, fmt.Errorf("database: %w", err)
	}
	return pool, nil
}
