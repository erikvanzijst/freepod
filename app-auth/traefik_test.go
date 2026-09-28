package main

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The verifier's whole contract with the edge rests on Traefik behavior the
// design verified by hand (context facts 1-4): listed response headers are
// deleted before they are copied, non-2xx responses reach the browser with
// Location and Set-Cookie, and X-Forwarded-* come from the real request. This
// test runs the verifier behind the same Traefik version the cluster runs,
// configured the way the custom chart configures it, so an upgrade that changes
// any of that fails here rather than in production.
const (
	traefikVersion = "v3.7.13"
	traefikSHA256  = "52cd039a34258dd61c617a95d69252bc6bcae27c520f338186c31c7fef8f6394" // linux_amd64.tar.gz
)

func traefikBinary(t *testing.T) string {
	t.Helper()
	if bin := os.Getenv("TRAEFIK_BIN"); bin != "" {
		return bin
	}
	cache, err := os.UserCacheDir()
	if err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(cache, "app-auth-test", "traefik-"+traefikVersion)
	if _, err := os.Stat(bin); err == nil {
		return bin
	}
	if err := os.MkdirAll(filepath.Dir(bin), 0o755); err != nil {
		t.Fatal(err)
	}
	u := fmt.Sprintf("https://github.com/traefik/traefik/releases/download/%[1]s/traefik_%[1]s_linux_amd64.tar.gz", traefikVersion)
	resp, err := http.Get(u)
	if err != nil {
		t.Fatalf("downloading Traefik (set TRAEFIK_BIN to use a local binary): %v", err)
	}
	defer resp.Body.Close()
	archive, err := io.ReadAll(resp.Body)
	if err != nil || resp.StatusCode != 200 {
		t.Fatalf("downloading %s: %d %v", u, resp.StatusCode, err)
	}
	if sum := sha256.Sum256(archive); hex.EncodeToString(sum[:]) != traefikSHA256 {
		t.Fatalf("Traefik archive checksum mismatch")
	}
	gz, err := gzip.NewReader(strings.NewReader(string(archive)))
	if err != nil {
		t.Fatal(err)
	}
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if err != nil {
			t.Fatalf("no traefik binary in archive: %v", err)
		}
		if h.Name == "traefik" {
			tmp := bin + ".tmp"
			f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := io.Copy(f, tr); err != nil {
				t.Fatal(err)
			}
			f.Close()
			if err := os.Rename(tmp, bin); err != nil {
				t.Fatal(err)
			}
			return bin
		}
	}
}

func freePort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

const (
	authHost  = "milk.erik.freepod.eu"
	plainHost = "plain.erik.freepod.eu"
)

// edge is Traefik in front of an echo app, with the chart's two middlewares on
// the auth-enabled host and only the strip middleware on the other.
type edge struct {
	url    string
	v      *verifier
	st     *memStore
	hits   chan http.Header
	client *http.Client
}

func startEdge(t *testing.T, public ...string) *edge {
	t.Helper()
	bin := traefikBinary(t)

	v, st, _ := newTestVerifier(t)
	v.now = time.Now
	st.now = time.Now
	verifySrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/verify" {
			http.NotFound(w, r)
			return
		}
		v.ServeHTTP(w, r)
	}))
	t.Cleanup(verifySrv.Close)

	hits := make(chan http.Header, 16)
	app := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits <- r.Header.Clone()
		w.Write([]byte("app"))
	}))
	t.Cleanup(app.Close)

	strip := map[string]string{}
	for _, h := range identityHeaders {
		strip[h] = ""
	}
	address := verifySrv.URL + "/verify"
	if len(public) > 0 {
		address += "?p=" + publicParam(public...)
	}
	cfg := map[string]any{"http": map[string]any{
		"routers": map[string]any{
			"auth":  map[string]any{"rule": "Host(`" + authHost + "`)", "service": "app", "entryPoints": []string{"web"}, "middlewares": []string{"strip", "auth"}},
			"plain": map[string]any{"rule": "Host(`" + plainHost + "`)", "service": "app", "entryPoints": []string{"web"}, "middlewares": []string{"strip"}},
		},
		"middlewares": map[string]any{
			"strip": map[string]any{"headers": map[string]any{"customRequestHeaders": strip}},
			"auth": map[string]any{"forwardAuth": map[string]any{
				"address":             address,
				"authResponseHeaders": append([]string{"Cookie"}, identityHeaders...),
			}},
		},
		"services": map[string]any{"app": map[string]any{"loadBalancer": map[string]any{"servers": []map[string]string{{"url": app.URL}}}}},
	}}
	dir := t.TempDir()
	raw, _ := json.Marshal(cfg)
	// JSON is valid YAML, which is what the file provider parses.
	dynamic := filepath.Join(dir, "dynamic.yml")
	os.WriteFile(dynamic, raw, 0o644)

	port := freePort(t)
	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, bin,
		fmt.Sprintf("--entryPoints.web.address=127.0.0.1:%d", port),
		"--providers.file.filename="+dynamic,
		"--global.checkNewVersion=false", "--global.sendAnonymousUsage=false", "--log.level=ERROR")
	var stderr strings.Builder
	cmd.Stderr = &stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cancel(); cmd.Wait() })

	e := &edge{url: fmt.Sprintf("http://127.0.0.1:%d", port), v: v, st: st, hits: hits,
		client: &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	deadline := time.Now().Add(15 * time.Second)
	for {
		resp, err := e.do(plainHost, "GET", "/", nil)
		if err == nil && resp.StatusCode == 200 {
			<-hits
			return e
		}
		if time.Now().After(deadline) {
			t.Fatalf("Traefik did not come up: %v\n%s", err, stderr.String())
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func (e *edge) do(host, method, path string, h http.Header) (*http.Response, error) {
	r, _ := http.NewRequest(method, e.url+path, nil)
	r.Host = host
	for k, vs := range h {
		for _, v := range vs {
			r.Header.Add(k, v)
		}
	}
	resp, err := e.client.Do(r)
	if err == nil {
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}
	return resp, err
}

// upstream returns what the app received for the request just made, or nil if
// the request never reached it.
func (e *edge) upstream() http.Header {
	select {
	case h := <-e.hits:
		return h
	case <-time.After(300 * time.Millisecond):
		return nil
	}
}

var spoofed = http.Header{
	"X-Freepod-User":    {"mallory"},
	"X-Freepod-Email":   {"admin@example.com"},
	"X-Freepod-Name":    {"Mallory"},
	"X-Freepod-Jwt":     {"forged"},
	"Remote-User":       {"mallory"},
	"X-Forwarded-User":  {"mallory"},
	"X-Forwarded-Email": {"admin@example.com"},
}

func withHeaders(extra http.Header, base http.Header) http.Header {
	h := base.Clone()
	for k, v := range extra {
		h[k] = v
	}
	return h
}

func TestBehindTraefik(t *testing.T) {
	if testing.Short() {
		t.Skip("starts Traefik")
	}
	e := startEdge(t, "^/$")
	sess := e.v.sessionFor(t, alice, authHost)

	t.Run("signed in: verifier's identity replaces spoofed headers, session cookie stripped", func(t *testing.T) {
		resp, err := e.do(authHost, "GET", "/lists", withHeaders(http.Header{
			"Cookie": {"theme=dark", sessionCookie + "=" + sess},
		}, spoofed))
		if err != nil || resp.StatusCode != 200 {
			t.Fatalf("%v %v", resp, err)
		}
		got := e.upstream()
		want := map[string]string{
			"X-Freepod-User": "3f2a", "Remote-User": "3f2a", "X-Forwarded-User": "3f2a",
			"X-Freepod-Email": "alice@example.com", "X-Forwarded-Email": "alice@example.com",
			"X-Freepod-Name": "Alice%20%C3%85ngstr%C3%B6m", "Cookie": "theme=dark",
		}
		for k, v := range want {
			if got.Get(k) != v || len(got.Values(k)) != 1 {
				t.Errorf("app received %s = %q, want exactly %q", k, got.Values(k), v)
			}
		}
		if got.Get("X-Freepod-Jwt") != "" {
			t.Error("spoofed X-Freepod-Jwt reached the app")
		}
	})

	t.Run("only the session cookie: app receives no Cookie header", func(t *testing.T) {
		e.do(authHost, "GET", "/lists", http.Header{"Cookie": {sessionCookie + "=" + sess}})
		if got := e.upstream(); got == nil || len(got.Values("Cookie")) != 0 {
			t.Fatalf("app received Cookie %q", got.Values("Cookie"))
		}
	})

	t.Run("public path without session: spoofed identity removed", func(t *testing.T) {
		resp, _ := e.do(authHost, "GET", "/", withHeaders(http.Header{"Sec-Fetch-Mode": {"navigate"}}, spoofed))
		got := e.upstream()
		if resp.StatusCode != 200 || got == nil {
			t.Fatalf("status %d", resp.StatusCode)
		}
		for h := range spoofed {
			if got.Get(h) != "" {
				t.Errorf("spoofed %s reached the app", h)
			}
		}
	})

	t.Run("navigation without session: redirect and login cookie reach the browser", func(t *testing.T) {
		resp, _ := e.do(authHost, "GET", "/lists?x=1", http.Header{"Sec-Fetch-Mode": {"navigate"}})
		if e.upstream() != nil {
			t.Fatal("the app saw an unauthenticated request")
		}
		loc, _ := url.Parse(resp.Header.Get("Location"))
		if resp.StatusCode != 302 || loc.Scheme != "https" || loc.Host != "login.freepod.eu" || loc.Query().Get("host") != authHost {
			t.Fatalf("%d Location=%s", resp.StatusCode, loc)
		}
		if !strings.Contains(strings.Join(resp.Header.Values("Set-Cookie"), "\n"), loginCookie+"=") {
			t.Fatalf("login cookie did not reach the browser: %v", resp.Header.Values("Set-Cookie"))
		}
	})

	t.Run("background request without session: 401, app untouched", func(t *testing.T) {
		resp, _ := e.do(authHost, "GET", "/api/items", http.Header{"Sec-Fetch-Mode": {"cors"}})
		if resp.StatusCode != 401 || e.upstream() != nil {
			t.Fatalf("status %d", resp.StatusCode)
		}
	})

	t.Run("callback: session cookie and absolute redirect reach the browser", func(t *testing.T) {
		code := issue(t, e.st, authHost, "the-nonce", "/lists")
		resp, _ := e.do(authHost, "GET", reservedPrefix+"callback?code="+url.QueryEscape(code),
			http.Header{"Cookie": {loginCookie + "=the-nonce"}})
		if e.upstream() != nil {
			t.Fatal("a reserved path reached the app")
		}
		if resp.StatusCode != 302 || resp.Header.Get("Location") != "https://"+authHost+"/lists" {
			t.Fatalf("%d Location=%q", resp.StatusCode, resp.Header.Get("Location"))
		}
		if !strings.Contains(strings.Join(resp.Header.Values("Set-Cookie"), "\n"), sessionCookie+"=") {
			t.Fatalf("no session cookie: %v", resp.Header.Values("Set-Cookie"))
		}
	})

	t.Run("app without authentication: identity headers stripped anyway", func(t *testing.T) {
		e.do(plainHost, "GET", "/", spoofed)
		got := e.upstream()
		if got == nil {
			t.Fatal("request did not reach the app")
		}
		for h := range spoofed {
			if got.Get(h) != "" {
				t.Errorf("spoofed %s reached an app without authentication", h)
			}
		}
	})
}
