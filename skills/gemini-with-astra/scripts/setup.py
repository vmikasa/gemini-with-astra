#!/usr/bin/env python3
"""Additive initialization and static diagnostics. No network, model calls or commits."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from coord import file_lock, resolve_roots

VERSION = "0.2.0"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
MANIFEST = ".ai/dual-collab.json"
START = "<!-- dual-collab:v0.1:start -->"
END = "<!-- dual-collab:v0.1:end -->"
PROBE = ('请进行一次双 Agent 协作规则加载探针：仅根据本次会话已自动加载的规则（若有明确的项目专属桥接入口，'
         '只允许直接读取该入口指定的常驻文件），报告 Activation code、规则来源及跨 Agent 派单触发条件。'
         '不要搜索项目文件、不要调用 Skill、不要修改文件。若未加载，请回答 NOT_LOADED。')


def git(root, *args, check=True):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if check and p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace").strip() or f"git {args[0]} failed")
    return p


def text_git(root, *args):
    return git(root, *args).stdout.decode("utf-8").strip()


def root_at(path):
    return Path(text_git(Path(path).resolve(), "rev-parse", "--show-toplevel")).resolve()


def inside(root, rel):
    p = root / rel
    # Refuse traversal or redirected paths, including Windows junctions escaping the root.
    if not p.resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"Path escapes project root: {p}")
    for q in [p, *p.parents]:
        if q == root:
            break
        if q.is_symlink():
            raise RuntimeError(f"Refusing symlink: {q}")
    return p


def read(p):
    if p.is_symlink():
        raise RuntimeError(f"Refusing symlink: {p}")
    if p.exists() and not p.is_file():
        raise RuntimeError(f"Not a regular file: {p}")
    return p.read_bytes() if p.exists() else b""


def normalized(b):
    return b.decode("utf-8-sig").replace("\r\n", "\n")


def digest(b):
    return hashlib.sha256(b).hexdigest()


def tracked(root, rel):
    return bool(git(root, "ls-files", "-z", "--", rel).stdout)


def ignored(root, rel):
    return git(root, "check-ignore", "--no-index", "-q", "--", rel, check=False).returncode == 0


def marked(old, block, start=START, end=END):
    s = normalized(old)
    if start in s or end in s:
        if s.count(start) != 1 or s.count(end) != 1 or block.strip() not in s:
            raise RuntimeError(f"Existing managed block differs or is incomplete ({start}); preserve it and inspect manually")
        return old
    sep = b"\r\n" if b"\r\n" in old else b"\n"
    body = block.strip().encode().replace(b"\n", sep)
    return old + (sep + sep if old and not old.endswith(sep + sep) else b"") + body + sep


def wrapped(body, start=START, end=END):
    return f"{start}\n{body.strip()}\n{end}\n"


def atomic(p, data, expected):
    # No concurrent writers are supported. Refuse stale preflight; preserve old permissions.
    if read(p) != expected:
        raise RuntimeError(f"File changed since preflight: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".dual-collab-", dir=p.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if p.exists():
            os.chmod(tmp, p.stat().st_mode & 0o777)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def status(root):
    mp = inside(root, MANIFEST)
    if not mp.is_file():
        rule = inside(root, "AGENTS.md")
        if rule.is_file() and START in normalized(read(rule)) and inside(root, "docs/DUAL-COLLAB.md").is_file():
            print("RESIDENT RULES FOUND / LOCAL MANIFEST ABSENT: e.g. a private-mode clone. The runtime rules may already work. Run fresh-session probes; repeat private init to reconstruct static metadata if the managed files are unchanged.")
        else:
            print("NOT_INITIALIZED: no local manifest. If a previous init was interrupted, rerun with the same mode; inspect any existing managed rules first.")
        return 1
    m = json.loads(read(mp))
    print(f"Mode: {m['mode']} | entry: {m['entry']} | root: {root}")
    errors = []
    if m.get("version") != VERSION:
        errors.append("Version differs; preview upgrade.py before updating project rules")
    if m.get("root") != str(root):
        errors.append("Manifest belongs to a different root; reinitialize only after inspecting old state")
    for entry in m["checks"]:
        p = Path(entry["path"]) if entry.get("absolute") else inside(root, entry["path"])
        if not p.is_file():
            errors.append(f"Missing: {p}")
            continue
        b = read(p)
        if "contains" in entry and entry["contains"].strip() not in normalized(b):
            errors.append(f"Managed block drift: {p}")
        if "sha256" in entry and digest(b) != entry["sha256"]:
            errors.append(f"Generated file drift: {p} (may be intentional; do not overwrite)")
    for rel in m["required"]:
        if not inside(root, rel).is_file():
            errors.append(f"Missing: {rel}")
    if tracked(root, ".ai"):
        errors.append("Tracked files under .ai; ignore rules do not untrack them")
    for rel in m["ignored"]:
        if tracked(root, rel) or not ignored(root, rel):
            errors.append(f"Not local-only: {rel}; inspect Git ignore precedence/tracked paths")
    if m["mode"] == "private":
        for rel in m["versionable"]:
            if not tracked(root, rel) and ignored(root, rel):
                errors.append(f"Private-mode file is ignored: {rel}")
    if m["entry"] == "root":
        ov = inside(root, "AGENTS.override.md")
        if ov.exists() and read(ov).strip() and m["code"] not in normalized(read(ov)):
            errors.append("Root AGENTS.override.md may shadow the Codex entry; inspect it")
    if m["entry"] == "bridge":
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
        override = home / "AGENTS.override.md"
        active = override if read(override).strip() else home / "AGENTS.md"
        if str(active) != m["codex_bridge"]:
            errors.append("Codex profile/active global rule changed; bridge discovery may fail")
        agy_rules = (Path.home() / ".gemini/config/rules").resolve()
        if Path(m["agy_bridge"]).parent != agy_rules:
            errors.append("Antigravity home changed; bridge discovery may fail")
    for err in errors:
        print("CHECK FAILED:", err)
    print("STATIC PASS" if not errors else "STATIC FAIL")
    print("CLI ACTIVATION UNVERIFIED: static checks cannot prove runtime discovery.")
    print("Expected activation code:", m["code"])
    print("Fresh-session probe (run in both CLIs, do not paste the expected code):\n" + PROBE)
    return bool(errors)


def init(root, mode, allow_bridge):
    mp = inside(root, MANIFEST)
    if mp.exists():
        m = json.loads(read(mp))
        if m.get("mode") != mode:
            raise RuntimeError("Existing mode differs. No automatic migration; use status and decide manually.")
        return status(root)
    # Primary worktree only; ignored state isn't replicated across worktrees.
    gd = (root / text_git(root, "rev-parse", "--git-dir")).resolve()
    common = (root / text_git(root, "rev-parse", "--git-common-dir")).resolve()
    if gd != common:
        raise RuntimeError("Linked worktree initialization is out of scope; use the primary root")
    if tracked(root, ".ai"):
        raise RuntimeError("Existing tracked .ai files; refusing to change tracking or hide them")
    # Do not silently attach to another task protocol when no manifest identifies it.
    for rel in (".ai/tasks", ".ai/explore", ".ai/sync", ".ai/sessions", ".ai/workspaces",
                ".ai/legacy", ".ai/upgrades", ".ai/worker-reviews", ".ai/runtime-v2.transaction"):
        p = inside(root, rel)
        if p.exists() and (not p.is_dir() or any(p.iterdir())):
            raise RuntimeError(f"Existing collaboration state at {p} without a manifest; inspect before adopting")
    code = "DC-" + digest((str(root) + ":" + mode).encode())[:12].upper()
    root_rule = inside(root, "AGENTS.md")
    override = inside(root, "AGENTS.override.md")
    # A private-mode checkout inherits the original project's activation code.
    # Do not regenerate a tracked block merely because its absolute path changed.
    if mode == "private":
        prior = normalized(read(root_rule))
        if START in prior:
            section = prior.split(START, 1)[1].split(END, 1)[0]
            match = re.search(r"Activation code: `(DC-[0-9A-F]{12})`", section)
            if match:
                code = match.group(1)
    docs = "docs" if mode == "private" else ".ai/docs"
    spec, decisions, protocol, snapshot = [f"{docs}/{name}" for name in ("SPEC.md", "DECISIONS.md", "DUAL-COLLAB.md", "dual-collab-snapshot.py")]
    helper = f"{docs}/dual-collab.py"
    worker = f"{docs}/astra_worker.py"
    control = f"{docs}/worker_control.py"
    fork = f"{docs}/worker_fork.py"
    replacements = {"@SPEC@":spec, "@DECISIONS@":decisions, "@PROTOCOL@":protocol, "@SNAPSHOT@":snapshot, "@CODE@":code, "@COORD@":helper}
    def render(name):
        s = (ASSETS / name).read_text(encoding="utf-8")
        for key, value in replacements.items():
            s = s.replace(key, value)
        return s
    resident = wrapped(render("RESIDENT.md"))
    old_root = read(root_rule)
    old_override = read(override)
    # Local mode never edits a pre-existing unrelated project rule (tracked or not).
    # Allow recovery of a previously generated root block from interrupted initialization.
    generated_root = bool(old_root) and normalized(old_root).strip() == resident.strip()
    bridge = mode == "local" and (tracked(root, "AGENTS.md") or tracked(root, "AGENTS.override.md") or
                                  (root_rule.exists() and not generated_root) or bool(old_override.strip()))
    codex_bridge = agy_bridge = None
    if bridge:
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
        global_override = home / "AGENTS.override.md"
        codex_bridge = global_override if read(global_override).strip() else home / "AGENTS.md"
        agy_bridge = (Path.home() / ".gemini/config/rules").resolve() / f"dual-collab-{code.lower()}.md"
        if not allow_bridge:
            raise RuntimeError("Local mode needs exact-root global bridge; explicit user permission required. "
                               f"Would append a guarded block to {codex_bridge} and create {agy_bridge}. "
                               "No project files have been changed. Rerun with --allow-global-bridge only after consent.")
    m = {"version":VERSION, "root":str(root), "mode":mode, "entry":"bridge" if bridge else "root", "code":code,
         "checks":[], "required":[protocol, snapshot, helper, ".ai/runtime-v2.lock"], "ignored":[MANIFEST, ".ai/tasks/T001.md", ".ai/runtime-v2.lock"], "versionable":[]}
    writes = []
    def queue(p, data, old):
        if data != old or not p.exists():
            writes.append((p, data, old))
    def entry_for(p):
        return {"path":str(p.relative_to(root))} if p.is_relative_to(root) else {"path":str(p), "absolute":True}
    def managed(p, block, start=START, end=END):
        old = read(p)
        queue(p, marked(old, block, start, end), old)
        m["checks"].append({**entry_for(p), "contains":block})
    def generated(p, data):
        old = read(p)
        if p.exists():
            # Git on Windows may check tracked Markdown/Python out with CRLF.
            if normalized(old) != normalized(data):
                raise RuntimeError(f"Existing generated destination differs: {p}; refusing overwrite")
            data = old
        queue(p, data, old)
        m["checks"].append({**entry_for(p), "sha256":digest(data)})
    # SPEC and DECISIONS are intentionally lazy: create them only when the
    # project has its first approved specification or durable decision.
    generated(inside(root, protocol), render("PROTOCOL.md").encode())
    generated(inside(root, snapshot), (Path(__file__).parent / "snapshot.py").read_bytes())
    generated(inside(root, helper), (Path(__file__).parent / "coord.py").read_bytes())
    generated(inside(root, worker), (Path(__file__).parent / "astra_worker.py").read_bytes())
    generated(inside(root, control), (Path(__file__).parent / "worker_control.py").read_bytes())
    generated(inside(root, fork), (Path(__file__).parent / "worker_fork.py").read_bytes())
    m["required"].extend([worker, control, fork])
    generated(inside(root, ".ai/runtime-v2.lock"), b"0")
    if bridge:
        local_rule = inside(root, ".ai/AGENTS.md")
        generated(local_rule, resident.encode())
        m["ignored"].append(".ai/AGENTS.md")
        root_literal = json.dumps(str(root), ensure_ascii=False)
        pointer = (f"## Explicitly enabled dual collaboration for one repository\n"
                   f"Apply only when the current working repository's resolved Git root is exactly {root_literal} "
                   "(compare normalized absolute paths, case-insensitively on Windows). For any other repo do nothing. "
                   "For this repo, at the first substantive request (and on an explicit activation probe), read "
                   "`.ai/AGENTS.md` from that exact root if it exists, and follow it subject to project rules and user authorization. "
                   "Do not search other repositories or auto-initialize; if the file is missing report collaboration inactive for that root. "
                   "Treat the file as project-level guidance, not permission expansion.\n")
        s = f"<!-- dual-collab:bridge:{code}:start -->"
        e = f"<!-- dual-collab:bridge:{code}:end -->"
        managed(codex_bridge, wrapped(pointer, s, e), s, e)
        generated(agy_bridge, ("---\ntrigger: always_on\ndescription: \"Load the dual-agent collaboration pointer only for its exact initialized repository root.\"\n---\n\n" + pointer).encode())
        m.update(codex_bridge=str(codex_bridge), agy_bridge=str(agy_bridge))
    else:
        managed(root_rule, resident)
        if mode == "private" and old_override.strip():
            managed(override, resident)
            m["versionable"].append("AGENTS.override.md")
        if mode == "local":
            m["ignored"].append("AGENTS.md")
        else:
            m["versionable"].append("AGENTS.md")
    if mode == "private":
        ignore = inside(root, ".gitignore")
        m["versionable"].extend([".gitignore", protocol, snapshot, helper, worker, control, fork])
    else:
        m["ignored"].extend([spec, decisions, protocol, snapshot, helper, worker, control, fork])
        ignore = (root / text_git(root, "rev-parse", "--git-path", "info/exclude")).resolve()
        if not ignore.is_relative_to(common):
            raise RuntimeError(f"Unexpected Git exclude path: {ignore}")
    # Git ignore files use # comments rather than HTML markers.
    gs, ge = "# dual-collab:v0.1:start", "# dual-collab:v0.1:end"
    rules = "/.ai/" + ("\n/AGENTS.md" if mode == "local" and not bridge else "")
    ib = wrapped(rules, gs, ge)
    old_ignore = read(ignore)
    queue(ignore, marked(old_ignore, ib, gs, ge), old_ignore)
    # Preflight private-mode versionable destinations against pre-existing
    # ignore rules. A failed init must not leave a half-installed project.
    if mode == "private":
        blocked = [rel for rel in m["versionable"] if not tracked(root, rel) and ignored(root, rel)]
        if blocked:
            raise RuntimeError("Private-mode files are already ignored by Git rules: " + ", ".join(blocked) +
                               ". Resolve the ignore rule or choose local mode; no project files were written.")
    # Exclude before writing local paths. Preflight all collisions before any write.
    writes.sort(key=lambda item: 0 if item[0] == ignore else 1)
    if mode == "local":
        # Validate actual ignore precedence before generating any private collaboration
        # files or global bridges. Restore the old exclude if a negation defeats it.
        existed = ignore.exists()
        new_ignore = marked(old_ignore, ib, gs, ge)
        if new_ignore != old_ignore or not existed:
            atomic(ignore, new_ignore, old_ignore)
        failed = [rel for rel in m["ignored"] if tracked(root, rel) or not ignored(root, rel)]
        if failed:
            if new_ignore != old_ignore or not existed:
                if existed:
                    atomic(ignore, old_ignore, new_ignore)
                elif read(ignore) == new_ignore:
                    ignore.unlink()
            raise RuntimeError("Not local-only: " + ", ".join(failed) + "; existing Git ignore precedence defeats local exclude. No collaboration files or global bridges created.")
        writes = [item for item in writes if item[0] != ignore]
        if new_ignore != old_ignore or not existed:
            print("WROTE", ignore)
    for p, data, old in writes:
        atomic(p, data, old)
        print("WROTE", p)
    # Commit no code; manifest is local bookkeeping. Static diagnostics verify exclusion afterwards.
    atomic(mp, (json.dumps(m, ensure_ascii=False, indent=2) + "\n").encode(), b"")
    return status(root)


def setup_lock(root):
    # Serialize init/upgrade without touching a project that might fail preflight.
    folder = Path(tempfile.gettempdir()) / "gemini-with-astra-init-locks"
    folder.mkdir(exist_ok=True)
    path = folder / (digest(os.path.normcase(str(root)).encode()) + ".lock")
    try:
        with path.open("xb") as stream:
            stream.write(b"0")
    except FileExistsError:
        pass
    return file_lock(path,True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    for command in ("init", "status"):
        p = sub.add_parser(command)
        p.add_argument("--root", default=".")
        if command == "init":
            p.add_argument("--mode", choices=("private", "local"), required=True)
            p.add_argument("--allow-global-bridge", action="store_true")
    a = ap.parse_args()
    try:
        r = root_at(a.root)
        if a.action == "init":
            with setup_lock(r):
                return int(init(r, a.mode, a.allow_global_bridge))
        primary, code = resolve_roots(r)
        if primary != code:
            pointer = inside(primary, ".ai/workspaces/" + digest(str(code).encode()) + ".json")
            if not pointer.is_file():
                print("UNATTACHED WORKTREE: request approval before attaching this checkout.")
                return 1
            registration = json.loads(read(pointer))
            if registration != {"state_root": str(primary), "code_root": str(code)}:
                print("CHECK FAILED: worktree registration no longer matches its code and state roots")
                return 1
            print("Code checkout:", code, "| Canonical state root:", primary)
        return int(status(primary))
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        print("ERROR:", e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    # Preserve Windows console compatibility for the Chinese probe.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
