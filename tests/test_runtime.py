import contextlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/gemini-with-astra/scripts"
sys.path.insert(0, str(SCRIPTS))
import coord


def invoke(root, request):
    path = Path(root).resolve()
    return coord.run(path, path, request)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".ai").mkdir()
        (self.root / coord.LOCK).write_bytes(b"0")
        (self.root / ".ai/dual-collab.json").write_bytes(
            coord.packed({"root": str(self.root), "mode": "local", "version": coord.VERSION})
        )
        self.g = self.call("register", agent="GEMINI")
        self.a = self.call("register", agent="ASTRA")
        self.b = self.call("register", agent="ASTRA")
        self.c = self.call("register", agent="ASTRA")
        self.t1 = self.task("T001", self.a, reviewer=self.g["session"])
        self.t2 = self.task("T002", self.b)

    def call(self, op, actor=None, **args):
        if actor:
            args["actor"] = actor["actor"]
        return invoke(self.root, {"op": op, **args})

    def task(self, task, owner, **kw):
        return self.call(
            "create-task", self.g, task=task, owner=owner["session"], body=task + " contract", **kw
        )

    def stream(self, ws, owner):
        return self.call(
            "create-stream", self.a, task="T001", ws=ws, owner=owner["session"], body="stream " + ws
        )

    def send(self, target, key, **kwargs):
        return self.call("send", self.g, target=target, key=key, body="message " + key, **kwargs)

    def check(self, actor, task="T001", **kwargs):
        return self.call("context", actor, level="L2", task=task, **kwargs)

    def ack(self, actor, delivery, **kwargs):
        return self.call("ack", actor, level="L2", delivery=delivery, outcome="durable outcome", **kwargs)

    @contextlib.contextmanager
    def observe(self):
        accessed = []
        original = Path.open
        listing = Path.glob

        def track(p, *args, **kw):
            accessed.append(p.as_posix())
            return original(p, *args, **kw)

        def scan(p, *args, **kw):
            accessed.append(p.as_posix() + "/<enumeration>")
            return listing(p, *args, **kw)

        with patch.object(Path, "open", track), patch.object(Path, "glob", scan):
            yield accessed

    def test_l1_never_touches_tasks_registry_or_message_counts(self):
        self.send("PROJECT", "public")
        with self.observe() as opened:
            out = self.call("context", level="L1", workspace="readonly")
        self.assertEqual(set(out), {"project", "level"})
        self.assertFalse(
            any(
                any(
                    name in p
                    for name in (
                        "/tasks/",
                        "/sessions/",
                        "/sync/",
                        "/legacy/",
                        "/checkpoints/",
                        "transaction",
                        "runtime-v2.lock",
                    )
                )
                for p in opened
            ),
            opened,
        )
        with self.assertRaises(ValueError):
            self.call("notifications", self.a, level="L1", explicit_notifications=True)

    def test_l2_only_selected_files_and_own_matching_messages(self):
        self.stream("WS-X", self.a)
        self.stream("WS-Y", self.b)
        self.send("SESSION:" + self.a["session"], "other", task="T002")
        self.send("PROJECT", "unscoped")
        self.send("SESSION:" + self.a["session"], "wanted", task="T001", ws="WS-X")
        self.send("SESSION:" + self.b["session"], "peer", task="T001", ws="WS-X")
        with self.observe() as opened:
            out = self.check(self.a, ws="WS-X")
        self.assertEqual([x["body"] for x in out["messages"]], ["message wanted"])
        for f in ("T002", "WS-Y", "/PROJECT/", self.b["session"] + "/", "checkpoints"):
            self.assertFalse(any(f in p for p in opened), (f, opened))

    def test_lazy_registration_and_distinct_session_handles(self):
        totals = lambda: len(list((self.root / ".ai/sessions").glob("C-*")))
        n = totals()
        self.call("context", level="L1")
        self.call("context", level="L2", task="T001")
        self.assertEqual(totals(), n)
        self.assertNotEqual(self.a["session"], self.b["session"])
        stolen = self.b["session"] + ":" + self.a["actor"].split(":")[1]
        with self.assertRaises(ValueError):
            self.call("context", level="L2", actor={"actor": stolen}, task="T001")

    def test_many_to_many_workstream_and_task_snapshot(self):
        self.stream("WS-X", self.b)
        self.stream("WS-Y", self.c)
        groups = self.send("WORKSTREAM", "wg", task="T001", ws="WS-X")["deliveries"]
        self.assertEqual(set(groups), {self.b["session"]})
        group = self.send("TASK", "tg", task="T001")["deliveries"]
        self.assertEqual(set(group), {s["session"] for s in (self.a, self.b, self.c, self.g)})
        for t in ("T001", "T002"):
            self.assertEqual(self.check(self.b, t)["task"]["meta"]["task"], t)
        self.assertEqual(self.check(self.b)["workstream"]["meta"]["ws"], "WS-X")
        self.assertEqual(self.check(self.g)["select_workstream"], ["WS-X", "WS-Y"])

    def test_task_without_streams_and_unscoped_notifications(self):
        self.assertEqual(
            set(self.send("TASK", "task", task="T001")["deliveries"]),
            {self.g["session"], self.a["session"]},
        )
        self.send("PROJECT", "project")
        direct = self.send("SESSION:" + self.a["session"], "direct")
        self.assertEqual(len(self.check(self.a)["messages"]), 1)
        with self.assertRaises(ValueError):
            self.call("notifications", self.a, level="L2")
        notices = self.call(
            "notifications", self.a, level="L2", explicit_notifications=True, workspace="readonly"
        )
        self.assertEqual(len(notices), 2)
        did = direct["deliveries"][self.a["session"]]
        with self.assertRaises(ValueError):
            self.ack(self.a, did)
        with self.assertRaises(ValueError):
            self.ack(self.a, did, workspace="readonly", explicit_notifications=True)
        self.ack(self.a, did, explicit_notifications=True)

    def test_fanout_ack_one_and_retry_frozen_membership(self):
        kwargs = dict(task="T001", all=True)
        self.stream("WS-Y", self.b)
        self.stream("WS-Z", self.c)
        send = self.send("AGENT:ASTRA", "b", **kwargs)
        self.assertEqual(set(send["deliveries"]), {x["session"] for x in (self.a, self.b, self.c)})
        self.assertEqual(len(set(send["deliveries"].values())), 3)
        did = send["deliveries"][self.a["session"]]
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.ack(self.b, did, task="T001")
        receipt = self.ack(self.a, did, task="T001")
        self.assertEqual(receipt, self.ack(self.a, did, task="T001"))
        late = self.call("register", agent="ASTRA")
        self.stream("WS-N", late)
        self.assertEqual(self.send("AGENT:ASTRA", "b", **kwargs), send)
        self.assertEqual(self.check(late)["messages"], [])
        self.assertEqual(self.check(self.a)["messages"], [])
        self.assertEqual(len(self.check(self.b)["messages"]), 1)
        state = self.call("delivery-status", self.g, key="b")
        self.assertEqual(state[self.a["session"]], "handled")
        self.assertEqual(state[self.c["session"]], "delivered")

    def test_project_snapshot_offline_and_explicit_close(self):
        self.call("close", self.c, approved=True)
        saved = self.send("PROJECT", "open")
        self.assertEqual(set(saved["deliveries"]), {s["session"] for s in (self.a, self.g, self.b)})
        with self.assertRaises(ValueError):
            self.call("close", self.b, approved=True)
        self.assertEqual(
            self.call("close", self.b, approved=True, retain_pending=True)["pending_retained"], 1
        )
        self.assertEqual(self.send("PROJECT", "open"), saved)

    def test_agent_not_unique_and_no_recipient(self):
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.send("AGENT:ASTRA", "x")
        self.assertEqual(
            set(self.send("AGENT:ASTRA", "one", task="T002")["deliveries"]), {self.b["session"]}
        )
        with self.assertRaisesRegex(ValueError, "No registered"):
            self.send("AGENT:GEMINI", "zero", task="T002")

    def test_explicit_l3_slice_no_other_checkpoints(self):
        for task in ("T001", "T002"):
            self.call("checkpoint", self.a, task=task, body="private " + task)
        self.call("checkpoint", self.a, body="project summary")
        self.call("checkpoint", self.b, task="T001", body="foreign checkpoint")
        origin = {"from": self.a["session"]}
        with self.observe() as accessed:
            sel = self.call("context", level="L3", **origin)
        self.assertEqual(sel["select_checkpoint"], ["PROJECT", "T001", "T002"])
        self.assertFalse(any("/checkpoints/" in p and p.endswith(".md") for p in accessed))
        new = self.call("register", agent="ASTRA", resumes_from=self.a["session"])
        with self.observe() as accessed:
            chosen = self.call("context", new, level="L3", task="T001", **origin)
        self.assertEqual(chosen["checkpoint"], "private T001")
        self.assertFalse(any("T002" in p or self.b["session"] in p for p in accessed))
        self.assertEqual(
            self.call("context", new, level="L3", slice="PROJECT", **origin)["checkpoint"],
            "project summary",
        )
        with self.assertRaises(ValueError):
            self.call("context", self.b, level="L3", task="T001", **origin)

    def test_explicit_takeover_selected_task_and_retry(self):
        n = self.call("register", agent="ASTRA", resumes_from=self.a["session"])
        pending = self.send("SESSION:" + self.a["session"], "old", task="T001")
        self.send("SESSION:" + self.a["session"], "second", task="T002")
        self.assertEqual(self.check(n)["messages"], [])
        q = {"from": self.a["session"], "task": "T001", "revision": 1, "key": "x", "approved": True}
        moved = self.call("takeover", n, **q)
        self.assertEqual(moved, self.call("takeover", n, **q))
        self.assertEqual(self.check(n)["task"]["meta"]["owner"], n["session"])
        self.assertEqual(len(self.check(n)["messages"]), 1)
        self.assertEqual(len(self.check(self.a, "T002")["messages"]), 1)
        with self.assertRaises(ValueError):
            self.call(
                "progress", self.a, task="T001", revision=2, status="IN_PROGRESS", body="stale writer"
            )
        receipt = self.ack(self.a, pending["deliveries"][self.a["session"]], task="T001")
        self.assertIn("transferred_to", receipt)
        self.assertNotIn("handled_at", receipt)

    def test_readonly_preview_and_explicit_notice_transfer(self):
        sent = self.send("PROJECT", "note")
        n = self.call("register", agent="ASTRA", resumes_from=self.b["session"])
        opts = {
            "from": self.b["session"],
            "deliveries": [sent["deliveries"][self.b["session"]]],
            "approved": True,
            "explicit_notifications": True,
        }
        with self.assertRaises(ValueError):
            self.call("transfer-notifications", n, workspace="readonly", **opts)
        result = self.call("transfer-notifications", n, **opts)
        self.assertEqual(self.call("transfer-notifications", n, **opts), result)
        self.assertEqual(len(self.call("notifications", n, level="L2", explicit_notifications=True)), 1)

    def test_source_of_truth_and_stale_revision(self):
        m = self.call("progress", self.a, task="T001", revision=1, status="IN_PROGRESS", body="base")
        with self.assertRaises(ValueError):
            self.call("progress", self.a, task="T001", revision=1, status="IMPLEMENTED", body="old")
        self.call(
            "progress",
            self.a,
            task="T001",
            revision=m["revision"],
            status="IMPLEMENTED",
            body="result sentinel",
        )
        self.send("SESSION:" + self.g["session"], "peer", task="T001")
        blinded = self.check(self.g, blind=True)
        self.assertNotIn("result sentinel", str(blinded))
        self.assertNotIn("messages", blinded)
        with self.assertRaises(ValueError):
            self.call("progress", self.a, task="T001", revision=3, status="ACCEPTED", body="self")
        self.call("progress", self.g, task="T001", revision=3, status="ACCEPTED", body="review")
        reviewed = self.check(self.g)["task"]["body"]
        self.assertIn(f"Reviewer {self.g['session']} passed the contract checks\nreview", reviewed)
        self.assertNotIn("user acceptance", reviewed)
        data = dict(
            file="SPEC.md",
            approved=True,
            approval="user message",
            expected_sha256=None,
            body="approved specification",
        )
        with self.assertRaises(ValueError):
            self.call("publish-fact", self.a, **dict(data, approved=False))
        self.call("publish-fact", self.a, **data)
        with self.assertRaises(ValueError):
            self.call("publish-fact", self.b, **data)
        self.assertEqual(self.call("context", level="L1")["project"]["SPEC.md"], data["body"])

    def test_legacy_inventory_preview_ambiguous_and_repeat(self):
        path = self.root / ".ai/sync/to-astra.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = b"Ambiguous prose\\n\\nID M42 update\\nPlease inspect filters.\\n".replace(b"\\n", b"\n")
        path.write_bytes(raw)
        admin = dict(explicit=True, side="astra")
        inv = self.call("legacy-inventory", self.g, **admin)
        args = dict(admin, expected_sha256=inv["sha256"], first=3, last=4)
        self.assertIn("filters", self.call("legacy-preview", self.g, **args)["body"])
        with self.assertRaises(ValueError):
            self.call("legacy-deliver", self.g, approved=True, task="T001", **args)
        result = self.call(
            "legacy-deliver", self.g, approved=True, task="T001", recipient=self.a["session"], **args
        )
        self.assertEqual(
            self.call(
                "legacy-deliver", self.g, approved=True, task="T001", recipient=self.a["session"], **args
            ),
            result,
        )
        with self.assertRaises(ValueError):
            self.call(
                "legacy-deliver", self.g, approved=True, task="T001", recipient=self.b["session"], **args
            )
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual((self.root / inv["pending_copy"]).read_bytes(), raw)
        self.assertEqual(self.check(self.b)["messages"], [])
        path.write_bytes(raw + b"user edit")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.call("legacy-inventory", self.g, **admin)

    def test_interrupted_fanout_and_ack_recover(self):
        self.stream("WS-X", self.b)
        original = coord.replace_file

        def cut(path, data):
            if self.b["session"] in path.parts and "inboxes" in path.parts:
                raise OSError("simulated crash")
            original(path, data)

        with patch.object(coord, "replace_file", cut), self.assertRaises(OSError):
            self.send("TASK", "crash", task="T001")
        with self.assertRaisesRegex(ValueError, "Interrupted"):
            self.check(self.a)
        self.assertEqual(self.call("context", level="L1")["level"], "L1")
        self.call("recover")
        send = self.send("TASK", "crash", task="T001")
        self.assertEqual(len(self.check(self.b)["messages"]), 1)
        did = send["deliveries"][self.a["session"]]
        original_unlink = Path.unlink

        def cut_ack(p, *args, **kw):
            if p.name == did + ".md":
                raise OSError("crash after receipt")
            return original_unlink(p, *args, **kw)

        with patch.object(Path, "unlink", cut_ack), self.assertRaises(OSError):
            self.ack(self.a, did, task="T001")
        self.call("recover")
        self.assertIn("handled_at", self.ack(self.a, did, task="T001"))
        self.assertEqual(self.check(self.a)["messages"], [])
        self.assertEqual(len(self.check(self.b)["messages"]), 1)

    def test_concurrent_processes_allocate_send_and_update(self):
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(invoke, self.root, {"op": "register", "agent": "ASTRA"}) for _ in range(8)
            ]
            ids = [f.result(timeout=30)["session"] for f in futures]
            self.assertEqual(len(set(ids)), 8)
            jobs = [
                pool.submit(
                    invoke,
                    self.root,
                    {
                        "op": "send",
                        "actor": self.g["actor"],
                        "key": "n" + str(i),
                        "target": "SESSION:" + self.a["session"],
                        "task": "T001",
                        "body": str(i),
                    },
                )
                for i in range(10)
            ]
            deliveries = [next(iter(j.result(timeout=30)["deliveries"].values())) for j in jobs]
            self.assertEqual(len(set(deliveries)), 10)
            self.assertEqual(len(self.check(self.a)["messages"]), 10)
            args = {
                "op": "progress",
                "actor": self.a["actor"],
                "task": "T001",
                "revision": 1,
                "status": "IN_PROGRESS",
                "body": "baseline",
            }
            writers = [pool.submit(invoke, self.root, args) for _ in range(2)]
            self.assertEqual(sum(f.exception(timeout=30) is None for f in writers), 1)

    def test_code_workspace_and_shared_state_separate_synthetic_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = Path(tmp).resolve()
            (self.root / "main.py").write_text("primary")
            (code / "main.py").write_text("branch")
            data = self.root / "external-data.bin"
            data.write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "Attach"):
                coord.run(self.root, code, {"op": "context", "level": "L1"})
            with self.assertRaises(ValueError):
                coord.run(self.root, code, {"op": "attach"})
            coord.run(self.root, code, {"op": "attach", "approved": True})
            out = coord.run(
                self.root, code, {"op": "context", "level": "L2", "task": "T001", "workspace": "isolated"}
            )
            self.assertEqual(out["task"]["meta"]["task"], "T001")
            self.assertEqual((self.root / "main.py").read_text(), "primary")
            self.assertEqual(sorted(p.name for p in code.iterdir()), ["main.py"])
            self.assertEqual(data.read_bytes(), b"fixture")

    def test_l3_task_checkpoint_stays_task_only(self):
        self.stream("WS-SIDE", self.b)
        self.call("checkpoint", self.a, task="T001", body="task-only")
        self.call("checkpoint", self.a, task="T001", ws="WS-SIDE", body="stream-only")
        successor = self.call("register", agent="ASTRA", resumes_from=self.a["session"])
        self.send("SESSION:" + successor["session"], "peer", task="T001", ws="WS-SIDE")
        with self.observe() as reads:
            out = self.call("context", successor, level="L3", task="T001", **{"from": self.a["session"]})
        self.assertNotIn("workstream", out)
        self.assertEqual(out["messages"], [])
        self.assertFalse(any("WS-SIDE" in p or "/workstreams/" in p for p in reads))

    def test_registration_retry_and_explicit_user_acceptance(self):
        key = coord.secrets.token_urlsafe(32)
        first = self.call("register", agent="ASTRA", registration_key=key)
        self.assertEqual(first, self.call("register", agent="ASTRA", registration_key=key))
        with self.assertRaises(ValueError):
            self.call("register", agent="GEMINI", registration_key=key)
        self.call("progress", self.b, task="T002", revision=1, status="IN_PROGRESS", body="base")
        self.call("progress", self.b, task="T002", revision=2, status="IMPLEMENTED", body="sha and tests")
        with self.assertRaises(ValueError):
            self.call("user-accept", self.b, task="T002", revision=3, body="self")
        accepted = self.call(
            "user-accept",
            self.b,
            task="T002",
            revision=3,
            approved=True,
            body="user approved delivered revision",
        )
        self.assertEqual(accepted["status"], "ACCEPTED")
        confirmed = self.check(self.b, task="T002")["task"]["body"]
        self.assertIn(f"user acceptance (recorded by {self.b['session']})\nuser approved delivered revision", confirmed)
        self.assertNotIn("passed the contract checks", confirmed)

    def test_parallel_code_writers_need_separate_checkouts(self):
        self.call("progress", self.a, task="T001", revision=1, status="IN_PROGRESS", body="start")
        with self.assertRaisesRegex(ValueError, "Another session"):
            self.call("progress", self.b, task="T002", revision=1, status="IN_PROGRESS", body="conflict")
        with tempfile.TemporaryDirectory() as tmp:
            code = Path(tmp).resolve()
            coord.run(self.root, code, {"op": "attach", "approved": True})
            coord.run(
                self.root,
                code,
                {
                    "op": "progress",
                    "actor": self.b["actor"],
                    "task": "T002",
                    "revision": 1,
                    "status": "IN_PROGRESS",
                    "body": "isolated code",
                    "workspace": "isolated",
                },
            )
            with self.assertRaisesRegex(ValueError, "checkout"):
                self.call(
                    "progress", self.b, task="T002", revision=2, status="IMPLEMENTED", body="wrong checkout"
                )
            self.assertEqual(self.check(self.a)["task"]["meta"]["code_root"], str(self.root))
            self.assertEqual(self.check(self.b, "T002")["task"]["meta"]["code_root"], str(code))

    def test_confirmed_fact_in_l1_does_not_require_registration(self):
        with self.observe() as reads:
            self.call(
                "publish-fact",
                level="L1",
                file="DECISIONS.md",
                expected_sha256=None,
                approved=True,
                approval="user confirmed",
                body="approved",
            )
        self.assertFalse(any("/sessions/" in p or "/sync/" in p for p in reads))
        self.assertEqual(self.call("context", self.a, level="L1")["project"]["DECISIONS.md"], "approved")

    def test_contract_revision_invalidates_previous_approval(self):
        self.call("progress", self.b, task="T002", revision=1, status="IN_PROGRESS", body="baseline")
        self.call(
            "progress", self.b, task="T002", revision=2, status="IN_PROGRESS", body="interim evidence"
        )
        self.call("progress", self.b, task="T002", revision=3, status="IMPLEMENTED", body="delivered")
        self.call("user-accept", self.b, task="T002", revision=4, approved=True, body="user accepted")
        meta = self.call(
            "revise",
            self.g,
            task="T002",
            revision=5,
            approved=True,
            reason="approved change",
            body="new acceptance criterion",
        )
        self.assertEqual((meta["contract_revision"], meta["status"]), (2, "READY"))
        self.assertIn(
            "user accepted", (self.root / ".ai/tasks/T002/history/TASK-5.md").read_text(encoding="utf-8")
        )

    def test_explicit_legacy_broadcast_and_unscoped_delivery(self):
        path = self.root / ".ai/sync/to-astra.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"common change\nprivate note\n")
        admin = dict(side="astra", explicit=True)
        inv = self.call("legacy-inventory", self.g, **admin)
        args = dict(admin, expected_sha256=inv["sha256"], approved=True)
        sent = self.call(
            "legacy-deliver", self.g, first=1, last=1, task="T001", approved_task_broadcast=True, **args
        )
        self.assertEqual(set(sent["send"]["deliveries"]), {self.g["session"], self.a["session"]})
        self.call(
            "legacy-deliver",
            self.g,
            first=2,
            last=2,
            recipient=self.b["session"],
            explicit_notifications=True,
            **args,
        )
        self.assertEqual(self.check(self.b, "T002")["messages"], [])
        self.assertEqual(
            len(self.call("notifications", self.b, level="L2", explicit_notifications=True)), 1
        )
        self.assertEqual(self.call("legacy-inventory", self.g, **admin)["pending_ranges"], [])

    def test_git_common_directory_resolution_uses_primary_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            linked = Path(tmp).resolve()

            def git_fixture(path, *args):
                if "--show-toplevel" in args:
                    return str(linked)
                if "--git-common-dir" in args:
                    return str(self.root / ".git")
                if args[0] == "worktree":
                    return "worktree " + str(self.root) + "\0\0worktree " + str(linked) + "\0"
                raise AssertionError(args)

            with patch.object(coord, "git", git_fixture):
                self.assertEqual(coord.resolve_roots(linked), (self.root, linked))


if __name__ == "__main__":
    unittest.main()
