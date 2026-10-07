package main

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

// Garage logs every request before handling it, as
//
//	<source> [(via <proxy>)] [(key GK…)] <METHOD> /<bucket>[/<key>][?…]
//
// The bucket is always the first path segment, because root_domain is unset.
// The key is absent from browser form uploads (PostObject), which authenticate
// in the body, so it is not required. Admin API requests share the log and are
// addressed to /v2/…; "v2" is too short to be a bucket name.
const (
	writeLineFilter = ` (PUT|POST|DELETE) /`
	writeExtract    = `[\])0-9] (?:PUT|POST|DELETE) /(?P<bucket>[^/?\s]+)`
	adminSegment    = "v2"
)

// After a long Loki outage the cursor catches up a bounded range per refresh.
const maxActivityRange = time.Hour

func activityQuery(namespace string, seconds int64) string {
	return fmt.Sprintf(
		"sum by (bucket) (count_over_time({namespace=%q, container=\"garage\"} |~ `%s` | regexp `%s` | bucket != \"\" | bucket != %q [%ds]))",
		namespace, writeLineFilter, writeExtract, adminSegment, seconds)
}

type window struct {
	from, to time.Time
	lines    float64
}

type reading struct {
	at    time.Time
	value float64
}

// Activity turns Garage's request log into "written since" marks, and checks it
// against Garage's own write counter (D3, D4).
type Activity struct {
	loki      *http.Client
	lokiURL   string
	namespace string
	lag       time.Duration

	// Everything before the cursor has been read from Loki.
	cursor   time.Time
	windows  []window
	readings []reading
	// The last cross-check that could be decided: whether the counter rose over an
	// interval in which the log showed no writes.
	broken bool
}

func NewActivity(client *http.Client, lokiURL, namespace string, lag time.Duration, now time.Time) *Activity {
	return &Activity{
		loki:      client,
		lokiURL:   lokiURL,
		namespace: namespace,
		lag:       lag,
		cursor:    now.Add(-lag).Truncate(time.Second),
	}
}

// Writes reads the log from the cursor up to now − lag: the buckets written to,
// by whatever name the requests used, the range's end, and how many write lines
// there were in all. The cursor advances only on success.
func (a *Activity) Writes(ctx context.Context, now time.Time) (names []string, to time.Time, err error) {
	from := a.cursor
	to = now.Add(-a.lag).Truncate(time.Second)
	if to.Sub(from) > maxActivityRange {
		to = from.Add(maxActivityRange)
	}
	seconds := int64(to.Sub(from) / time.Second)
	if seconds <= 0 {
		return nil, from, nil
	}
	samples, err := instantQuery(ctx, a.loki, a.lokiURL+"/loki/api/v1/query", url.Values{
		"query": {activityQuery(a.namespace, seconds)},
		"time":  {strconv.FormatInt(to.UnixNano(), 10)},
	})
	if err != nil {
		return nil, from, fmt.Errorf("loki: %w", err)
	}
	var lines float64
	for _, s := range samples {
		names = append(names, s.Metric["bucket"])
		lines += s.Value
	}
	a.cursor = to
	a.windows = keepLast(append(a.windows, window{from: from, to: to, lines: lines}), 4)
	return names, to, nil
}

// Counted records Garage's write counter as read at `at`.
func (a *Activity) Counted(at time.Time, value float64) {
	a.readings = keepLast(append(a.readings, reading{at: at, value: value}), 3)
}

// Broken says whether the log missed writes Garage counted.
//
// It judges the latest interval between two counter readings that the log has
// been read past, so a write in the final lag before a refresh is never taken for
// a miss. Only "some versus none": counters and log lines do not line up exactly
// at the edges. An interval without writes says nothing, a counter that went down
// is a Garage restart, and an interval the stored windows do not cover is
// undecidable: all three keep the last verdict.
func (a *Activity) Broken() bool {
	if len(a.windows) == 0 {
		return a.broken
	}
	readTo := a.windows[len(a.windows)-1].to
	for i := len(a.readings) - 1; i > 0; i-- {
		before, after := a.readings[i-1], a.readings[i]
		if after.at.After(readTo) {
			continue
		}
		switch {
		case after.value <= before.value:
		case a.windows[0].from.After(before.at):
		default:
			var lines float64
			for _, w := range a.windows {
				if w.to.After(before.at) && w.from.Before(after.at) {
					lines += w.lines
				}
			}
			a.broken = lines == 0
		}
		break
	}
	return a.broken
}

func keepLast[T any](s []T, n int) []T {
	if len(s) > n {
		return s[len(s)-n:]
	}
	return s
}
