package main

import (
	"encoding/json"
	"math"
	"testing"
	"time"
)

func TestFmtResets(t *testing.T) {
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	epoch := time.Unix(0, 0)
	ts := float64(now.Unix())
	tests := []struct {
		value any
		now   time.Time
		want  string
	}{
		{ts + 2*3600 + 5*60, now, "2h 05m"},
		{(ts + 45*60) * 1000, now, "45m"},
		{"2026-01-01T13:30:00Z", now, "1h 30m"},
		{"2026-01-01T12:10:00", now, "10m"},
		{ts - 60, now, "now"},
		{"soon", now, "?"},
		{math.Inf(1), now, "?"},
		{math.Inf(-1), now, "?"},
		{math.NaN(), now, "?"},
		{true, now, "now"},
		{json.Number("1767269400"), now, "10m"},
		{json.Number("1e400"), now, "?"},
		{"2026-01-01T15:05:30.5+02:00", now, "1h 05m"},
		{"2026-01-01T12:00:59.9999999Z", now, "0m"},

		// Fractions round to the microsecond, half to even, before the subtraction.
		{59.9999999, epoch, "1m"},
		{59.99999949, epoch, "0m"},

		// Milliseconds from 1e10; Python's datetime range is years 1 to 9999.
		{1e10, now, "now"},
		{9999999999.0, now, "2286869h 46m"},
		{-62135596800.0, now, "now"},
		{-62135596801.0, now, "?"},
		{253402300799999.0, now, "69898619h 59m"},
		{253402300800000.0, now, "?"},

		// ISO 8601 extended date-times, as Python's fromisoformat reads them.
		{"2026-01-01 12:30:00", now, "30m"},
		{"2026-01-01T12:30:00Z", now, "30m"},
		{"2026-01-01T13:00:00.5", now, "1h 00m"},
		{"2026-01-01T13:00:00-23:59", now, "24h 59m"},
		{"2026-01-01T13:00:00.1234567-00:30", now, "1h 30m"},
		{"9999-12-31T23:59:59-23:59", now, "69898643h 58m"},
		{"0001-01-01T00:00:00+01:00", now, "now"},
		{"2026-01-01T", now, "?"},
		{"2026-02-29T00:00:00", now, "?"},
		{"0000-01-01T00:00:00", now, "?"},
		{"2026-01-01T24:00:00", now, "?"},
		{"2026-01-01T13:00:60", now, "?"},
		{"2026-01-01T13:00:00+24:00", now, "?"},
		{"2026-01-01T13:00:00.1x", now, "?"},
		{"2026-1-1T13:00:00", now, "?"},
		{"\u0662026-01-01T13:00:00", now, "?"},
		{"", now, "?"},

		// Python reads these too, but Claude Code sends numbers, so Go doesn't.
		{"2026-W01-4T12:30", now, "?"},
		{"20260101T1230Z", now, "?"},
		{"2026-01-01T12:30", now, "?"},
		{"2026-01-01t13:00:00", now, "?"},
		{"2026-01-01\u00e912:30:00", now, "?"},
		{"2026-01-01T13:00:00+0100", now, "?"},

		{[]any{1.0}, now, "?"},
		{map[string]any{}, now, "?"},
		{nil, now, "?"},
	}
	for _, tt := range tests {
		if got := fmtResets(tt.value, tt.now); got != tt.want {
			t.Errorf("fmtResets(%#v) = %q, want %q", tt.value, got, tt.want)
		}
	}
}
