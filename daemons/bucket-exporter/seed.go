package main

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

// recoverSizes reads each bucket's last published size back from Prometheus, as
// far back as it retains them.
//
// Every exporter pod publishes under its own `instance`, so a bucket can have one
// series per past pod. The newest is the one from the pod whose last successful
// Garage call was latest, which its own timestamp gauge says.
func recoverSizes(ctx context.Context, client *http.Client, prometheusURL, namespace string, now time.Time) (map[string]int64, error) {
	query := func(series string) ([]sample, error) {
		return instantQuery(ctx, client, prometheusURL+"/api/v1/query", url.Values{
			"query": {fmt.Sprintf("last_over_time(%s{namespace=%q}[10d])", series, namespace)},
			"time":  {strconv.FormatInt(now.Unix(), 10)},
		})
	}
	sizes, err := query("caelus_bucket_bytes")
	if err != nil {
		return nil, err
	}
	successes, err := query("caelus_bucket_exporter_last_success_timestamp_seconds")
	if err != nil {
		return nil, err
	}
	latest := map[string]float64{}
	for _, s := range successes {
		latest[s.Metric["instance"]] = s.Value
	}

	recovered := map[string]int64{}
	rank := map[string]float64{}
	for _, s := range sizes {
		bucket := s.Metric["bucket"]
		if bucket == "" {
			continue
		}
		r, ok := latest[s.Metric["instance"]]
		if !ok {
			r = -1
		}
		if prev, seen := rank[bucket]; !seen || r > prev {
			recovered[bucket], rank[bucket] = int64(s.Value), r
		}
	}
	return recovered, nil
}
