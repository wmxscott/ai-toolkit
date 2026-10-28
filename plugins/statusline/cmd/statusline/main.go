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

	src := themeSource{home: home, now: now}
	if dir, err := os.UserCacheDir(); err == nil {
		src.cacheDir = filepath.Join(dir, "ai-toolkit-statusline")
	}
	if runtime.GOOS == "darwin" {
		src.appearance = func() (string, error) { return readAppearance("defaults") }
	}
	p, _ := paletteFor(detectTheme(src))

	os.Stdout.WriteString(render(parseInput(in), p, env{now: now, home: home, cwd: cwd}))
}
