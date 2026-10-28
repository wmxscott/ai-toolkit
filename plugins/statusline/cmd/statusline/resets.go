package main

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"strconv"
	"time"
)

// Python's datetime range, 0001-01-01 to 9999-12-31T23:59:59, in Unix seconds.
const (
	minUnix = -62135596800
	maxUnix = 253402300799
)

// fmtResets ports statusline.py's fmt_resets for epoch seconds, epoch milliseconds and
// ISO 8601 extended date-times; other strings Python's fromisoformat accepts give "?".
func fmtResets(value any, now time.Time) string {
	var at int64
	var ok bool
	switch v := value.(type) {
	case bool:
		t := 0.0
		if v {
			t = 1
		}
		at, ok = fromTimestamp(t)
	case float64:
		at, ok = fromTimestamp(v)
	case json.Number:
		f, _ := strconv.ParseFloat(string(v), 64)
		at, ok = fromTimestamp(f)
	case string:
		at, ok = fromISO(v)
	}
	if !ok {
		return "?"
	}
	diff, _ := new(big.Rat).SetFrac64(at-now.UnixMicro(), 1_000_000).Float64()
	sec := int64(diff)
	if sec <= 0 {
		return "now"
	}
	h, rest := sec/3600, sec%3600
	if h != 0 {
		return fmt.Sprintf("%dh %02dm", h, rest/60)
	}
	return fmt.Sprintf("%dm", rest/60)
}

// fromTimestamp returns Unix microseconds, rounding as datetime.fromtimestamp does.
func fromTimestamp(t float64) (int64, bool) {
	if t >= 1e10 {
		t /= 1000
	}
	whole, frac := math.Modf(t)
	us := math.RoundToEven(frac * 1e6)
	if us >= 1e6 {
		us, whole = us-1e6, whole+1
	} else if us < 0 {
		us, whole = us+1e6, whole-1
	}
	if !(whole >= minUnix && whole <= maxUnix) {
		return 0, false
	}
	return int64(whole)*1_000_000 + int64(us), true
}

// fromISO accepts YYYY-MM-DD{T| }HH:MM:SS[.f], then Z, ±HH:MM or nothing (UTC),
// and returns Unix microseconds, dropping digits past the sixth as Python does.
func fromISO(s string) (int64, bool) {
	if len(s) < 19 || s[4] != '-' || s[7] != '-' || s[13] != ':' || s[16] != ':' ||
		(s[10] != 'T' && s[10] != ' ') {
		return 0, false
	}
	s = s[:10] + "T" + s[11:]
	t, err := time.Parse("2006-01-02T15:04:05Z07:00", s)
	if err != nil {
		t, err = time.Parse("2006-01-02T15:04:05", s)
	}
	if err != nil || t.Year() < 1 {
		return 0, false
	}
	if _, off := t.Zone(); off <= -86400 || off >= 86400 {
		return 0, false
	}
	return t.UnixMicro(), true
}
