"""验证本机入口迁移保留外来内容且重复执行无副作用。"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "agent-links.sh"


class AgentLinksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(SOURCE, self.root / "scripts/agent-links.sh")
        (self.root / ".agents/skills").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text("# 入口\n")

    def run_links(self):
        return subprocess.run(
            ["bash", "scripts/agent-links.sh"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_legacy_migration_and_idempotence(self):
        skills = self.root / ".claude/skills"
        skills.mkdir(parents=True)
        (skills / "removed").symlink_to("../../.agents/skills/removed")
        (self.root / "CLAUDE.md").symlink_to("AGENTS.md")
        self.assertEqual(self.run_links().returncode, 0)
        self.assertEqual(skills.resolve(), self.root / ".agents/skills")
        self.assertFalse((self.root / "CLAUDE.md").is_symlink())
        self.assertEqual(self.run_links().returncode, 0)

    def test_foreign_content_is_preserved_before_mutation(self):
        skills = self.root / ".claude/skills"
        skills.mkdir(parents=True)
        legacy = skills / "old"
        legacy.symlink_to("../../.agents/skills/old")
        foreign = skills / "foreign"
        foreign.mkdir()
        self.assertNotEqual(self.run_links().returncode, 0)
        self.assertTrue(legacy.is_symlink())
        self.assertTrue(foreign.is_dir())

    def test_real_instruction_and_external_links_are_preserved(self):
        instruction = self.root / "CLAUDE.md"
        instruction.write_text("# 外来指令\n")
        self.assertNotEqual(self.run_links().returncode, 0)
        self.assertEqual(instruction.read_text(), "# 外来指令\n")
        instruction.unlink()
        (self.root / ".claude").mkdir()
        skills = self.root / ".claude/skills"
        skills.symlink_to("../external")
        self.assertNotEqual(self.run_links().returncode, 0)
        self.assertEqual(skills.readlink().as_posix(), "../external")
