import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

DEV = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEV / "skills/gemini-with-astra/scripts"))
import coord
import setup
import upgrade


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "project space"
        self.root.mkdir()
        self.home = self.base / "user"
        self.home.mkdir()
        env = {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "CODEX_HOME": str(self.home / "codex"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
        # Restore only the fixture's keys. Clearing the entire Windows environment
        # can drop unrelated Git config values whose original value is empty.
        for key, value in env.items():
            if key in os.environ:
                self.addCleanup(os.environ.__setitem__, key, os.environ[key])
            else:
                self.addCleanup(os.environ.pop, key, None)
            os.environ[key] = value
        with zipfile.ZipFile(DEV / "tests/fixtures/public-v0.1.1.zip") as z:
            z.extractall(self.base / "old")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "main.py").write_bytes(b"# uncommitted user code\n")

    def baseline(self, mode="private", bridge=False):
        if mode == "private" or bridge:
            (self.root / "AGENTS.md").write_bytes(b"# Existing root rule\r\n")
        if bridge:
            p = self.home / "codex/AGENTS.override.md"
            p.parent.mkdir(parents=True)
            p.write_bytes(b"# Keep existing personal override\n")
        args = [
            sys.executable,
            "-B",
            str(self.base / "old/gemini-with-astra/scripts/setup.py"),
            "init",
            "--root",
            str(self.root),
            "--mode",
            mode,
        ]
        if bridge:
            args.append("--allow-global-bridge")
        proc = subprocess.run(args, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        task = self.root / ".ai/tasks/T007.md"
        task.parent.mkdir()
        task.write_bytes(b"# existing user task\n")
        sync = self.root / ".ai/sync"
        sync.mkdir()
        self.legacy = sync / "to-astra.md"
        self.legacy.write_bytes(b"old unresolved message\r\nsecond line\r\n")
        self.original = {
            p.relative_to(self.root): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file() and not p.is_relative_to(self.root / ".git")
        }
        self.source = json.loads((self.root / setup.MANIFEST).read_bytes())

    def up(self, apply):
        with contextlib.redirect_stdout(io.StringIO()):
            return upgrade.execute(self.root, apply)

    def contents(self):
        return {
            p.relative_to(self.root): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file() and not p.is_relative_to(self.root / ".git")
        }

    def verify_upgraded(self):
        self.assertEqual(json.loads((self.root / setup.MANIFEST).read_bytes())["version"], "0.2.0")
        self.assertEqual(
            (self.root / ".ai/tasks/T007.md").read_bytes(), self.original[Path(".ai/tasks/T007.md")]
        )
        self.assertEqual(self.legacy.read_bytes(), self.original[Path(".ai/sync/to-astra.md")])
        self.assertFalse((self.root / ".ai/sync/inboxes").exists())
        backup = self.root / upgrade.ARCHIVE / "original"
        for path in backup.rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), self.original[path.relative_to(backup)])
        unchanged = self.contents()
        self.assertEqual(self.up(True), 0)
        self.assertEqual(self.contents(), unchanged)
        self.assertEqual(coord.run(self.root, self.root, {"op": "context", "level": "L1"})["level"], "L1")

    def test_private_preview_and_preserve(self):
        self.baseline()
        self.assertEqual(self.up(False), 0)
        self.assertEqual(self.contents(), self.original)
        self.assertEqual(self.up(True), 0)
        self.assertTrue((self.root / "AGENTS.md").read_bytes().startswith(b"# Existing root rule\r\n"))
        self.verify_upgraded()

    def test_local_preserves_git_status(self):
        self.baseline("local")
        status = lambda: subprocess.check_output(["git", "-C", str(self.root), "status", "--short"])
        before = status()
        self.assertEqual(self.up(True), 0)
        self.assertEqual(status(), before)
        self.verify_upgraded()

    def test_bridge_upgrade_leaves_both_personal_entries_byte_identical(self):
        self.baseline("local", True)
        original = {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(self.up(True), 0)
        self.verify_upgraded()
        self.assertEqual(original, {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()})
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), b"# Existing root rule\r\n")

    def test_bridge_drift_blocks_before_first_project_write(self):
        self.baseline("local", True)
        Path(self.source["agy_bridge"]).write_bytes(b"# drifted\n")
        for apply in (False, True):
            with self.assertRaisesRegex(ValueError, "drift"):
                self.up(apply)
            self.assertEqual(self.contents(), self.original)

    def test_existing_drift_rejects_before_backup_or_overwrite(self):
        self.baseline()
        (self.root / "docs/DUAL-COLLAB.md").write_bytes(b"custom protocol")
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "drift"):
            self.up(True)
        self.assertEqual(self.contents(), before)

    def test_resume_interrupted_upgrade(self):
        self.baseline()
        real = setup.atomic

        def interrupt(p, data, expected):
            if p.name == "dual-collab.py":
                raise OSError("intentional interruption")
            real(p, data, expected)

        with patch.object(setup, "atomic", interrupt), self.assertRaises(OSError):
            self.up(True)
        self.assertEqual(json.loads((self.root / setup.MANIFEST).read_bytes())["version"], "0.1.1")
        self.assertEqual(self.up(True), 0)
        self.verify_upgraded()

    def test_legacy_only_classified_stays_pending_then_exact_delivery(self):
        self.baseline()
        self.up(True)

        def call(op, **kw):
            return coord.run(self.root, self.root, dict(op=op, **kw))

        actor = call("register", agent="GEMINI")["actor"]
        receiver = call("register", agent="ASTRA")
        admin = dict(actor=actor, side="astra", explicit=True)
        inv = call("legacy-inventory", **admin)
        kw = dict(admin, expected_sha256=inv["sha256"], first=1, last=1, task="T007", approved=True)
        call("legacy-classify", **kw)
        check = call("legacy-inventory", **admin)
        self.assertEqual(check["pending_ranges"], [[1, 2]])
        self.assertEqual(check["classifications"][0]["task"], "T007")
        self.assertFalse((self.root / ".ai/sync/inboxes").exists())
        # A confirmed legacy task may be read as-is; adopt separately to route membership broadcasts.
        call(
            "adopt-task",
            actor=actor,
            task="T007",
            owner=receiver["session"],
            status="READY",
            expected_sha256=hashlib.sha256((self.root / ".ai/tasks/T007.md").read_bytes()).hexdigest(),
            approved=True,
        )
        result = call("legacy-deliver", recipient=receiver["session"], **kw)
        self.assertEqual(call("legacy-deliver", recipient=receiver["session"], **kw), result)
        self.assertEqual(call("legacy-inventory", **admin)["pending_ranges"], [[2, 2]])
        self.assertEqual(call("legacy-inventory", **admin)["classifications"], [])
