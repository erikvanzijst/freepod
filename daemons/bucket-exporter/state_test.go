package main

import (
	"fmt"
	"testing"
	"time"
)

var t0 = time.Date(2026, 10, 7, 12, 0, 0, 0, time.UTC)

func listOf(aliases ...string) []GarageBucket {
	list := make([]GarageBucket, 0, len(aliases))
	for i, alias := range aliases {
		list = append(list, GarageBucket{ID: fmt.Sprintf("id%d", i), GlobalAliases: []string{alias}})
	}
	return list
}

// readAll reads n times, a second apart from `start`, returning the reads in order.
func readAll(s *State, start time.Time, n int) []string {
	var reads []string
	for i := 0; i < n; i++ {
		now := start.Add(time.Duration(i) * time.Second)
		alias, _ := s.Next(now)
		s.Read(alias, 1, now)
		reads = append(reads, alias)
	}
	return reads
}

func TestTheBucketListAddsDropsAndIgnores(t *testing.T) {
	s := NewState()
	s.SetBuckets(listOf("dep-a", "dep-b", "artifacts"))
	s.Read("dep-a", 7, t0)
	s.SetBuckets(listOf("dep-a", "dep-c", "artifacts"))

	snap := s.Snapshot()
	if snap.Buckets != 2 {
		t.Fatalf("buckets = %d, want dep-a and dep-c", snap.Buckets)
	}
	if snap.Sizes["dep-a"] != 7 {
		t.Error("a refresh forgot a size")
	}
	if _, ok := snap.Sizes["dep-c"]; ok {
		t.Error("an unread bucket published a size")
	}
}

func TestThePlatformBucketIsNeverRead(t *testing.T) {
	s := NewState()
	s.SetBuckets(listOf("artifacts", "dep-a"))
	for _, alias := range readAll(s, t0, 4) {
		if alias != "dep-a" {
			t.Fatalf("read %q", alias)
		}
	}
}

func TestReadsAlternateBetweenChangedAndLongestAgo(t *testing.T) {
	s := NewState()
	s.SetActivityOK(true)
	s.SetBuckets(listOf("dep-a", "dep-b", "dep-c", "dep-d"))
	// Every bucket read once, a..d in that order.
	readAll(s, t0, 4)
	// dep-c and dep-d keep getting written to. Changed turns take whichever of
	// them was read longest ago; the turns between take the longest-ago overall.
	start := t0.Add(time.Minute)
	var reads []string
	for i := 0; i < 6; i++ {
		now := start.Add(time.Duration(i) * time.Second)
		s.MarkWritten([]string{"dep-c", "dep-d"}, now.Add(-time.Millisecond))
		alias, _ := s.Next(now)
		s.Read(alias, 1, now)
		reads = append(reads, alias)
	}
	want := []string{"dep-c", "dep-a", "dep-d", "dep-b", "dep-c", "dep-a"}
	if fmt.Sprint(reads) != fmt.Sprint(want) {
		t.Fatalf("reads = %v, want %v", reads, want)
	}
}

func TestWithNothingChangedEveryReadIsLongestAgo(t *testing.T) {
	s := NewState()
	s.SetActivityOK(true)
	s.SetBuckets(listOf("dep-a", "dep-b", "dep-c"))
	reads := readAll(s, t0, 6)
	want := []string{"dep-a", "dep-b", "dep-c", "dep-a", "dep-b", "dep-c"}
	if fmt.Sprint(reads) != fmt.Sprint(want) {
		t.Fatalf("reads = %v, want %v", reads, want)
	}
}

func TestManyWritesNeedOneRead(t *testing.T) {
	s := NewState()
	s.SetActivityOK(true)
	s.SetBuckets(listOf("dep-a", "dep-b", "dep-c"))
	readAll(s, t0, 3)
	for i := 0; i < 100; i++ {
		s.MarkWritten([]string{"dep-b"}, t0.Add(10*time.Second+time.Duration(i)*time.Millisecond))
	}
	start := t0.Add(time.Minute)
	var changedReads []string
	reads := map[string]int{}
	for i := 0; i < 4; i++ {
		now := start.Add(time.Duration(i) * time.Second)
		alias, changed := s.Next(now)
		s.Read(alias, 1, now)
		reads[alias]++
		if changed {
			changedReads = append(changedReads, alias)
		}
	}
	if fmt.Sprint(changedReads) != "[dep-b]" {
		t.Fatalf("changed reads = %v, want dep-b once", changedReads)
	}
	if reads["dep-b"] != 1 {
		t.Fatalf("dep-b read %d times in four reads", reads["dep-b"])
	}
}

func TestWritesByGarageIDAreAttributedToTheAlias(t *testing.T) {
	s := NewState()
	s.SetActivityOK(true)
	s.SetBuckets(listOf("dep-a", "dep-b"))
	readAll(s, t0, 2)
	s.MarkWritten([]string{"id1", "unknown", "artifacts"}, t0.Add(time.Minute))
	if alias, changed := s.Next(t0.Add(2 * time.Minute)); alias != "dep-b" || !changed {
		t.Fatalf("read %q (changed %v), want dep-b by its id", alias, changed)
	}
}

func TestIdleBucketsAreNotStarved(t *testing.T) {
	const n = 50
	aliases := make([]string, n)
	for i := range aliases {
		aliases[i] = fmt.Sprintf("dep-%02d", i)
	}
	s := NewState()
	s.SetActivityOK(true)
	s.SetBuckets(listOf(aliases...))
	readAll(s, t0, n)

	// Half the buckets are written to before every single read: far more change
	// than one read a second can keep up with.
	busy := aliases[:n/2]
	last := map[string]time.Time{}
	start := t0.Add(time.Hour)
	for i := 0; i < 20*n; i++ {
		now := start.Add(time.Duration(i) * time.Second)
		s.MarkWritten(busy, now.Add(-time.Millisecond))
		alias, _ := s.Next(now)
		s.Read(alias, 1, now)
		if prev, ok := last[alias]; ok && now.Sub(prev) > 2*n*time.Second {
			t.Fatalf("%s waited %v between reads, over 2N/rate = %v", alias, now.Sub(prev), 2*n*time.Second)
		}
		last[alias] = now
	}
	end := start.Add(time.Duration(20*n) * time.Second)
	for _, alias := range aliases {
		if end.Sub(last[alias]) > 2*n*time.Second {
			t.Errorf("%s last read %v before the end", alias, end.Sub(last[alias]))
		}
	}
}

func TestABrokenSignalReadsInPlainOrder(t *testing.T) {
	s := NewState()
	s.SetActivityOK(true)
	s.SetBuckets(listOf("dep-a", "dep-b", "dep-c"))
	readAll(s, t0, 3)
	s.MarkWritten([]string{"dep-c"}, t0.Add(time.Minute))
	s.SetActivityOK(false)
	s.MarkWritten([]string{"dep-b"}, t0.Add(time.Minute))

	reads := readAll(s, t0.Add(2*time.Minute), 3)
	if fmt.Sprint(reads) != fmt.Sprint([]string{"dep-a", "dep-b", "dep-c"}) {
		t.Fatalf("reads = %v", reads)
	}
}

func TestAFailedReadMovesOn(t *testing.T) {
	s := NewState()
	s.SetBuckets(listOf("dep-a", "dep-b"))
	if alias, _ := s.Next(t0); alias != "dep-a" {
		t.Fatal(alias)
	}
	s.ReadFailed()
	if alias, _ := s.Next(t0.Add(time.Second)); alias != "dep-b" {
		t.Fatalf("retried %q instead of moving on", alias)
	}
}

func TestSeededSizesArePublishedAndReadFirst(t *testing.T) {
	s := NewState()
	s.SetBuckets(listOf("dep-a"))
	readAll(s, t0, 1)
	s.Seed(map[string]int64{"dep-a": 99, "dep-b": 5, "artifacts": 3})
	s.SetBuckets(listOf("dep-a", "dep-b"))

	snap := s.Snapshot()
	if snap.Sizes["dep-a"] != 1 || snap.Sizes["dep-b"] != 5 || len(snap.Sizes) != 2 {
		t.Fatalf("sizes = %v", snap.Sizes)
	}
	if alias, _ := s.Next(t0.Add(time.Second)); alias != "dep-b" {
		t.Fatalf("read %q first, want the recovered dep-b", alias)
	}
}
