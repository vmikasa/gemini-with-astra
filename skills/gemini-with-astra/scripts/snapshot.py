#!/usr/bin/env python3
"""Read-only Git-visible workspace fingerprint; does not store or print source content."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys


def main():
    def git(*args):
        return subprocess.check_output(["git", "--no-optional-locks", *args])
    root = Path(git("rev-parse", "--show-toplevel").decode("utf-8").strip())
    os.chdir(root)
    h = hashlib.sha256()
    def add(label, data):
        h.update(label + b"\0" + str(len(data)).encode() + b"\0" + data)
    # For unborn repos --cached and worktree diffs are still available.
    try:
        head = subprocess.check_output(["git", "rev-parse", "--verify", "HEAD"], stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        head = b"UNBORN"
    add(b"head", head)
    add(b"status", git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"))
    diff = ("diff", "--no-ext-diff", "--no-textconv", "--binary", "--no-renames", "--no-color", "--ignore-submodules=none")
    add(b"staged", git(*diff, "--cached"))
    add(b"unstaged", git(*diff))
    paths = sorted(filter(None, git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")))
    for raw in paths:
        path = Path(os.fsdecode(raw))
        if path.is_symlink():
            sha = hashlib.sha256(os.fsencode(os.readlink(path))).digest()
            kind = b"symlink"
        elif path.is_file():
            d = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    d.update(chunk)
            sha, kind = d.digest(), b"file"
        else:
            raise RuntimeError(f"Unsupported or changing untracked path: {path}")
        add(b"untracked-path", raw)
        add(kind, sha)
    print("HEAD:", head.decode())
    print("WORKSPACE_SHA256:", h.hexdigest())
    print("Untracked nonignored paths:", len(paths))
    print("Scope: Git-visible tracked patches + untracked content; excludes ignored inputs and nested repo internals. Keep workspace stable during capture.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"SNAPSHOT FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
