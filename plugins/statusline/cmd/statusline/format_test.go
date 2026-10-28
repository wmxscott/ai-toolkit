package main

import (
	"encoding/json"
	"math"
	"testing"
)

func TestNumber(t *testing.T) {
	inf := math.Inf(1)
	tests := []struct {
		in   any
		want float64
		ok   bool
	}{
		{42.0, 42, true},
		{-0.5, -0.5, true},
		{json.Number("1e3"), 1000, true},
		{json.Number("12"), 12, true},
		{"50", 50, true},
		{" 42.5\n", 42.5, true},
		{"\t+7\r\v\f", 7, true},
		{" 5　", 5, true},
		{"\u00855", 5, true},
		{"1_000", 1000, true},
		{"1_0.2_5", 10.25, true},
		{"1e1_0", 1e10, true},
		{".5", 0.5, true},
		{"5.", 5, true},
		{"1.e5", 1e5, true},
		{"1E5", 1e5, true},
		{"-.5e-1", -0.05, true},
		{"007", 7, true},
		{"inf", inf, true},
		{"-Infinity", -inf, true},
		{"+iNf", inf, true},
		{"1e400", inf, true},
		{"-1e400", -inf, true},
		{"1e-400", 0, true},
		{true, 0, false},
		{false, 0, false},
		{nil, 0, false},
		{[]any{1.0}, 0, false},
		{map[string]any{}, 0, false},
		{"", 0, false},
		{" ", 0, false},
		{"n/a", 0, false},
		{"1__0", 0, false},
		{"_1", 0, false},
		{"1_", 0, false},
		{"1_.5", 0, false},
		{"1._5", 0, false},
		{"1_e5", 0, false},
		{"in_f", 0, false},
		{"infinit", 0, false},
		{"0x10", 0, false},
		{".", 0, false},
		{"e5", 0, false},
		{"1e", 0, false},
		{"1e+", 0, false},
		{"+-5", 0, false},
		{"1,5", 0, false},
		{"1 5", 0, false},
		{"5\x00", 0, false},
		{"\x7f5", 0, false},
		{"\x1c5", 0, false},
		{"5\x1f", 0, false},
		{"½", 0, false},
		{"⅕", 0, false},
	}
	for _, tt := range tests {
		got, ok := number(tt.in)
		if ok != tt.ok || (ok && got != tt.want) || (ok && math.Signbit(got) != math.Signbit(tt.want)) {
			t.Errorf("number(%#v) = %v, %v; want %v, %v", tt.in, got, ok, tt.want, tt.ok)
		}
	}
	for _, s := range []string{"nan", " NaN "} {
		if got, ok := number(s); !ok || !math.IsNaN(got) {
			t.Errorf("number(%q) = %v, %v; want NaN, true", s, got, ok)
		}
	}

	// Python's float() reads these, but Claude Code sends JSON numbers, so Go doesn't.
	for _, s := range []string{
		"١٢", "\U0001D7D9", "١_٠", "-NaN", "+nan",
	} {
		if got, ok := number(s); ok {
			t.Errorf("number(%q) = %v, true; want false", s, got)
		}
	}
}

func TestPyFixed(t *testing.T) {
	tests := []struct {
		x    float64
		prec int
		want string
	}{
		{0.5, 0, "0"},
		{1.5, 0, "2"},
		{2.5, 0, "2"},
		{-0.5, 0, "-0"},
		{-0.4, 0, "-0"},
		{59.5, 0, "60"},
		{58.5, 0, "58"},
		{84.5, 0, "84"},
		{2.675, 2, "2.67"},
		{1.005, 2, "1.00"},
		{0.0015, 3, "0.002"},
		{1.05, 1, "1.1"},
		{1.25, 1, "1.2"},
		{math.Inf(1), 0, "inf"},
		{math.Inf(-1), 2, "-inf"},
		{math.NaN(), 0, "nan"},
		{math.Copysign(math.NaN(), -1), 0, "nan"},
	}
	for _, tt := range tests {
		if got := pyFixed(tt.x, tt.prec); got != tt.want {
			t.Errorf("pyFixed(%v, %d) = %q, want %q", tt.x, tt.prec, got, tt.want)
		}
	}
}

func TestFmtTokens(t *testing.T) {
	tests := []struct {
		n    int64
		want string
	}{
		{0, "0"},
		{999, "999"},
		{1000, "1k"},
		{1499, "1k"},
		{1500, "2k"},
		{2500, "2k"},
		{3500, "4k"},
		{84000, "84k"},
		{999_499, "999k"},
		{999_500, "1000k"},
		{1_000_000, "1.0M"},
		{1_050_000, "1.1M"},
		{1_250_000, "1.2M"},
		{1_500_000, "1.5M"},
		{-5, "-5"},
	}
	for _, tt := range tests {
		if got := fmtTokens(tt.n); got != tt.want {
			t.Errorf("fmtTokens(%d) = %q, want %q", tt.n, got, tt.want)
		}
	}
}

func TestFmtCost(t *testing.T) {
	tests := []struct {
		usd  float64
		want string
	}{
		{0, "$0"},
		{-5, "$0"},
		{0.0005, "$0"},
		{0.000999, "$0"},
		{0.001, "$0.001"},
		{0.0015, "$0.002"},
		{0.0421, "$0.042"},
		{0.9995, "$1.000"},
		{0.99949, "$0.999"},
		{1, "$1.00"},
		{1.005, "$1.00"},
		{1.234, "$1.23"},
		{2.675, "$2.67"},
		{math.Inf(1), "$inf"},
		{math.NaN(), "$nan"},
	}
	for _, tt := range tests {
		if got := fmtCost(tt.usd); got != tt.want {
			t.Errorf("fmtCost(%v) = %q, want %q", tt.usd, got, tt.want)
		}
	}
}

func TestFmtDuration(t *testing.T) {
	tests := []struct {
		seconds int64
		want    string
	}{
		{0, "0m 00s"},
		{59, "0m 59s"},
		{125, "2m 05s"},
		{3600, "1h 00m"},
		{3*3600 + 7*60, "3h 07m"},
		{100*3600 + 59*60 + 59, "100h 59m"},
		{-5, "-1h 59m"},
		{-3600, "-1h 00m"},
		{-3601, "-2h 59m"},
	}
	for _, tt := range tests {
		if got := fmtDuration(tt.seconds); got != tt.want {
			t.Errorf("fmtDuration(%d) = %q, want %q", tt.seconds, got, tt.want)
		}
	}
}

func TestPctColor(t *testing.T) {
	tests := []struct {
		pct  float64
		want colour
	}{
		{-1, barOK},
		{0, barOK},
		{59.99, barOK},
		{60, barWarn},
		{84.99, barWarn},
		{85, barCrit},
		{100, barCrit},
		{math.NaN(), barCrit},
	}
	for _, tt := range tests {
		if got := pctColor(&dark, tt.pct); got != dark[tt.want] {
			t.Errorf("pctColor(%v) = %q, want %q", tt.pct, got, dark[tt.want])
		}
	}
}

func TestProgressCircle(t *testing.T) {
	tests := []struct {
		pct    float64
		colour colour
		circle int
	}{
		{0, barOK, 0},
		{12.5, barOK, 0},
		{37.5, barOK, 2},
		{59, barOK, 2},
		{60, barWarn, 2},
		{62.5, barWarn, 2},
		{84.99, barWarn, 3},
		{85, barCrit, 3},
		{87.5, barCrit, 4},
		{100, barCrit, 4},
		{-50, barOK, 0},
		{1000, barCrit, 4},
		{math.MaxFloat64, barCrit, 4},
	}
	for _, tt := range tests {
		got, err := progressCircle(&light, tt.pct)
		want := light[tt.colour] + circles[tt.circle] + reset
		if err != nil || got != want {
			t.Errorf("progressCircle(%v) = %q, %v; want %q", tt.pct, got, err, want)
		}
	}
	for _, pct := range []float64{math.NaN(), math.Inf(1), math.Inf(-1)} {
		if _, err := progressCircle(&light, pct); err == nil {
			t.Errorf("progressCircle(%v) succeeded; Python raises", pct)
		}
	}
}
