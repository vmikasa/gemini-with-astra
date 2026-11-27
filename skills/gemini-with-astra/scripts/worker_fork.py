"""Immutable source points and explicit input selection for scoped Astra review branches."""
from hashlib import sha256
from contextlib import closing
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time


MAX_PACKET = 1024 * 1024
MAX_ROLLOUT = 16 * 1024 * 1024
BEFORE, AFTER = "before-review", "through-review"
LABELS = {"native": "原生 Fork", "materials": "基于材料新建 Worker"}


def check(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return sha256(data).hexdigest()


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def has(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def enable(db):
    db.execute("""CREATE TABLE fork_history (point TEXT PRIMARY KEY, thread TEXT, turn TEXT,
               filename TEXT, sha256 TEXT, rollout BLOB)""")


def save_origin(db, plan):
    db.execute("CREATE TABLE fork_origin (plan TEXT, native_confirmed INTEGER)")
    db.execute("INSERT INTO fork_origin VALUES (?,0)", (packed(plan).decode(),))


def origin(db):
    if has(db, "fork_origin"):
        plan, confirmed = db.execute("SELECT plan, native_confirmed FROM fork_origin").fetchone()
        return json.loads(plan), bool(confirmed)
    return None, False


def safe_name(name, thread):
    pat = r"sessions/\d{4}/\d{2}/\d{2}/rollout-[\dT-]+-" + re.escape(thread) + r"\.jsonl"
    return re.fullmatch(r"[0-9a-fA-F-]{36}", thread) and re.fullmatch(pat, name)


class Capture:
    """Keep exact native JSONL prefixes, ending at the matching native marker."""

    def __init__(self, db, home, thread):
        self.db = db
        self.thread = thread["id"]
        self.home = home
        self.path = Path(thread.get("path") or "")
        self.before = False
        self.next_read = 0

    def record(self, turn, finished=False):
        if not finished and (self.before or time.monotonic() < self.next_read):
            return False
        self.next_read = time.monotonic() + .25
        if self.path.resolve() != self.path or not self.path.is_relative_to(self.home):
            return False
        filename = self.path.relative_to(self.home).as_posix()
        if not safe_name(filename, self.thread):
            return False
        try:
            with self.path.open("rb") as stream:
                data = bytearray()
                found_start = False
                records = 0
                while len(data) < MAX_ROLLOUT:
                    line = stream.readline(MAX_ROLLOUT - len(data))
                    if not line.endswith(b"\n"):
                        break
                    item = json.loads(line)
                    payload = item["payload"]
                    if not data and (item["type"] != "session_meta" or payload.get("id") != self.thread):
                        return False
                    data.extend(line)
                    records += 1
                    if item["type"] != "event_msg" or payload.get("turn_id") != turn:
                        continue
                    if payload.get("type") == "task_started":
                        found_start = True
                        # The early point contains only session metadata and the start
                        # marker. Fail closed if a new format puts other content there.
                        if not self.before and records == 2:
                            self.save(BEFORE, turn, filename, data)
                            self.before = True
                        if not finished:
                            return self.before
                    if found_start and payload.get("type") == "task_complete" and finished:
                        self.save(AFTER, turn, filename, data)
                        return True
        except (OSError, ValueError, KeyError, TypeError):
            # Incomplete/unrecognized native history cannot be advertised as a checkpoint.
            return False
        return False

    def save(self, point, turn, filename, data):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO fork_history VALUES (?,?,?,?,?,?)",
                            (point, self.thread, turn, filename, digest(data), bytes(data)))


def materials(db, with_result=False):
    packet = json.loads(db.execute("SELECT packet FROM review").fetchone()[0])
    items = {"brief": packet["brief"]}
    items.update(("file:" + e["file"], e["text"]) for e in packet["evidence"])
    items.update(("inherited:" + e["id"], e["text"]) for e in packet.get("inherited", []))
    if with_result:
        raw = db.execute("SELECT result FROM review WHERE state='completed'").fetchone()
        check(raw is not None and isinstance(raw[0], str), "A completed original review is required")
        items["review"] = raw[0]
    return items


def inventory(db):
    retained = has(db, "fork_history")
    native = [row[0] for row in db.execute("SELECT point FROM fork_history ORDER BY rowid")] if retained else []
    state = db.execute("SELECT state FROM review").fetchone()[0]
    if state != "completed" and AFTER in native:
        native.remove(AFTER)
    result = {"materials": ["submission", "result"] if state == "completed" else ["submission"],
              "native": native, "history_retention": retained}
    if retained and state == "completed" and len(native) < 2:
        result["native_notice"] = "Only verified native checkpoints within the 16 MiB limit are available"
    return result


def describe_items(items):
    return [{"id": key, "sha256": digest(text.encode()), "bytes": len(text.encode())}
            for key, text in items.items()]


def plan(db, q, parent, scope):
    points = inventory(db)
    mode, point = q.get("mode"), q.get("point")
    check(mode in ("native", "materials") and point in points[mode], "Selected fork mode or source point is unavailable")
    check(not q.get("blind") or point not in ("result", AFTER), "Keep the parent review sealed until reveal")
    brief = q.get("brief")
    check(isinstance(brief, str) and brief.strip() and len(brief.encode()) <= MAX_PACKET,
          "Supply the approved branch question")
    selection = q.get("inherit")
    check(isinstance(selection, list) and all(isinstance(k, str) for k in selection)
          and len(set(selection)) == len(selection), "Select the exact materials to inherit")
    check(not q.get("blind") or not any(re.fullmatch(r"(?:inherited:)*review", k) for k in selection),
          "Keep inherited original reviews sealed until reveal")
    items = materials(db, point == "result")
    manifest = {"parent_job": parent, "scope": scope, "mode": mode, "label": LABELS[mode], "point": point, "brief": brief}
    if mode == "native":
        thread, turn, sha, size = db.execute(
            "SELECT thread,turn,sha256,length(rollout) FROM fork_history WHERE point=?", (point,)).fetchone()
        manifest["native"] = {"thread": thread, "turn": turn, "sha256": sha, "bytes": size}
    if point == AFTER:
        check(selection == ["native-history"], "This native checkpoint inherits the whole turn; select native-history")
        selected = {}
        manifest["inherit"] = [{"id": "native-history", "sha256": sha, "bytes": size}]
        manifest["original_inputs"] = describe_items(items)
        original = db.execute("SELECT result FROM review").fetchone()[0]
        manifest["original_review_sha256"] = digest(original.encode())
        receipts = db.execute("SELECT key,sender,basis,source,body,state FROM corrections WHERE turn=? ORDER BY rowid",
                              (turn,)).fetchall()
        manifest["steer_receipts"] = [{"key": key, "sender": sender, "basis": basis, "state": state,
                                       "sha256": digest(packed([source, body]))}
                                      for key, sender, basis, source, body, state in receipts]
        manifest["includes"] = ["turn inputs and steers", "native model and tool context", "original conclusion"]
    else:
        check(all(k in items for k in selection), "Material is unavailable at this point")
        selected = {k: items[k] for k in sorted(selection)}
        manifest["inherit"] = describe_items(selected)
    manifest["approval_sha256"] = digest(packed(manifest))
    packet = {"brief": brief, "evidence": [], "inherited": [{"id": k, "text": v} for k, v in selected.items()]}
    check(len(brief.encode()) + sum(len(v.encode()) for v in selected.values()) <= MAX_PACKET,
          "Selected branch materials exceed 1 MiB")
    return manifest, json.dumps(packet, ensure_ascii=False)


def restore_source(job_path, plan, home):
    native = plan["native"]
    parent = plan["parent_job"]
    check(re.fullmatch(r"W-[0-9a-f]{32}", parent), "Invalid parent job")
    source = job_path.with_name(parent + ".sqlite")
    check(source.is_file() and source == source.resolve(), "Approved native source is unavailable")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT thread,turn,filename,rollout FROM fork_history WHERE point=?",
                         (plan["point"],)).fetchone()
    check(row is not None, "Approved native source is unavailable")
    thread, turn, name, data = row
    check(thread == native["thread"] and turn == native["turn"] and safe_name(name, thread)
          and digest(data) == native["sha256"], "Approved native checkpoint changed")
    path = home.joinpath(*PurePosixPath(name).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    boundary = "beforeTurnId" if plan["point"] == BEFORE else "lastTurnId"
    return {"threadId": thread, boundary: turn, "excludeTurns": False}


def verify_history(thread, plan):
    native = plan["native"]
    check(thread.get("forkedFromId") == native["thread"] and thread.get("id")
          and thread["id"] != native["thread"], "Codex did not confirm the parent and an independent child")
    turns = thread.get("turns")
    if plan["point"] == BEFORE:
        check(turns == [], "Early branch unexpectedly contains a review turn")
        return
    check(isinstance(turns, list) and len(turns) == 1 and turns[0].get("id") == native["turn"]
          and turns[0].get("status") == "completed", "Codex did not restore the approved completed turn")
    messages = [item["text"] for item in turns[0].get("items", []) if item.get("type") == "agentMessage"
                and item.get("phase") in (None, "final_answer")]
    check(messages and digest(messages[-1].encode()) == plan["original_review_sha256"],
          "Restored conclusion differs from the approved original")
