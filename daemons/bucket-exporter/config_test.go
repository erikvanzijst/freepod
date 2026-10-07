package main

import (
	"strings"
	"testing"
	"time"
)

func env(values map[string]string) func(string) string {
	return func(key string) string { return values[key] }
}

var required = map[string]string{
	"GARAGE_ADMIN_URL":   "http://garage:3903",
	"GARAGE_ADMIN_TOKEN": "t",
	"GARAGE_NAMESPACE":   "caelus-garage-dev",
	"LOKI_URL":           "http://loki:3100",
}

func with(overrides map[string]string) map[string]string {
	merged := map[string]string{}
	for k, v := range required {
		merged[k] = v
	}
	for k, v := range overrides {
		merged[k] = v
	}
	return merged
}

func TestConfigDefaults(t *testing.T) {
	c, err := loadConfig(env(required))
	if err != nil {
		t.Fatal(err)
	}
	if c.Rate != 0.2 || c.RefreshInterval != 5*time.Minute || c.LokiLag != time.Minute || c.Listen != ":9100" {
		t.Fatalf("defaults: %+v", c)
	}
	if c.PrometheusURL != "" {
		t.Fatalf("PrometheusURL defaulted to %q", c.PrometheusURL)
	}
}

func TestConfigOverrides(t *testing.T) {
	c, err := loadConfig(env(with(map[string]string{
		"READ_RATE":        "2",
		"REFRESH_INTERVAL": "90s",
		"LOKI_LAG":         "30s",
		"LISTEN_ADDR":      ":8080",
		"PROMETHEUS_URL":   "http://prometheus",
	})))
	if err != nil {
		t.Fatal(err)
	}
	if c.Rate != 2 || c.RefreshInterval != 90*time.Second || c.LokiLag != 30*time.Second ||
		c.Listen != ":8080" || c.PrometheusURL != "http://prometheus" {
		t.Fatalf("overrides: %+v", c)
	}
}

func TestConfigRequiresGarageAndLoki(t *testing.T) {
	_, err := loadConfig(env(map[string]string{}))
	if err == nil {
		t.Fatal("no error without configuration")
	}
	for name := range required {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error does not name %s: %v", name, err)
		}
	}
}

func TestConfigRejectsBadValues(t *testing.T) {
	for _, bad := range []map[string]string{
		{"READ_RATE": "0"},
		{"READ_RATE": "-1"},
		{"READ_RATE": "fast"},
		{"REFRESH_INTERVAL": "soon"},
		{"REFRESH_INTERVAL": "30s", "LOKI_LAG": "1m"},
	} {
		if _, err := loadConfig(env(with(bad))); err == nil {
			t.Errorf("%v accepted", bad)
		}
	}
}
