package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

var realGit, python string

func TestMain(m *testing.M) {
	if os.Getenv("STATUSLINE_TEST_MAIN") == "1" {
		main()
		os.Exit(0)
	}
	for _, k := range []string{"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES"} {
		os.Unsetenv(k)
	}
	for k, v := range map[string]string{
		"GIT_CONFIG_GLOBAL": os.DevNull, "GIT_CONFIG_NOSYSTEM": "1",
		"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
		"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
	} {
		os.Setenv(k, v)
	}
	realGit, _ = exec.LookPath("git")
	python, _ = exec.LookPath("python3")
	os.Exit(m.Run())
}

func git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	if realGit == "" {
		t.Skip("git is not installed")
	}
	cmd := exec.Command(realGit, args...)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func tempDir(t *testing.T) string {
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

// newRepo makes <tmp>/<name> with one commit on main holding a.txt.
func newRepo(t *testing.T, name string) string {
	root := filepath.Join(tempDir(t), name)
	write(t, filepath.Join(root, "a.txt"), "one\ntwo\n")
	git(t, root, "init", "-q", "-b", "main")
	git(t, root, "add", ".")
	git(t, root, "commit", "-qm", "init")
	return root
}

type gitCase struct {
	name  string
	setup func(t *testing.T) (cwd string, want *gitDetails)
}

var gitCases = []gitCase{
	{"changes", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		write(t, filepath.Join(root, "a.txt"), "one\nthree\nfour\n")
		write(t, filepath.Join(root, "b.txt"), "x\ny\n")
		git(t, root, "add", "b.txt")
		write(t, filepath.Join(root, "new.txt"), "1\n2\n3\n4\n")
		write(t, filepath.Join(root, "café menu.txt"), "a\n")
		write(t, filepath.Join(root, ".gitignore"), "*.log\n")
		write(t, filepath.Join(root, "debug.log"), "x\nx\n")
		write(t, filepath.Join(root, "big.txt"), strings.Repeat("\n", maxUntrackedBytes+1))
		return root, &gitDetails{repo: "project", branch: "main", added: 2 + 2 + 4 + 1 + 1, deleted: 1}
	}},
	{"subdirectory", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		write(t, filepath.Join(root, "src", "lib", "deep.txt"), "c\n")
		return filepath.Join(root, "src", "lib"), &gitDetails{repo: "project", branch: "main", rel: "src/lib", added: 1}
	}},
	{"symlinked-cwd", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		write(t, filepath.Join(root, "src", "x.txt"), "x\n")
		link := filepath.Join(tempDir(t), "link")
		if err := os.Symlink(filepath.Join(root, "src"), link); err != nil {
			t.Fatal(err)
		}
		return link, &gitDetails{repo: "project", branch: "main", rel: "src", added: 1}
	}},
	{"detached", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		git(t, root, "checkout", "-q", "--detach")
		return root, &gitDetails{repo: "project", branch: git(t, root, "rev-parse", "--short", "HEAD")}
	}},
	{"detached-core-abbrev", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		git(t, root, "config", "core.abbrev", "10")
		git(t, root, "checkout", "-q", "--detach")
		short := git(t, root, "rev-parse", "--short", "HEAD")
		if len(short) != 10 {
			t.Fatalf("git abbreviated to %q", short)
		}
		return root, &gitDetails{repo: "project", branch: short}
	}},
	{"no-commits", func(t *testing.T) (string, *gitDetails) {
		root := filepath.Join(tempDir(t), "fresh")
		write(t, filepath.Join(root, "x.txt"), "1\n2\n")
		git(t, root, "init", "-q", "-b", "trunk")
		return root, &gitDetails{repo: "fresh", branch: "trunk", added: 2}
	}},
	{"linked-worktree", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		wt := filepath.Join(filepath.Dir(root), "feature-wt")
		git(t, root, "worktree", "add", "-q", "-b", "feature", wt)
		write(t, filepath.Join(wt, "a.txt"), "one\n")
		write(t, filepath.Join(wt, "sub", "n.txt"), "n\n")
		return filepath.Join(wt, "sub"), &gitDetails{repo: "feature-wt", branch: "feature", rel: "sub", added: 1, deleted: 1}
	}},
	{"bare-repo-worktree", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		bare := filepath.Join(filepath.Dir(root), ".bare")
		git(t, root, "clone", "-q", "--bare", root, bare)
		wt := filepath.Join(filepath.Dir(root), "topic")
		git(t, bare, "worktree", "add", "-q", "-b", "topic", wt)
		git(t, bare, "config", "core.abbrev", "9")
		git(t, wt, "checkout", "-q", "--detach")
		write(t, filepath.Join(wt, "u.txt"), "u\n")
		short := git(t, wt, "rev-parse", "--short", "HEAD")
		if len(short) != 9 {
			t.Fatalf("git abbreviated to %q", short)
		}
		return wt, &gitDetails{repo: "topic", branch: short, added: 1}
	}},
	{"submodule", func(t *testing.T) (string, *gitDetails) {
		lib := newRepo(t, "lib")
		root := newRepo(t, "project")
		git(t, root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", lib, "vendor/lib")
		mod := filepath.Join(root, "vendor", "lib")
		write(t, filepath.Join(mod, "m.txt"), "m\nm\n")
		return mod, &gitDetails{repo: "lib", branch: "main", added: 2}
	}},
	{"git-dir-env", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		write(t, filepath.Join(root, "src", "s.txt"), "s\n")
		t.Setenv("GIT_DIR", filepath.Join(root, ".git"))
		t.Setenv("GIT_WORK_TREE", root)
		return filepath.Join(root, "src"), &gitDetails{repo: "project", branch: "main", rel: "src", added: 1}
	}},
	{"git-dir-env-detached", func(t *testing.T) (string, *gitDetails) {
		root := newRepo(t, "project")
		git(t, root, "checkout", "-q", "--detach")
		t.Setenv("GIT_DIR", filepath.Join(root, ".git"))
		return root, &gitDetails{repo: "project", branch: git(t, root, "rev-parse", "--short", "HEAD")}
	}},
	{"git-dir-env-no-commits", func(t *testing.T) (string, *gitDetails) {
		root := filepath.Join(tempDir(t), "fresh")
		write(t, filepath.Join(root, "x.txt"), "1\n")
		git(t, root, "init", "-q", "-b", "trunk")
		t.Setenv("GIT_DIR", filepath.Join(root, ".git"))
		return root, &gitDetails{repo: "fresh", branch: "trunk", added: 1}
	}},
	{"bad-gitfile", func(t *testing.T) (string, *gitDetails) {
		root := filepath.Join(tempDir(t), "broken")
		write(t, filepath.Join(root, ".git"), "not a gitfile\n")
		return root, nil
	}},
	{"not-a-repo", func(t *testing.T) (string, *gitDetails) {
		return tempDir(t), nil
	}},
	{"missing-dir", func(t *testing.T) (string, *gitDetails) {
		return filepath.Join(tempDir(t), "gone"), nil
	}},
}

func TestGitInfo(t *testing.T) {
	for _, tc := range gitCases {
		t.Run(tc.name, func(t *testing.T) {
			cwd, want := tc.setup(t)
			got := gitInfo(cwd, "", time.Time{})
			if (got == nil) != (want == nil) || got != nil && *got != *want {
				t.Errorf("gitInfo = %+v, want %+v", got, want)
			}
		})
	}
}

// TestLine1MatchesPython runs statusline.py on the same repositories.
func TestLine1MatchesPython(t *testing.T) {
	if python == "" {
		t.Skip("python3 is not installed")
	}
	for _, tc := range gitCases {
		t.Run(tc.name, func(t *testing.T) {
			cwd, _ := tc.setup(t)
			in := `{"cwd": "` + cwd + `"}`
			cmd := exec.Command(python, "../../scripts/statusline.py")
			cmd.Stdin = strings.NewReader(in)
			cmd.Env = append(os.Environ(), "CLAUDE_STATUSLINE_THEME=dark")
			want, err := cmd.Output()
			if err != nil {
				t.Fatal(err)
			}
			got := render(parseInput([]byte(in)), &dark, env{home: os.Getenv("HOME")})
			if got != string(want) {
				t.Errorf("render mismatch\n got: %q\nwant: %q", got, want)
			}
		})
	}
}

func TestCountLines(t *testing.T) {
	dir := tempDir(t)
	write(t, filepath.Join(dir, "three"), "a\nb\nc")
	write(t, filepath.Join(dir, "big"), string(bytes.Repeat([]byte("\n"), maxUntrackedBytes+1)))
	write(t, filepath.Join(dir, "limit"), string(bytes.Repeat([]byte("\n"), maxUntrackedBytes)))
	os.Mkdir(filepath.Join(dir, "d"), 0o755)
	if got := countLines(dir, []string{"three", "big", "limit", "d", "missing", ""}); got != 2+maxUntrackedBytes {
		t.Errorf("countLines = %d", got)
	}
}

// gitShim puts a logging git first on PATH and returns the log's path.
func gitShim(t *testing.T, extra string) string {
	if realGit == "" {
		t.Skip("git is not installed")
	}
	dir := tempDir(t)
	log := filepath.Join(dir, "calls.log")
	write(t, filepath.Join(dir, "bin", "git"), "#!/bin/sh\necho \"$GIT_OPTIONAL_LOCKS:$*\" >> '"+log+"'\n"+extra+"exec '"+realGit+"' \"$@\"\n")
	os.Chmod(filepath.Join(dir, "bin", "git"), 0o755)
	t.Setenv("PATH", filepath.Join(dir, "bin")+string(os.PathListSeparator)+os.Getenv("PATH"))
	return log
}

func calls(t *testing.T, log string) []string {
	b, err := os.ReadFile(log)
	if os.IsNotExist(err) {
		return nil
	} else if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSpace(string(b)), "\n")
}

func TestReadingGitStartsOnlyTheCountCommands(t *testing.T) {
	root := newRepo(t, "project")
	log := gitShim(t, "")
	if gi := gitInfo(root, "", time.Time{}); gi == nil || gi.branch != "main" {
		t.Fatalf("gitInfo = %+v", gi)
	}
	want := []string{"0:diff --shortstat HEAD", "0:ls-files -z --others --exclude-standard"}
	if got := calls(t, log); strings.Join(got, "|") != strings.Join(want, "|") {
		t.Errorf("git calls = %q, want %q", got, want)
	}
}
