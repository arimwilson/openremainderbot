import re
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from remainderbot import run
from remainderbot.config import Config


class Render(unittest.TestCase):
    def test_render_only_known_keys(self):
        out = run.render("id={id} size={size} keep={other} {{literal}}", {"id": "x", "size": "small"})
        self.assertEqual(out, "id=x size=small keep={other} {{literal}}")

    def test_prompts_render_fully(self):
        cfg = Config()
        mapping = {"id": "20260912-1200-codex", "provider": "codex", "deadline_utc": "2026-09-12T14:00:00Z",
                   "size": "small", "quota_before": "codex 5h 3% / weekly 1% used", "goals_path": "GOALS.md",
                   "snapshot_dir": "runs/20260912-1200-codex/snapshot", "inbox_path": "INBOX.md", "finalize_minutes": "10",
                   "sources": "   - `tasks.md`", "recheck_rows": "| An item from `tasks.md` | look again |",
                   "private_sources": "none"}
        for name in ("worker.md", "finalize.md"):
            text = run.render((cfg.prompts_dir / name).read_text(), mapping)
            self.assertEqual(re.findall(r"\{[a-z_]+\}", text), [], f"{name} has keys the mapping does not fill")

    def test_agent_command(self):
        cfg = Config(repo_dir=Path("/r"))
        c = run.agent_command(cfg, "claude", "xhigh", "id1")
        self.assertEqual(c[:2], ["claude", "-p"])
        self.assertIn("--dangerously-skip-permissions", c)
        self.assertIn("xhigh", c)
        c = run.agent_command(cfg, "codex", "high", "id1")
        self.assertEqual(c[-1], "-")
        self.assertIn('model_reasoning_effort="high"', c)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", c)
        cfg.agent_full_access = False
        c = run.agent_command(cfg, "codex", "high", "id1")
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", c)
        self.assertIn("workspace-write", c)

    def test_chat_command_claude(self):
        line = run.chat_command("claude", "20260923-1449-claude", "claude-opus-5-5", "xhigh")
        self.assertEqual(line, "gh pr checkout run/20260923-1449-claude && claude --model claude-opus-5-5 --effort xhigh "
                         "'This is remainderbot run 20260923-1449-claude. Read runs/20260923-1449-claude/README.md, "
                         "prompt.md and run.json, then the log under runs/20260923-1449-claude/log/ if it is there, "
                         "and take my questions.'")
        self.assertEqual(shlex.split(line.split(" && ", 1)[1])[:5],
                         ["claude", "--model", "claude-opus-5-5", "--effort", "xhigh"])

    def test_chat_command_codex_quotes_the_toml_override(self):
        line = run.chat_command("codex", "20260919-1200-codex", "gpt-6-astra", "xhigh")
        self.assertTrue(line.startswith("gh pr checkout run/20260919-1200-codex && codex -m gpt-6-astra "
                                        "-c 'model_reasoning_effort=\"xhigh\"' 'This is remainderbot run"))
        self.assertEqual(shlex.split(line.split(" && ", 1)[1])[:5],
                         ["codex", "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="xhigh"'])

    def test_chat_section_uses_the_configured_model(self):
        cfg = Config(repo_dir=Path("/r"), claude_model="claude-x", codex_model="gpt-x")
        sec = run.chat_section(cfg, "claude", "r1", "high")
        self.assertEqual(sec, "\n## Chat about this run\nSame harness and model, from any clone of the repo:\n\n```\n"
                         + run.chat_command("claude", "r1", "claude-x", "high") + "\n```\n")
        self.assertIn("codex -m gpt-x -c 'model_reasoning_effort=\"xhigh\"'", run.chat_section(cfg, "codex", "r1", "xhigh"))
        with self.assertRaises(ValueError):
            run.chat_command("gemini", "r1", "m", "high")

    def test_quota_wall(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            p.write_text('{"type":"result"}\n{"type":"error","message":"You have hit your rate limit"}\n')
            self.assertTrue(run.hit_quota_wall(p))
            p.write_text('{"type":"result","text":"the rate limit is fine"}\n')
            self.assertFalse(run.hit_quota_wall(p))


class SourcesBlock(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)
        self.config = Config(repo_dir=self.td)
        self.snap = self.td / "snapshot"
        self.snap.mkdir()

    def write(self, name, text="<!-- generated -->\n\n# x\n"):
        (self.snap / name).write_text(text)

    def test_files_in_config_order_with_descriptions(self):
        (self.td / "sources.toml").write_text(
            'version = 1\n'
            '[[sources]]\nname = "tasks"\ntype = "gws-tasks"\ndescription = "Errands, mostly."\n'
            '[[sources]]\nname = "issues"\ntype = "gh-issues"\nowner = "you"\n'
            '[[sources]]\nname = "notes"\ntype = "gh-issues"\nowner = "you"\nprivate = true\n'
            '[[sources]]\nname = "never-fetched"\ntype = "gws-tasks"\n')
        for name in ("notes.md", "issues.md", "tasks.md", "left-over.md"):
            self.write(name)
        self.write("issues.md", "stale: 2026-10-07 10:00 UTC: gh search issues: exit 1: down\n\n# old\n")
        self.assertEqual(run.sources_block(self.config, self.snap), "\n".join([
            "   - `tasks.md` — Errands, mostly",
            "   - `issues.md` — Open GitHub issues, grouped by repo. Stale: its last refresh failed, so this is "
            "older content; its first line says why",
            "   - `notes.md` (private) — Open GitHub issues, grouped by repo",
            "   - `left-over.md` (private: not in sources.toml)",
        ]))

    def test_without_a_usable_config_the_files_are_still_listed(self):
        self.write("b.md")
        self.write("a.md")
        unknown = "   - `a.md` (private: not in sources.toml)\n   - `b.md` (private: not in sources.toml)"
        self.assertEqual(run.sources_block(self.config, self.snap), unknown)
        (self.td / "sources.toml").write_text("version = 1\n[[sources]\n")
        self.assertEqual(run.sources_block(self.config, self.snap), unknown)

    def test_an_empty_snapshot(self):
        self.assertEqual(run.sources_block(self.config, self.snap), "   - (none: the snapshot is empty)")
        self.assertEqual(run.recheck_rows(self.config, self.snap), "")
        self.assertEqual(run.private_sources(self.config, self.snap), "none")

    def test_recheck_rows_in_config_order_for_files_in_the_snapshot(self):
        (self.td / "sources.toml").write_text(
            'version = 1\n'
            '[[sources]]\nname = "tasks"\ntype = "gws-tasks"\nrecheck = """still open?\n  | look | again"""\n'
            '[[sources]]\nname = "never-fetched"\ntype = "gws-tasks"\n'
            '[[sources]]\nname = "issues"\ntype = "gh-issues"\nowner = "you"\n')
        for name in ("issues.md", "tasks.md", "left-over.md"):
            self.write(name)
        self.assertEqual(run.recheck_rows(self.config, self.snap), "\n".join([
            "| An item from `tasks.md` | still open? \\| look \\| again |",
            "| An item from `issues.md` | `gh issue view`: still open? does a linked PR or a recent commit already "
            "fix it? |",
        ]))

    def test_private_sources_name_the_files_that_are_in_the_snapshot(self):
        def private(names, fetched):
            (self.td / "sources.toml").write_text("version = 1\n" + "".join(
                f'[[sources]]\nname = "{n}"\ntype = "gws-tasks"\nprivate = true\n' for n in names)
                + '[[sources]]\nname = "public"\ntype = "gws-tasks"\n')
            for p in self.snap.glob("*.md"):
                p.unlink()
            for n in fetched + ["public"]:
                self.write(f"{n}.md")
            return run.private_sources(self.config, self.snap)

        self.assertEqual(private([], []), "none")
        self.assertEqual(private(["wiki"], ["wiki"]), "`wiki.md`")
        self.assertEqual(private(["wiki", "notes"], ["wiki"]), "`wiki.md`")
        self.assertEqual(private(["wiki", "notes"], ["notes", "wiki"]), "`wiki.md` and `notes.md`")
        self.assertEqual(private(["a", "b", "c"], ["a", "b", "c"]), "`a.md`, `b.md`, and `c.md`")

    def test_a_file_sources_toml_does_not_describe_is_private(self):
        # a private source removed from sources.toml, then a --no-snapshot run: its old file is still there
        (self.td / "sources.toml").write_text('version = 1\n[[sources]]\nname = "tasks"\ntype = "gws-tasks"\n')
        self.write("tasks.md")
        self.write("wiki.md")
        self.assertEqual(run.private_sources(self.config, self.snap), "`wiki.md`")

    def test_every_file_is_private_when_the_config_does_not_load(self):
        self.write("b.md")
        self.write("a.md")
        self.assertEqual(run.private_sources(self.config, self.snap), "`a.md` and `b.md`")
        self.assertEqual(run.recheck_rows(self.config, self.snap), "")


if __name__ == "__main__":
    unittest.main()
