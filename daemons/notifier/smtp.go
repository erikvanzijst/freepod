package main

import (
	"bytes"
	"fmt"
	"mime"
	"mime/multipart"
	"mime/quotedprintable"
	"net"
	"net/mail"
	"net/smtp"
	"net/textproto"
	"strings"
	"time"
)

const smtpTimeout = 10 * time.Second

// relay delivers through the shared in-cluster SMTP relay: unauthenticated and
// without STARTTLS, as the relay authenticates upstream itself. net/smtp's
// SendMail would attempt STARTTLS whenever the relay offers it.
type relay struct {
	addr  string
	from  string
	helo  string
	clock func() time.Time
}

// deliver sends one rendered message to one address. id names the
// notification, so a redelivery after a crash carries the same Message-ID.
func (r *relay) deliver(id, to string, m message) error {
	raw, err := r.compose(id, to, m)
	if err != nil {
		return err
	}
	conn, err := net.DialTimeout("tcp", r.addr, smtpTimeout)
	if err != nil {
		return err
	}
	defer conn.Close()
	if err := conn.SetDeadline(time.Now().Add(smtpTimeout)); err != nil {
		return err
	}
	host, _, _ := net.SplitHostPort(r.addr)
	c, err := smtp.NewClient(conn, host)
	if err != nil {
		return err
	}
	defer c.Close()
	if err := c.Hello(r.helo); err != nil {
		return err
	}
	if err := c.Mail(r.from); err != nil {
		return err
	}
	if err := c.Rcpt(to); err != nil {
		return err
	}
	w, err := c.Data()
	if err != nil {
		return err
	}
	if _, err := w.Write(raw); err != nil {
		return err
	}
	if err := w.Close(); err != nil {
		return err
	}
	return c.Quit()
}

// compose builds the message: multipart/alternative, plain text before HTML,
// both quoted-printable UTF-8.
func (r *relay) compose(id, to string, m message) ([]byte, error) {
	if _, err := mail.ParseAddress(to); err != nil || strings.ContainsAny(to, "\r\n<>") {
		return nil, fmt.Errorf("not a deliverable address: %q", to)
	}
	text, html, err := render(m)
	if err != nil {
		return nil, err
	}
	domain := r.from[strings.LastIndex(r.from, "@")+1:]

	var body bytes.Buffer
	parts := multipart.NewWriter(&body)
	for _, p := range []struct{ kind, content string }{{"text/plain", text}, {"text/html", html}} {
		w, err := parts.CreatePart(textproto.MIMEHeader{
			"Content-Type":              {p.kind + "; charset=utf-8"},
			"Content-Transfer-Encoding": {"quoted-printable"},
		})
		if err != nil {
			return nil, err
		}
		qp := quotedprintable.NewWriter(w)
		if _, err := qp.Write([]byte(p.content)); err != nil {
			return nil, err
		}
		if err := qp.Close(); err != nil {
			return nil, err
		}
	}
	if err := parts.Close(); err != nil {
		return nil, err
	}

	var msg bytes.Buffer
	for _, h := range [][2]string{
		{"From", r.from},
		{"To", to},
		{"Subject", mime.QEncoding.Encode("utf-8", m.Subject)},
		{"Date", r.clock().Format(time.RFC1123Z)},
		{"Message-ID", "<" + id + "@" + domain + ">"},
		{"MIME-Version", "1.0"},
		{"Content-Type", `multipart/alternative; boundary="` + parts.Boundary() + `"`},
	} {
		fmt.Fprintf(&msg, "%s: %s\r\n", h[0], h[1])
	}
	msg.WriteString("\r\n")
	msg.Write(body.Bytes())
	return msg.Bytes(), nil
}
