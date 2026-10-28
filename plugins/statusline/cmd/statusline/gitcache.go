package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

const (
	countsTTL = 5 * time.Second
	lockStale = 10 * time.Second
)

var errLocked = errors.New("locked by another run")

type countsFile struct {
	Added      int   `json:"added"`
	Deleted    int   `json:"deleted"`
	WrittenAt  int64 `json:"written_at"`
	HeadMtime  int64 `json:"head_mtime"`
	IndexMtime int64 `json:"index_mtime"`
}

func countsPath(cacheDir, root string) string {
	sum := sha256.Sum256([]byte(root))
	return filepath.Join(cacheDir, "git-"+hex.EncodeToString(sum[:8])+".json")
}

func mtime(path string) int64 {
	fi, err := os.Stat(path)
	if err != nil {
		return 0
	}
	return fi.ModTime().UnixNano()
}

// cachedCounts shares a worktree's line counts between every session in it.
func cachedCounts(root, gitDir, cacheDir string, now time.Time) (added, deleted int) {
	if cacheDir == "" {
		return lineCounts(root)
	}
	path := countsPath(cacheDir, root)
	cur := countsFile{
		HeadMtime:  mtime(filepath.Join(gitDir, "HEAD")),
		IndexMtime: mtime(filepath.Join(gitDir, "index")),
	}
	var old countsFile
	b, err := os.ReadFile(path)
	if err != nil || json.Unmarshal(b, &old) != nil {
		old = countsFile{}
	} else if age := now.UnixNano() - old.WrittenAt; old.HeadMtime == cur.HeadMtime &&
		old.IndexMtime == cur.IndexMtime && age >= 0 && age < int64(countsTTL) {
		return old.Added, old.Deleted
	}

	unlock, err := lock(path+".lock", now)
	if errors.Is(err, errLocked) {
		return old.Added, old.Deleted
	} else if err != nil {
		return lineCounts(root)
	}
	defer unlock()
	cur.Added, cur.Deleted = lineCounts(root)
	cur.WrittenAt = now.UnixNano()
	if b, err := json.Marshal(cur); err == nil {
		writeAtomic(path, string(b))
	}
	return cur.Added, cur.Deleted
}

// lock creates path exclusively, once breaking a lock left for lockStale.
func lock(path string, now time.Time) (unlock func(), err error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	for retried := false; ; retried = true {
		f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		if err == nil {
			f.Close()
			return func() { os.Remove(path) }, nil
		}
		if !errors.Is(err, fs.ErrExist) {
			return nil, err
		}
		if fi, err := os.Stat(path); retried || err == nil && now.Sub(fi.ModTime()) < lockStale {
			return nil, errLocked
		}
		os.Remove(path)
	}
}
