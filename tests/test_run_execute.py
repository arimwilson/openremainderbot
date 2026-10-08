"""End-to-end test of run.execute() against a fake `codex` binary in a throwaway repo."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from remainderbot import run, usage
from remainderbot.config import Config
from remainderbot.decide import Decision

HERE = Path(__file__).parent
FIX = HERE / "fixtures"
# a `{key}` left in a rendered prompt is one execute() does not supply
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def fake_usage(providers):
    return {"codex": usage.parse_codex(json.loads((FIX / "codex_ratelimits.json").read_text()))}


class Execute(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.repo = self.td / "repo"
        self.repo.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)
        g("init", "-q", "-b", "main")
        g("config", "user.email", "t@example.com")
        g("config", "user.name", "t")
        (self.repo / "GOALS.md").write_text("# goals\n")
        (self.repo / "INBOX.md").write_text("| id |\n")
        (self.repo / "goals" / "snapshot").mkdir(parents=True)
        (self.repo / "goals" / "snapshot" / "tasks.md").write_text("- x\n")
        (self.repo / ".gitignore").write_text("goals/snapshot/\n")
        g("add", "-A")
        g("commit", "-qm", "init")
        bin_dir = self.td / "bin"
        bin_dir.mkdir()
        shutil.copy(HERE / "fake_codex.py", bin_dir / "codex")
        os.chmod(bin_dir / "codex", 0o755)
        self.env = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.env.start()
        self.usage_patch = mock.patch.object(run.usage_mod, "read_all", fake_usage)
        self.usage_patch.start()
        self.min_timeout = mock.patch.object(run, "MIN_TIMEOUT_S", 1.0)
        self.min_timeout.start()
        self.config = Config(repo_dir=self.repo, providers=["codex"], finalize_minutes=1)
        self.logs = []

    def tearDown(self):
        self.min_timeout.stop()
        self.usage_patch.stop()
        self.env.stop()
        shutil.rmtree(self.td, ignore_errors=True)

    def decision(self, minutes=5):
        now = datetime.now(tz=timezone.utc).replace(microsecond=0)
        return Decision("codex", now + timedelta(minutes=minutes), "small",
                        int((now + timedelta(minutes=minutes + 15)).timestamp()), 80, 90)

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True, text=True).stdout

    def test_done_path(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "done"}):
            r = run.execute(self.decision(), self.config, self.logs.append, run_id="20260912-1200-codex")
        self.assertTrue(r.done and not r.finalized and not r.timed_out and r.exit_code == 0)
        self.assertEqual(r.outcome, "done")
        self.assertEqual(r.branch, "run/20260912-1200-codex")
        # back on main, and main did not get the run
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "main")
        self.assertFalse((self.repo / "runs").exists())
        files = self.git("ls-tree", "-r", "--name-only", r.branch).split()
        for f in ("prompt.md", "run.json", "PLAN.md", "README.md", "DONE", "artifact/thing.md", "log/codex.jsonl",
                  "snapshot/tasks.md"):
            self.assertIn(f"runs/20260912-1200-codex/{f}", files, f)
        self.assertNotIn("goals/snapshot/tasks.md", files)  # never committed from main, only the run's copy
        # the copy is in the very first commit of the run, alongside the prompt
        first = self.git("log", r.branch, "--format=%H", "--diff-filter=A", "--", "runs/20260912-1200-codex/prompt.md").strip()
        self.assertIn("runs/20260912-1200-codex/snapshot/tasks.md",
                      self.git("show", "--name-only", "--format=", first))
        show = self.git("show", f"{r.branch}:runs/20260912-1200-codex/README.md")
        self.assertIn("quota before: codex 5h 3% / weekly 1% used", show)
        self.assertIn("finished: DONE", show)
        # the wrapper closes the README with the chat line: main-run effort, configured model
        self.assertTrue(show.endswith("\n## Chat about this run\nSame harness and model, from any clone of the repo:\n\n"
                                      "```\n" + run.chat_command("codex", "20260912-1200-codex", self.config.codex_model, "high")
                                      + "\n```\n"), show[-400:])
        self.assertEqual(show.count("## Chat about this run"), 1)
        prompt = self.git("show", f"{r.branch}:runs/20260912-1200-codex/prompt.md")
        self.assertIn("Deadline: " + self.decision().deadline_str[:13], prompt)
        self.assertIn("`GOALS.md`", prompt)
        self.assertIn("`runs/20260912-1200-codex/snapshot/`", prompt)
        self.assertIn("One file per source:\n   - `tasks.md` (private: not in sources.toml)\n3. `INBOX.md`", prompt)
        self.assertIn('Source: runs/20260912-1200-codex/snapshot/<file>', prompt)
        self.assertEqual(PLACEHOLDER.findall(prompt), [], "worker.md has keys execute() does not fill")
        # no sources.toml in this repo: nothing to recheck by source, and every file counts as private
        self.assertIn("| Document or plan | search where it would live", prompt)
        self.assertIn("Private sources this run: `tasks.md`.", prompt)
        info = json.loads(self.git("show", f"{r.branch}:runs/20260912-1200-codex/run.json"))
        self.assertTrue(info["done"])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", info["command"])
        self.assertIn('model_reasoning_effort="high"', info["command"])
        log = self.git("show", f"{r.branch}:runs/20260912-1200-codex/log/codex.jsonl")
        self.assertIn('"prompt_head": "# remainderbot worker run', log)
        self.assertEqual(self.git("log", "--oneline", r.branch).count("\n"), 5)  # init, start, plan, agent done, wrapper done

    def test_ignored_files_are_cleaned_but_logs_kept(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "done", "FAKE_JUNK": "1"}):
            r = run.execute(self.decision(), self.config, self.logs.append)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "main")
        self.assertIn(f"runs/{r.id}/.gitignore", self.git("ls-tree", "-r", "--name-only", r.branch).split())
        left = sorted(str(p.relative_to(r.run_dir)) for p in r.run_dir.rglob("*") if p.is_file())
        self.assertEqual(left, ["log/kept.jsonl"])
        self.assertTrue(any("cleaned ignored files" in l for l in self.logs), self.logs)

    def test_no_done_runs_finalize(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "nodone"}):
            r = run.execute(self.decision(), self.config, self.logs.append)
        self.assertFalse(r.done)
        self.assertEqual(r.outcome, "abandoned")
        self.assertTrue(r.finalized and r.readme_exists)
        files = self.git("ls-tree", "-r", "--name-only", r.branch).split()
        self.assertIn(f"runs/{r.id}/finalize-prompt.md", files)
        self.assertIn(f"runs/{r.id}/log/codex-finalize.jsonl", files)
        fin_prompt = self.git("show", f"{r.branch}:runs/{r.id}/finalize-prompt.md")
        self.assertEqual(PLACEHOLDER.findall(fin_prompt), [], "finalize.md has keys execute() does not fill")
        readme = self.git("show", f"{r.branch}:runs/{r.id}/README.md")
        self.assertIn("status: trimmed", readme)
        self.assertIn("finished: via finalize", readme)
        self.assertIn(f"gh pr checkout run/{r.id} && codex -m", readme)
        self.assertIn('model_reasoning_effort="medium"', self.git("show", f"{r.branch}:runs/{r.id}/log/codex-finalize.jsonl"))

    def test_deadline_kills_and_finalizes(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "hang"}):
            t0 = datetime.now()
            r = run.execute(self.decision(minutes=0), self.config, self.logs.append)
        self.assertLess((datetime.now() - t0).total_seconds(), 30)
        self.assertTrue(r.timed_out and r.finalized and not r.done)
        self.assertEqual(r.outcome, "timeout")
        self.assertIsNone(r.exit_code)
        self.assertTrue(any("killing the process group" in l for l in self.logs))
        self.assertIn("status: trimmed", self.git("show", f"{r.branch}:runs/{r.id}/README.md"))
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "main")

    def test_rate_limit_waits_then_finalizes(self):
        d = self.decision()
        # reset "in the past" so the wait is zero but the branch is exercised
        d = Decision(d.provider, d.deadline_utc, d.size, int(datetime.now(tz=timezone.utc).timestamp()) - 1, 80, 90)
        with mock.patch.dict(os.environ, {"FAKE_MODE": "ratelimit"}):
            r = run.execute(d, self.config, self.logs.append)
        self.assertEqual(r.exit_code, 1)
        self.assertTrue(r.quota_wall)
        self.assertEqual(r.outcome, "quota")
        self.assertTrue(r.finalized)
        self.assertFalse(any("sleeping" in l for l in self.logs))  # reset already passed: no wait
        self.assertFalse(run.hit_quota_wall(self.repo / "nonexistent"))

    def test_rate_limit_sleeps_until_reset(self):
        d = self.decision()
        d = Decision(d.provider, d.deadline_utc, d.size, int(datetime.now(tz=timezone.utc).timestamp()) + 2, 80, 90)
        with mock.patch.dict(os.environ, {"FAKE_MODE": "ratelimit"}):
            t0 = datetime.now()
            r = run.execute(d, self.config, self.logs.append)
        self.assertTrue(r.finalized)
        self.assertTrue(any("quota wall detected; sleeping" in l for l in self.logs), self.logs)
        self.assertGreater((datetime.now() - t0).total_seconds(), 1)

    def test_refuses_dirty_repo(self):
        (self.repo / "GOALS.md").write_text("changed\n")
        with self.assertRaises(RuntimeError):
            run.execute(self.decision(), self.config, self.logs.append)


if __name__ == "__main__":
    unittest.main()
