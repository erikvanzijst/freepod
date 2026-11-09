package main

import (
	"io"
	"mime"
	"mime/multipart"
	"net/mail"
	"strings"
	"testing"
	"time"
)

func testRelay(addr string) *relay {
	return &relay{
		addr:  addr,
		from:  "no-reply@freepod.eu",
		helo:  "notifier.test",
		clock: func() time.Time { return time.Date(2026, 11, 9, 12, 0, 0, 0, time.UTC) },
	}
}

func TestDeliverSendsAWellFormedMessage(t *testing.T) {
	f := startFakeSMTP(t)
	m := full()
	m.Subject = "Zugang für cloud.freepod.app"
	if err := testRelay(f.addr).deliver("0b1e", "ana@example.com", m); err != nil {
		t.Fatal(err)
	}
	got := f.received()
	if len(got) != 1 || got[0].from != "no-reply@freepod.eu" || got[0].to != "ana@example.com" {
		t.Fatalf("envelope: %+v", got)
	}
	msg, err := mail.ReadMessage(strings.NewReader(got[0].data))
	if err != nil {
		t.Fatal(err)
	}
	subject, err := new(mime.WordDecoder).DecodeHeader(msg.Header.Get("Subject"))
	if err != nil || subject != m.Subject {
		t.Fatalf("subject %q (%v)", subject, err)
	}
	for k, want := range map[string]string{
		"From":       "no-reply@freepod.eu",
		"To":         "ana@example.com",
		"Message-Id": "<0b1e@freepod.eu>",
		"Date":       "Mon, 09 Nov 2026 12:00:00 +0000",
	} {
		if got := msg.Header.Get(k); got != want {
			t.Errorf("%s: %q, want %q", k, got, want)
		}
	}
	mediaType, params, err := mime.ParseMediaType(msg.Header.Get("Content-Type"))
	if err != nil || mediaType != "multipart/alternative" {
		t.Fatalf("content type %q (%v)", mediaType, err)
	}
	parts := multipart.NewReader(msg.Body, params["boundary"])
	var kinds, bodies []string
	for {
		p, err := parts.NextPart() // decodes quoted-printable
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		b, _ := io.ReadAll(p)
		kinds = append(kinds, p.Header.Get("Content-Type"))
		// SMTP carries CRLF line endings.
		bodies = append(bodies, strings.ReplaceAll(string(b), "\r\n", "\n"))
	}
	if strings.Join(kinds, ",") != "text/plain; charset=utf-8,text/html; charset=utf-8" {
		t.Fatalf("parts: %v", kinds)
	}
	text, html, _ := render(m)
	if bodies[0] != text || bodies[1] != html {
		t.Fatal("parts differ from the rendered message")
	}
}

func TestHeaderInjectionIsRefusedOrEncoded(t *testing.T) {
	r := testRelay("unused:25")
	if _, err := r.compose("x", "ana@example.com\r\nBcc: eve@example.com", full()); err == nil {
		t.Fatal("an address with a line break was accepted")
	}
	m := full()
	m.Subject = "Hi\r\nBcc: eve@example.com"
	raw, err := r.compose("x", "ana@example.com", m)
	if err != nil {
		t.Fatal(err)
	}
	msg, err := mail.ReadMessage(strings.NewReader(string(raw)))
	if err != nil {
		t.Fatal(err)
	}
	if msg.Header.Get("Bcc") != "" {
		t.Fatal("subject injected a header")
	}
}

func TestDeliverReportsARefusal(t *testing.T) {
	f := startFakeSMTP(t)
	f.refuseNext(1)
	if err := testRelay(f.addr).deliver("x", "ana@example.com", full()); err == nil || !strings.Contains(err.Error(), "451") {
		t.Fatalf("err = %v", err)
	}
}
