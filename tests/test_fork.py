from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import test_runtime as fixtures
import astra_worker as worker
import worker_fork as forks


class ForkTests(unittest.TestCase):
    def setUp(self):
        self.project = fixtures.RuntimeTests()
        self.project.setUp()
        self.addCleanup(self.project.doCleanups)
        self.root = self.project.root
        self.scope = dict(level="L2", task="T001")
        self.actor = self.project.g
        (self.root / "notes.txt").write_text("first snapshot", encoding="utf-8")
        self.spawns = self.mock("astra_worker.launch")
        self.mock("astra_worker.codex_executable", return_value=sys.executable)
        self.selection = dict(point="submission", mode="materials", inherit=["file:notes.txt"], brief="Explore B")
        self.thread = "01234567-1234-1234-1234-123456789abc"
        self.turn = "test-review-turn"

    def mock(self, name, **kwargs):
        item = patch(name, **kwargs)
        self.addCleanup(item.stop)
        return item.start()

    def call(self, op, **changes):
        return self.project.call(op, self.actor, **dict(self.scope, **changes))

    def parent(self, **changes):
        res = self.call("worker-submit", destination="worker", key="parent", files=["notes.txt"],
                        brief="parent question", **changes)
        self.scope["job"] = res["job"]
        self.path = self.spawns.call_args.args[0]
        return res

    def preview(self, **changes):
        return self.call("worker-fork-preview", workspace="readonly", **dict(self.selection, **changes))

    def branch(self, preview, **changes):
        args = dict(self.selection, key="child", confirmed=True, approval_sha256=preview["approval_sha256"])
        return self.call("worker-fork", **dict(args, **changes))

    def complete(self):
        with closing(worker.open_job(self.path, True)) as db, db:
            db.execute("UPDATE review SET state='completed', result='A raw review  '")

    def capture(self):
        profile = self.root / "profile"
        path = profile / "sessions/2026/11/27" / ("rollout-2026-11-27T10-00-00-" + self.thread + ".jsonl")
        path.parent.mkdir(parents=True)
        events = [("session_meta", {"id": self.thread}), ("event_msg", {"type":"task_started", "turn_id":self.turn}),
                  ("response_item", {"type":"message", "text":"private thought A"}),
                  ("event_msg", {"type":"task_complete", "turn_id":self.turn}),
                  ("event_msg", {"type":"later", "text":"outside the boundary"})]
        path.write_bytes(b"".join(forks.packed({"type":kind,"payload":data}) + b"\n" for kind,data in events))
        with closing(worker.open_job(self.path, True)) as db:
            capture = forks.Capture(db, profile, {"id":self.thread, "path":str(path)})
            self.assertTrue(capture.record(self.turn))
            self.assertTrue(capture.record(self.turn, finished=True))

    def test_materials_are_selected_from_original_snapshot(self):
        parent = self.parent()
        (self.root / "notes.txt").write_text("changed on disk", encoding="utf-8")
        self.complete()
        plan = self.preview()
        child = self.branch(plan)
        self.assertNotEqual(child["job"], parent["job"])
        self.assertEqual(child["branch"]["mode"], "materials")
        self.assertEqual(child["branch"]["label"], "基于材料新建 Worker")
        with closing(worker.open_job(self.spawns.call_args.args[0])) as db:
            packet = db.execute("SELECT packet FROM review").fetchone()[0]
        self.assertIn("first snapshot", packet)
        for excluded in ("changed on disk", "A raw review", "parent question"):
            self.assertNotIn(excluded, packet)
        self.assertEqual(self.call("worker-result")["original_review"], "A raw review  ")
        self.assertEqual(self.branch(plan)["job"], child["job"])
        self.assertEqual(self.spawns.call_count, 2)

    def test_confirmation_scope_and_immutable_request_key(self):
        self.parent()
        plan = self.preview()
        for change in (dict(confirmed=False),dict(brief="Changed B"),dict(inherit=["brief"]),
                       dict(approval_sha256="bad"),dict(workspace="readonly"),dict(task="T002"),dict(level="L1")):
            with self.assertRaises(ValueError):
                self.branch(plan, **change)
        with self.assertRaises(ValueError):
            self.project.call("worker-fork-points", self.project.a, **self.scope)
        with self.assertRaises(ValueError):
            self.preview(point="through-review", mode="native", inherit=["native-history"])
        self.branch(plan)
        different = self.preview(brief="Different B")
        with self.assertRaisesRegex(ValueError, "key"):
            self.branch(different, brief="Different B")
        self.assertEqual(self.spawns.call_count, 2)

    def test_concurrent_retries_start_one_child(self):
        self.parent()
        plan = self.preview()
        with ThreadPoolExecutor(2) as pool:
            jobs = list(pool.map(lambda _: self.branch(plan)["job"], range(2)))
        self.assertEqual(jobs[0], jobs[1])
        self.assertEqual(self.spawns.call_count, 2)

    def test_complete_raw_review_only_on_explicit_material_selection(self):
        self.parent()
        with self.assertRaises(ValueError):
            self.preview(point="result", inherit=["review"])
        self.complete()
        with self.assertRaises(ValueError):
            self.preview(inherit=["review"])
        self.selection.update(point="result", inherit=["review"])
        self.branch(self.preview())
        with closing(worker.open_job(self.spawns.call_args.args[0])) as db:
            packet = json.loads(db.execute("SELECT packet FROM review").fetchone()[0])
        self.assertEqual(packet["inherited"], [{"id":"review","text":"A raw review  "}])
        with self.assertRaisesRegex(ValueError, "sealed"):
            self.preview(job=self.spawns.call_args.args[0].stem, point="submission", blind=True, inherit=["inherited:review"])

    def test_native_before_and_after_are_immutable_and_blind_is_sealed(self):
        self.parent(forkable=True)
        self.capture()
        self.assertEqual(self.call("worker-fork-points")["native"], [forks.BEFORE])
        plan = self.preview(point=forks.BEFORE, mode="native")
        dest = self.root / "empty-profile"
        params = forks.restore_source(self.path, plan, dest)
        self.assertEqual(params["beforeTurnId"], self.turn)
        self.assertNotIn(b"private thought", next(dest.rglob("*.jsonl")).read_bytes())
        self.complete()
        self.assertEqual(self.call("worker-fork-points", blind=True)["native"], [forks.BEFORE])
        self.assertEqual(self.preview(point=forks.BEFORE, mode="native"), plan)
        for change in ({"blind":True}, {"inherit":["file:notes.txt"]}):
            with self.assertRaises(ValueError):
                self.preview(**dict(dict(point=forks.AFTER,mode="native",inherit=["native-history"]),**change))
        self.selection.update(point=forks.AFTER,mode="native",inherit=["native-history"])
        plan = self.preview()
        self.assertFalse(self.branch(plan)["branch"]["native_confirmed"])
        dest = self.root / "other-profile"
        self.assertEqual(forks.restore_source(self.path,plan,dest)["lastTurnId"], self.turn)
        raw = next(dest.rglob("*.jsonl")).read_bytes()
        self.assertIn(b"private thought", raw)
        self.assertNotIn(b"outside the boundary", raw)

    def test_tampered_or_missing_native_source_fails_without_a_fresh_turn(self):
        self.parent(forkable=True)
        self.capture()
        self.selection.update(point=forks.BEFORE,mode="native")
        self.branch(self.preview())
        child = self.spawns.call_args.args[0]
        with closing(worker.open_job(self.path, True)) as db, db:
            db.execute("UPDATE fork_history SET rollout=x'00'")
        with patch.object(worker.control, "connection") as connect:
            worker.run_job(child, sys.executable)
            connect.assert_not_called()
        self.assertEqual(worker.snapshot(child,child.stem)["state"],"failed")
        self.assertEqual(self.spawns.call_count, 2)

    def test_confirmed_native_fork_requires_matching_boundary_and_original(self):
        self.parent(forkable=True)
        self.capture()
        self.complete()
        args = dict(point=forks.AFTER,mode="native",inherit=["native-history"])
        plan = self.preview(**args)
        turn = {"id":self.turn, "status":"completed", "items":[{"type":"agentMessage","text":"A raw review  "}]}
        good = {"id":"child", "forkedFromId":self.thread, "turns":[turn]}
        forks.verify_history(good, plan)
        for bad in (dict(good,id=self.thread),dict(good,forkedFromId="other"),dict(good,turns=[]),
                    dict(good,turns=[turn,turn]),dict(good,turns=[dict(turn,items=[])])):
            with self.assertRaises(ValueError):
                forks.verify_history(bad,plan)
        with self.assertRaises(ValueError):
            forks.verify_history(good,self.preview(point=forks.BEFORE,mode="native"))

    def test_native_runner_uses_verified_history_and_asks_only_the_branch_question(self):
        self.parent(forkable=True)
        self.capture()
        self.complete()
        self.selection.update(point=forks.AFTER, mode="native", inherit=["native-history"])
        self.branch(self.preview())
        child = self.spawns.call_args.args[0]
        wire = Mock()
        def setup(method, params):
            if method == "initialize":
                return {}
            self.assertEqual(method, "thread/fork")
            self.assertEqual(params["lastTurnId"], self.turn)
            self.assertEqual(params["threadId"], self.thread)
            turn = {"id":self.turn, "status":"completed", "items":[{"type":"agentMessage","text":"A raw review  "}]}
            return {"thread":{"id":"child-thread","forkedFromId":self.thread,"ephemeral":False,"turns":[turn]},
                    "cwd":params["cwd"], "approvalPolicy":"never","sandbox":{"type":"readOnly","networkAccess":False}}
        wire.setup.side_effect = setup
        with patch.object(worker.control, "connection", return_value=nullcontext(wire)), \
             patch.object(worker.control, "codex_login"), patch.object(worker.control, "codex_turn", return_value="B") as run:
            worker.run_job(child, sys.executable)
        self.assertEqual(run.call_args.args[2:4], ("child-thread", "Explore B"))
        receipt = self.call("worker-result", job=child.stem)
        self.assertEqual(receipt["original_review"], "B")
        self.assertTrue(receipt["branch"]["native_confirmed"])

    def test_pre_steer_job_remains_a_material_source(self):
        parent = self.parent()
        with closing(worker.open_job(self.path, True)) as db, db:
            db.execute("DROP TABLE channel")
        self.assertEqual(self.call("worker-fork-points")["native"], [])
        child = self.branch(self.preview())
        self.assertEqual(child["branch"]["parent_job"], parent["job"])
