package main

import (
	"sort"
	"strings"
	"sync"
	"time"
)

const bucketPrefix = "dep-"

type bucket struct {
	bytes int64
	// Whether bytes holds a reading, either read or recovered at start.
	known bool
	// The last successful read, against which a write makes the bucket changed.
	readAt time.Time
	// The last attempt, successful or not, which orders reads: a bucket whose read
	// failed waits its turn again rather than being retried at once.
	triedAt   time.Time
	writtenAt time.Time
}

func (b *bucket) changed() bool { return b.writtenAt.After(b.readAt) }

// State is everything the exporter knows, keyed by bucket alias. In memory only:
// a restart recovers sizes from Prometheus (Seed) and nothing else.
type State struct {
	mu      sync.Mutex
	buckets map[string]*bucket
	// Garage's own bucket ids, which a request may address a bucket by.
	aliasOf map[string]string
	// Whose turn the next read is: a changed bucket, or the one read longest ago.
	changedTurn bool
	// While false, every read is in longest-ago order (D4).
	activityOK bool

	lastSuccess time.Time
	readErrors  uint64
}

func NewState() *State {
	return &State{
		buckets:     map[string]*bucket{},
		aliasOf:     map[string]string{},
		changedTurn: true,
	}
}

// deploymentAlias is the bucket's `dep-` alias, or "" when it has none.
func deploymentAlias(b GarageBucket) string {
	for _, alias := range b.GlobalAliases {
		if strings.HasPrefix(alias, bucketPrefix) {
			return alias
		}
	}
	return ""
}

// SetBuckets replaces the bucket list: new deployment buckets are added unread,
// vanished ones dropped, and every other bucket, the platform's own included,
// ignored.
func (s *State) SetBuckets(list []GarageBucket) {
	s.mu.Lock()
	defer s.mu.Unlock()
	present := map[string]bool{}
	aliasOf := map[string]string{}
	for _, b := range list {
		alias := deploymentAlias(b)
		if alias == "" {
			continue
		}
		present[alias] = true
		aliasOf[b.ID] = alias
		if _, ok := s.buckets[alias]; !ok {
			s.buckets[alias] = &bucket{}
		}
	}
	for alias := range s.buckets {
		if !present[alias] {
			delete(s.buckets, alias)
		}
	}
	s.aliasOf = aliasOf
}

// Seed publishes sizes recovered from Prometheus as the oldest readings, so the
// regular order refreshes them first. Only for buckets not read since.
func (s *State) Seed(sizes map[string]int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for alias, bytes := range sizes {
		if !strings.HasPrefix(alias, bucketPrefix) {
			continue
		}
		b, ok := s.buckets[alias]
		if !ok {
			b = &bucket{}
			s.buckets[alias] = b
		}
		if !b.known {
			b.bytes, b.known = bytes, true
		}
	}
}

// MarkWritten records writes to buckets, by alias or Garage id, as of `at`.
// Names that are neither are ignored. Ignored entirely while the activity signal
// is broken.
func (s *State) MarkWritten(names []string, at time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.activityOK {
		return
	}
	for _, name := range names {
		if alias, ok := s.aliasOf[name]; ok {
			name = alias
		}
		if b, ok := s.buckets[name]; ok && at.After(b.writtenAt) {
			b.writtenAt = at
		}
	}
}

func (s *State) SetActivityOK(ok bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.activityOK = ok
}

// Next is the bucket to read now, or "" when there are none, and whether it was
// chosen for having changed. Turns alternate
// between the changed bucket tried longest ago and the bucket tried longest ago
// overall; with nothing changed, the first falls through to the second. So at
// least every other read goes to the longest-ago bucket, which bounds every
// bucket's staleness at 2 × buckets reads.
func (s *State) Next(now time.Time) (alias string, changed bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	changedTurn := s.changedTurn && s.activityOK
	s.changedTurn = !s.changedTurn

	if changedTurn {
		alias = s.oldest(func(b *bucket) bool { return b.changed() })
		changed = alias != ""
	}
	if alias == "" {
		alias = s.oldest(func(*bucket) bool { return true })
	}
	if alias != "" {
		s.buckets[alias].triedAt = now
	}
	return alias, changed
}

// oldest is the matching bucket tried longest ago, ties broken by alias so the
// order is deterministic. A linear scan: at 50k buckets and a few reads a
// second it is not worth a heap.
func (s *State) oldest(match func(*bucket) bool) string {
	var pick string
	var at time.Time
	for alias, b := range s.buckets {
		if !match(b) {
			continue
		}
		if pick == "" || b.triedAt.Before(at) || (b.triedAt.Equal(at) && alias < pick) {
			pick, at = alias, b.triedAt
		}
	}
	return pick
}

// Read records a successful size read that started at `at`.
func (s *State) Read(alias string, bytes int64, at time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.lastSuccess = at
	if b, ok := s.buckets[alias]; ok {
		b.bytes, b.known, b.readAt = bytes, true, at
	}
}

// ReadFailed counts a failed size read. The size it would have replaced stays
// published.
func (s *State) ReadFailed() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.readErrors++
}

// Succeeded records a successful Garage call other than a size read.
func (s *State) Succeeded(at time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if at.After(s.lastSuccess) {
		s.lastSuccess = at
	}
}

type Snapshot struct {
	Sizes       map[string]int64
	Buckets     int
	LastSuccess time.Time
	ReadErrors  uint64
	ActivityOK  bool
}

func (s *State) Snapshot() Snapshot {
	s.mu.Lock()
	defer s.mu.Unlock()
	sizes := make(map[string]int64, len(s.buckets))
	for alias, b := range s.buckets {
		if b.known {
			sizes[alias] = b.bytes
		}
	}
	return Snapshot{
		Sizes:       sizes,
		Buckets:     len(s.buckets),
		LastSuccess: s.lastSuccess,
		ReadErrors:  s.readErrors,
		ActivityOK:  s.activityOK,
	}
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
