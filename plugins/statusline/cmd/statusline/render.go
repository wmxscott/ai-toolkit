package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"
	"time"
)

type env struct {
	now  time.Time
	home string
	cwd  string
}

type gitDetails struct {
	repo, branch, rel string
	added, deleted    int
}

// parseInput returns the JSON object in b, or an empty map for anything else.
func parseInput(b []byte) map[string]any {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return map[string]any{}
	}
	if _, err := dec.Token(); err != io.EOF {
		return map[string]any{}
	}
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

func get(d any, keys ...string) any {
	for _, k := range keys {
		m, ok := d.(map[string]any)
		if !ok {
			return nil
		}
		d = m[k]
	}
	return d
}

func nonEmpty(v any) (string, bool) {
	s, ok := v.(string)
	return s, ok && s != ""
}

// toInt fails where Python's int() of a float raises.
func toInt(f float64) (int64, error) {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return 0, fmt.Errorf("cannot convert %v to integer", f)
	}
	return int64(f), nil
}

// truthy mirrors Python's truth test for a decoded JSON value.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case json.Number:
		f, _ := strconv.ParseFloat(string(x), 64)
		return f != 0
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

func separator(p *palette) string {
	return "  " + p[muted] + "·" + reset + "  "
}

func vimBadge(p *palette, mode string) string {
	m := strings.ToUpper(mode)
	c := p[silver]
	for _, v := range vimModes {
		if v.mode == m {
			c = p[v.colour]
		}
	}
	return bold + c + icoVim + " " + m + reset
}

func effortBadge(p *palette, level string) string {
	label, c := level, p[silver]
	for _, e := range efforts {
		if e.level == level {
			label, c = e.label, p[e.colour]
		}
	}
	return bold + c + icoBolt + " " + label + reset
}

func gitParts(p *palette, gi *gitDetails) []string {
	repo := bold + p[lavender] + gi.repo + reset
	if gi.rel != "" {
		repo += p[muted] + "/" + gi.rel + reset
	}
	parts := []string{bold + p[lavender] + icoGit + " " + reset + repo}
	if gi.branch != "" {
		parts = append(parts, p[gold]+icoBranch+" "+gi.branch+reset)
	}
	var changes []string
	if gi.added != 0 {
		changes = append(changes, fmt.Sprintf("%s+%d%s", p[mint], gi.added, reset))
	}
	if gi.deleted != 0 {
		changes = append(changes, fmt.Sprintf("%s-%d%s", p[barCrit], gi.deleted, reset))
	}
	if len(changes) > 0 {
		parts = append(parts, strings.Join(changes, " "))
	}
	return parts
}

func line1(d map[string]any, p *palette, e env) (string, error) {
	cwd := e.cwd
	if v, ok := nonEmpty(get(d, "workspace", "current_dir")); ok {
		cwd = v
	} else if v, ok := nonEmpty(get(d, "cwd")); ok {
		cwd = v
	}

	var parts []string
	if mode, ok := nonEmpty(get(d, "vim", "mode")); ok {
		parts = append(parts, vimBadge(p, mode))
	}

	if gi := gitInfo(cwd); gi != nil {
		parts = append(parts, gitParts(p, gi)...)
	} else {
		home := strings.TrimRight(e.home, "/")
		if home == "" {
			home = "/"
		}
		path := cwd
		if path == home || strings.HasPrefix(path, home+"/") {
			path = "~" + path[len(home):]
		}
		parts = append(parts, p[silver]+path+reset)
	}
	return strings.Join(parts, separator(p)), nil
}

func line2(d map[string]any, p *palette, _ env) (string, error) {
	name, _ := get(d, "model", "display_name").(string)
	for _, mp := range modelPrefixes {
		name = strings.ReplaceAll(name, mp[0], mp[1])
	}
	if name == "" {
		name = emDash
	}
	model := bold + p[lavender] + icoModel + " " + name + reset

	var inner []string
	if level, ok := nonEmpty(get(d, "effort", "level")); ok {
		inner = append(inner, effortBadge(p, level))
	}
	if style, ok := nonEmpty(get(d, "output_style", "name")); ok && strings.ToLower(style) != "default" {
		inner = append(inner, p[sky]+icoStyle+" "+style+reset)
	}
	modes := strings.Join(inner, p[muted]+" | "+reset)

	pct, ok := number(get(d, "context_window", "used_percentage"))
	if !ok || pct == 0 {
		pct = 0
	}
	var total int64
	if size, ok := number(get(d, "context_window", "context_window_size")); ok && size != 0 {
		var err error
		if total, err = toInt(size); err != nil {
			return "", err
		}
	}
	col := pctColor(p, pct)
	circle, err := progressCircle(p, pct)
	if err != nil {
		return "", err
	}
	ctx := col + icoDB + reset + " " + circle + " " + bold + col + pyFixed(pct, 0) + "%" + reset
	if total != 0 {
		used, err := toInt(pct / 100 * float64(total))
		if err != nil {
			return "", err
		}
		ctx += "  " + dim + "(" + fmtTokens(used) + "/" + fmtTokens(total) + ")" + reset
	}

	parts := []string{model}
	if modes != "" {
		parts = append(parts, modes)
	}
	return strings.Join(append(parts, ctx), separator(p)), nil
}

func line3(d map[string]any, p *palette, e env) (string, error) {
	var parts []string

	if resets := get(d, "rate_limits", "five_hour", "resets_at"); truthy(resets) {
		parts = append(parts, p[sky]+icoClock+" "+fmtResets(resets, e.now)+reset)
	}

	usd, hasUSD := number(get(d, "cost", "total_cost_usd"))
	session, hasSession := number(get(d, "rate_limits", "five_hour", "used_percentage"))
	if hasUSD && usd > 0 {
		s := p[mint] + icoDollar + " " + fmtCost(usd) + reset
		if hasSession {
			s += "  " + pctColor(p, session) + pyFixed(session, 0) + "% session" + reset
		}
		parts = append(parts, s)
	} else if hasSession {
		parts = append(parts, pctColor(p, session)+icoDollar+" "+pyFixed(session, 0)+"% session"+reset)
	}

	if weekly, ok := number(get(d, "rate_limits", "seven_day", "used_percentage")); ok {
		parts = append(parts, pctColor(p, weekly)+icoCal+"  "+pyFixed(weekly, 0)+"% weekly"+reset)
	}

	if len(parts) == 0 {
		if ms, ok := number(get(d, "cost", "total_duration_ms")); ok && ms != 0 {
			seconds, err := toInt(ms / 1000)
			if err != nil {
				return "", err
			}
			parts = append(parts, p[sky]+icoClock+" "+fmtDuration(seconds)+reset)
		}
	}

	return strings.Join(parts, separator(p)), nil
}

func render(d map[string]any, p *palette, e env) string {
	var out strings.Builder
	for _, line := range []func(map[string]any, *palette, env) (string, error){line1, line2, line3} {
		s, err := line(d, p, e)
		if err != nil {
			s = p[barCrit] + "statusline error: " + err.Error() + reset
		}
		if s != "" {
			out.WriteString(s + "\n")
		}
	}
	return out.String()
}
