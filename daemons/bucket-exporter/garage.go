package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

// The S3 endpoints that change what a bucket holds, as Garage's
// api_s3_request_counter names them.
var writeEndpoints = map[string]bool{
	"PutObject":               true,
	"PostObject":              true,
	"CopyObject":              true,
	"UploadPart":              true,
	"UploadPartCopy":          true,
	"CompleteMultipartUpload": true,
	"AbortMultipartUpload":    true,
	"DeleteObject":            true,
	"DeleteObjects":           true,
}

type GarageBucket struct {
	ID            string   `json:"id"`
	GlobalAliases []string `json:"globalAliases"`
}

type garageClient struct {
	baseURL string
	token   string
	http    *http.Client
}

func (g *garageClient) ListBuckets(ctx context.Context) ([]GarageBucket, error) {
	var buckets []GarageBucket
	return buckets, g.getJSON(ctx, "/v2/ListBuckets", &buckets)
}

// BucketBytes is the bytes of a bucket's completed objects. Unfinished multipart
// uploads are not counted, as Garage does not count them against its quota.
func (g *garageClient) BucketBytes(ctx context.Context, alias string) (int64, error) {
	var info struct {
		Bytes *int64 `json:"bytes"`
	}
	if err := g.getJSON(ctx, "/v2/GetBucketInfo?globalAlias="+url.QueryEscape(alias), &info); err != nil {
		return 0, err
	}
	if info.Bytes == nil {
		return 0, fmt.Errorf("GetBucketInfo %s: no bytes in the response", alias)
	}
	return *info.Bytes, nil
}

// WriteRequests is Garage's own count of write requests since it started. Read
// from /metrics, which the admin port serves without authentication.
func (g *garageClient) WriteRequests(ctx context.Context) (float64, error) {
	body, err := g.get(ctx, "/metrics", false)
	if err != nil {
		return 0, err
	}
	defer body.Close()
	return parseWriteRequests(body)
}

func parseWriteRequests(r io.Reader) (float64, error) {
	const prefix = `api_s3_request_counter{`
	var total float64
	found := false
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, prefix) {
			continue
		}
		found = true
		labels, value, ok := strings.Cut(line[len(prefix):], "} ")
		if !ok {
			continue
		}
		if !writeEndpoints[labelValue(labels, "api_endpoint")] {
			continue
		}
		n, err := strconv.ParseFloat(strings.Fields(value)[0], 64)
		if err != nil {
			return 0, fmt.Errorf("api_s3_request_counter: %w", err)
		}
		total += n
	}
	if err := scanner.Err(); err != nil {
		return 0, err
	}
	if !found {
		// Garage registers the counter on its first S3 request.
		return 0, nil
	}
	return total, nil
}

// labelValue reads one label out of a Prometheus text-format label set, which
// for Garage's counters never holds escaped quotes.
func labelValue(labels, name string) string {
	for _, pair := range strings.Split(labels, ",") {
		key, value, ok := strings.Cut(pair, "=")
		if ok && key == name {
			return strings.Trim(value, `"`)
		}
	}
	return ""
}

func (g *garageClient) getJSON(ctx context.Context, path string, into any) error {
	body, err := g.get(ctx, path, true)
	if err != nil {
		return err
	}
	defer body.Close()
	if err := json.NewDecoder(body).Decode(into); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	return nil
}

func (g *garageClient) get(ctx context.Context, path string, auth bool) (io.ReadCloser, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, g.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	if auth {
		req.Header.Set("Authorization", "Bearer "+g.token)
	}
	resp, err := g.http.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		detail, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		return nil, fmt.Errorf("%s: HTTP %d: %s", strings.SplitN(path, "?", 2)[0], resp.StatusCode, strings.TrimSpace(string(detail)))
	}
	return resp.Body, nil
}
