// Command app-auth is "Sign in with Freepod" for tenant apps: the Traefik
// forward-auth verifier, and the login-host broker that is also an OpenID
// Provider for SSO-enabled deployments, in one process with two listeners. See
// README.md and the app-authentication and app-oidc-provider design docs.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sort"
	"strings"
	"syscall"
	"time"
)

type config struct {
	verifyListen string
	brokerListen string
	databaseURL  string
	sessionKeys  string
	loginURL     string
	issuer       string
	clientID     string
	clientSecret string
	// The OpenID Provider's keys. Optional: without both, its routes are
	// absent, so an image can roll out ahead of the configuration.
	providerClientKeys  string
	providerSigningKeys string
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func loadConfig() (config, error) {
	c := config{
		verifyListen: env("APP_AUTH_VERIFY_LISTEN", ":8080"),
		brokerListen: env("APP_AUTH_BROKER_LISTEN", ":8081"),
		databaseURL:  os.Getenv("APP_AUTH_DATABASE_URL"),
		sessionKeys:  os.Getenv("APP_AUTH_SESSION_KEYS"),
		loginURL:     strings.TrimRight(os.Getenv("APP_AUTH_LOGIN_URL"), "/"),
		issuer:       os.Getenv("APP_AUTH_OIDC_ISSUER"),
		clientID:     os.Getenv("APP_AUTH_OIDC_CLIENT_ID"),
		clientSecret: os.Getenv("APP_AUTH_OIDC_CLIENT_SECRET"),

		providerClientKeys:  os.Getenv("APP_AUTH_OIDC_CLIENT_KEYS"),
		providerSigningKeys: os.Getenv("APP_AUTH_OIDC_SIGNING_KEYS"),
	}
	var missing []string
	for k, v := range map[string]string{
		"APP_AUTH_DATABASE_URL":       c.databaseURL,
		"APP_AUTH_SESSION_KEYS":       c.sessionKeys,
		"APP_AUTH_LOGIN_URL":          c.loginURL,
		"APP_AUTH_OIDC_ISSUER":        c.issuer,
		"APP_AUTH_OIDC_CLIENT_ID":     c.clientID,
		"APP_AUTH_OIDC_CLIENT_SECRET": c.clientSecret,
	} {
		if v == "" {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return c, fmt.Errorf("missing configuration: %s", strings.Join(missing, ", "))
	}
	if !strings.HasPrefix(c.loginURL, "https://") {
		return c, errors.New("APP_AUTH_LOGIN_URL must be an https:// URL")
	}
	return c, nil
}

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	if err := run(log); err != nil {
		log.Error("exiting", "err", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	cfg, err := loadConfig()
	if err != nil {
		return err
	}
	keys, err := parseKeyring(cfg.sessionKeys)
	if err != nil {
		return fmt.Errorf("APP_AUTH_SESSION_KEYS: %w", err)
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	pool, err := openPool(ctx, cfg.databaseURL, 8)
	if err != nil {
		return err
	}
	defer pool.Close()
	st := &pgStore{pool: pool}

	v := &verifier{
		keys: keys, store: st, loginURL: cfg.loginURL, now: time.Now, log: log,
		patterns: newPatternCache(log), allowed: newAllowCache(log),
	}
	b := &broker{
		chrome:   newChrome(cfg.loginURL),
		loginURL: cfg.loginURL,
		keys:     keys, store: st, now: time.Now, log: log,
		auth: &oidcAuth{
			issuer: cfg.issuer, clientID: cfg.clientID, clientSecret: cfg.clientSecret,
			redirectURL: cfg.loginURL + "/callback",
		},
	}
	if b.oidc, err = loadProvider(cfg, log); err != nil {
		return err
	}

	verifyMux := http.NewServeMux()
	verifyMux.Handle("/verify", v)
	// Readiness is the process alone, deliberately not the database: checking a
	// session never touches it, so a database outage must cost only new
	// sign-ins, not every signed-in user's access.
	verifyMux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok\n")) })

	servers := []*http.Server{
		{Addr: cfg.verifyListen, Handler: verifyMux, ReadHeaderTimeout: 5 * time.Second},
		{Addr: cfg.brokerListen, Handler: b.routes(), ReadHeaderTimeout: 5 * time.Second},
	}
	errs := make(chan error, len(servers))
	for _, s := range servers {
		go func(s *http.Server) {
			log.Info("listening", "addr", s.Addr)
			if err := s.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
				errs <- err
			}
		}(s)
	}
	go purgeLoop(ctx, st, log)

	select {
	case err = <-errs:
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	for _, s := range servers {
		s.Shutdown(shutdown)
	}
	return err
}

func loadProvider(cfg config, log *slog.Logger) (*provider, error) {
	if cfg.providerClientKeys == "" || cfg.providerSigningKeys == "" {
		if cfg.providerClientKeys != "" || cfg.providerSigningKeys != "" {
			log.Warn("OpenID Provider disabled: APP_AUTH_OIDC_CLIENT_KEYS and APP_AUTH_OIDC_SIGNING_KEYS must both be set")
		}
		return nil, nil
	}
	clientKeys, err := parseKeyring(cfg.providerClientKeys)
	if err != nil {
		return nil, fmt.Errorf("APP_AUTH_OIDC_CLIENT_KEYS: %w", err)
	}
	signer, err := parseSigningKeys(cfg.providerSigningKeys)
	if err != nil {
		return nil, fmt.Errorf("APP_AUTH_OIDC_SIGNING_KEYS: %w", err)
	}
	log.Info("OpenID Provider enabled", "issuer", cfg.loginURL, "signing_key", signer.keys[0].kid)
	return &provider{clientKeys: clientKeys, signer: signer}, nil
}

// purgeLoop removes expired codes. Every replica runs it; the delete is
// idempotent, so running it twice costs nothing but a query. The first run
// waits a minute: on a rollout this pod can start before the worker's init
// container has (re)created its database role.
func purgeLoop(ctx context.Context, st store, log *slog.Logger) {
	t := time.NewTicker(10 * time.Minute)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return
	case <-time.After(time.Minute):
	}
	for {
		c, cancel := context.WithTimeout(ctx, 30*time.Second)
		if n, err := st.purgeExpiredCodes(c); err != nil {
			log.Warn("purging expired codes", "err", err)
		} else if n > 0 {
			log.Info("purged expired codes", "count", n)
		}
		cancel()
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}
