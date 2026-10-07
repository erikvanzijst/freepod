// bucket-exporter reads every deployment bucket's size from one Garage instance,
// one bucket per call at a fixed rate, and publishes it to Prometheus.
//
// Spec: openspec/specs/bucket-size-exporter/spec.md
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const callTimeout = 30 * time.Second

type Exporter struct {
	garage   *garageClient
	state    *State
	activity *Activity
	log      *slog.Logger
}

// Refresh re-reads the bucket list, Garage's write counter and the activity
// signal, in that order. Each step's failure is logged and leaves the others.
func (e *Exporter) Refresh(ctx context.Context, now time.Time) {
	call, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()

	if list, err := e.garage.ListBuckets(call); err != nil {
		e.log.Warn("bucket list not refreshed", "err", err)
	} else {
		e.state.SetBuckets(list)
		e.state.Succeeded(now)
	}

	if count, err := e.garage.WriteRequests(call); err != nil {
		e.log.Warn("Garage's write counter not read", "err", err)
	} else {
		e.activity.Counted(now, count)
	}

	names, to, err := e.activity.Writes(call, now)
	if err != nil {
		e.state.SetActivityOK(false)
		e.log.Warn("activity signal unreadable; reading buckets in plain order", "err", err)
		return
	}
	if e.activity.Broken() {
		e.state.SetActivityOK(false)
		e.log.Warn("activity signal broken: Garage counted writes its request log does not show; reading buckets in plain order")
		return
	}
	e.state.SetActivityOK(true)
	e.state.MarkWritten(names, to)
}

// Start recovers the last published sizes, when Prometheus is configured and
// answers, and then reads the bucket list. Neither failing stops the exporter.
func (e *Exporter) Start(ctx context.Context, client *http.Client, prometheusURL, namespace string, now time.Time) {
	if prometheusURL != "" {
		seedCtx, cancel := context.WithTimeout(ctx, callTimeout)
		sizes, err := recoverSizes(seedCtx, client, prometheusURL, namespace, now)
		cancel()
		if err != nil {
			e.log.Warn("sizes not recovered from Prometheus; starting without them", "err", err)
		} else {
			e.state.Seed(sizes)
			e.log.Info("sizes recovered from Prometheus", "buckets", len(sizes))
		}
	}
	e.Refresh(ctx, now)
}

// ReadOne reads the size of the bucket whose turn it is.
func (e *Exporter) ReadOne(ctx context.Context, now time.Time) {
	alias, changed := e.state.Next(now)
	if alias == "" {
		return
	}
	call, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	bytes, err := e.garage.BucketBytes(call, alias)
	if err != nil {
		e.state.ReadFailed()
		e.log.Warn("bucket size not read", "bucket", alias, "err", err)
		return
	}
	e.state.Read(alias, bytes, now)
	level := slog.LevelDebug
	if changed {
		level = slog.LevelInfo
	}
	e.log.Log(ctx, level, "bucket read", "bucket", alias, "bytes", bytes, "changed", changed)
}

func main() {
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	if err := run(log); err != nil {
		log.Error("bucket-exporter stopped", "err", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	cfg, err := loadConfigFromEnv()
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	client := &http.Client{Timeout: callTimeout}
	now := time.Now()
	e := &Exporter{
		garage:   &garageClient{baseURL: cfg.AdminURL, token: cfg.AdminToken, http: client},
		state:    NewState(),
		activity: NewActivity(client, cfg.LokiURL, cfg.Namespace, cfg.LokiLag, now),
		log:      log,
	}

	e.Start(ctx, client, cfg.PrometheusURL, cfg.Namespace, now)

	server := &http.Server{Addr: cfg.Listen, Handler: routes(e.state), ReadHeaderTimeout: 10 * time.Second}
	serverErr := make(chan error, 1)
	go func() { serverErr <- server.ListenAndServe() }()
	log.Info("bucket-exporter started", "namespace", cfg.Namespace, "rate", cfg.Rate,
		"refresh", cfg.RefreshInterval, "listen", cfg.Listen)

	go every(ctx, cfg.RefreshInterval, e.Refresh)
	go every(ctx, time.Duration(float64(time.Second)/cfg.Rate), e.ReadOne)

	select {
	case <-ctx.Done():
	case err := <-serverErr:
		return err
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdown); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

func routes(state *State) http.Handler {
	mux := http.NewServeMux()
	mux.Handle("GET /metrics", metricsHandler(state))
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	return mux
}

// every runs fn on a fixed schedule until ctx ends. A slow run delays the next
// rather than overlapping it, so the rate is a ceiling.
func every(ctx context.Context, interval time.Duration, fn func(context.Context, time.Time)) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			fn(ctx, now)
		}
	}
}
