package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func fakePrometheus(t *testing.T, series map[string][]map[string]any) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query().Get("query")
		if !strings.Contains(query, `{namespace="caelus-garage-dev"}[10d]`) {
			t.Errorf("unscoped query %s", query)
		}
		var result []map[string]any
		for name, rows := range series {
			if strings.Contains(query, name+"{") {
				result = rows
			}
		}
		json.NewEncoder(w).Encode(map[string]any{
			"status": "success",
			"data":   map[string]any{"resultType": "vector", "result": result},
		})
	}))
	t.Cleanup(srv.Close)
	return srv
}

func row(labels map[string]string, value string) map[string]any {
	return map[string]any{"metric": labels, "value": []any{1791400000, value}}
}

func TestSizesAreRecoveredFromTheNewestExporter(t *testing.T) {
	srv := fakePrometheus(t, map[string][]map[string]any{
		"caelus_bucket_bytes": {
			row(map[string]string{"bucket": "dep-a", "instance": "old:9100"}, "100"),
			row(map[string]string{"bucket": "dep-a", "instance": "new:9100"}, "150"),
			row(map[string]string{"bucket": "dep-b", "instance": "old:9100"}, "7"),
		},
		"caelus_bucket_exporter_last_success_timestamp_seconds": {
			row(map[string]string{"instance": "old:9100"}, "1791300000"),
			row(map[string]string{"instance": "new:9100"}, "1791390000"),
		},
	})
	sizes, err := recoverSizes(context.Background(), srv.Client(), srv.URL, "caelus-garage-dev", t0)
	if err != nil {
		t.Fatal(err)
	}
	if len(sizes) != 2 || sizes["dep-a"] != 150 || sizes["dep-b"] != 7 {
		t.Fatalf("sizes = %v", sizes)
	}

	s := NewState()
	s.Seed(sizes)
	if body := scrape(t, s); !strings.Contains(body, `caelus_bucket_bytes{bucket="dep-a"} 150`) {
		t.Fatalf("recovered size not published:\n%s", body)
	}
}

func TestStartupProceedsWithoutPrometheus(t *testing.T) {
	down := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	t.Cleanup(down.Close)
	e := newExporter(t, fakeGarage(t, "t"), (&fakeLoki{}).server(t))

	e.Start(context.Background(), down.Client(), down.URL, "caelus-garage-dev", t0)

	if body := scrape(t, e.state); !strings.Contains(body, "caelus_bucket_exporter_buckets 3\n") {
		t.Fatalf("the bucket list was not read after Prometheus failed:\n%s", body)
	}
}

func TestStartupSeedsBeforeTheBucketList(t *testing.T) {
	prometheus := fakePrometheus(t, map[string][]map[string]any{
		"caelus_bucket_bytes": {
			row(map[string]string{"bucket": recorded, "instance": "old:9100"}, "42"),
			row(map[string]string{"bucket": "dep-deleted-since", "instance": "old:9100"}, "9"),
		},
	})
	e := newExporter(t, fakeGarage(t, "t"), (&fakeLoki{}).server(t))

	e.Start(context.Background(), prometheus.Client(), prometheus.URL, "caelus-garage-dev", t0)

	body := scrape(t, e.state)
	if !strings.Contains(body, `caelus_bucket_bytes{bucket="`+recorded+`"} 42`) {
		t.Fatalf("recovered size not published:\n%s", body)
	}
	if strings.Contains(body, "dep-deleted-since") {
		t.Fatalf("a bucket Garage no longer lists was kept:\n%s", body)
	}
}
