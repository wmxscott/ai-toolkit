package main

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const appearanceTTL = 5 * time.Second

type themeSource struct {
	home       string
	cacheDir   string
	appearance func() (string, error)
	now        time.Time
}

func knownTheme(s string) (string, bool) {
	s = strings.ToLower(strings.TrimSpace(s))
	return s, s == "dark" || s == "light"
}

func detectTheme(src themeSource) string {
	if t, ok := knownTheme(os.Getenv("CLAUDE_STATUSLINE_THEME")); ok {
		return t
	}
	trigger := strings.TrimRight(src.home, "/") + "/.local/share/theme-monitor/theme-change.trigger"
	if b, err := os.ReadFile(trigger); err == nil {
		if t, ok := knownTheme(string(b)); ok {
			return t
		}
	}
	if src.appearance != nil {
		if t, ok := cachedAppearance(src); ok {
			return t
		}
	}
	return "dark"
}

func cachedAppearance(src themeSource) (string, bool) {
	path := filepath.Join(src.cacheDir, "appearance")
	if src.cacheDir != "" {
		if info, err := os.Stat(path); err == nil {
			if age := src.now.Sub(info.ModTime()); age >= 0 && age < appearanceTTL {
				if b, err := os.ReadFile(path); err == nil && (string(b) == "dark" || string(b) == "light") {
					return string(b), true
				}
			}
		}
	}
	t, err := src.appearance()
	if err != nil {
		return "", false
	}
	if src.cacheDir != "" {
		writeAtomic(path, t)
	}
	return t, true
}

func writeAtomic(path, content string) {
	if os.MkdirAll(filepath.Dir(path), 0o755) != nil {
		return
	}
	f, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*")
	if err != nil {
		return
	}
	_, err = f.WriteString(content)
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err == nil {
		err = os.Rename(f.Name(), path)
	}
	if err != nil {
		os.Remove(f.Name())
	}
}

// readAppearance runs `defaults` (or a stand-in) and fails only when it cannot run.
func readAppearance(cmd string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, cmd, "read", "-g", "AppleInterfaceStyle").Output()
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	// The key only exists in dark mode, so a failed read means light.
	var exit *exec.ExitError
	if err != nil && !errors.As(err, &exit) {
		return "", err
	}
	if err == nil && strings.TrimSpace(string(out)) == "Dark" {
		return "dark", nil
	}
	return "light", nil
}
