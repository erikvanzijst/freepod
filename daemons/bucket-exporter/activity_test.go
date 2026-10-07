package main

import (
	"bufio"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"time"
)

// written applies the activity query's pipeline to one log line, as Loki would:
// the line filter, the extraction, then the two label filters. LogQL's
// regular expressions are Go's.
func written(line string) (string, bool) {
	if !regexp.MustCompile(writeLineFilter).MatchString(line) {
		return "", false
	}
	m := regexp.MustCompile(writeExtract).FindStringSubmatch(line)
	if m == nil || m[1] == "" || m[1] == adminSegment {
		return "", false
	}
	return m[1], true
}

func TestTheRegularExpressionMatchesGarageV230RequestLines(t *testing.T) {
	file, err := os.Open("testdata/v2.3.0-requests.log")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()

	// Recorded from dev's Loki, ANSI colors and all, in the order written.
	want := []string{
		"artifacts", // PUT via the public endpoint, (via …) (key GK…)
		"artifacts", // DELETE via the public endpoint
		"dep-940b7eb8-d8ee-4a95-b8db-9f9301a27064", // PUT from inside the cluster
		"dev",       // DELETE from inside the cluster, to a bucket that is no deployment's
		"",          // GET: a read
		"",          // HEAD: a read
		"",          // GET /v2/ListBuckets: the admin API
		"",          // POST /v2/CreateAdminToken: the admin API, no key
		"",          // an error line answering a GET
		"",          // an error line answering an admin GET
		"artifacts", // a browser form upload: POST via the public endpoint, no key
	}
	var got []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		bucket, _ := written(scanner.Text())
		got = append(got, bucket)
	}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("got  %q\nwant %q", got, want)
	}
}

func TestTheRegularExpressionMatchesTheOtherRequestForms(t *testing.T) {
	const prefix = "\x1b[2m2026-10-07T09:05:21.153894Z\x1b[0m \x1b[32m INFO\x1b[0m \x1b[2mgarage_api_common::generic_server\x1b[0m\x1b[2m:\x1b[0m "
	for line, want := range map[string]string{
		// A form upload from inside the cluster: no proxy and no key.
		"[::ffff:127.0.0.1]:35156 POST /dep-5006d4fd-b458-48dc-bd90-20f1cac6ee85": "dep-5006d4fd-b458-48dc-bd90-20f1cac6ee85",
		// IPv4 direct, multi-object delete.
		"10.42.0.9:4711 (key GK0e4462380b3331f373bf324d) POST /dep-5006d4fd-b458-48dc-bd90-20f1cac6ee85?delete": "dep-5006d4fd-b458-48dc-bd90-20f1cac6ee85",
		// A bucket addressed by Garage's own id.
		"[::ffff:127.0.0.1]:35156 (key GK0e4462380b3331f373bf324d) PUT /90547472817ecc5a1e7df91d214a2db22983774f357c343a0b87874892d26251/x": "90547472817ecc5a1e7df91d214a2db22983774f357c343a0b87874892d26251",
		// An admin write with a bearer token.
		"[::ffff:10.42.0.220]:58514 (key f8ba7e2046139d5fad5e735c) POST /v2/UpdateBucket?id=f600a5": "",
		// An object key crafted to look like a write. Counted: whatever the log
		// says only reorders reads, it never adds one.
		"[::ffff:127.0.0.1]:1 (key GK0) GET /dep-x/a) PUT /dep-y": "dep-y",
	} {
		if got, _ := written(prefix + line); got != want {
			t.Errorf("%s\n  got %q, want %q", line, got, want)
		}
	}
}

// fakeLoki answers activity queries from a script, recording what was asked.
type fakeLoki struct {
	fail    bool
	buckets map[string]float64
	asked   []url_
}

type url_ struct {
	query string
	at    time.Time
}

func (f *fakeLoki) server(t *testing.T) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ns, _ := strconv.ParseInt(r.URL.Query().Get("time"), 10, 64)
		f.asked = append(f.asked, url_{query: r.URL.Query().Get("query"), at: time.Unix(0, ns).UTC()})
		if f.fail {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		result := []map[string]any{}
		for bucket, n := range f.buckets {
			result = append(result, map[string]any{
				"metric": map[string]string{"bucket": bucket},
				"value":  []any{float64(ns) / 1e9, strconv.FormatFloat(n, 'f', -1, 64)},
			})
		}
		json.NewEncoder(w).Encode(map[string]any{
			"status": "success",
			"data":   map[string]any{"resultType": "vector", "result": result},
		})
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestTheCursorAdvancesOnlyOnSuccess(t *testing.T) {
	loki := &fakeLoki{fail: true}
	srv := loki.server(t)
	a := NewActivity(srv.Client(), srv.URL, "caelus-garage-dev", time.Minute, t0)

	if _, _, err := a.Writes(context.Background(), t0.Add(5*time.Minute)); err == nil {
		t.Fatal("a failed query reported success")
	}
	loki.fail = false
	loki.buckets = map[string]float64{"dep-a": 2}
	names, to, err := a.Writes(context.Background(), t0.Add(10*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	// The range the failure missed is read with the next: from start − lag.
	if to != t0.Add(9*time.Minute) || !strings.Contains(loki.asked[1].query, "[600s]") {
		t.Fatalf("to %v, query %s", to, loki.asked[1].query)
	}
	if loki.asked[1].at != to || len(names) != 1 || names[0] != "dep-a" {
		t.Fatalf("asked at %v, names %v", loki.asked[1].at, names)
	}
	if !strings.Contains(loki.asked[1].query, `{namespace="caelus-garage-dev", container="garage"}`) {
		t.Fatalf("query not scoped: %s", loki.asked[1].query)
	}

	loki.buckets = nil
	if _, _, err := a.Writes(context.Background(), t0.Add(15*time.Minute)); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(loki.asked[2].query, "[300s]") {
		t.Fatalf("the next range did not start at the cursor: %s", loki.asked[2].query)
	}
}

func TestALongOutageIsCaughtUpInBoundedRanges(t *testing.T) {
	loki := &fakeLoki{}
	srv := loki.server(t)
	a := NewActivity(srv.Client(), srv.URL, "ns", time.Minute, t0)

	_, to, err := a.Writes(context.Background(), t0.Add(5*time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	if to != t0.Add(-time.Minute+maxActivityRange) || !strings.Contains(loki.asked[0].query, "[3600s]") {
		t.Fatalf("to %v, query %s", to, loki.asked[0].query)
	}
}

// refreshes drives an Activity through refreshes every five minutes, with the
// counter and the log's write lines for each.
func refreshes(t *testing.T, steps []struct {
	counter float64
	lines   float64
}) []bool {
	t.Helper()
	loki := &fakeLoki{}
	srv := loki.server(t)
	a := NewActivity(srv.Client(), srv.URL, "ns", time.Minute, t0)
	var verdicts []bool
	for i, step := range steps {
		now := t0.Add(time.Duration(i) * 5 * time.Minute)
		a.Counted(now, step.counter)
		loki.buckets = map[string]float64{}
		if step.lines > 0 {
			loki.buckets["dep-a"] = step.lines
		}
		if _, _, err := a.Writes(context.Background(), now); err != nil {
			t.Fatal(err)
		}
		verdicts = append(verdicts, a.Broken())
	}
	return verdicts
}

type step = struct {
	counter float64
	lines   float64
}

func TestWritesTheLogMissesBreakTheSignal(t *testing.T) {
	got := refreshes(t, []step{{10, 0}, {12, 0}, {12, 0}, {12, 0}})
	// The rise in the second interval is judged once the log has been read past it.
	if got[len(got)-1] != true || got[1] != false {
		t.Fatalf("verdicts %v", got)
	}
}

func TestWritesTheLogShowsKeepTheSignal(t *testing.T) {
	got := refreshes(t, []step{{10, 0}, {12, 1}, {14, 1}, {14, 1}})
	for _, broken := range got {
		if broken {
			t.Fatalf("verdicts %v", got)
		}
	}
}

func TestAWriteInTheFinalLagIsNotAMiss(t *testing.T) {
	// The write lands after the second refresh's window closed, so the counter has
	// it at the second refresh and the log only at the third.
	got := refreshes(t, []step{{10, 0}, {11, 0}, {11, 1}, {11, 0}})
	for _, broken := range got {
		if broken {
			t.Fatalf("verdicts %v", got)
		}
	}
}

func TestACounterDecreaseIsARestartNotAMiss(t *testing.T) {
	got := refreshes(t, []step{{10, 0}, {12, 1}, {3, 0}, {3, 0}})
	for _, broken := range got {
		if broken {
			t.Fatalf("verdicts %v", got)
		}
	}
}

func TestAQuietIntervalKeepsTheVerdict(t *testing.T) {
	got := refreshes(t, []step{{10, 0}, {12, 0}, {12, 0}, {12, 0}, {12, 0}})
	if !got[len(got)-1] {
		t.Fatalf("a quiet interval cleared a broken signal: %v", got)
	}
	recovered := refreshes(t, []step{{10, 0}, {12, 0}, {12, 0}, {15, 2}, {15, 1}, {15, 0}})
	if recovered[len(recovered)-1] {
		t.Fatalf("writes the log showed did not restore it: %v", recovered)
	}
}
