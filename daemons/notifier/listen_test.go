package main

import (
	"context"
	"net"
	"strconv"
	"sync"
	"testing"
	"time"
)

func (f *fixture) listener(s *sender, dsn string, poll time.Duration) (*listener, func()) {
	ctx, cancel := context.WithCancel(context.Background())
	l := &listener{dsn: dsn, sender: s, pollInterval: poll, reconnectDelay: 50 * time.Millisecond}
	var wg sync.WaitGroup
	wg.Add(1)
	go func() { defer wg.Done(); l.run(ctx) }()
	f.t.Cleanup(func() { cancel(); wg.Wait() })
	return l, func() { cancel(); wg.Wait() }
}

func (f *fixture) waitFor(id, state string, within time.Duration) time.Duration {
	f.t.Helper()
	start := time.Now()
	for time.Since(start) < within {
		if f.outcome(id).state == state {
			return time.Since(start)
		}
		time.Sleep(20 * time.Millisecond)
	}
	f.t.Fatalf("%s did not become %s within %s: %+v", id, state, within, f.outcome(id))
	return 0
}

func TestAQueuedRowIsSentWithinSeconds(t *testing.T) {
	f := newFixture(t)
	tr := &fakeTransport{}
	// A poll far longer than the test: only the wake-up can deliver in time.
	f.listener(f.sender(tr), roleDSN(t), time.Hour)
	time.Sleep(300 * time.Millisecond) // listening
	id := f.queue("a@notifier.test")
	if took := f.waitFor(id, "sent", 5*time.Second); took > 2*time.Second {
		t.Fatalf("took %s", took)
	}
}

func TestPendingRowsAreSentAtStart(t *testing.T) {
	f := newFixture(t)
	id := f.queue("a@notifier.test")
	f.listener(f.sender(&fakeTransport{}), roleDSN(t), time.Hour)
	f.waitFor(id, "sent", 5*time.Second)
}

func TestTheTimerFindsARowWhoseWakeUpWasLost(t *testing.T) {
	f := newFixture(t)
	tr := &fakeTransport{}
	f.listener(f.sender(tr), roleDSN(t), 500*time.Millisecond)
	time.Sleep(300 * time.Millisecond)
	// Inserted with the trigger disabled for this transaction, as if the
	// notification had been raised while nobody listened.
	ctx := context.Background()
	tx, err := f.admin.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := tx.Exec(ctx, `SET LOCAL session_replication_role = replica`); err != nil {
		t.Fatal(err)
	}
	var id string
	if err := tx.QueryRow(ctx, `INSERT INTO notification_outbox (kind, recipient_email, subject, body, reason)
		VALUES ('access.invitation', 'a@notifier.test', 's', 'b', 'r') RETURNING id::text`).Scan(&id); err != nil {
		t.Fatal(err)
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	f.waitFor(id, "sent", 3*time.Second)
}

// proxy forwards TCP to the database until cut, so a test can drop the
// listener's connection without touching the server.
type proxy struct {
	ln       net.Listener
	mu       sync.Mutex
	conns    []net.Conn
	upstream string
}

func startProxy(t *testing.T, upstream string) *proxy {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	p := &proxy{ln: ln, upstream: upstream}
	t.Cleanup(func() { ln.Close(); p.cut() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			u, err := net.Dial("tcp", upstream)
			if err != nil {
				c.Close()
				continue
			}
			p.mu.Lock()
			p.conns = append(p.conns, c, u)
			p.mu.Unlock()
			go pipe(c, u)
			go pipe(u, c)
		}
	}()
	return p
}

func pipe(a, b net.Conn) {
	buf := make([]byte, 32*1024)
	for {
		n, err := a.Read(buf)
		if n > 0 {
			if _, werr := b.Write(buf[:n]); werr != nil {
				return
			}
		}
		if err != nil {
			a.Close()
			b.Close()
			return
		}
	}
}

func (p *proxy) cut() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, c := range p.conns {
		c.Close()
	}
	p.conns = nil
}

func TestARowQueuedWhileDisconnectedIsSentAfterReconnecting(t *testing.T) {
	f := newFixture(t)
	cfg := f.role.Config().ConnConfig
	p := startProxy(t, net.JoinHostPort(cfg.Host, strconv.Itoa(int(cfg.Port))))
	dsn := "postgresql://" + roleName + ":" + rolePassword + "@" + p.ln.Addr().String() + "/" + cfg.Database + "?sslmode=disable"
	tr := &fakeTransport{}
	f.listener(f.sender(tr), dsn, time.Hour)
	time.Sleep(300 * time.Millisecond)
	p.cut()
	id := f.queue("a@notifier.test") // its wake-up reaches nobody
	f.waitFor(id, "sent", 5*time.Second)
}
