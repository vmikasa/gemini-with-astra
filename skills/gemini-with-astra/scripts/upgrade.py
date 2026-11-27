#!/usr/bin/env python3
"""Preview or explicitly upgrade a quiescent v0.1.1 project; keep exact original bytes."""

import argparse
import base64
import json
import os
from pathlib import Path
import sys

import setup
from coord import packed, replace_file, require, sha, under

ARCHIVE = ".ai/upgrades/0.1.1-to-0.2.0"
PLAN = ARCHIVE + "/plan.json"


def encode(b):
    return base64.b64encode(b).decode("ascii")


def checked_block(old, before, after):
    for eol in (b"\n", b"\r\n"):
        source = before.strip().encode().replace(b"\n", eol)
        if old.count(source) == 1:
            return old.replace(source, after.strip().encode().replace(b"\n", eol), 1)
    raise ValueError("Managed rule changed; inspect it before upgrading")


def build(root):
    mp = under(root, setup.MANIFEST)
    require(
        mp.is_file(),
        "Missing local manifest; inspect existing state and restore validated v0.1.1 metadata first",
    )
    m = json.loads(mp.read_bytes())
    require(
        m.get("version") == "0.1.1" and m["root"] == str(root),
        "Requires a v0.1.1 primary checkout with matching root",
    )
    require(
        not setup.tracked(root, ".ai") and setup.ignored(root, setup.MANIFEST),
        "Private state must be Git-excluded",
    )
    mode = m["mode"]
    for name in (
        "sessions",
        "workspaces",
        "legacy",
        "sync/sends",
        "sync/inboxes",
        "sync/receipts",
        "runtime-v2.transaction",
    ):
        path = under(root, ".ai/" + name)
        require(
            not path.exists() or (path.is_dir() and not any(path.iterdir())),
            "Existing v0.2 state without matching version: " + name,
        )
    require(mode in ("local", "private") and m["entry"] in ("root", "bridge"), "Unknown layout")
    folder = "docs/" if mode == "private" else ".ai/docs/"
    helper = folder + "dual-collab.py"
    lock = ".ai/runtime-v2.lock"
    if mode == "private":
        require(not setup.ignored(root, helper), "Versionable runtime path is ignored")
    replacements = {
        "@SPEC@": folder + "SPEC.md",
        "@DECISIONS@": folder + "DECISIONS.md",
        "@PROTOCOL@": folder + "DUAL-COLLAB.md",
        "@SNAPSHOT@": folder + "dual-collab-snapshot.py",
        "@COORD@": helper,
        "@CODE@": m["code"],
    }

    def render(n):
        text = (setup.ASSETS / n).read_text(encoding="utf-8")
        for a, b in replacements.items():
            text = text.replace(a, b)
        return text

    writes = {}
    originals = {}

    def add(name, new, old):
        writes[name] = {"expected": sha(old) if old is not None else None, "new": encode(new)}
        if old is not None:
            originals[name] = encode(old)

    rule = setup.wrapped(render("RESIDENT.md"))
    found = set()
    common = (root / setup.text_git(root, "rev-parse", "--git-common-dir")).resolve()
    allowed_external = {(common / "info/exclude").resolve()}
    if m["entry"] == "bridge":
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
        active = home / (
            "AGENTS.override.md" if setup.read(home / "AGENTS.override.md").strip() else "AGENTS.md"
        )
        agy = (
            Path.home() / ".gemini/config/rules" / ("dual-collab-" + m["code"].lower() + ".md")
        ).resolve()
        require(
            str(active) == m["codex_bridge"] and str(agy) == m["agy_bridge"], "Bridge profile/root changed"
        )
        allowed_external.update((active, agy))
    for check in m["checks"]:
        if check.get("absolute"):
            path = Path(check["path"])
            require(path in allowed_external and path.is_file(), "Invalid or missing external rule")
            data = setup.read(path)
            if "sha256" in check:
                require(sha(data) == check["sha256"], "External file drift: " + str(path))
            if "contains" in check:
                require(
                    check["contains"].strip() in setup.normalized(data), "External rule drift: " + str(path)
                )
            continue
        rel = Path(check["path"]).as_posix()
        f = under(root, rel)
        require(f.is_file(), "Missing managed file: " + rel)
        old = f.read_bytes()
        if "sha256" in check:
            require(sha(old) == check["sha256"], "Generated file drift: " + rel)
        elif "contains" in check:
            require(check["contains"].strip() in setup.normalized(old), "Managed block drift: " + rel)
        if rel in ("AGENTS.md", "AGENTS.override.md") and "contains" in check:
            new = checked_block(old, check["contains"], rule)
            check["contains"] = rule
        elif rel == ".ai/AGENTS.md":
            new = rule.encode()
            check["sha256"] = sha(new)
        elif rel == folder + "DUAL-COLLAB.md":
            new = render("PROTOCOL.md").encode()
            check["sha256"] = sha(new)
        else:
            continue
        add(rel, new, old)
        found.add(rel)
    entry = ".ai/AGENTS.md" if m["entry"] == "bridge" else "AGENTS.md"
    require(
        {entry, folder + "DUAL-COLLAB.md"}.issubset(found),
        "Manifest lacks the original rule or protocol checks",
    )
    worker = folder + "astra_worker.py"
    control = folder + "worker_control.py"
    for rel, data in ((helper, (Path(__file__).parent / "coord.py").read_bytes()),
                      (worker, (Path(__file__).parent / "astra_worker.py").read_bytes()),
                      (control, (Path(__file__).parent / "worker_control.py").read_bytes()), (lock, b"0")):
        require(not under(root, rel).exists(), "Existing destination: " + rel)
        add(rel, data, None)
        m["checks"].append({"path": rel, "sha256": sha(data)})
        m["required"].append(rel)
    m["ignored"].append(lock)
    m["versionable" if mode == "private" else "ignored"].extend([helper, worker, control])
    for side in ("astra", "gemini"):
        legacy = ".ai/sync/to-" + side + ".md"
        path = under(root, legacy)
        if path.is_file():
            raw = path.read_bytes()
            originals[legacy] = encode(raw)
            prefix = ".ai/legacy/pending/" + side + "/"
            for rel, data in (
                (prefix + sha(raw) + ".md", raw),
                (prefix + "source.json", packed({"sha256": sha(raw)})),
            ):
                require(not under(root, rel).exists(), "Legacy backup destination already exists")
                add(rel, data, None)
    m["version"] = setup.VERSION
    add(setup.MANIFEST, (json.dumps(m, ensure_ascii=False, indent=2) + "\n").encode(), mp.read_bytes())
    return {"root": str(root), "writes": writes, "originals": originals}


def execute(root, apply):
    control = under(root, PLAN)
    mp = under(root, setup.MANIFEST)
    if control.exists():
        plan = json.loads(control.read_bytes())
        if (control.parent / "complete").is_file():
            require(
                mp.is_file() and json.loads(mp.read_bytes())["version"] == setup.VERSION,
                "Completed upgrade metadata mismatch",
            )
            print("Already upgraded; existing user edits preserved.")
            return setup.status(root)
    else:
        if mp.is_file() and json.loads(mp.read_bytes()).get("version") == setup.VERSION:
            return setup.status(root)
        plan = build(root)
    require(plan["root"] == str(root), "Upgrade plan belongs to another checkout")
    print("Backup:", under(root, ARCHIVE + "/original"))
    for name in plan["writes"]:
        print("UPDATE", name)
    for name in plan["originals"]:
        if name.startswith(".ai/sync/"):
            print("RETAIN LEGACY", name)
    if not apply:
        print("PREVIEW ONLY. Quiesce old writers and obtain approval before --apply.")
        return 0
    # Validate all old/new states before mutating. The persisted plan survives crashes.
    for name, step in plan["writes"].items():
        p = under(root, name)
        current = sha(p.read_bytes()) if p.exists() else None
        require(
            current in (step["expected"], sha(base64.b64decode(step["new"]))), "Source changed: " + name
        )
    for name, value in plan["originals"].items():
        if name.startswith(".ai/sync/"):
            require(under(root, name).read_bytes() == base64.b64decode(value), "Legacy writer still active")
    if not control.exists():
        require(not control.parent.exists(), "Unexpected backup directory; inspect it first")
        replace_file(control, packed(plan))
    for name, encoded in plan["originals"].items():
        backup = under(root, ARCHIVE + "/original/" + name)
        data = base64.b64decode(encoded)
        if backup.exists():
            require(backup.read_bytes() == data, "Backup drift: " + name)
        else:
            replace_file(backup, data)
    # The manifest is the commit marker and is always replaced last.
    for name in sorted(plan["writes"], key=lambda n: n == setup.MANIFEST):
        p = under(root, name)
        data = base64.b64decode(plan["writes"][name]["new"])
        if p.exists() and p.read_bytes() == data:
            continue
        current = p.read_bytes() if p.exists() else None
        require(
            (sha(current) if current is not None else None) == plan["writes"][name]["expected"],
            "Concurrent edit: " + name,
        )
        setup.atomic(p, data, current or b"")
    result = setup.status(root)
    if not result:
        replace_file(control.parent / "complete", b"0.2.0\n")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    try:
        root = setup.root_at(a.root)
        if a.apply:
            with setup.setup_lock(root):
                sys.exit(execute(root, True))
        sys.exit(execute(root, False))
    except (ValueError, KeyError, OSError, RuntimeError) as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(2)
