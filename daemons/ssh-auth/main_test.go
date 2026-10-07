package main

import (
	"net"
	"os/exec"
	"path/filepath"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/health/grpc_health_v1"
)

// The readiness probe is this binary run as `-healthcheck`, not a `grpc` probe
// on the pod spec: the kubelet dials those at the pod IP, and the server binds
// loopback only. An exec probe runs inside the container, where that is the
// right address.
//
// So the probe is a code path, and it is worth building and running for real --
// a probe that always exits 0 would mark a dead resolver ready, and a probe
// that always exits 1 would take the SSH edge out of its Service.
func TestHealthcheckExitStatus(t *testing.T) {
	bin := filepath.Join(t.TempDir(), "ssh-auth")
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := listener.Addr().String()

	t.Run("nothing listening", func(t *testing.T) {
		closed, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		deadAddr := closed.Addr().String()
		closed.Close()

		cmd := exec.Command(bin, "-healthcheck")
		cmd.Env = append(cmd.Environ(), "CAELUS_SSH_RESOLVER_LISTEN="+deadAddr)
		if err := cmd.Run(); err == nil {
			t.Error("exit 0 with nothing listening; a dead resolver would be marked ready")
		}
	})

	pool := testPool(t)
	s := grpc.NewServer()
	grpc_health_v1.RegisterHealthServer(s, &health{db: pool, log: newLogger()})
	go s.Serve(listener)
	t.Cleanup(s.Stop)

	t.Run("serving", func(t *testing.T) {
		cmd := exec.Command(bin, "-healthcheck")
		cmd.Env = append(cmd.Environ(), "CAELUS_SSH_RESOLVER_LISTEN="+addr)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Errorf("exit %v with a healthy resolver: %s", err, out)
		}
	})

	t.Run("not serving", func(t *testing.T) {
		broken, err := newBrokenPool()
		if err != nil {
			t.Fatal(err)
		}
		defer broken.Close()

		other, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		bs := grpc.NewServer()
		grpc_health_v1.RegisterHealthServer(bs, &health{db: broken, log: newLogger()})
		go bs.Serve(other)
		defer bs.Stop()

		cmd := exec.Command(bin, "-healthcheck")
		cmd.Env = append(cmd.Environ(), "CAELUS_SSH_RESOLVER_LISTEN="+other.Addr().String())
		if err := cmd.Run(); err == nil {
			t.Error("exit 0 while NOT_SERVING; the SSH edge would look healthy with no database")
		}
	})

}
