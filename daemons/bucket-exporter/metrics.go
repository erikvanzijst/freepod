package main

import (
	"fmt"
	"net/http"
	"strings"
)

// metricsHandler publishes the state in Prometheus's text format (D5). Every
// known size is published, zeros included: the usage worker averages over each
// window, so an emptied bucket must contribute its zeros.
func metricsHandler(state *State) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		snap := state.Snapshot()
		w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		var b strings.Builder

		b.WriteString("# HELP caelus_bucket_bytes Bytes of a deployment bucket's completed objects, as of its last read.\n")
		b.WriteString("# TYPE caelus_bucket_bytes gauge\n")
		for _, alias := range sortedKeys(snap.Sizes) {
			fmt.Fprintf(&b, "caelus_bucket_bytes{bucket=\"%s\"} %d\n", escapeLabel(alias), snap.Sizes[alias])
		}

		b.WriteString("# HELP caelus_bucket_exporter_buckets Deployment buckets known to the exporter; published for as long as it runs.\n")
		b.WriteString("# TYPE caelus_bucket_exporter_buckets gauge\n")
		fmt.Fprintf(&b, "caelus_bucket_exporter_buckets %d\n", snap.Buckets)

		if !snap.LastSuccess.IsZero() {
			b.WriteString("# HELP caelus_bucket_exporter_last_success_timestamp_seconds When Garage last answered a call.\n")
			b.WriteString("# TYPE caelus_bucket_exporter_last_success_timestamp_seconds gauge\n")
			fmt.Fprintf(&b, "caelus_bucket_exporter_last_success_timestamp_seconds %.3f\n",
				float64(snap.LastSuccess.UnixMilli())/1000)
		}

		b.WriteString("# HELP caelus_bucket_exporter_read_errors_total Bucket size reads that failed.\n")
		b.WriteString("# TYPE caelus_bucket_exporter_read_errors_total counter\n")
		fmt.Fprintf(&b, "caelus_bucket_exporter_read_errors_total %d\n", snap.ReadErrors)

		b.WriteString("# HELP caelus_bucket_exporter_activity_signal_ok 1 while Garage's request log reflects its writes; 0 while reads are in plain order.\n")
		b.WriteString("# TYPE caelus_bucket_exporter_activity_signal_ok gauge\n")
		ok := 0
		if snap.ActivityOK {
			ok = 1
		}
		fmt.Fprintf(&b, "caelus_bucket_exporter_activity_signal_ok %d\n", ok)

		_, _ = w.Write([]byte(b.String()))
	})
}

var labelEscaper = strings.NewReplacer(`\`, `\\`, `"`, `\"`, "\n", `\n`)

func escapeLabel(value string) string { return labelEscaper.Replace(value) }
