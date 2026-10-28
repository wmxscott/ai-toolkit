package main

import (
	"bytes"
	"context"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const gitTimeout = 2 * time.Second

var (
	insertions = regexp.MustCompile(`(\d+) insertion`)
	deletions  = regexp.MustCompile(`(\d+) deletion`)
)

type repoAt struct {
	root, gitDir, rel, branch string
}

func gitInfo(cwd string) *gitDetails {
	dir, err := filepath.EvalSymlinks(cwd)
	if err != nil {
		return nil
	}
	if fi, err := os.Stat(dir); err != nil || !fi.IsDir() {
		return nil
	}
	r, ok := readGitDir(dir)
	if !ok {
		r = revParse(dir)
	}
	if r == nil {
		return nil
	}
	gi := &gitDetails{repo: filepath.Base(r.root), branch: r.branch, rel: r.rel}
	gi.added, gi.deleted = lineCounts(r.root)
	return gi
}

// readGitDir finds the repository from .git without starting git; ok is false
// when only git itself can tell.
func readGitDir(dir string) (r *repoAt, ok bool) {
	if os.Getenv("GIT_DIR") != "" || os.Getenv("GIT_WORK_TREE") != "" {
		return nil, false
	}
	root := dir
	var fi fs.FileInfo
	for {
		var err error
		if fi, err = os.Stat(filepath.Join(root, ".git")); err == nil {
			break
		} else if !errors.Is(err, fs.ErrNotExist) {
			return nil, false
		}
		parent := filepath.Dir(root)
		if parent == root {
			return nil, true
		}
		root = parent
	}

	gitDir := filepath.Join(root, ".git")
	if !fi.IsDir() {
		b, err := os.ReadFile(gitDir)
		path, found := strings.CutPrefix(strings.TrimSpace(string(b)), "gitdir: ")
		if err != nil || !found {
			return nil, false
		}
		if !filepath.IsAbs(path) {
			path = filepath.Join(root, path)
		}
		gitDir = filepath.Clean(path)
	}

	b, err := os.ReadFile(filepath.Join(gitDir, "HEAD"))
	if err != nil {
		return nil, false
	}
	head := strings.TrimSpace(string(b))
	var branch string
	if ref, found := strings.CutPrefix(head, "ref: "); found {
		var heads bool
		// Reftable repositories keep a placeholder HEAD that names no branch.
		if branch, heads = strings.CutPrefix(ref, "refs/heads/"); !heads || branch == ".invalid" {
			return nil, false
		}
	} else if isHash(head) {
		branch = head[:min(abbrevLen(gitDir), len(head))]
	} else {
		return nil, false
	}

	rel, err := filepath.Rel(root, dir)
	if err != nil {
		return nil, false
	}
	if rel == "." {
		rel = ""
	}
	return &repoAt{root: root, gitDir: gitDir, rel: filepath.ToSlash(rel), branch: branch}, true
}

func isHash(s string) bool {
	if len(s) != 40 && len(s) != 64 {
		return false
	}
	for _, c := range s {
		if !strings.ContainsRune("0123456789abcdef", c) {
			return false
		}
	}
	return true
}

// abbrevLen reads a fixed core.abbrev from the repository's config, else 7.
func abbrevLen(gitDir string) int {
	common := gitDir
	if b, err := os.ReadFile(filepath.Join(gitDir, "commondir")); err == nil {
		common = strings.TrimSpace(string(b))
		if !filepath.IsAbs(common) {
			common = filepath.Join(gitDir, common)
		}
	}
	b, err := os.ReadFile(filepath.Join(common, "config"))
	if err != nil {
		return 7
	}
	n, inCore := 7, false
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "[") {
			inCore = strings.EqualFold(strings.TrimSpace(strings.Trim(line, "[]")), "core")
			continue
		}
		key, value, _ := strings.Cut(line, "=")
		if inCore && strings.EqualFold(strings.TrimSpace(key), "abbrev") {
			n = 7
			if v, err := strconv.Atoi(strings.TrimSpace(value)); err == nil && v >= 4 {
				n = v
			}
		}
	}
	return n
}

// revParse asks git, for repositories readGitDir can't read.
func revParse(dir string) *repoAt {
	out, ok := runGit(dir, "rev-parse", "--absolute-git-dir", "--show-toplevel", "--show-prefix", "--abbrev-ref", "HEAD")
	lines := strings.Split(out, "\n")
	if len(lines) < 3 || lines[1] == "" {
		return nil
	}
	r := &repoAt{gitDir: lines[0], root: lines[1], rel: strings.TrimSuffix(lines[2], "/")}
	if ok && len(lines) > 3 && lines[3] != "HEAD" {
		r.branch = lines[3]
	} else if r.branch = trimmedGit(dir, "branch", "--show-current"); r.branch == "" {
		r.branch = trimmedGit(dir, "rev-parse", "--short", "HEAD")
	}
	return r
}

// runGit returns git's whole output, even when git fails partway.
func runGit(dir string, args ...string) (string, bool) {
	ctx, cancel := context.WithTimeout(context.Background(), gitTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	// Frequent redraws must not contend for the index lock.
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0")
	out, err := cmd.Output()
	return strings.ToValidUTF8(string(out), "�"), err == nil
}

func trimmedGit(dir string, args ...string) string {
	out, ok := runGit(dir, args...)
	if !ok {
		return ""
	}
	return strings.TrimSpace(out)
}

func lineCounts(root string) (added, deleted int) {
	stat := trimmedGit(root, "diff", "--shortstat", "HEAD")
	if m := insertions.FindStringSubmatch(stat); m != nil {
		added, _ = strconv.Atoi(m[1])
	}
	if m := deletions.FindStringSubmatch(stat); m != nil {
		deleted, _ = strconv.Atoi(m[1])
	}
	untracked := trimmedGit(root, "ls-files", "-z", "--others", "--exclude-standard")
	return added + countLines(root, strings.Split(untracked, "\x00")), deleted
}

func countLines(root string, names []string) int {
	total := 0
	for _, name := range names {
		if name == "" {
			continue
		}
		path := filepath.Join(root, name)
		if fi, err := os.Stat(path); err != nil || !fi.Mode().IsRegular() || fi.Size() > maxUntrackedBytes {
			continue
		}
		if b, err := os.ReadFile(path); err == nil {
			total += bytes.Count(b, []byte{'\n'})
		}
	}
	return total
}
