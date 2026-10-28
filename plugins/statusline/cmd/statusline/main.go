package main

import (
	"io"
	"os"
	"path/filepath"
	"runtime"
	"time"
)

func main() {
	in, _ := io.ReadAll(os.Stdin)
	now := time.Now()
	home := os.Getenv("HOME")
	cwd, _ := os.Getwd()

	var cacheDir string
	if dir, err := os.UserCacheDir(); err == nil {
		cacheDir = filepath.Join(dir, "ai-toolkit-statusline")
	}
	src := themeSource{home: home, cacheDir: cacheDir, now: now}
	if runtime.GOOS == "darwin" {
		src.appearance = func() (string, error) { return readAppearance("defaults") }
	}
	p, _ := paletteFor(detectTheme(src))

	os.Stdout.WriteString(render(parseInput(in), p, env{now: now, home: home, cwd: cwd, cacheDir: cacheDir}))
}
