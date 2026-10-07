package main

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

const recorded = "dep-d597d0fa-c81d-4148-b467-0785e8d152bb"

func newExporter(t *testing.T, garage, loki *httptest.Server) *Exporter {
	t.Helper()
	return &Exporter{
		garage:   &garageClient{baseURL: garage.URL, token: "t", http: garage.Client()},
		state:    NewState(),
		activity: NewActivity(loki.Client(), loki.URL, "caelus-garage-dev", time.Minute, t0),
		log:      slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

func scrape(t *testing.T, state *State) string {
	t.Helper()
	rec := httptest.NewRecorder()
	routes(state).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("scrape: HTTP %d", rec.Code)
	}
	return rec.Body.String()
}

func TestSizesSurviveAFailedRead(t *testing.T) {
	garage := fakeGarage(t, "t")
	loki := (&fakeLoki{}).server(t)
	e := newExporter(t, garage, loki)
	e.Refresh(context.Background(), t0)
	for i := 0; i < 3; i++ {
		e.ReadOne(context.Background(), t0.Add(time.Duration(i)*time.Second))
	}
	before := scrape(t, e.state)
	for _, want := range []string{
		`caelus_bucket_bytes{bucket="` + recorded + `"} 2673759`,
		"caelus_bucket_exporter_buckets 3\n",
		"caelus_bucket_exporter_read_errors_total 2\n", // the fixture knows one bucket only
		"caelus_bucket_exporter_last_success_timestamp_seconds ",
		"caelus_bucket_exporter_activity_signal_ok 1\n",
	} {
		if !strings.Contains(before, want) {
			t.Errorf("before: no %q in\n%s", want, before)
		}
	}
	if strings.Contains(before, "artifacts") {
		t.Error("the platform bucket was published")
	}

	garage.Close()
	e.state.SetBuckets(listOf(recorded))
	e.ReadOne(context.Background(), t0.Add(time.Hour))
	after := scrape(t, e.state)
	if !strings.Contains(after, `caelus_bucket_bytes{bucket="`+recorded+`"} 2673759`) {
		t.Errorf("a failed read dropped the size:\n%s", after)
	}
	if !strings.Contains(after, "caelus_bucket_exporter_read_errors_total 3\n") {
		t.Errorf("the failure was not counted:\n%s", after)
	}
}

func TestZerosArePublished(t *testing.T) {
	s := NewState()
	s.SetBuckets(listOf("dep-a"))
	alias, _ := s.Next(t0)
	s.Read(alias, 0, t0)
	if body := scrape(t, s); !strings.Contains(body, `caelus_bucket_bytes{bucket="dep-a"} 0`) {
		t.Fatalf("no zero:\n%s", body)
	}
}

func TestNoBucketsStillPublishesTheCount(t *testing.T) {
	body := scrape(t, NewState())
	if !strings.Contains(body, "caelus_bucket_exporter_buckets 0\n") {
		t.Fatalf("no bucket count:\n%s", body)
	}
	if strings.Contains(body, "caelus_bucket_bytes{") {
		t.Fatalf("sizes published:\n%s", body)
	}
}

// writesCounter serves /metrics with a scripted PutObject count, the rest of
// the admin API from the recorded fixtures.
func writesCounter(t *testing.T, puts *int) *httptest.Server {
	fixtures := fakeGarage(t, "t")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/metrics" {
			fmt.Fprintf(w, "api_s3_request_counter{api_endpoint=\"PutObject\"} %d\n", *puts)
			return
		}
		req, _ := http.NewRequest(r.Method, fixtures.URL+r.URL.String(), nil)
		req.Header = r.Header.Clone()
		resp, err := fixtures.Client().Do(req)
		if err != nil {
			t.Error(err)
			return
		}
		defer resp.Body.Close()
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestABrokenSignalSuspendsMarkingAndSaysSo(t *testing.T) {
	puts := 0
	e := newExporter(t, writesCounter(t, &puts), (&fakeLoki{}).server(t))

	// Writes Garage counts and its log does not show.
	for i := 0; i < 3; i++ {
		puts += 5
		e.Refresh(context.Background(), t0.Add(time.Duration(i)*5*time.Minute))
	}
	if body := scrape(t, e.state); !strings.Contains(body, "caelus_bucket_exporter_activity_signal_ok 0\n") {
		t.Fatalf("signal not reported broken:\n%s", body)
	}
	if len(e.state.buckets) != 3 {
		t.Fatalf("%d buckets known", len(e.state.buckets))
	}

	// While broken, a write mark is not acted on, and every read is in plain
	// order.
	e.state.MarkWritten([]string{recorded}, t0.Add(15*time.Minute))
	for alias, b := range e.state.buckets {
		if b.changed() {
			t.Fatalf("%s marked changed while the signal is broken", alias)
		}
	}
	for i := 0; i < 4; i++ {
		if _, changed := e.state.Next(t0.Add(16*time.Minute + time.Duration(i)*time.Second)); changed {
			t.Fatal("a changed turn while the signal is broken")
		}
	}
}

func TestAnUnreadableLogBreaksTheSignal(t *testing.T) {
	garage := fakeGarage(t, "t")
	e := newExporter(t, garage, (&fakeLoki{fail: true}).server(t))
	e.Refresh(context.Background(), t0)
	e.Refresh(context.Background(), t0.Add(5*time.Minute))
	if body := scrape(t, e.state); !strings.Contains(body, "caelus_bucket_exporter_activity_signal_ok 0\n") {
		t.Fatalf("signal not reported broken:\n%s", body)
	}
}

func TestAWriteIsReadOnTheNextChangedTurn(t *testing.T) {
	garage := fakeGarage(t, "t")
	loki := &fakeLoki{}
	e := newExporter(t, garage, loki.server(t))
	e.Refresh(context.Background(), t0)
	for i := 0; i < 3; i++ {
		e.ReadOne(context.Background(), t0.Add(time.Duration(i)*time.Second))
	}
	loki.buckets = map[string]float64{
		// Addressed by Garage's id, and an unknown name beside it.
		"90547472817ecc5a1e7df91d214a2db22983774f357c343a0b87874892d26251": 3,
		"dev": 1,
	}
	e.Refresh(context.Background(), t0.Add(5*time.Minute))
	var reads []string
	for i := 0; i < 2; i++ {
		alias, changed := e.state.Next(t0.Add(6*time.Minute + time.Duration(i)*time.Second))
		if changed {
			reads = append(reads, alias)
		}
	}
	if len(reads) != 1 || reads[0] != recorded {
		t.Fatalf("changed reads %v, want %s", reads, recorded)
	}
}

func TestTheSignalRecoversWhenTheLogShowsCountedWrites(t *testing.T) {
	puts := 0
	loki := &fakeLoki{}
	e := newExporter(t, writesCounter(t, &puts), loki.server(t))
	for i := 0; i < 3; i++ {
		puts += 5
		e.Refresh(context.Background(), t0.Add(time.Duration(i)*5*time.Minute))
	}
	loki.buckets = map[string]float64{recorded: 1}
	for i := 3; i < 5; i++ {
		puts += 5
		e.Refresh(context.Background(), t0.Add(time.Duration(i)*5*time.Minute))
	}
	if body := scrape(t, e.state); !strings.Contains(body, "caelus_bucket_exporter_activity_signal_ok 1\n") {
		t.Fatalf("signal not restored:\n%s", body)
	}
}
