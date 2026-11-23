import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("guards", ROOT / "tools" / "security_guards.py")
guards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guards)


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


class FrontmatterGuardsTest(unittest.TestCase):
    def run_checks(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".claude" / "skills").mkdir(parents=True)
            (root / ".claude" / "agents").mkdir(parents=True)
            for rel, text in files.items():
                write(root, rel, text)
            old, guards.ROOT = guards.ROOT, root
            try:
                errors: list[str] = []
                guards.check_skills(errors)
                guards.check_agents(errors)
                return errors
            finally:
                guards.ROOT = old

    def test_clean_definitions_pass(self):
        errors = self.run_checks({
            ".claude/skills/sync/SKILL.md": "---\nname: sync\ndescription: x\ndisable-model-invocation: true\n"
                                           "allowed-tools: Bash(python3 tools/isa.py:*), Write(data/imports/mcp/**)\n---\nbody\n",
            ".claude/agents/fact-verifier.md": "---\nname: fact-verifier\ndescription: x\ntools: WebSearch, WebFetch, Read\n"
                                               "maxTurns: 25\nskills:\n  - research-rules\n---\nbody\n",
        })
        self.assertEqual(errors, [])

    def test_unscoped_tools_and_missing_flag_fail(self):
        errors = self.run_checks({
            ".claude/skills/sync/SKILL.md": "---\nname: sync\ndescription: x\nallowed-tools: Read, Bash, Write\n---\n",
        })
        joined = "\n".join(errors)
        self.assertIn("over-broad allowed-tools entry: Bash", joined)
        self.assertIn("over-broad allowed-tools entry: Write", joined)
        self.assertIn("disable-model-invocation", joined)

    def test_order_tool_in_skill_fails(self):
        errors = self.run_checks({
            ".claude/skills/portfolio/SKILL.md": "---\nname: portfolio\ndescription: x\nallowed-tools: mcp__kite__place_order\n---\n",
        })
        self.assertTrue(any("order tool" in e for e in errors))

    def test_agent_rules(self):
        errors = self.run_checks({
            ".claude/agents/news-summarizer.md": "---\nname: news-summarizer\ndescription: x\ntools: Read, WebFetch, Bash\n---\n",
            ".claude/agents/open.md": "---\nname: open\ndescription: x\nmaxTurns: 5\n---\n",
        })
        joined = "\n".join(errors)
        self.assertIn("may not have Bash", joined)
        self.assertIn("may use WebFetch", joined)
        self.assertIn("missing maxTurns", joined)
        self.assertIn("no explicit tools list", joined)

    def test_legacy_commands_folder_fails(self):
        errors = self.run_checks({".claude/commands/sync.md": "# /sync\n"})
        self.assertTrue(any("commands live in .claude/skills" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
