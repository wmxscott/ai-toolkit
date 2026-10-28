package main

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestDetectTheme(t *testing.T) {
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	tests := []struct {
		name       string
		env        string
		trigger    *string
		appearance func() (string, error)
		want       string
		calls      int
	}{
		{name: "override wins", env: " Light\n", trigger: ptr("dark"), want: "light"},
		{name: "unknown override falls through", env: "blue", trigger: ptr("light"), want: "light"},
		{name: "trigger", trigger: ptr("  DARK\n"), appearance: answer("light", nil), want: "dark"},
		{name: "unknown trigger falls through", trigger: ptr("auto"), appearance: answer("light", nil), want: "light", calls: 1},
		{name: "appearance", appearance: answer("light", nil), want: "light", calls: 1},
		{name: "appearance fails", appearance: answer("", errors.New("no defaults")), want: "dark", calls: 1},
		{name: "not macOS", want: "dark"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("CLAUDE_STATUSLINE_THEME", tt.env)
			home := t.TempDir()
			if tt.trigger != nil {
				writeFile(t, filepath.Join(home, ".local/share/theme-monitor/theme-change.trigger"), *tt.trigger)
			}
			calls := 0
			var appearance func() (string, error)
			if tt.appearance != nil {
				appearance = func() (string, error) { calls++; return tt.appearance() }
			}
			src := themeSource{home: home, cacheDir: filepath.Join(t.TempDir(), "cache"), appearance: appearance, now: now}
			if got := detectTheme(src); got != tt.want {
				t.Errorf("detectTheme = %q, want %q", got, tt.want)
			}
			if calls != tt.calls {
				t.Errorf("appearance called %d times, want %d", calls, tt.calls)
			}
		})
	}
}

func TestAppearanceCache(t *testing.T) {
	t.Setenv("CLAUDE_STATUSLINE_THEME", "")
	now := time.Now()
	cacheDir := filepath.Join(t.TempDir(), "ai-toolkit-statusline")
	cached := filepath.Join(cacheDir, "appearance")
	calls := 0
	reply := "light"
	src := themeSource{
		home:       t.TempDir(),
		cacheDir:   cacheDir,
		appearance: func() (string, error) { calls++; return reply, nil },
		now:        now,
	}

	if got := detectTheme(src); got != "light" || calls != 1 {
		t.Fatalf("first run: %q after %d calls", got, calls)
	}
	if b, err := os.ReadFile(cached); err != nil || string(b) != "light" {
		t.Fatalf("cache file = %q, %v", b, err)
	}
	if entries, _ := os.ReadDir(cacheDir); len(entries) != 1 {
		t.Errorf("cache dir holds %d entries, want only the cache file", len(entries))
	}

	reply = "dark"
	if err := os.Chtimes(cached, now, now.Add(-4*time.Second)); err != nil {
		t.Fatal(err)
	}
	if got := detectTheme(src); got != "light" || calls != 1 {
		t.Errorf("fresh cache: %q after %d calls, want the cached answer", got, calls)
	}

	if err := os.Chtimes(cached, now, now.Add(-5*time.Second)); err != nil {
		t.Fatal(err)
	}
	if got := detectTheme(src); got != "dark" || calls != 2 {
		t.Errorf("stale cache: %q after %d calls, want a new answer", got, calls)
	}

	writeFile(t, cached, "purple")
	if got := detectTheme(src); got != "dark" || calls != 3 {
		t.Errorf("garbage cache: %q after %d calls, want a new answer", got, calls)
	}

	src.appearance = answer("", errors.New("no defaults"))
	if err := os.Chtimes(cached, now, now.Add(-time.Minute)); err != nil {
		t.Fatal(err)
	}
	if got := detectTheme(src); got != "dark" {
		t.Errorf("failed refresh: %q", got)
	}
}

func TestAppearanceCacheUnwritable(t *testing.T) {
	t.Setenv("CLAUDE_STATUSLINE_THEME", "")
	notADir := filepath.Join(t.TempDir(), "file")
	writeFile(t, notADir, "")
	src := themeSource{home: t.TempDir(), cacheDir: filepath.Join(notADir, "cache"), appearance: answer("light", nil), now: time.Now()}
	if got := detectTheme(src); got != "light" {
		t.Errorf("detectTheme = %q, want light", got)
	}
	src.cacheDir = ""
	if got := detectTheme(src); got != "light" {
		t.Errorf("detectTheme with no cache dir = %q, want light", got)
	}
}

func TestReadAppearance(t *testing.T) {
	dir := t.TempDir()
	stub := func(name, body string) string {
		path := filepath.Join(dir, name)
		writeFile(t, path, "#!/bin/sh\n"+body+"\n")
		if err := os.Chmod(path, 0o755); err != nil {
			t.Fatal(err)
		}
		return path
	}
	tests := []struct {
		cmd     string
		want    string
		wantErr bool
	}{
		{stub("dark", `[ "$*" = "read -g AppleInterfaceStyle" ] && echo Dark`), "dark", false},
		{stub("other", "echo Light"), "light", false},
		{stub("missing-key", "echo 'does not exist' >&2; exit 1"), "light", false},
		{stub("hangs", "exec sleep 5"), "", true},
		{filepath.Join(dir, "absent"), "", true},
	}
	for _, tt := range tests {
		got, err := readAppearance(tt.cmd)
		if got != tt.want || (err != nil) != tt.wantErr {
			t.Errorf("readAppearance(%s) = %q, %v; want %q, error %v", filepath.Base(tt.cmd), got, err, tt.want, tt.wantErr)
		}
	}
}

func ptr(s string) *string { return &s }

func answer(theme string, err error) func() (string, error) {
	return func() (string, error) { return theme, err }
}
