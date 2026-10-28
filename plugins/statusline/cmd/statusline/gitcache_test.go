package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type cacheFixture struct {
	root, cache, log string
	now              time.Time
}

// newCacheFixture is a repo with one untracked line and a logging git on PATH.
func newCacheFixture(t *testing.T) *cacheFixture {
	root := newRepo(t, "project")
	write(t, filepath.Join(root, "u.txt"), "u\n")
	return &cacheFixture{root: root, cache: filepath.Join(tempDir(t), "cache"), log: gitShim(t, ""), now: time.Now()}
}

// counts runs gitInfo at f.now+offset and reports how many git processes it started.
func (f *cacheFixture) counts(t *testing.T, offset time.Duration) (added, gitCalls int) {
	t.Helper()
	before := len(calls(t, f.log))
	gi := gitInfo(f.root, f.cache, f.now.Add(offset))
	if gi == nil {
		t.Fatal("gitInfo = nil")
	}
	return gi.added, len(calls(t, f.log)) - before
}

func (f *cacheFixture) expect(t *testing.T, offset time.Duration, added, gitCalls int) {
	t.Helper()
	if a, n := f.counts(t, offset); a != added || n != gitCalls {
		t.Errorf("at +%v: added %d with %d git calls, want %d with %d", offset, a, n, added, gitCalls)
	}
}

func touch(t *testing.T, path string, offset time.Duration) {
	at := time.Now().Add(offset)
	if err := os.Chtimes(path, at, at); err != nil {
		t.Fatal(err)
	}
}

func TestCountsCacheIsReusedWhileFresh(t *testing.T) {
	f := newCacheFixture(t)
	f.expect(t, 0, 1, 2)
	write(t, filepath.Join(f.root, "v.txt"), "v\n")
	f.expect(t, 4900*time.Millisecond, 1, 0)
	f.expect(t, 5*time.Second, 2, 2)
	f.expect(t, 5*time.Second, 2, 0)
	f.expect(t, 4*time.Second, 2, 2)
}

func TestCountsCacheRefreshesWhenHeadOrIndexChanges(t *testing.T) {
	for _, name := range []string{"HEAD", "index"} {
		t.Run(name, func(t *testing.T) {
			f := newCacheFixture(t)
			f.expect(t, 0, 1, 2)
			write(t, filepath.Join(f.root, "v.txt"), "v\n")
			touch(t, filepath.Join(f.root, ".git", name), time.Second)
			f.expect(t, 0, 2, 2)
			f.expect(t, 0, 2, 0)
		})
	}
}

func TestCountsCacheServesStaleCountsWhileLocked(t *testing.T) {
	f := newCacheFixture(t)
	f.expect(t, 0, 1, 2)
	write(t, filepath.Join(f.root, "v.txt"), "v\n")
	lock := countsPath(f.cache, f.root) + ".lock"
	write(t, lock, "")
	f.expect(t, 6*time.Second, 1, 0)

	touch(t, lock, -11*time.Second)
	f.expect(t, 6*time.Second, 2, 2)
	if _, err := os.Stat(lock); !os.IsNotExist(err) {
		t.Errorf("lock left behind: %v", err)
	}
}

func TestCountsCacheLockedWithNoCountsYet(t *testing.T) {
	f := newCacheFixture(t)
	write(t, countsPath(f.cache, f.root)+".lock", "")
	f.expect(t, 0, 0, 0)
}

func TestCountsWithoutAUsableCacheDir(t *testing.T) {
	f := newCacheFixture(t)
	write(t, f.cache, "a file, not a directory")
	f.expect(t, 0, 1, 2)
	f.expect(t, 0, 1, 2)

	f.cache = ""
	f.expect(t, 0, 1, 2)
}

// runMain runs this test binary as the statusline in cwd.
func runMain(cwd string, extraEnv ...string) *exec.Cmd {
	cmd := exec.Command(os.Args[0], "-test.run=^$")
	cmd.Stdin = strings.NewReader(`{"cwd": "` + cwd + `"}`)
	cmd.Env = append(os.Environ(), append([]string{"STATUSLINE_TEST_MAIN=1", "CLAUDE_STATUSLINE_THEME=dark"}, extraEnv...)...)
	return cmd
}

func userCache(t *testing.T) string {
	home := tempDir(t)
	t.Setenv("HOME", home)
	t.Setenv("XDG_CACHE_HOME", filepath.Join(home, ".cache"))
	dir, err := os.UserCacheDir()
	if err != nil {
		t.Fatal(err)
	}
	return filepath.Join(dir, "ai-toolkit-statusline")
}

func TestBinaryStartsNoGitWhenTheCacheIsFresh(t *testing.T) {
	cache := userCache(t)
	root := newRepo(t, "project")
	write(t, filepath.Join(root, "u.txt"), "u\n")
	log := gitShim(t, "")

	first, err := runMain(root).Output()
	if err != nil || !strings.Contains(string(first), "+1") {
		t.Fatalf("first run: %q, %v", first, err)
	}
	if n := len(calls(t, log)); n != 2 {
		t.Fatalf("first run started %d git processes, want 2", n)
	}
	if _, err := os.Stat(countsPath(cache, root)); err != nil {
		t.Fatalf("no cache written: %v", err)
	}
	second, err := runMain(root).Output()
	if err != nil || string(second) != string(first) {
		t.Fatalf("second run: %q, %v; want %q", second, err, first)
	}
	if got := calls(t, log); len(got) != 2 {
		t.Errorf("second run started git: %q", got[2:])
	}
}

func TestKilledRefreshLeavesTheOldCache(t *testing.T) {
	cache := userCache(t)
	root := newRepo(t, "project")
	write(t, filepath.Join(root, "u.txt"), "u\n")
	log := gitShim(t, `[ "$1" = diff ] && [ -n "$GIT_SHIM_SLEEP" ] && sleep "$GIT_SHIM_SLEEP"`+"\n")
	if err := runMain(root).Run(); err != nil {
		t.Fatal(err)
	}
	path := countsPath(cache, root)
	old, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	write(t, filepath.Join(root, "v.txt"), "v\n")
	touch(t, filepath.Join(root, ".git", "index"), time.Second)
	cmd := runMain(root, "GIT_SHIM_SLEEP=5")
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(3 * time.Second); len(calls(t, log)) < 3; time.Sleep(10 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatal("refresh never started git")
		}
	}
	cmd.Process.Kill()
	cmd.Wait()

	if now, err := os.ReadFile(path); err != nil || string(now) != string(old) {
		t.Errorf("cache after a killed refresh = %q, %v; want %q", now, err, old)
	}
	if out, _ := runMain(root).Output(); !strings.Contains(string(out), "+1") || len(calls(t, log)) != 3 {
		t.Errorf("while the dead run's lock is fresh: %q, git calls %q", out, calls(t, log))
	}
	touch(t, path+".lock", -11*time.Second)
	if out, _ := runMain(root).Output(); !strings.Contains(string(out), "+2") {
		t.Errorf("after the lock went stale: %q", out)
	}
}
