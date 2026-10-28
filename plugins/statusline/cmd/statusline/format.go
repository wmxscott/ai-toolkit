package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
)

// number mirrors statusline.py's number(): JSON numbers and numeric strings, never booleans.
func number(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case json.Number:
		return pyFloat(string(x))
	case string:
		return pyFloat(x)
	}
	return 0, false
}

// pyFloat accepts what both float() and strconv.ParseFloat do; Python has no hex floats.
func pyFloat(s string) (float64, bool) {
	s = strings.TrimSpace(s)
	if s == "" || strings.ContainsAny(s, "xX") {
		return 0, false
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil && !errors.Is(err, strconv.ErrRange) {
		return 0, false
	}
	return f, true
}

// pyFixed formats like Python's f"{x:.{prec}f}".
func pyFixed(x float64, prec int) string {
	switch {
	case math.IsNaN(x):
		return "nan"
	case math.IsInf(x, 1):
		return "inf"
	case math.IsInf(x, -1):
		return "-inf"
	}
	return strconv.FormatFloat(x, 'f', prec, 64)
}

func pctColor(p *palette, pct float64) string {
	switch {
	case pct < 60:
		return p[barOK]
	case pct < 85:
		return p[barWarn]
	}
	return p[barCrit]
}

// progressCircle fails where Python's round() raises: on NaN and infinities.
func progressCircle(p *palette, pct float64) (string, error) {
	x := math.RoundToEven(pct / 100 * float64(len(circles)-1))
	if math.IsNaN(x) || math.IsInf(x, 0) {
		return "", fmt.Errorf("cannot round %v", pct)
	}
	idx := int(max(0, min(float64(len(circles)-1), x)))
	return pctColor(p, pct) + circles[idx] + reset, nil
}

func fmtTokens(n int64) string {
	switch {
	case n >= 1_000_000:
		return pyFixed(float64(n)/1_000_000, 1) + "M"
	case n >= 1_000:
		return pyFixed(float64(n)/1_000, 0) + "k"
	}
	return strconv.FormatInt(n, 10)
}

func fmtCost(usd float64) string {
	switch {
	case usd < 0.001:
		return "$0"
	case usd < 1:
		return "$" + pyFixed(usd, 3)
	}
	return "$" + pyFixed(usd, 2)
}

// floorDivmod is Python's divmod for a positive divisor.
func floorDivmod(a, b int64) (int64, int64) {
	q, r := a/b, a%b
	if r < 0 {
		q, r = q-1, r+b
	}
	return q, r
}

func fmtDuration(seconds int64) string {
	h, rest := floorDivmod(seconds, 3600)
	m, s := floorDivmod(rest, 60)
	if h != 0 {
		return fmt.Sprintf("%dh %02dm", h, m)
	}
	return fmt.Sprintf("%dm %02ds", m, s)
}
