#!/usr/bin/env python3
"""Local collaboration operations. One JSON request on stdin; JSON response on stdout."""

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time


VERSION = "0.2.0"
LOCK = ".ai/runtime-v2.lock"
JOURNAL = ".ai/runtime-v2.transaction"
PATTERNS = {
    "session": r"C-[AG][0-9]{3,12}",
    "task": r"T[0-9]{3,12}",
    "workstream": r"WS-[A-Za-z0-9][A-Za-z0-9_-]{0,48}",
    "key": r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}",
    "delivery": r"D-[a-f0-9]{32}",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def ident(kind, value):
    require(isinstance(value, str) and re.fullmatch(PATTERNS[kind], value), "Invalid or missing " + kind)
    return value


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def packed(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def under(root, name):
    rel = Path(name)
    require(not rel.is_absolute() and ".." not in rel.parts and not rel.drive, "Invalid relative path")
    p = root / rel
    require(p.resolve() == p and p.resolve().is_relative_to(root), "Redirected state path: " + str(p))
    return p


def replace_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".coord-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def lock_state(root, write):
    path = under(root, LOCK)
    require(path.is_file(), "Runtime lock missing; check initialization/upgrade")
    return file_lock(path, write)


@contextmanager
def file_lock(path, write):
    with path.open("r+b" if write else "rb") as stream:
        if os.name == "nt":
            import msvcrt

            flag = msvcrt.LK_NBLCK if write else msvcrt.LK_NBRLCK
            deadline = time.monotonic() + 20
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), flag, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError("State busy; retry")
                    time.sleep(0.03)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class Transaction:
    """A recoverable batch for cooperating clients. Replay completes the original write set."""

    def __init__(self, root):
        self.root = root
        self.changes = {}

    def put(self, rel, data):
        self.changes[str(rel)] = data

    def replay(self, operations):
        for name, old, encoded in operations:
            path = under(self.root, name)
            current = path.read_bytes() if path.exists() else None
            data = None if encoded is None else base64.b64decode(encoded, validate=True)
            if current == data:
                continue
            require(
                (None if current is None else sha(current)) == old,
                "External edit during transaction: " + name,
            )
            if data is None:
                path.unlink()
            else:
                replace_file(path, data)
        under(self.root, JOURNAL).unlink()

    def recover(self):
        path = under(self.root, JOURNAL)
        if path.exists():
            self.replay(json.loads(path.read_bytes()))

    def commit(self):
        if not self.changes:
            return
        ops = []
        for name, data in self.changes.items():
            path = under(self.root, name)
            old = sha(path.read_bytes()) if path.exists() else None
            ops.append([name, old, None if data is None else base64.b64encode(data).decode()])
        replace_file(under(self.root, JOURNAL), packed(ops))
        self.replay(ops)


def doc(meta, body=""):
    require(isinstance(body, str), "Markdown body must be text")
    return b"---\n" + packed(meta) + b"\n---\n" + body.encode()


def header(path):
    with path.open("rb") as f:
        require(f.readline() == b"---\n", "Unmanaged record: " + str(path))
        line = f.readline(131073)
        require(len(line) <= 131072 and f.readline() == b"---\n", "Invalid record header")
    return json.loads(line)


def content(path):
    return path.read_bytes().split(b"\n---\n", 1)[1].decode("utf-8")


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], stderr=subprocess.PIPE).decode().strip()


def resolve_roots(path):
    code = Path(git(path, "rev-parse", "--show-toplevel")).resolve()
    common = Path(git(code, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    locations = git(code, "worktree", "list", "--porcelain", "-z").split("\0")
    require(locations and locations[0].startswith("worktree "), "Cannot identify primary worktree")
    primary = Path(locations[0][9:]).resolve()
    require(
        Path(git(primary, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() == common,
        "Primary checkout belongs to a different repository",
    )
    return primary, code


def area(task=None, ws=None):
    if ws:
        require(task, "Workstream needs a task")
        return ident("task", task) + "~" + ident("workstream", ws)
    return ident("task", task) if task else "PROJECT"


def sfile(sid):
    return ".ai/sessions/" + ident("session", sid) + "/SESSION.md"


def tfile(task, ws=None):
    task = ident("task", task)
    if ws:
        return ".ai/tasks/" + task + "/workstreams/" + ident("workstream", ws) + ".md"
    return ".ai/tasks/" + task + ".md"


def checkpoint(sid, task, ws=None):
    return ".ai/sessions/" + ident("session", sid) + "/checkpoints/" + area(task, ws) + ".md"


def inbox(sid):
    return ".ai/sync/inboxes/" + ident("session", sid)


def snapshot_id(*parts):
    return sha(packed(parts))[:32]


class Runtime:
    def __init__(self, root, code, req, tx, manifest):
        self.root, self.code, self.req, self.tx = root, code, req, tx
        self.docs = ".ai/docs/" if manifest["mode"] == "local" else "docs/"
        self.actor = None

    def path(self, name):
        return under(self.root, name)

    def optional_text(self, name):
        p = self.path(name)
        return p.read_text(encoding="utf-8-sig") if p.is_file() else None

    def project(self):
        return {k: self.optional_text(self.docs + k) for k in ("SPEC.md", "DECISIONS.md")}

    def sessions(self):
        return [p.name for p in self.path(".ai/sessions").glob("C-*") if self.path(sfile(p.name)).is_file()]

    def session_meta(self, sid):
        return header(self.path(sfile(sid)))

    def authenticate(self):
        sid, sep, token = self.req.get("actor", "").partition(":")
        require(sep and token, "Operation requires this chat's session handle")
        m = self.session_meta(sid)
        require(
            secrets.compare_digest(m["handle_hash"], sha(token.encode())) and m["open"],
            "Invalid or closed session",
        )
        self.actor = sid
        return sid

    def register(self):
        agent = self.req.get("agent")
        require(agent in ("ASTRA", "GEMINI"), "Identify the CLI host first")
        prefix = "C-" + agent[0]
        supplied = self.req.get("registration_key")
        if supplied is not None:
            require(
                isinstance(supplied, str) and re.fullmatch(r"[A-Za-z0-9_-]{32,100}", supplied),
                "Use a fresh private high-entropy registration key for this chat",
            )
        token = supplied or secrets.token_urlsafe(32)
        sessions = self.sessions()
        if supplied:
            for existing in sessions:
                m = self.session_meta(existing)
                if secrets.compare_digest(m["handle_hash"], sha(token.encode())):
                    require(
                        m["open"]
                        and m["agent"] == agent
                        and m["resumes_from"] == self.req.get("resumes_from"),
                        "Registration key already bound to a different or closed registration",
                    )
                    return {
                        "session": existing,
                        "actor": existing + ":" + token,
                        "resumes_from": m["resumes_from"],
                    }
        used = [
            int(p.name[3:])
            for p in self.path(".ai/sessions").glob(prefix + "*")
            if re.fullmatch(PATTERNS["session"], p.name)
        ]
        sid = prefix + format(max(used, default=0) + 1, "03d")
        origin = self.req.get("resumes_from")
        if origin:
            self.session_meta(origin)
        m = {
            "id": sid,
            "agent": agent,
            "open": True,
            "created_at": utc(),
            "resumes_from": origin,
            "handle_hash": sha(token.encode()),
        }
        self.tx.put(sfile(sid), doc(m))
        return {"session": sid, "actor": sid + ":" + token, "resumes_from": origin}

    def record(self, task, ws=None):
        return header(self.path(tfile(task, ws)))

    def streams(self, task):
        folder = self.path(".ai/tasks/" + ident("task", task) + "/workstreams")
        return sorted(p.stem for p in folder.glob("WS-*.md"))

    def members(self, m):
        return set(m["participants"]) | {s for s in (m["owner"], m["reviewer"]) if s and s != "User"}

    def participants(self, task, ws=None):
        group = self.members(self.record(task, ws))
        if not ws:
            for w in self.streams(task):
                group.update(self.members(self.record(task, w)))
        return group

    def writer_claim(self, task, ws, owner, checkout, add):
        rel = ".ai/workspaces/writers/" + sha(checkout.encode()) + ".json"
        path = self.path(rel)
        data = self.tx.changes.get(rel)
        if rel not in self.tx.changes and path.exists():
            data = path.read_bytes()
        claim = json.loads(data) if data else {"owner": owner, "scopes": [], "checkout": checkout}
        require(
            claim["owner"] == owner,
            "Another session owns active code writes in this checkout; coordinate or use an approved worktree",
        )
        scope = area(task, ws)
        scopes = set(claim["scopes"])
        if add:
            scopes.add(scope)
        else:
            scopes.discard(scope)
        claim["scopes"] = sorted(scopes)
        self.tx.put(rel, packed(claim) if scopes else None)

    def work(self):
        q = self.req
        task, ws = q.get("task"), q.get("ws")
        if q["op"] == "create-task" and not task:
            nums = [
                int(p.stem[1:])
                for p in self.path(".ai/tasks").glob("T*.md")
                if re.fullmatch(PATTERNS["task"], p.stem)
            ]
            task = "T" + format(max(nums, default=0) + 1, "03d")
        rel = tfile(task, ws)
        path = self.path(rel)
        if q["op"] == "create-task":
            require(not ws, "create-task does not create a workstream")
        if q["op"] == "create-stream":
            require(ws and self.record(task)["owner"] == self.actor, "Task owner creates its workstreams")
        if q["op"] in ("create-task", "create-stream"):
            require(not path.exists(), "Record already exists")
            m = {
                "task": task,
                "ws": ws,
                "owner": q.get("owner", self.actor),
                "reviewer": q.get("reviewer"),
                "participants": q.get("participants", []),
                "issuer": self.actor,
                "contract_revision": 1,
                "revision": 1,
                "status": "READY",
            }
            require(m["owner"], "An owner is required")
            body = q.get("body")
            require(
                isinstance(body, str) and body.strip(),
                "Provide the authorized contract and completion criteria",
            )
        else:
            m = self.record(task, ws)
            require(q.get("revision") == m["revision"], "Stale revision; reread this task or workstream")
            body = content(path)
            if q["op"] == "revise":
                require(
                    q.get("approved") is True
                    and self.actor in (m.get("issuer"), m["owner"])
                    and isinstance(q.get("body"), str)
                    and q["body"].strip()
                    and q.get("reason"),
                    "A contract revision requires an authorized writer, the approved text and reason",
                )
                if m["status"] == "IN_PROGRESS" and m.get("code_root"):
                    self.writer_claim(task, ws, m["owner"], m["code_root"], False)
                history = (
                    ".ai/tasks/" + task + "/history/" + (ws or "TASK") + "-" + str(m["revision"]) + ".md"
                )
                require(not self.path(history).exists(), "Contract history already exists")
                self.tx.put(history, path.read_bytes())
                m.update(
                    contract_revision=m.get("contract_revision", 1) + 1,
                    status="READY",
                    change_reason=q["reason"],
                )
                body = q["body"]
            elif q["op"] == "user-accept":
                require(
                    m["status"] == "IMPLEMENTED"
                    and m["reviewer"] in (None, "User")
                    and q.get("approved") is True
                    and q.get("body")
                    and self.actor == m["owner"],
                    "Record explicit user acceptance of the delivered revision",
                )
                m["status"] = "ACCEPTED"
                body += f"\n\n## Review · user acceptance (recorded by {self.actor})\n" + q["body"] + "\n"
            elif q["op"] == "assign":
                require(
                    self.actor == m["owner"] and q.get("approved") is True,
                    "Reassignment needs owner and user approval",
                )
                if (
                    m["status"] == "IN_PROGRESS"
                    and m.get("code_root")
                    and q.get("owner", self.actor) != self.actor
                ):
                    self.writer_claim(task, ws, self.actor, m["code_root"], False)
                    self.writer_claim(task, ws, q["owner"], m["code_root"], True)
                for key in ("participants", "reviewer", "owner"):
                    if key in q:
                        m[key] = q[key]
            else:
                state = q.get("status")
                reviews = state in ("ACCEPTED", "REWORK")
                require(
                    self.actor == (m["reviewer"] if reviews else m["owner"]),
                    "Only the assigned writer can update this phase",
                )
                transitions = {
                    "READY": {"IN_PROGRESS", "CANCELLED"},
                    "IN_PROGRESS": {"IN_PROGRESS", "IMPLEMENTED", "BLOCKED", "CANCELLED"},
                    "BLOCKED": {"IN_PROGRESS", "CANCELLED"},
                    "IMPLEMENTED": {"ACCEPTED", "REWORK"},
                    "REWORK": {"IN_PROGRESS", "CANCELLED"},
                }
                require(state in transitions.get(m["status"], set()), "Invalid task transition")
                require(
                    state != "CANCELLED" or q.get("approved") is True, "Cancellation requires user approval"
                )
                require(
                    isinstance(q.get("body"), str) and q["body"].strip(),
                    "Record evidence for the transition",
                )
                if state == "IN_PROGRESS":
                    require(
                        m["status"] != "IN_PROGRESS"
                        or m.get("code_root", str(self.code)) == str(self.code),
                        "Active work belongs to another checkout",
                    )
                    self.writer_claim(task, ws, self.actor, str(self.code), True)
                    m["code_root"] = str(self.code)
                elif m["status"] == "IN_PROGRESS" and m.get("code_root"):
                    require(
                        m["code_root"] == str(self.code),
                        "Finish from the checkout containing the actual work",
                    )
                    self.writer_claim(task, ws, self.actor, m["code_root"], False)
                section = "Review" if reviews else "Result"
                conclusion = state
                if state == "ACCEPTED":
                    conclusion = f"ACCEPTED · Reviewer {self.actor} passed the contract checks"
                body += f"\n\n## {section} · {conclusion}\n{q['body']}\n"
                m["status"] = state
            m["revision"] += 1
        require(
            isinstance(m["participants"], list) and m["owner"] and m["owner"] != m["reviewer"],
            "Invalid participation or self-review",
        )
        for sid in self.members(m):
            if q["op"] in ("assign", "create-task", "create-stream"):
                self.open_session(sid)
            else:
                self.session_meta(sid)
        self.tx.put(rel, doc(m, body))
        return m

    def open_session(self, sid):
        require(self.session_meta(sid)["open"], "Closed session: " + sid)
        return sid

    def resolve(self, target, task, ws, all_agents):
        kind, _, value = target.partition(":")
        if kind == "SESSION" and value:
            group = {self.open_session(value)}
        elif kind == "PROJECT" and not value:
            group = set(self.sessions())
        elif kind == "WORKSTREAM" and not value and task and ws:
            group = self.participants(task, ws)
        elif kind == "TASK" and not value and task and not ws:
            group = self.participants(task)
        elif kind == "AGENT" and value in ("ASTRA", "GEMINI"):
            pool = self.participants(task, ws) if task else self.sessions()
            group = {s for s in pool if self.session_meta(s)["agent"] == value}
        else:
            raise ValueError("Invalid target or route scope")
        group = {s for s in group if self.session_meta(s)["open"]}
        if kind == "AGENT":
            require(
                len(group) <= 1 or all_agents is True,
                "Ambiguous agent; select a session or explicitly request all",
            )
        require(group, "No registered open recipient")
        return sorted(group)

    def send(self, legacy_key=None, fixed_group=None):
        q = self.req
        task, ws = q.get("task"), q.get("ws")
        bucket = area(task, ws)
        target = q.get("target", "")
        require(isinstance(target, str) and target, "A route is required")
        key = legacy_key or ident("key", q.get("key"))
        logical = "M-" + snapshot_id(self.actor, key)
        rel = ".ai/sync/sends/" + logical + ".json"
        text = q.get("body")
        require(isinstance(text, str) and text.strip(), "Supply Why, Message and Action")
        kind = q.get("type", "UPDATE")
        signature = sha(packed([target, task, ws, kind, text, q.get("all", False)]))
        if self.path(rel).is_file():
            saved = json.loads(self.path(rel).read_bytes())
            require(saved["signature"] == signature, "Same send key used for different content")
            return saved
        if task:
            require(self.path(tfile(task, ws)).is_file(), "Unknown task/workstream")
        group = self.resolve(target, task, ws, q.get("all")) if fixed_group is None else fixed_group
        stamp = utc()
        bid = "B-" + logical[2:] if target in ("PROJECT", "TASK", "WORKSTREAM") or len(group) > 1 else None
        deliveries = {}
        for sid in group:
            did = "D-" + snapshot_id(logical, sid)
            deliveries[sid] = did
            meta = {
                "message_id": logical,
                "broadcast_id": bid,
                "delivery_id": did,
                "target": target,
                "from_session": self.actor,
                "from_agent": self.session_meta(self.actor)["agent"],
                "to_session": sid,
                "to_agent": self.session_meta(sid)["agent"],
                "scope": "WORKSTREAM"
                if ws
                else "TASK"
                if task
                else "PROJECT"
                if target == "PROJECT"
                else "SESSION",
                "task_id": task,
                "workstream_id": ws,
                "type": kind,
                "status": "PENDING",
                "created_at": stamp,
            }
            self.tx.put(inbox(sid) + "/" + bucket + "/" + did + ".md", doc(meta, text))
        saved = {
            "message_id": logical,
            "broadcast_id": bid,
            "deliveries": deliveries,
            "signature": signature,
            "created_at": stamp,
        }
        self.tx.put(rel, packed(saved))
        return saved

    def envelopes(self, sid, buckets):
        items = []
        for bucket in buckets:
            for p in sorted(self.path(inbox(sid) + "/" + bucket).glob("D-*.md")):
                rel = p.relative_to(self.root).as_posix()
                m = header(self.path(rel))
                require(
                    m["to_session"] == sid and area(m["task_id"], m["workstream_id"]) == bucket,
                    "Misfiled delivery",
                )
                items.append({"meta": m, "body": content(self.path(rel))})
        return items

    def read_work(self, task, ws=None):
        rel = tfile(task, ws)
        p = self.path(rel)
        require(p.is_file(), "Unknown task/workstream")
        with p.open("rb") as stream:
            managed = stream.readline() == b"---\n"
        if self.req.get("blind"):
            with p.open(encoding="utf-8-sig") as stream:
                if managed:
                    for _ in range(3):
                        next(stream)
                pieces = []
                for line in stream:
                    if re.match(r"^## (Result|Review)\b", line):
                        break
                    pieces.append(line)
            body = "".join(pieces)
        else:
            body = content(p) if managed else p.read_text(encoding="utf-8-sig")
        if managed:
            return {"meta": header(p), "body": body}
        require(not ws, "Unrecognized workstream")
        return {
            "legacy_task": task,
            "body": body,
            "note": "Existing v0.1 contract preserved. Adopt explicitly before automated participation.",
        }

    def context(self):
        q = self.req
        level = q.get("level")
        require(level in ("L1", "L2", "L3"), "Choose L1, L2 + task, or L3 + prior session")
        out = {"level": level, "project": self.project()}
        if level == "L1":
            return out
        task, ws = q.get("task"), q.get("ws")
        prior = q.get("from")
        if level == "L3":
            self.session_meta(prior)
            if self.actor:
                require(
                    self.session_meta(self.actor)["resumes_from"] == prior,
                    "Select the checkpoint linked to this successor",
                )
            folder = self.path(".ai/sessions/" + ident("session", prior) + "/checkpoints")
            options = sorted(p.stem for p in folder.glob("*.md"))
            if q.get("slice") == "PROJECT":
                require(not task and not ws, "Project checkpoint cannot be combined with task/stream")
            elif not task and not ws:
                if len(options) != 1:
                    out["select_checkpoint"] = options
                    return out
                bucket = options[0]
                if bucket != "PROJECT":
                    task, _, ws = bucket.partition("~")
            bucket = area(task, ws)
            require(bucket in options, "No such checkpoint; select an available task/workstream")
            cp = self.path(checkpoint(prior, task, ws))
            out["checkpoint"] = content(cp)
        else:
            ident("task", task)
        if task:
            out["task"] = self.read_work(task)
            names = self.streams(task) if level == "L2" and not ws else []
            if not ws and names:
                mine = [n for n in names if self.actor and self.record(task, n)["owner"] == self.actor]
                if len(mine) == 1:
                    ws = mine[0]
                else:
                    out["select_workstream"] = mine or names
            if ws:
                out["workstream"] = self.read_work(task, ws)
            if self.actor and not q.get("blind"):
                buckets = [area(task)]
                if ws:
                    buckets.append(area(task, ws))
                out["messages"] = self.envelopes(self.actor, buckets)
        return out

    def ack(self):
        q = self.req
        if q.get("level") == "L1":
            raise ValueError("L1 has no inbox")
        task, ws = q.get("task"), q.get("ws")
        bucket = area(task, ws)
        require(q.get("level") in ("L2", "L3"), "Select an active task context")
        require(
            task or q.get("explicit_notifications") is True,
            "Unscoped notifications require explicit scope expansion",
        )
        did = ident("delivery", q.get("delivery"))
        receipt = ".ai/sync/receipts/" + self.actor + "/" + did + ".json"
        if self.path(receipt).is_file():
            already = json.loads(self.path(receipt).read_bytes())
            require(already["area"] == bucket, "Wrong context for receipt")
            return already
        rel = inbox(self.actor) + "/" + bucket + "/" + did + ".md"
        m = header(self.path(rel))
        require(
            m["delivery_id"] == did
            and m["to_session"] == self.actor
            and area(m["task_id"], m["workstream_id"]) == bucket,
            "Wrong delivery",
        )
        evidence = q.get("outcome")
        require(
            isinstance(evidence, str) and evidence.strip(),
            "Record an outcome or durable evidence reference",
        )
        saved = {"delivery": did, "area": bucket, "handled_at": utc(), "outcome": evidence}
        self.tx.put(receipt, packed(saved))
        self.tx.put(rel, None)
        return saved

    def takeover(self):
        q = self.req
        old = q.get("from")
        require(
            q.get("approved") is True
            and self.session_meta(self.actor)["resumes_from"] == old
            and old != self.actor,
            "Explicit takeover by the successor session required",
        )
        task, ws = q.get("task"), q.get("ws")
        ident("task", task)
        m = self.record(task, ws)
        request_key = ident("key", q.get("key"))
        log = ".ai/sessions/" + self.actor + "/transfers/" + request_key + ".json"
        sig = [old, task, ws]
        if self.path(log).exists():
            previous = json.loads(self.path(log).read_bytes())
            require(previous["scope"] == sig, "Transfer key reused")
            return previous
        require(
            m["revision"] == q.get("revision") and old in self.members(m),
            "Stale ownership or unrelated source",
        )
        if old == m["owner"] and m["status"] == "IN_PROGRESS" and m.get("code_root"):
            require(
                m["code_root"] == str(self.code), "Take over from the checkout containing the active work"
            )
            self.writer_claim(task, ws, old, m["code_root"], False)
            self.writer_claim(task, ws, self.actor, m["code_root"], True)
        for k in ("owner", "reviewer"):
            if m[k] == old:
                m[k] = self.actor
        require(m["owner"] != m["reviewer"], "Takeover would cause self-review; resolve assignment first")
        m["participants"] = sorted({self.actor if s == old else s for s in m["participants"]})
        m["revision"] += 1
        rp = tfile(task, ws)
        self.tx.put(rp, doc(m, content(self.path(rp))))
        moved = []
        bucket = area(task, ws)
        for item in self.envelopes(old, [bucket]):
            meta = item["meta"]
            original = meta["delivery_id"]
            did = "D-" + snapshot_id(original, self.actor)
            meta.update(
                delivery_id=did,
                to_session=self.actor,
                to_agent=self.session_meta(self.actor)["agent"],
                transferred_from=original,
            )
            self.tx.put(inbox(self.actor) + "/" + bucket + "/" + did + ".md", doc(meta, item["body"]))
            self.tx.put(inbox(old) + "/" + bucket + "/" + original + ".md", None)
            self.tx.put(
                ".ai/sync/receipts/" + old + "/" + original + ".json",
                packed({"delivery": original, "area": bucket, "transferred_to": did}),
            )
            moved.append(did)
        result = {"scope": sig, "moved": moved, "revision": m["revision"]}
        self.tx.put(log, packed(result))
        return result

    def lifecycle(self):
        q = self.req
        op = q["op"]
        if op == "checkpoint":
            task, ws = q.get("task"), q.get("ws")
            body = q.get("body")
            require(
                isinstance(body, str) and body.strip(),
                "Checkpoint needs scoped observations and next action",
            )
            if task:
                require(self.path(tfile(task, ws)).is_file(), "Unknown task/stream")
            rel = checkpoint(self.actor, task, ws)
            self.tx.put(rel, doc({"session": self.actor, "task": task, "ws": ws, "time": utc()}, body))
            return {"checkpoint": rel}
        if op == "close":
            require(q.get("approved") is True, "Close explicitly; terminal exit does not close a session")
            pending = sum(1 for _ in self.path(inbox(self.actor)).glob("*/D-*.md"))
            require(
                not pending or q.get("retain_pending") is True,
                f"{pending} pending deliveries; hand off or explicitly retain",
            )
            m = self.session_meta(self.actor)
            m.update(open=False, closed_at=utc())
            self.tx.put(sfile(self.actor), doc(m))
            return {"closed": self.actor, "pending_retained": pending}
        return self.takeover()

    def dispatch(self):
        q = self.req
        op = q["op"]
        if op == "register":
            return self.register()
        if op == "context" and q.get("level") == "L1":
            return self.context()
        if op == "attach":
            require(
                self.code != self.root and q.get("approved") is True,
                "Explicit user approval for existing linked worktree required",
            )
            rel = ".ai/workspaces/" + sha(str(self.code).encode()) + ".json"
            self.tx.put(rel, packed({"code_root": str(self.code), "state_root": str(self.root)}))
            return {"code_root": str(self.code), "state_root": str(self.root)}
        if op == "context":
            if q.get("actor"):
                self.authenticate()
            return self.context()
        if op == "sessions":
            require(q.get("explicit") is True, "List only when explicitly managing collaboration")
            return [{"id": s, "open": self.session_meta(s)["open"]} for s in self.sessions()]
        if op == "recover":
            return {"recovered": True}
        if op != "publish-fact" or (q.get("actor") and q.get("level") != "L1"):
            self.authenticate()
        if op in ("worker-submit", "worker-status", "worker-result"):
            from astra_worker import request
            return request(self)
        if op in ("create-task", "create-stream", "progress", "assign", "revise", "user-accept"):
            return self.work()
        if op == "publish-fact":
            name = q.get("file")
            require(
                name in ("SPEC.md", "DECISIONS.md") and q.get("approved") is True and q.get("approval"),
                "Publish user-confirmed project facts only, with approval source",
            )
            rel = self.docs + name
            path = self.path(rel)
            expected = sha(path.read_bytes()) if path.exists() else None
            require("expected_sha256" in q and q["expected_sha256"] == expected, "Stale fact revision")
            require(isinstance(q.get("body"), str) and q["body"].strip(), "Provide the full approved text")
            data = q["body"].encode()
            self.tx.put(rel, data)
            return {"file": rel, "sha256": sha(data)}
        if op == "delivery-status":
            logical = "M-" + snapshot_id(self.actor, ident("key", q.get("key")))
            sent = json.loads(self.path(".ai/sync/sends/" + logical + ".json").read_bytes())
            states = {}
            for sid, did in sent["deliveries"].items():
                receipt = self.path(".ai/sync/receipts/" + sid + "/" + did + ".json")
                if receipt.exists():
                    info = json.loads(receipt.read_bytes())
                    state = "transferred" if "transferred_to" in info else "handled"
                else:
                    state = "delivered"
                states[sid] = state
            return states
        if op == "transfer-notifications":
            old = ident("session", q.get("from"))
            require(
                q.get("approved") is True
                and q.get("explicit_notifications") is True
                and self.session_meta(self.actor)["resumes_from"] == old,
                "Approve specific unscoped deliveries and successor",
            )
            moved = {}
            for did in q.get("deliveries", []):
                ident("delivery", did)
                oldrel = inbox(old) + "/PROJECT/" + did + ".md"
                receipt = ".ai/sync/receipts/" + old + "/" + did + ".json"
                new = "D-" + snapshot_id(did, self.actor)
                if self.path(receipt).is_file():
                    require(
                        json.loads(self.path(receipt).read_bytes()).get("transferred_to") == new,
                        "Previously handled elsewhere",
                    )
                else:
                    oldpath = self.path(oldrel)
                    meta = header(oldpath)
                    require(meta["to_session"] == old and not meta["task_id"], "Wrong notification")
                    meta.update(
                        to_session=self.actor,
                        to_agent=self.session_meta(self.actor)["agent"],
                        delivery_id=new,
                        transferred_from=did,
                    )
                    self.tx.put(inbox(self.actor) + "/PROJECT/" + new + ".md", doc(meta, content(oldpath)))
                    self.tx.put(oldrel, None)
                    self.tx.put(
                        receipt, packed({"delivery": did, "area": "PROJECT", "transferred_to": new})
                    )
                moved[did] = new
            require(moved, "Specify the affected delivery IDs")
            return moved
        if op == "transfer-preview":
            old = ident("session", q.get("from"))
            require(
                q.get("approved") is True and self.session_meta(self.actor)["resumes_from"] == old,
                "Approve inspecting the selected predecessor's routing metadata",
            )
            bucket = area(q.get("task"), q.get("ws"))
            require(
                bucket != "PROJECT" or q.get("explicit_notifications") is True,
                "Select unscoped notifications explicitly",
            )
            return [header(p) for p in sorted(self.path(inbox(old) + "/" + bucket).glob("D-*.md"))]
        if op == "adopt-task":
            task = ident("task", q.get("task"))
            path = self.path(tfile(task))
            require(
                q.get("approved") is True and sha(path.read_bytes()) == q.get("expected_sha256"),
                "Approve the exact legacy task before adoption",
            )
            with path.open("rb") as f:
                require(f.readline() != b"---\n", "Already managed")
            original = path.read_bytes()
            self.tx.put(".ai/legacy/task-backups/" + task + "-" + sha(original) + ".md", original)
            owner = self.open_session(q["owner"])
            m = {
                "task": task,
                "ws": None,
                "owner": owner,
                "reviewer": q.get("reviewer"),
                "participants": [],
                "revision": 1,
                "status": q["status"],
            }
            require(
                m["status"]
                in ("READY", "IN_PROGRESS", "IMPLEMENTED", "ACCEPTED", "REWORK", "CANCELLED", "BLOCKED"),
                "Confirm existing task status",
            )
            require(m["reviewer"] != owner, "Self-review is not independent")
            if m["reviewer"] not in (None, "User"):
                self.open_session(m["reviewer"])
            self.tx.put(tfile(task), doc(m, original.decode("utf-8-sig")))
            return m
        if op in ("close", "checkpoint", "takeover"):
            return self.lifecycle()
        if op == "send":
            return self.send()
        if op == "ack":
            return self.ack()
        if op == "notifications":
            require(
                q.get("explicit_notifications") is True and q.get("level") in ("L2", "L3"),
                "Explicit non-L1 scope expansion required",
            )
            return self.envelopes(self.actor, ["PROJECT"])
        if op.startswith("legacy-"):
            return legacy(self)
        raise ValueError("Unknown operation: " + op)


def legacy(rt):
    """Inventory runs only on operator request. Old markdown had no guaranteed entry delimiter."""
    q = rt.req
    require(q.get("explicit") is True, "Explicit legacy administration required")
    side = q.get("side")
    require(side in ("astra", "gemini"), "Select old recipient side")
    rel = ".ai/sync/to-" + side + ".md"
    source = rt.path(rel)
    data = source.read_bytes()
    digest = sha(data)
    archive = ".ai/legacy/pending/" + side + "/" + digest + ".md"
    ledger = ".ai/legacy/resolved/" + side + "/" + digest
    labels = ".ai/legacy/classified/" + side + "/" + digest
    resolved = [json.loads(p.read_bytes()) for p in rt.path(ledger).glob("*.json")]
    classified = [json.loads(p.read_bytes()) for p in rt.path(labels).glob("*.json")]
    pin = ".ai/legacy/pending/" + side + "/source.json"
    if rt.path(pin).exists():
        require(
            json.loads(rt.path(pin).read_bytes())["sha256"] == digest,
            "Legacy source changed after backup; reconcile manually before delivery",
        )
    if q["op"] == "legacy-inventory":
        rt.tx.put(pin, packed({"sha256": digest}))
        rt.tx.put(archive, data)
        lines = data.decode("utf-8-sig").splitlines()
        candidates = [
            i
            for i, l in enumerate(lines, 1)
            if re.match(r"^(?:#{1,4}\s+|[-*]\s+)(?:ID\b|M[-0-9]|(?:19|20)[0-9]{2}-)", l, re.I)
        ]
        pending = []
        start = 1
        for rec in sorted(resolved, key=lambda r: r["first"]):
            if start < rec["first"]:
                pending.append([start, rec["first"] - 1])
            start = rec["last"] + 1
        if start <= len(lines):
            pending.append([start, len(lines)])
        return {
            "source": rel,
            "sha256": digest,
            "pending_copy": archive,
            "lines": len(lines),
            "pending_ranges": pending,
            "classifications": classified,
            "suggested_starts": candidates,
            "note": "Candidate boundaries require user review.",
        }
    require(
        rt.path(archive).is_file() and q.get("expected_sha256") == digest,
        "Inventory/backup this exact source first",
    )
    lines = data.decode("utf-8-sig").splitlines(keepends=True)
    lo, hi = q.get("first", 0), q.get("last", 0)
    require(
        isinstance(lo, int) and isinstance(hi, int) and 1 <= lo <= hi <= len(lines), "Invalid line range"
    )
    if q["op"] == "legacy-preview":
        return {"first": lo, "last": hi, "body": "".join(lines[lo - 1 : hi])}
    require(
        q["op"] in ("legacy-deliver", "legacy-classify") and q.get("approved") is True,
        "Confirm exact legacy entry",
    )
    task, ws = q.get("task"), q.get("ws")
    if task:
        require(rt.path(tfile(task, ws)).is_file(), "Unknown task/stream")
    label = labels + "/" + str(lo) + "-" + str(hi) + ".json"
    for item in classified:
        if item["last"] >= lo and item["first"] <= hi:
            require(
                (item["first"], item["last"]) == (lo, hi),
                "Overlaps a classification with different boundaries",
            )
            if q["op"] == "legacy-deliver":
                require((item["task"], item["ws"]) == (task, ws), "Scope differs from classification")
    request_target = q.get("recipients") or ([q["recipient"]] if q.get("recipient") else [])
    if q.get("approved_task_broadcast") is True:
        require(
            task and not request_target, "Select either confirmed task broadcast or explicit recipients"
        )
        destination = "TASK-BROADCAST"
    else:
        require(isinstance(request_target, list), "Specify recipient session IDs")
        destination = sorted(set(ident("session", sid) for sid in request_target))
    for record in resolved:
        if record["last"] >= lo and record["first"] <= hi:
            require(
                q["op"] == "legacy-deliver"
                and (record["first"], record["last"], record["destination"], record["task"], record["ws"])
                == (lo, hi, destination, task, ws),
                "Already migrated overlapping source range",
            )
            return record
    if q["op"] == "legacy-classify":
        require(task and not destination, "Classification only records the task/stream")
        item = {"first": lo, "last": hi, "task": task, "ws": ws}
        rt.tx.put(label, packed(item))
        return item
    require(destination and not q.get("all"), "Confirm specific recipients; no implicit broadcasting")
    require(
        task or q.get("explicit_notifications") is True, "Confirm that this old entry is an unscoped notice"
    )
    if destination == "TASK-BROADCAST":
        route = "WORKSTREAM" if ws else "TASK"
        group = rt.resolve(route, task, ws, False)
    else:
        group = [rt.open_session(s) for s in destination]
        require(
            all(rt.session_meta(s)["agent"].lower() == side for s in group), "Wrong agent for old inbox"
        )
        route = "SESSION:" + group[0] if len(group) == 1 else "EXPLICIT-SESSIONS"
    q.update(target=route, type="LEGACY", body="".join(lines[lo - 1 : hi]))
    result = rt.send("legacy-" + snapshot_id(side, digest, lo, hi), fixed_group=group)
    rec = {"first": lo, "last": hi, "task": task, "ws": ws, "destination": destination, "send": result}
    if rt.path(label).exists():
        rt.tx.put(label, None)
    rt.tx.put(ledger + "/" + str(lo) + "-" + str(hi) + ".json", packed(rec))
    return rec


READS = {"context", "sessions", "notifications", "legacy-preview", "delivery-status", "transfer-preview",
         "worker-status", "worker-result"}


def run(primary, code, request):
    op = request.get("op")
    require(isinstance(op, str), "Missing op")
    require(
        request.get("workspace", "shared") in ("shared", "readonly", "isolated"), "Unknown workspace mode"
    )
    require(
        request.get("workspace") != "isolated" or code != primary,
        "Isolated mode requires an attached worktree",
    )
    if request.get("level") == "L1":
        require(op in ("context", "publish-fact"), "L1 never uses an actor or inbox")
    manifest = json.loads(under(primary, ".ai/dual-collab.json").read_bytes())
    require(
        manifest.get("version") == VERSION and Path(manifest["root"]) == primary,
        "Initialize or explicitly upgrade the primary checkout",
    )
    if code != primary and op != "attach":
        rel = ".ai/workspaces/" + sha(str(code).encode()) + ".json"
        pointer = under(primary, rel)
        require(pointer.is_file(), "Attach this existing worktree with user approval first")
        require(
            json.loads(pointer.read_bytes()) == {"code_root": str(code), "state_root": str(primary)},
            "Worktree registration differs; inspect before proceeding",
        )
    tx = Transaction(primary)
    rt = Runtime(primary, code, request, tx, manifest)
    if op == "context" and request.get("level") == "L1":
        return rt.context()
    writable = op not in READS
    require(not writable or request.get("workspace") != "readonly", "Strictly read-only; mutation refused")
    with lock_state(primary, writable):
        if under(primary, JOURNAL).exists():
            require(
                writable and request.get("level") != "L1",
                "Interrupted transaction: use recover in an authorized writable collaboration context",
            )
            tx.recover()
        result = rt.dispatch()
        require(writable or not tx.changes, "Read operation attempted a mutation")
        tx.commit()
        return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    try:
        root, code = resolve_roots(args.root)
        req = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        require(isinstance(req, dict), "Request must be a JSON object")
        result = run(root, code, req)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as err:
        print("ERROR:", err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
