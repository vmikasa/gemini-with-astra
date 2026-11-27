"""Behavioral tests for Gemini's scoped, asynchronous review lane."""
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_runtime as fixtures
import astra_worker as worker


class WorkerTests(unittest.TestCase):
    def setUp(self):
        # Use the normal registered sessions and two distinct tasks from the coordination suite.
        self.project = fixtures.RuntimeTests()
        self.project.setUp()
        self.addCleanup(self.project.doCleanups)
        self.gemini = self.project.g
        self.scope = dict(level="L2", task="T001")
        self.submission = dict(destination="worker", key="design-audit", brief="Compare two design options.",
                               files=["design.md"])
        (self.project.root / "design.md").write_text("Approved evidence A", encoding="utf-8")
        self.launch = self.enter_patch(patch("astra_worker.subprocess.Popen"))
        self.enter_patch(patch("astra_worker.codex_executable", return_value=sys.executable))

    def enter_patch(self, item):
        mocked = item.start()
        self.addCleanup(item.stop)
        return mocked

    def submit(self, **changes):
        args = {**self.scope, **self.submission, **changes}
        return self.project.call("worker-submit", self.gemini, **args)

    def read(self, op, job, actor=None, **changes):
        return self.project.call(op, actor or self.gemini, job=job, workspace="readonly", **dict(self.scope, **changes))

    def path(self):
        command = self.launch.call_args.args[0]
        return Path(command[command.index("--run") + 1])

    def test_choice_new_job_scope_and_retry(self):
        for changes in ({"destination": None}, {"destination": "main"}, {"level": "L1"}, {"workspace": "readonly"}):
            with self.assertRaises(ValueError):
                self.submit(**changes)
        self.launch.assert_not_called()
        receipt = self.submit()
        (self.project.root / "design.md").write_text("Changed after submission", encoding="utf-8")
        self.assertEqual(receipt["job"], self.submit()["job"])
        with self.assertRaisesRegex(ValueError, "different review"):
            self.submit(brief="Another independent question")
        self.launch.assert_called_once()
        self.assertNotIn(self.gemini["actor"], str(self.launch.call_args))
        self.assertNotIn("original_review", self.read("worker-status", receipt["job"]))
        with self.assertRaisesRegex(ValueError, "sealed"):
            self.read("worker-result", receipt["job"], blind=True)
        with closing(worker.open_job(self.path())) as db:
            packet = db.execute("SELECT packet FROM review").fetchone()[0]
        self.assertIn("Approved evidence A", packet)
        self.assertNotIn("T001 contract", packet)
        self.assertNotIn("Changed after", packet)
        other = self.project.call("register", agent="GEMINI")
        for actor, extra in [(self.project.a, {}), (other, {}), (self.gemini, {"task": "T002"})]:
            with self.assertRaises(ValueError):
                self.read("worker-result", receipt["job"], actor, **extra)
        self.assertEqual(self.project.check(self.gemini)["task"]["meta"]["status"], "READY")

    def test_files_are_explicit_and_scoped(self):
        for name in ("../other", ".ai/dual-collab.json", ".git/config", str(self.project.root / "design.md"), "."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.submit(files=[name])
        self.launch.assert_not_called()

    def test_workstream_uses_separate_receipt(self):
        self.project.call("create-stream", self.project.a, task="T001", ws="WS-EEG",
                          participants=[self.gemini["session"]], body="Review the EEG evidence")
        whole = self.submit()
        scoped = self.submit(ws="WS-EEG")
        self.assertNotEqual(whole["job"], scoped["job"])
        with self.assertRaisesRegex(ValueError, "No such review"):
            self.read("worker-result", scoped["job"])
        self.assertEqual(self.read("worker-status", scoped["job"], ws="WS-EEG")["job"], scoped["job"])

    def test_stale_supervisor_and_launch_failure_do_not_relaunch(self):
        self.launch.side_effect = OSError("failed to create process")
        failed = self.submit()
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(self.submit()["state"], "failed")
        self.launch.assert_called_once()
        self.launch.side_effect = None
        receipt = self.submit(key="second-attempt")
        with closing(worker.open_job(self.path(), True)) as db, db:
            db.execute("UPDATE review SET heartbeat=?", (time.time() - 120,))
        self.assertEqual(self.read("worker-status", receipt["job"])["state"], "unconfirmed")
        self.assertEqual(self.submit(key="second-attempt")["state"], "unconfirmed")
        self.assertEqual(self.launch.call_count, 2)

    def test_streaming_progress_repeatable_raw_result_and_failure(self):
        # Run the actual supervisor and stream parser with a deterministic child process.
        real_popen = REAL_POPEN
        root = self.project.root
        gate = root / "continue.fixture"
        script = root / "mock_backend.py"
        raw = "ASTRA 原文  \r\n不同意这项结论。\n"
        script.write_text(
            "import json,sys,time\nfrom pathlib import Path\n"
            "assert 'Approved evidence A' in sys.stdin.buffer.read().decode()\n"
            "assert not Path('design.md').exists()\n"
            "print(json.dumps({'type':'turn.started'}),flush=True)\n"
            "gate,out=map(Path,sys.argv[1:])\n"
            "while not gate.exists():time.sleep(.02)\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'irrelevant partial'}}),flush=True)\n"
            "out.write_bytes(" + repr(raw.encode()) + ")\n"
            "print(json.dumps({'type':'turn.completed'}),flush=True)\n", encoding="utf-8")
        receipt = self.submit()
        path = self.path()
        completed = []
        def runner():
            with patch.object(worker, "review_command", side_effect=lambda exe,out:[exe,str(script),str(gate),str(out)]):
                worker.run_job(path, sys.executable)
            completed.append(True)
        self.launch.side_effect = real_popen
        t = threading.Thread(target=runner)
        t.start()
        try:
            deadline = time.monotonic()+10
            while self.read("worker-status", receipt["job"])["phase"] != "reviewing":
                if time.monotonic() > deadline:
                    self.fail("No live turn progress")
                time.sleep(.03)
            self.assertNotIn("original_review", self.read("worker-result", receipt["job"]))
        finally:
            gate.touch()
            t.join(12)
        self.assertEqual(completed,[True])
        status=self.read("worker-status",receipt["job"])
        self.assertEqual((status["state"],status["completed_items"]),("completed",1))
        self.assertNotIn("original_review",status)
        for _ in range(2):
            result=self.read("worker-result",receipt["job"])
            self.assertEqual(result["original_review"],raw)
            self.assertEqual(result["sha256"],worker.digest(raw.encode()))
        self.assertEqual(self.project.check(self.gemini)["task"]["meta"]["status"], "READY")
        self.launch.side_effect = None
        bad = self.submit(key="bad")
        bad_path = self.path()
        self.launch.side_effect = real_popen
        with patch.object(worker,"review_command",return_value=[sys.executable,"-c","print('invalid JSON')"]):
            worker.run_job(bad_path, sys.executable)
        failure=self.read("worker-result",bad["job"])
        self.assertEqual(failure["state"],"failed")
        self.assertNotIn("original_review",failure)

    def test_command_selects_fresh_readonly_execution(self):
        cmd = worker.review_command("codex", Path("result.txt"))
        self.assertEqual(cmd[:2], ["codex","exec"])
        self.assertEqual(cmd[cmd.index("--sandbox")+1],"read-only")
        self.assertIn('approval_policy="never"',cmd)
        self.assertIn("--ephemeral",cmd)
        self.assertIn("--ignore-user-config",cmd)
        self.assertFalse({"--remote","resume","fork","--trust"} & set(cmd))


REAL_POPEN = subprocess.Popen
