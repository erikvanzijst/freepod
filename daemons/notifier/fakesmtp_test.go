package main

import (
	"bufio"
	"net"
	"strings"
	"sync"
	"testing"
)

// fakeSMTP is a relay in the test process: it records what it accepts and
// refuses the first `refuse` messages with a temporary failure.
type fakeSMTP struct {
	addr string

	mu       sync.Mutex
	refuse   int
	accepted []received
	sessions int
}

type received struct {
	from, to, data string
}

func startFakeSMTP(t *testing.T) *fakeSMTP {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	f := &fakeSMTP{addr: ln.Addr().String()}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go f.serve(conn)
		}
	}()
	return f
}

func (f *fakeSMTP) serve(conn net.Conn) {
	defer conn.Close()
	f.mu.Lock()
	f.sessions++
	f.mu.Unlock()
	r := bufio.NewReader(conn)
	reply := func(s string) { conn.Write([]byte(s + "\r\n")) }
	reply("220 fake ESMTP")
	var cur received
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return
		}
		cmd := strings.TrimRight(line, "\r\n")
		upper := strings.ToUpper(cmd)
		switch {
		case strings.HasPrefix(upper, "EHLO"), strings.HasPrefix(upper, "HELO"):
			reply("250 fake")
		case strings.HasPrefix(upper, "MAIL FROM:"):
			cur = received{from: strings.Trim(cmd[len("MAIL FROM:"):], "<> ")}
			reply("250 ok")
		case strings.HasPrefix(upper, "RCPT TO:"):
			f.mu.Lock()
			refuse := f.refuse > 0
			if refuse {
				f.refuse--
			}
			f.mu.Unlock()
			if refuse {
				reply("451 try again later")
				continue
			}
			cur.to = strings.Trim(cmd[len("RCPT TO:"):], "<> ")
			reply("250 ok")
		case upper == "DATA":
			reply("354 go ahead")
			var data strings.Builder
			for {
				l, err := r.ReadString('\n')
				if err != nil {
					return
				}
				if l == ".\r\n" {
					break
				}
				data.WriteString(strings.TrimPrefix(l, "."))
			}
			cur.data = data.String()
			f.mu.Lock()
			f.accepted = append(f.accepted, cur)
			f.mu.Unlock()
			reply("250 queued")
		case upper == "QUIT":
			reply("221 bye")
			return
		default:
			reply("250 ok")
		}
	}
}

func (f *fakeSMTP) received() []received {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]received(nil), f.accepted...)
}

func (f *fakeSMTP) refuseNext(n int) {
	f.mu.Lock()
	f.refuse = n
	f.mu.Unlock()
}
