package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

// fakeGarage serves the admin API from responses recorded against Garage v2.3.0.
func fakeGarage(t *testing.T, token string) *httptest.Server {
	t.Helper()
	fixture := func(name string) []byte {
		body, err := os.ReadFile("testdata/" + name)
		if err != nil {
			t.Fatal(err)
		}
		return body
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/metrics" {
			w.Write(fixture("v2.3.0-metrics.txt"))
			return
		}
		if r.Header.Get("Authorization") != "Bearer "+token {
			w.WriteHeader(http.StatusForbidden)
			w.Write([]byte(`{"code":"AccessDenied","message":"Forbidden: Invalid bearer token"}`))
			return
		}
		switch r.URL.Path {
		case "/v2/ListBuckets":
			w.Write(fixture("v2.3.0-ListBuckets.json"))
		case "/v2/GetBucketInfo":
			if r.URL.Query().Get("globalAlias") != "dep-d597d0fa-c81d-4148-b467-0785e8d152bb" {
				w.WriteHeader(http.StatusNotFound)
				w.Write([]byte(`{"code":"NoSuchBucket","message":"Bucket not found"}`))
				return
			}
			w.Write(fixture("v2.3.0-GetBucketInfo.json"))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func client(srv *httptest.Server, token string) *garageClient {
	return &garageClient{baseURL: srv.URL, token: token, http: srv.Client()}
}

func TestListBuckets(t *testing.T) {
	g := client(fakeGarage(t, "t"), "t")
	buckets, err := g.ListBuckets(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(buckets) != 4 {
		t.Fatalf("got %d buckets", len(buckets))
	}
	aliases := map[string]string{}
	for _, b := range buckets {
		aliases[b.ID] = deploymentAlias(b)
	}
	if aliases["f600a537c9d9dfe886a30b5aeaf0876afc1f8c2b8490d2d9d53a67a1479ea8c3"] != "" {
		t.Error("the platform's artifacts bucket counted as a deployment's")
	}
	if aliases["90547472817ecc5a1e7df91d214a2db22983774f357c343a0b87874892d26251"] != "dep-d597d0fa-c81d-4148-b467-0785e8d152bb" {
		t.Errorf("aliases: %v", aliases)
	}
}

func TestBucketBytes(t *testing.T) {
	g := client(fakeGarage(t, "t"), "t")
	bytes, err := g.BucketBytes(context.Background(), "dep-d597d0fa-c81d-4148-b467-0785e8d152bb")
	if err != nil {
		t.Fatal(err)
	}
	if bytes != 2673759 {
		t.Fatalf("bytes = %d", bytes)
	}
}

func TestBucketBytesFailures(t *testing.T) {
	srv := fakeGarage(t, "t")
	if _, err := client(srv, "t").BucketBytes(context.Background(), "dep-gone"); err == nil ||
		!strings.Contains(err.Error(), "404") {
		t.Errorf("missing bucket: %v", err)
	}
	if _, err := client(srv, "wrong").BucketBytes(context.Background(), "dep-d597d0fa-c81d-4148-b467-0785e8d152bb"); err == nil ||
		!strings.Contains(err.Error(), "403") {
		t.Errorf("bad token: %v", err)
	}
}

func TestWriteRequestsSumsTheWritingEndpointsOnly(t *testing.T) {
	g := client(fakeGarage(t, "t"), "")
	total, err := g.WriteRequests(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	// PutObject 9 + DeleteObject 2 + PostObject 2; not CreateBucket, reads, the
	// error counter or the duration histogram.
	if total != 13 {
		t.Fatalf("total = %v", total)
	}
}

func TestWriteRequestsBeforeAnyS3Request(t *testing.T) {
	total, err := parseWriteRequests(strings.NewReader("# TYPE garage_build_info gauge\ngarage_build_info{version=\"v2.3.0\"} 1\n"))
	if err != nil || total != 0 {
		t.Fatalf("total = %v, err = %v", total, err)
	}
}
