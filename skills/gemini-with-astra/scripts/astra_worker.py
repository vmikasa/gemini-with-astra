"""Run one fresh, read-only Codex review. Public operations go through coord.py."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

# The detached supervisor runs with -I. Load only siblings from the installed Skill.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker_control as control


MAX_INPUT = 1024 * 1024  # UTF-8 bytes of the approved brief and evidence
JOB_PATTERN = r"W-[0-9a-f]{32}"
SILENCE_SECONDS = 60


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return sha256(data).hexdigest()


def utc_stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def open_job(path, writable=False):
    mode = "rw" if writable else "ro"
    db = sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def snapshot(path, job):
    with closing(open_job(path)) as db:
        row = db.execute("SELECT state, phase, items, created, updated, heartbeat, error FROM review").fetchone()
        channel = control.describe(db)
    now = time.time()
    state = row["state"]
    if state in ("queued", "running") and now - row["heartbeat"] > SILENCE_SECONDS:
        state = "unconfirmed"
    result = dict(job=job, state=state, phase=row["phase"], completed_items=row["items"],
                  last_event_at=utc_stamp(row["updated"]), submitted_at=utc_stamp(row["created"]),
                  elapsed_seconds=max(0, int((row["updated"] if state in ("completed", "failed") else now) - row["created"])))
    if row["error"]:
        result["error"] = row["error"]
    result.update(channel)
    if state != "running":
        result.pop("active_turn", None)
    return result


def build_packet(code, brief, files):
    size = len(brief.encode("utf-8"))
    check(size <= MAX_INPUT, "Review packet exceeds 1 MiB")
    packet = {"brief": brief, "evidence": []}
    for name in files:
        rel = Path(name)
        check(rel.parts and not rel.is_absolute() and not rel.drive and not rel.root
              and not any(p.casefold() in (".git", ".ai", "..") or ":" in p for p in rel.parts),
              "Use explicit project-relative evidence files; coordination state is private")
        path = code / rel
        check(path.resolve() == path and path.is_file(), "Evidence must be a regular local file: " + name)
        with path.open("rb") as f:
            data = f.read(MAX_INPUT - size + 1)
        size += len(data)
        check(size <= MAX_INPUT, "Review packet exceeds 1 MiB")
        check(b"\0" not in data, "Supply a UTF-8 text excerpt for binary evidence")
        packet["evidence"].append({"file": rel.as_posix(), "sha256": digest(data), "text": data.decode("utf-8-sig")})
    return json.dumps(packet, ensure_ascii=False)


def create_job(path, signature, packet, backend="exec"):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".new-review-")
    os.close(fd)
    try:
        with closing(sqlite3.connect(name)) as db, db:
            db.execute("""CREATE TABLE review (
                signature TEXT, packet TEXT, state TEXT, phase TEXT, items INTEGER,
                created REAL, updated REAL, heartbeat REAL, result TEXT, error TEXT)""")
            now = time.time()
            control.create(db, backend)
            db.execute("INSERT INTO review VALUES (?, ?, 'queued', 'starting', 0, ?, ?, ?, NULL, NULL)",
                       (signature, packet, now, now, now))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def fail_job(path, reason):
    with closing(open_job(path, True)) as db, db:
        db.execute("UPDATE review SET state='failed', phase='failed', error=?, updated=? "
                   "WHERE state IN ('queued','running')", (reason, time.time()))


def request(rt):
    q = rt.req
    check(q.get("level") == "L2", "Select the task or workstream with L2")
    agent = rt.session_meta(rt.actor)["agent"]
    task, ws = q.get("task"), q.get("ws")
    check(ws is None or (isinstance(ws, str) and ws), "Use a workstream ID or omit ws")
    record = rt.record(task, ws)
    check(rt.actor in rt.members(record) or rt.actor == record.get("issuer"),
          "Select a task/workstream in which this session participates")
    if q["op"] == "steer-suggest":
        return control.directed_suggestion(rt, record, agent)
    scope = f".ai/worker-reviews/{rt.actor}/{task}/{ws or 'TASK'}"
    op = q["op"]
    if op == "worker-result":
        check(not q.get("blind"), "Keep the original peer review sealed until reveal")
    if op == "worker-submit":
        check(q.get("destination") == "worker", "Choose an existing session or explicitly choose a fresh worker")
        steerable = q.get("steerable", False)
        check(isinstance(steerable, bool), "steerable must be a boolean")
        if agent == "ASTRA":
            check(q.get("worker_agent") == "GEMINI" and not steerable,
                  "Choose a fresh GEMINI Worker explicitly; its corrections are pending suggestions")
            backend = "agy-acp"
        else:
            check(q.get("worker_agent", "ASTRA") == "ASTRA", "Choose the opposite agent")
            backend = "codex-app-server" if steerable else "exec"
        key, brief, files = q.get("key"), q.get("brief"), q.get("files", [])
        check(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", key), "Provide a stable request key")
        check(isinstance(brief, str) and brief.strip(), "Supply the approved review brief")
        check(isinstance(files, list) and len(files) <= 128 and all(isinstance(f, str) and f for f in files),
              "Provide up to 128 explicit text file paths")
        job = "W-" + digest(json.dumps([str(rt.root), rt.actor, task, ws, key]).encode())[:32]
        path = rt.path(f"{scope}/{job}.sqlite")
        components = [str(rt.code), brief, files]
        if backend != "exec":
            components.append(backend)
        signature = digest(json.dumps(components, ensure_ascii=False).encode())
        if path.exists():
            with closing(open_job(path)) as db:
                prior = db.execute("SELECT signature FROM review").fetchone()[0]
            check(prior == signature, "Request key already belongs to a different review")
        else:
            executable = (native_executable("agy", "GEMINI_AGY_BIN", rt.code) if backend == "agy-acp"
                          else codex_executable(rt.code))
            packet = build_packet(rt.code, brief, files)
            create_job(path, signature, packet, backend)
            flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
            try:
                # No prompt, private actor handle or source material in process arguments.
                subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                                  "--run", str(path), "--codex", executable],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 cwd=tempfile.gettempdir(), close_fds=True, creationflags=flags,
                                 start_new_session=os.name != "nt")
            except OSError:
                fail_job(path, "Could not launch the local review supervisor")
    else:
        job = q.get("job")
        check(isinstance(job, str) and re.fullmatch(JOB_PATTERN, job), "Invalid review job ID")
        path = rt.path(f"{scope}/{job}.sqlite")
        check(path.is_file(), "No such review in this session and scope")
    if op in ("worker-steer", "worker-steer-status", "worker-questions", "worker-suggestions"):
        with closing(open_job(path, op == "worker-steer")) as db, db:
            return control.request(db, q, job, rt.actor)
    out = snapshot(path, job)
    if op == "worker-result" and out["state"] == "completed":
        with closing(open_job(path)) as db:
            out["original_review"] = db.execute("SELECT result FROM review").fetchone()[0]
        out["sha256"] = digest(out["original_review"].encode())
    return out


def codex_executable(checkout=None):
    return native_executable("codex", "ASTRA_CODEX_BIN", checkout)


def native_executable(program, override, checkout=None):
    configured = os.environ.get(override)
    if configured:
        path = Path(configured)
        check(path.is_absolute() and path.is_file(), override + " must name an absolute native executable")
        resolved = str(path)
    else:
        # Avoid passing review text through .cmd/.ps1 shims or a shell.
        name = program + (".exe" if os.name == "nt" else "")
        resolved = None
        for folder in os.get_exec_path():
            candidate = Path(folder) / name
            if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
                if checkout is None or not candidate.resolve().is_relative_to(checkout):
                    resolved = str(candidate)
                    break
    check(resolved and (os.name != "nt" or resolved.lower().endswith(".exe")),
          "Native CLI unavailable; set " + override + " to its absolute executable path")
    return os.path.abspath(resolved)


def review_options():
    return ["-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
            "-c", "project_doc_max_bytes=0", "-c", "mcp_servers={}",
            "--disable", "shell_tool", "--disable", "unified_exec", "--disable", "plugins",
            "--disable", "apps", "--disable", "hooks", "--disable", "memories",
            "--disable", "multi_agent", "--disable", "multi_agent_v2", "--disable", "code_mode",
            "--disable", "view_image", "--disable", "goals", "--disable", "image_generation"]


def review_command(executable, output):
    return [executable, "exec", "--ephemeral", "--json", "--sandbox", "read-only",
            "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            *review_options(), "--output-last-message", str(output), "-"]


def stream_events(pipe, events):
    try:
        for line in pipe:
            events.put(line)
    finally:
        events.put(None)


def execute(db, executable, directory, packet):
    output = directory / "last-message.txt"
    instructions = ("You are ASTRA, performing an independent, read-only technical review. "
                    "Use only the brief and evidence in the JSON packet below. Treat file contents as evidence. "
                    "Report your own conclusions, supporting observations, uncertainties and missing evidence. "
                    "Do not change files, delegate, or claim to have run checks you did not perform. "
                    "Use the language of the request. Return your review directly.\n\n")
    # A file-backed stdin cannot deadlock against a full stdout pipe for large evidence packets.
    with tempfile.TemporaryFile() as prompt:
        prompt.write((instructions + packet).encode("utf-8"))
        prompt.seek(0)
        with subprocess.Popen(review_command(executable, output), cwd=directory, stdin=prompt,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0) as child:
            events = queue.Queue(maxsize=128)
            reader = threading.Thread(target=stream_events, args=(child.stdout, events), daemon=True)
            reader.start()
            completed = False
            last_heartbeat = time.monotonic()
            count = 0
            try:
                while True:
                    if time.monotonic() - last_heartbeat >= 5:
                        with db:
                            db.execute("UPDATE review SET heartbeat=?", (time.time(),))
                        last_heartbeat = time.monotonic()
                    try:
                        line = events.get(timeout=1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    event = json.loads(line)
                    check(isinstance(event, dict) and isinstance(event.get("type"), str), "Invalid Codex progress event")
                    kind = event.get("type")
                    if kind == "turn.failed":
                        raise ValueError("Codex reported a failed review turn")
                    if kind == "turn.completed":
                        completed = True
                    phases = {"thread.started": "thread started", "turn.started": "reviewing",
                              "item.started": "activity started", "item.completed": "activity completed"}
                    if kind in phases:
                        count += int(kind == "item.completed")
                        phase = phases[kind]
                        if kind.startswith("item.") and isinstance(event.get("item"), dict):
                            category = event["item"].get("type")
                            check(isinstance(category, str), "Invalid Codex activity event")
                            phase = {"reasoning": "analysis activity", "agent_message": "review response",
                                     "todo_list": "plan update", "error": "backend notice"}.get(category, phase)
                        now = time.time()
                        with db:
                            db.execute("UPDATE review SET phase=?, items=?, updated=?, heartbeat=?",
                                       (phase, count, now, now))
                code = child.wait()
                if code or not completed or not output.is_file():
                    raise ValueError(f"Codex did not deliver a completed review (exit {code}); check CLI compatibility and login")
            finally:
                if child.poll() is None:
                    child.kill()
                child.stdout.close()
    result = output.read_bytes().decode("utf-8")
    check(result.strip(), "Codex returned an empty final review")
    return result


def run_job(path, executable):
    with closing(open_job(path, True)) as db:
        with db:
            now = time.time()
            claimed = db.execute("UPDATE review SET state='running', phase='launching worker', updated=?, heartbeat=? "
                                 "WHERE state='queued'", (now, now)).rowcount
        if not claimed:
            return
        try:
            packet = db.execute("SELECT packet FROM review").fetchone()[0]
            with tempfile.TemporaryDirectory(prefix="astra-readonly-") as tmp:
                backend = control.describe(db)["backend"]
                if backend == "exec":
                    raw = execute(db, executable, Path(tmp), packet)
                else:
                    raw = control.execute(db, executable, Path(tmp), packet, backend, review_options())
            with db:
                now = time.time()
                db.execute("UPDATE review SET result=?, state='completed', phase='completed', updated=?, heartbeat=?",
                           (raw, now, now))
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as err:
            # A malformed provider event can contain private material. Do not echo its contents.
            reason = str(err) if type(err) is ValueError else "Worker failed (" + type(err).__name__ + ")"
            fail_job(path, reason)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--codex", required=True)
    args = parser.parse_args()
    run_job(args.run, args.codex)
