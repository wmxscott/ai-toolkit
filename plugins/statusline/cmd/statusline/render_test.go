package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

var testEnv = env{
	now:  time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC),
	home: "/u/me",
	cwd:  "/u/me/nowhere",
}

// recordedEnv reads the now, HOME and process cwd the golden files were recorded with.
func recordedEnv(t *testing.T) env {
	b, err := os.ReadFile("../../testdata/golden/README.md")
	if err != nil {
		t.Fatal(err)
	}
	var e env
	for _, line := range strings.Split(string(b), "\n") {
		key, value, ok := strings.Cut(strings.TrimPrefix(line, "- "), ": ")
		switch {
		case !ok || !strings.HasPrefix(line, "- "):
		case key == "now":
			e.now, err = time.Parse(time.RFC3339, value)
		case key == "HOME":
			e.home = value
		case strings.HasPrefix(key, "process working directory"):
			e.cwd = value
		}
	}
	if err != nil || e.now.IsZero() || e.home == "" || e.cwd == "" {
		t.Fatalf("golden README values: %+v, %v", e, err)
	}
	return e
}

func TestGolden(t *testing.T) {
	e := recordedEnv(t)
	inputs, err := filepath.Glob("../../testdata/golden/*.json")
	if err != nil || len(inputs) == 0 {
		t.Fatalf("no golden inputs: %v", err)
	}
	for _, in := range inputs {
		raw, err := os.ReadFile(in)
		if err != nil {
			t.Fatal(err)
		}
		for _, theme := range []string{"dark", "light"} {
			name := strings.TrimSuffix(filepath.Base(in), ".json") + "." + theme
			t.Run(name, func(t *testing.T) {
				want, err := os.ReadFile(strings.TrimSuffix(in, ".json") + "." + theme + ".txt")
				if err != nil {
					t.Fatal(err)
				}
				p, _ := paletteFor(theme)
				if got := render(parseInput(raw), p, e); got != string(want) {
					t.Errorf("render mismatch\n got: %q\nwant: %q", got, want)
				}
			})
		}
	}
}

func TestParseInput(t *testing.T) {
	tests := []struct {
		in   string
		want int
	}{
		{``, 0},
		{`   `, 0},
		{`not json`, 0},
		{`[1, 2]`, 0},
		{`"text"`, 0},
		{`null`, 0},
		{`{"a": 1} {"b": 2}`, 0},
		{`{"a": 1} x`, 0},
		{`{"a": NaN}`, 0},
		{"\ufeff{\"a\": 1}", 0},
		{`{"a": 1, "b": {"c": 2}}`, 2},
		{" {\"a\": 1}\n\t", 1},
	}
	for _, tt := range tests {
		if got := parseInput([]byte(tt.in)); got == nil || len(got) != tt.want {
			t.Errorf("parseInput(%q) = %v, want %d keys", tt.in, got, tt.want)
		}
	}
}

func TestGet(t *testing.T) {
	d := parseInput([]byte(`{"a": {"b": {"c": 5}}, "l": [1], "n": null}`))
	if got := get(d, "a", "b", "c"); got == nil || got.(interface{ String() string }).String() != "5" {
		t.Errorf("get(a.b.c) = %#v", got)
	}
	for _, keys := range [][]string{{"x"}, {"a", "x", "c"}, {"l", "0"}, {"n", "x"}, {"a", "b", "c", "d"}} {
		if got := get(d, keys...); got != nil {
			t.Errorf("get(%v) = %#v, want nil", keys, got)
		}
	}
}

func TestRenderReplacesAFailingLine(t *testing.T) {
	d := parseInput([]byte(`{"cwd": "/srv", "context_window": {"used_percentage": "nan"},
		"cost": {"total_duration_ms": 1000}}`))
	lines := strings.Split(render(d, &dark, testEnv), "\n")
	if len(lines) != 4 || lines[3] != "" {
		t.Fatalf("want 3 lines and a trailing newline, got %q", lines)
	}
	if lines[0] != dark[silver]+"/srv"+reset {
		t.Errorf("line 1 = %q", lines[0])
	}
	if !strings.HasPrefix(lines[1], dark[barCrit]+"statusline error: ") || !strings.HasSuffix(lines[1], reset) {
		t.Errorf("line 2 = %q, want an error line", lines[1])
	}
	if lines[2] != dark[sky]+icoClock+" 0m 01s"+reset {
		t.Errorf("line 3 = %q", lines[2])
	}
}

func TestRenderErrors(t *testing.T) {
	for _, in := range []string{
		`{"context_window": {"used_percentage": "inf"}}`,
		`{"context_window": {"context_window_size": "nan"}}`,
		`{"context_window": {"context_window_size": "-inf"}}`,
		`{"cost": {"total_duration_ms": "nan"}}`,
		`{"cost": {"total_duration_ms": "inf"}}`,
	} {
		if got := render(parseInput([]byte(in)), &dark, testEnv); !strings.Contains(got, "statusline error: ") {
			t.Errorf("render(%s) = %q, want an error line", in, got)
		}
	}
}

func TestHomePath(t *testing.T) {
	tests := []struct{ home, cwd, want string }{
		{"/u/me", "/u/me", "~"},
		{"/u/me/", "/u/me/src", "~/src"},
		{"/u/me", "/u/me2", "/u/me2"},
		{"/", "/", "~"},
		{"", "/srv", "/srv"},
		{"", "/", "~"},
	}
	for _, tt := range tests {
		e := testEnv
		e.home = tt.home
		d := map[string]any{"cwd": tt.cwd}
		if got, _ := line1(d, &dark, e); got != dark[silver]+tt.want+reset {
			t.Errorf("home %q, cwd %q: line1 = %q, want %q", tt.home, tt.cwd, got, tt.want)
		}
	}
}

func TestGitParts(t *testing.T) {
	vim := "\x1b[1m\x1b[38;2;138;173;244m NORMAL\x1b[0m  \x1b[38;2;110;115;141m·\x1b[0m  "
	repo := "\x1b[1m\x1b[38;2;183;189;248m \x1b[0m\x1b[1m\x1b[38;2;183;189;248mproject\x1b[0m"
	sep := "  \x1b[38;2;110;115;141m·\x1b[0m  "
	tests := []struct {
		gi   gitDetails
		want string
	}{
		{
			gitDetails{repo: "project", branch: "main", rel: "src/app", added: 12, deleted: 3},
			vim + repo + "\x1b[38;2;110;115;141m/src/app\x1b[0m" + sep + "\x1b[38;2;238;212;159m main\x1b[0m" +
				sep + "\x1b[38;2;166;218;149m+12\x1b[0m \x1b[38;2;237;135;150m-3\x1b[0m",
		},
		{gitDetails{repo: "project"}, vim + repo},
		{
			gitDetails{repo: "project", branch: "a1b2c3d", deleted: 7},
			vim + repo + sep + "\x1b[38;2;238;212;159m a1b2c3d\x1b[0m" + sep + "\x1b[38;2;237;135;150m-7\x1b[0m",
		},
	}
	for _, tt := range tests {
		got := strings.Join(append([]string{vimBadge(&dark, "normal")}, gitParts(&dark, &tt.gi)...), separator(&dark))
		if got != tt.want {
			t.Errorf("gitParts(%+v)\n got: %q\nwant: %q", tt.gi, got, tt.want)
		}
	}
}
