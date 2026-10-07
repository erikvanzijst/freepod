package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

type sample struct {
	Metric map[string]string
	Value  float64
}

// instantQuery runs an instant query against Prometheus's or Loki's query API,
// which answer it in the same shape.
func instantQuery(ctx context.Context, client *http.Client, endpoint string, params url.Values) ([]sample, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint+"?"+params.Encode(), nil)
	if err != nil {
		return nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		detail, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(detail)))
	}
	var payload struct {
		Status string `json:"status"`
		Data   struct {
			ResultType string `json:"resultType"`
			Result     []struct {
				Metric map[string]string `json:"metric"`
				Value  [2]any            `json:"value"`
			} `json:"result"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return nil, err
	}
	if payload.Status != "success" {
		return nil, fmt.Errorf("query status %q", payload.Status)
	}
	if payload.Data.ResultType != "vector" {
		return nil, fmt.Errorf("result type %q, want vector", payload.Data.ResultType)
	}
	samples := make([]sample, 0, len(payload.Data.Result))
	for _, r := range payload.Data.Result {
		text, _ := r.Value[1].(string)
		value, err := strconv.ParseFloat(text, 64)
		if err != nil {
			return nil, fmt.Errorf("value %v: %w", r.Value[1], err)
		}
		samples = append(samples, sample{Metric: r.Metric, Value: value})
	}
	return samples, nil
}
