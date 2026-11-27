from contextlib import closing
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_runtime as fixtures
import astra_worker as worker
import worker_control as control


class SteerTests(unittest.TestCase):
    def setUp(self):
        self.project = fixtures.RuntimeTests()
        self.project.setUp()
        self.addCleanup(self.project.doCleanups)
        self.actor = self.project.g
        self.scope = {"task": "T001", "level": "L2"}
        self.details = dict(key="split", basis="user-authorized", source="User confirmed subject split", body="Check it.")
        self.trace = self.project.root / "native.jsonl"
        self.gate = self.project.root / "finish"

    def call(self, op, **changes):
        args = dict(self.scope, **changes)
        return self.project.call(op, self.actor, **args)

    def job(self, backend, behavior):
        gemini = backend == "agy-acp"
        self.actor = self.project.a if gemini else self.project.g
        opts = {"worker_agent": "GEMINI"} if gemini else {"steerable": True}
        with patch.object(worker, "native_executable", return_value=sys.executable), patch.object(worker.subprocess, "Popen") as launch:
            receipt = self.call("worker-submit", key=behavior, destination="worker", brief="Synthetic review", **opts)
            args = launch.call_args.args[0]
        path = Path(args[args.index("--run") + 1])
        self.scope["job"] = receipt["job"]
        connect = control.connection
        fixture = Path(__file__).parent / "fixtures/steer_peer.py"

        def child(command, directory, env, db):
            return connect([sys.executable, str(fixture), backend, behavior, str(self.trace), str(self.gate)],
                           directory, env, db)

        def run():
            with patch.object(control, "connection", side_effect=child), patch.object(control, "codex_login"):
                worker.run_job(path, sys.executable)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        self.addCleanup(self.thread.join, 12)
        self.addCleanup(self.gate.touch)
        return path

    def wait(self, op, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = self.call(op, workspace="readonly")
            if predicate(result):
                return result
            time.sleep(.02)
        self.fail("Worker did not reach expected state: " + str(result))

    def steer(self, turn, **changes):
        return self.call("worker-steer", expected_turn=turn, **dict(self.details, **changes))

    def history(self, method):
        msgs = map(json.loads, self.trace.read_text(encoding="utf-8").splitlines())
        return [msg for msg in msgs if msg.get("method") == method]

    def test_live_delivery_idempotence_scope_questions_and_raw_result(self):
        self.job("codex-app-server", "delivered")
        turn = self.wait("worker-status", lambda r: r.get("active_turn"))["active_turn"]
        self.assertEqual(self.wait("worker-questions", lambda r: r["questions"])["questions"], ["Which unit?"])
        for extra in ({"workspace": "readonly"}, {"task": "T002"}, {"level": "L1"}, {"basis": "preference"}, {"source": ""}):
            with self.assertRaises(ValueError):
                self.steer(turn, **extra)
        with self.assertRaises(ValueError):
            self.project.call("worker-steer", self.project.a, **self.scope, expected_turn=turn, **self.details)
        self.assertEqual(self.steer("stale-id", key="old")["state"], "stale")
        self.assertEqual(self.steer(turn)["state"], "queued")
        self.wait("worker-status", lambda r: r["state"] == "completed")
        self.assertEqual(self.steer(turn)["state"], "delivered")
        with self.assertRaisesRegex(ValueError, "different content"):
            self.steer(turn, body="Different")
        raw = self.call("worker-result")["original_review"]
        self.assertEqual(raw, "  原文\r\n保留分歧。\n")
        sent, = self.history("turn/steer")
        self.assertEqual(sent["params"]["expectedTurnId"], turn)
        self.assertEqual(len(self.history("turn/start")), 1)
        with self.assertRaises(ValueError):
            self.call("worker-questions", blind=True)

    def check_reply(self, behavior, expected):
        self.job("codex-app-server", behavior)
        turn = self.wait("worker-status", lambda r: r.get("active_turn"))["active_turn"]
        self.steer(turn)
        self.wait("worker-status", lambda r: r["state"] in ("completed", "failed"))
        self.assertEqual(self.steer(turn)["state"], expected)
        self.assertEqual(len(self.history("turn/start")), 1)
        self.assertEqual(len(self.history("turn/steer")), 1)

    def test_disconnect_after_transmission(self):
        self.check_reply("disconnect", "unknown")

    def test_native_rejection_is_not_retried(self):
        self.check_reply("rejected", "rejected")

    def test_mismatched_acknowledgement(self):
        self.check_reply("mismatch", "unknown")

    def test_ack_after_completion_is_attributed_to_original_turn(self):
        self.check_reply("late-ack", "delivered")

    def test_lost_final_ack_preserves_completed_review(self):
        self.check_reply("lost-final-ack", "unknown")
        self.assertEqual(self.call("worker-result")["original_review"], "  原文\r\n保留分歧。\n")

    def test_completed_turn_cannot_be_reopened(self):
        self.job("codex-app-server", "instant")
        self.wait("worker-status", lambda r: r["state"] == "completed")
        self.assertEqual(self.steer("native-turn")["state"], "stale")
        self.assertFalse(self.history("turn/steer"))
        self.assertEqual(len(self.history("turn/start")), 1)

    def test_acp_pending_survives_completion_without_second_prompt(self):
        self.job("agy-acp", "success")
        turn = self.wait("worker-status", lambda r: r.get("active_turn"))["active_turn"]
        self.assertEqual(self.steer(turn)["state"], "pending")
        self.gate.touch()
        self.wait("worker-status", lambda r: r["state"] == "completed")
        self.assertEqual(self.steer(turn)["state"], "pending")
        self.assertEqual(self.steer(turn, key="late")["state"], "stale")
        self.assertEqual(self.call("worker-suggestions")["suggestions"][0]["body"], "Check it.")
        self.assertEqual(self.call("worker-result")["original_review"], "Gemini 原文\n")
        self.assertEqual(len(self.history("session/prompt")), 1)
        self.assertFalse(self.history("turn/steer"))

    def test_acp_service_notice_is_failed(self):
        self.gate.touch()
        self.job("agy-acp", "notice")
        self.wait("worker-status", lambda r: r["state"] == "failed")
        self.assertNotIn("original_review", self.call("worker-result"))

    def test_main_session_advice_both_directions_is_scoped(self):
        for sender, receiver in ((self.project.g,self.project.a), (self.project.a,self.project.g)):
            self.actor = sender
            args = dict(self.details, basis="clarification", target="SESSION:" + receiver["session"])
            result = self.call("steer-suggest", **args)
            self.assertEqual(self.call("steer-suggest", **args), result)
            self.assertEqual(self.project.check(receiver)["messages"][0]["meta"]["type"], "STEER-SUGGESTION")
            self.assertNotIn("messages", self.project.call("context", level="L1"))
            self.project.ack(receiver, result["delivery"], task="T001")
            self.assertEqual(self.call("steer-suggest", **args)["state"], "handled")
            for target in ("AGENT:GEMINI", "PROJECT", "SESSION:" + self.project.c["session"]):
                with self.assertRaises(ValueError):
                    self.call("steer-suggest", **dict(args, target=target))

    def test_old_database_is_readable_without_migration(self):
        with closing(worker.sqlite3.connect(":memory:")) as db:
            self.assertEqual(control.describe(db), {"backend":"exec", "steering":"unavailable"})
