import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1] / "skills" / "gemini-with-astra"
SETUP = PACKAGE / "scripts/setup.py"
SNAP = PACKAGE / "scripts/snapshot.py"


class SkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "project space"
        self.repo.mkdir()
        self.home = self.base / "test-home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / "codex"), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, PYTHONUTF8="1")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.write("main.txt", "base\n")
        self.git("add", "main.txt")
        self.git("commit", "-qm", "baseline")

    def git(self, *args, cwd=None):
        return subprocess.check_output(["git", *args], cwd=cwd or self.repo, env=self.env, stderr=subprocess.STDOUT).decode().strip()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def run_setup(self, *args, root=None, expect=0):
        p = subprocess.run([sys.executable, str(SETUP), *args, "--root", str(root or self.repo)], env=self.env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, expect, p.stdout + p.stderr)
        return p.stdout + p.stderr

    def init(self, mode="private", *extra, expect=0):
        return self.run_setup("init", "--mode", mode, *extra, expect=expect)

    def manifest(self):
        return json.loads((self.repo / ".ai/dual-collab.json").read_text(encoding="utf-8"))

    def test_private_idempotent_existing_files(self):
        self.write("AGENTS.md", "# Existing rules\nUse project tests.\n")
        self.write("docs/SPEC.md", "# Existing spec\nKeep me.\n")
        self.write(".gitignore", "cache/\n")
        self.write("main.txt", "user's uncommitted edit\n")
        self.assertIn("STATIC PASS", self.init())
        self.assertTrue((self.repo / "AGENTS.md").read_text(encoding="utf-8").startswith("# Existing rules\nUse project tests."))
        self.assertEqual((self.repo / "docs/SPEC.md").read_text(encoding="utf-8"), "# Existing spec\nKeep me.\n")
        self.assertEqual((self.repo / "main.txt").read_text(encoding="utf-8"), "user's uncommitted edit\n")
        first = (self.repo / "AGENTS.md").read_bytes()
        self.init()
        self.assertEqual(first, (self.repo / "AGENTS.md").read_bytes())
        self.assertFalse((self.repo / ".ai/tasks").exists())
        self.assertFalse((self.repo / ".ai/sync").exists())
        self.assertNotIn(".ai/", self.git("status", "--short"))
        self.assertIn("CLI ACTIVATION UNVERIFIED", self.run_setup("status"))
        self.assertIn("Existing mode differs", self.init("local", expect=2))

    def test_private_override_and_clone(self):
        self.write("AGENTS.override.md", "# Existing override\n")
        self.init()
        self.assertIn(self.manifest()["code"], (self.repo / "AGENTS.override.md").read_text(encoding="utf-8"))
        self.git("add", ".")
        self.git("commit", "-qm", "collab")
        target = self.base / "clone"
        self.git("clone", "-q", str(self.repo), str(target))
        self.assertIn("RESIDENT RULES FOUND", self.run_setup("status", root=target, expect=1))
        self.git("config", "core.autocrlf", "true", cwd=target)
        # Simulate a Windows CRLF checkout of the generated text files.
        for name in ("docs/DUAL-COLLAB.md", "docs/dual-collab-snapshot.py"):
            p = target / name
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        before = self.git("status", "--short", cwd=target)
        original = {name: (target / name).read_bytes() for name in ("docs/DUAL-COLLAB.md", "docs/dual-collab-snapshot.py")}
        self.run_setup("init", "--mode", "private", root=target)
        self.assertEqual(self.git("status", "--short", cwd=target), before)
        for name, data in original.items():
            self.assertEqual((target / name).read_bytes(), data)

    def test_local_no_tracked_changes(self):
        before = self.git("status", "--short")
        self.assertIn("STATIC PASS", self.init("local"))
        self.assertEqual(before, self.git("status", "--short"))
        self.assertEqual(self.manifest()["entry"], "root")
        self.assertFalse((self.home / "codex").exists())
        self.assertFalse((self.repo / ".ai/docs/SPEC.md").exists())
        self.assertTrue((self.repo / ".ai/docs/DUAL-COLLAB.md").is_file())

    def test_local_bridge_requires_permission_and_preserves_rules(self):
        self.write("AGENTS.md", "# Upstream rules\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-qm", "rules")
        global_rule = self.home / "codex/AGENTS.override.md"
        global_rule.parent.mkdir()
        global_rule.write_text("# Personal override\n")
        self.assertIn("explicit user permission", self.init("local", expect=2))
        self.assertFalse((self.repo / ".ai").exists())
        self.assertEqual(global_rule.read_text(encoding="utf-8"), "# Personal override\n")
        self.assertIn("STATIC PASS", self.init("local", "--allow-global-bridge"))
        m = self.manifest()
        self.assertEqual(m["entry"], "bridge")
        self.assertEqual(self.git("status", "--short"), "")
        self.assertTrue(global_rule.read_text(encoding="utf-8").startswith("# Personal override\n"))
        self.assertIn(json.dumps(str(self.repo), ensure_ascii=False), global_rule.read_text(encoding="utf-8"))
        self.assertIn("trigger: always_on", Path(m["agy_bridge"]).read_text(encoding="utf-8"))
        self.assertIn("description:", Path(m["agy_bridge"]).read_text(encoding="utf-8"))
        self.assertEqual((self.repo / "AGENTS.md").read_text(encoding="utf-8"), "# Upstream rules\n")
        before = global_rule.read_bytes()
        self.init("local")
        self.assertEqual(before, global_rule.read_bytes())

    def test_collision_non_destructive(self):
        self.write("docs/DUAL-COLLAB.md", "unrelated protocol\n")
        self.assertIn("refusing overwrite", self.init(expect=2))
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertFalse((self.repo / "docs/SPEC.md").exists())
        self.assertEqual((self.repo / "docs/DUAL-COLLAB.md").read_text(encoding="utf-8"), "unrelated protocol\n")

    def test_tracked_ai_refusal(self):
        self.write(".ai/existing.md", "tracked\n")
        self.git("add", ".ai/existing.md")
        self.assertIn("tracked .ai", self.init(expect=2))
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_drift_detected_not_repaired(self):
        self.init()
        self.write("docs/DUAL-COLLAB.md", "edited\n")
        self.assertIn("Generated file drift", self.run_setup("status", expect=1))
        self.assertIn("STATIC FAIL", self.init(expect=1))
        self.assertEqual((self.repo / "docs/DUAL-COLLAB.md").read_text(encoding="utf-8"), "edited\n")

    def test_snapshot_tracks_real_changes(self):
        self.init("local")
        def snap():
            return subprocess.check_output([sys.executable, str(SNAP)], cwd=self.repo, env=self.env).decode().split("WORKSPACE_SHA256: ")[1].splitlines()[0]
        a = snap()
        self.write(".ai/transient.md", "ignored\n")
        self.assertEqual(a, snap())
        self.write("main.txt", "unstaged\n")
        b = snap()
        self.assertNotEqual(a, b)
        self.git("add", "main.txt")
        c = snap()
        self.assertNotEqual(b, c)
        self.write("new file.txt", "first\n")
        d = snap()
        self.assertNotEqual(c, d)
        self.write("new file.txt", "second\n")
        self.assertNotEqual(d, snap())
        self.assertEqual(snap(), snap())

    def test_reject_existing_workflow_without_manifest(self):
        self.write(".ai/tasks/T001.md", "another workflow\n")
        self.assertIn("Existing collaboration state", self.init(expect=2))
        self.assertFalse((self.repo / "AGENTS.md").exists())


    def test_private_ignore_conflict_preflight_no_partial_writes(self):
        self.write(".gitignore", "AGENTS.md\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore local instructions")
        before = self.git("status", "--short")
        out = self.init(expect=2)
        self.assertIn("already ignored by Git rules", out)
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertFalse((self.repo / "docs/DUAL-COLLAB.md").exists())
        self.assertFalse((self.repo / ".ai").exists())
        self.assertEqual(before, self.git("status", "--short"))

    def test_gitignore_conflict_detected(self):
        self.write(".gitignore", "!/.ai/\n!/.ai/**\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "conflict")
        before = self.git("status", "--short")
        self.assertIn("Not local-only", self.init("local", expect=2))
        self.assertFalse((self.repo / ".ai").exists())
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertEqual(before, self.git("status", "--short"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
