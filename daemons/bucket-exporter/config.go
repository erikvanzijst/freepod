package main

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"time"
)

type Config struct {
	// Garage's admin API, and a token scoped to ListBuckets and GetBucketInfo.
	AdminURL   string
	AdminToken string
	// The namespace Garage, and this exporter, run in: Loki's stream selector and
	// Prometheus's `namespace` label both scope to it.
	Namespace string
	LokiURL   string
	// Optional: without it a restart starts from no sizes rather than the last
	// published ones.
	PrometheusURL string

	// Size reads per second, one bucket per call, whatever the number of buckets.
	// Every call costs Garage about 45 ms of CPU (Argon2 token verification), so
	// this alone sets the exporter's load. Every bucket is re-read at least once
	// per 2 × buckets ÷ rate; on a quiet platform, half that:
	//
	//	rate     50k buckets, worst case   50k buckets, quiet
	//	0.2 Hz   5.8 days                  2.9 days
	//	1 Hz     28 h                      14 h
	//	5 Hz     5.6 h                     2.8 h
	Rate float64
	// How often the bucket list, the activity signal and Garage's own write
	// counter are refreshed.
	RefreshInterval time.Duration
	// How far behind now the activity signal reads, for Loki's ingestion delay.
	LokiLag time.Duration

	Listen string
}

func loadConfig(getenv func(string) string) (Config, error) {
	c := Config{
		AdminURL:      getenv("GARAGE_ADMIN_URL"),
		AdminToken:    getenv("GARAGE_ADMIN_TOKEN"),
		Namespace:     getenv("GARAGE_NAMESPACE"),
		LokiURL:       getenv("LOKI_URL"),
		PrometheusURL: getenv("PROMETHEUS_URL"),
		Listen:        orDefault(getenv("LISTEN_ADDR"), ":9100"),
	}
	var errs []error
	for _, v := range []struct{ name, value string }{
		{"GARAGE_ADMIN_URL", c.AdminURL},
		{"GARAGE_ADMIN_TOKEN", c.AdminToken},
		{"GARAGE_NAMESPACE", c.Namespace},
		{"LOKI_URL", c.LokiURL},
	} {
		if v.value == "" {
			errs = append(errs, fmt.Errorf("%s is required", v.name))
		}
	}

	var err error
	if c.Rate, err = parseFloat(getenv("READ_RATE"), 0.2); err != nil {
		errs = append(errs, fmt.Errorf("READ_RATE: %w", err))
	} else if c.Rate <= 0 {
		errs = append(errs, errors.New("READ_RATE must be positive"))
	}
	if c.RefreshInterval, err = parseDuration(getenv("REFRESH_INTERVAL"), 5*time.Minute); err != nil {
		errs = append(errs, fmt.Errorf("REFRESH_INTERVAL: %w", err))
	}
	if c.LokiLag, err = parseDuration(getenv("LOKI_LAG"), time.Minute); err != nil {
		errs = append(errs, fmt.Errorf("LOKI_LAG: %w", err))
	}
	// The cross-check compares a refresh interval's write count with the activity
	// windows that cover it, which needs the windows to have caught up with it.
	if c.RefreshInterval < c.LokiLag || c.RefreshInterval <= 0 {
		errs = append(errs, errors.New("REFRESH_INTERVAL must be positive and at least LOKI_LAG"))
	}
	return c, errors.Join(errs...)
}

func loadConfigFromEnv() (Config, error) { return loadConfig(os.Getenv) }

func orDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func parseFloat(value string, fallback float64) (float64, error) {
	if value == "" {
		return fallback, nil
	}
	return strconv.ParseFloat(value, 64)
}

func parseDuration(value string, fallback time.Duration) (time.Duration, error) {
	if value == "" {
		return fallback, nil
	}
	return time.ParseDuration(value)
}
