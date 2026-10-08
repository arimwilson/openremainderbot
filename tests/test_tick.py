"""tick restarts itself once when the pull at its start changed the package (code or prompts),
stops before anything else when origin may not be pushed to, and stops before the snapshot
when sources.toml is invalid."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from remainderbot import __main__ as cli
from remainderbot.config import Config


class Restarted(Exception):
    """Raised by the patched os.execve in place of replacing the test process."""


class TickRepo(unittest.TestCase):
    """A checkout with a bare origin, and a second clone that pushes changes to it."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.origin = self.td / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.repo = self.td / "repo"
        self.repo.mkdir()
        g = self.git
        g("init", "-q", "-b", "main")
        g("config", "user.email", "t@example.com")
        g("config", "user.name", "t")
        g("remote", "add", "origin", str(self.origin))
        (self.repo / "pkg").mkdir()
        (self.repo / "pkg" / "mod.py").write_text("v = 1\n")
        (self.repo / "GOALS.md").write_text("# goals\n")
        g("add", "-A")
        g("commit", "-qm", "init")
        g("push", "-q", "-u", "origin", "main")
        # a second clone stands in for the user pushing a change from elsewhere
        self.other = self.td / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.other)], check=True)
        g("config", "user.email", "t@example.com", cwd=self.other)
        g("config", "user.name", "t", cwd=self.other)

        self.logs = []
        self.execve = mock.Mock(side_effect=Restarted)
        env = {k: v for k, v in os.environ.items() if k != cli.REEXEC_ENV}
        self.patches = [
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(cli, "PACKAGE_DIR", self.repo / "pkg"),
            mock.patch.object(cli, "log", self.logs.append),
            mock.patch.object(cli.os, "execve", self.execve),
            # everything after the restart check is out of scope here: no PRs, no quota
            mock.patch.object(cli.origin_mod, "check", lambda config: None),
            mock.patch.object(cli.inbox_mod, "sync", lambda config, log: 0),
            mock.patch.object(cli.publish_mod, "retry_unpublished", lambda config, log: None),
            mock.patch.object(cli.usage_mod, "read_all", lambda providers: {}),
        ]
        for p in self.patches:
            p.start()
        self.config = Config(repo_dir=self.repo, providers=["codex"])
        self.args = Namespace(no_snapshot=True)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.td, ignore_errors=True)

    def git(self, *a, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *a], check=True,
                              capture_output=True, text=True).stdout

    def push_change(self, path, text):
        (self.other / path).parent.mkdir(parents=True, exist_ok=True)
        (self.other / path).write_text(text)
        self.git("add", "-A", cwd=self.other)
        self.git("commit", "-qm", f"change {path}", cwd=self.other)
        self.git("push", "-q", "origin", "main", cwd=self.other)


class RestartAfterPull(TickRepo):
    def test_code_change_restarts(self):
        self.push_change("pkg/mod.py", "v = 2\n")
        with self.assertRaises(Restarted):
            cli._tick(self.config, self.args)
        self.assertEqual((self.repo / "pkg" / "mod.py").read_text(), "v = 2\n")  # pulled first
        self.execve.assert_called_once()
        path, argv, env = self.execve.call_args.args
        self.assertEqual(path, sys.executable)
        self.assertEqual(argv, [sys.executable, "-m", "remainderbot", *sys.argv[1:]])
        self.assertEqual(env[cli.REEXEC_ENV], "1")
        self.assertTrue(any("restarting the tick" in l for l in self.logs), self.logs)

    def test_prompt_change_restarts(self):
        self.push_change("pkg/prompts/worker.md", "# new prompt {sources}\n")
        with self.assertRaises(Restarted):
            cli._tick(self.config, self.args)

    def test_other_changes_do_not_restart(self):
        self.push_change("GOALS.md", "# goals, edited\n")
        self.push_change("runs/x/README.md", "# a merged run\n")
        self.assertEqual(cli._tick(self.config, self.args), 0)
        self.execve.assert_not_called()
        self.assertEqual((self.repo / "GOALS.md").read_text(), "# goals, edited\n")
        self.assertEqual(self.logs[-1], "tick end")

    def test_restarts_only_once(self):
        self.push_change("pkg/mod.py", "v = 2\n")
        with mock.patch.dict(os.environ, {cli.REEXEC_ENV: "1"}):
            self.assertEqual(cli._tick(self.config, self.args), 0)
        self.execve.assert_not_called()
        self.assertTrue(any("going on" in l for l in self.logs), self.logs)

    def test_started_on_a_run_branch(self):
        # a tick that died mid-run leaves the checkout on run/<id>; this process imported
        # the code from there, so the comparison starts from that branch, not from main
        self.git("checkout", "-q", "-b", "run/20260912-1200-codex")
        self.push_change("pkg/mod.py", "v = 2\n")
        with self.assertRaises(Restarted):
            cli._tick(self.config, self.args)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "main")

    def test_package_outside_the_repo_never_restarts(self):
        before = self.git("rev-parse", "HEAD").strip()
        self.push_change("pkg/mod.py", "v = 2\n")
        self.git("pull", "-q", "origin", "main")
        self.assertEqual(cli.changed_code(self.config, before, self.repo / "pkg"), ["pkg/mod.py"])
        self.assertEqual(cli.changed_code(self.config, before, self.td / "elsewhere" / "pkg"), [])


class PublicOrigin(TickRepo):
    def test_ends_the_tick_before_it_syncs_or_runs(self):
        refuse = mock.Mock(side_effect=cli.origin_mod.PublicRepoError("origin you/bot is public, ..."))
        sync, read_all = mock.Mock(), mock.Mock(return_value={})
        with mock.patch.object(cli.origin_mod, "check", refuse), mock.patch.object(cli.inbox_mod, "sync", sync), \
                mock.patch.object(cli.usage_mod, "read_all", read_all):
            self.assertEqual(cli._tick(self.config, Namespace(no_snapshot=False)), 1)
        refuse.assert_called_once_with(self.config)
        sync.assert_not_called()
        read_all.assert_not_called()
        self.assertEqual(self.logs[-2:], ["not running: origin you/bot is public, ...", "tick end"])
        self.assertFalse(self.config.snapshot_dir.exists())


class InvalidSources(TickRepo):
    def test_skips_the_snapshot_and_the_run(self):
        (self.repo / "sources.toml").write_text('version = 1\n[[sources]]\nname = "t"\ntype = "gmail"\n')
        read_all = mock.Mock(return_value={})
        with mock.patch.object(cli.usage_mod, "read_all", read_all):
            self.assertEqual(cli._tick(self.config, Namespace(no_snapshot=False)), 1)
        read_all.assert_not_called()
        self.assertTrue(any(l.startswith("sources.toml: source 't': unknown type 'gmail'") and
                            l.endswith("; skipping the snapshot and the run") for l in self.logs), self.logs)
        self.assertEqual(self.logs[-1], "tick end")
        self.assertFalse(self.config.snapshot_dir.exists())


if __name__ == "__main__":
    unittest.main()
