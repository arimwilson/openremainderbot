"""End-to-end test of publish.pr() and inbox.sync() against a bare origin and a fake `gh`,
including the refusal to push to a public origin (origin.py)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from remainderbot import inbox, origin, publish, run, usage
from remainderbot.config import Config
from remainderbot.decide import Decision, load_state

HERE = Path(__file__).parent
FIX = HERE / "fixtures"


def fake_usage(providers):
    return {"codex": usage.parse_codex(json.loads((FIX / "codex_ratelimits.json").read_text()))}


class Publish(unittest.TestCase):
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
        (self.repo / "GOALS.md").write_text("# goals\n")
        (self.repo / "INBOX.md").write_text("# INBOX\n\nledger.\n\n" + inbox.HEADER + "\n" + inbox.SEPARATOR + "\n")
        (self.repo / "state.json").write_text("{}\n")
        (self.repo / "goals" / "snapshot").mkdir(parents=True)
        (self.repo / "goals" / "snapshot" / "tasks.md").write_text("- x\n")
        (self.repo / ".gitignore").write_text("goals/snapshot/\n")
        g("add", "-A")
        g("commit", "-qm", "init")
        g("push", "-q", "-u", "origin", "main")
        bin_dir = self.td / "bin"
        bin_dir.mkdir()
        for src, name in (("fake_codex.py", "codex"), ("fake_gh.py", "gh")):
            shutil.copy(HERE / src, bin_dir / name)
            os.chmod(bin_dir / name, 0o755)
        self.db = self.td / "prs.json"
        self.env = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}",
                                                "FAKE_GH_DB": str(self.db), "FAKE_MODE": "done"})
        self.env.start()
        self.patches = [mock.patch.object(run.usage_mod, "read_all", fake_usage),
                        mock.patch.object(run, "MIN_TIMEOUT_S", 1.0)]
        for p in self.patches:
            p.start()
        self.config = Config(repo_dir=self.repo, providers=["codex"], finalize_minutes=1)
        self.logs = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        shutil.rmtree(self.td, ignore_errors=True)

    def git(self, *a, check=True):
        return subprocess.run(["git", "-C", str(self.repo), *a], check=check, capture_output=True, text=True).stdout

    def prs(self):
        return json.loads(self.db.read_text()) if self.db.exists() else []

    def execute(self, run_id):
        now = datetime.now(tz=timezone.utc).replace(microsecond=0)
        d = Decision("codex", now + timedelta(minutes=5), "small", int((now + timedelta(minutes=20)).timestamp()), 80, 90)
        return run.execute(d, self.config, self.logs.append, run_id=run_id)

    def rows(self):
        return inbox.load(self.repo / "INBOX.md")[1]

    def test_publish_then_sync(self):
        r = self.execute("20260912-1200-codex")
        url = publish.pr(r.run_dir, self.config, self.logs.append)
        self.assertEqual(url, "https://github.com/example/remainderbot/pull/1")

        # branch and main are on origin; the PR body is the README verbatim
        remote = self.git("ls-remote", "--heads", str(self.origin))
        self.assertIn("refs/heads/run/20260912-1200-codex", remote)
        self.assertEqual(self.git("rev-parse", "main").strip(),
                         self.git("ls-remote", str(self.origin), "main").split()[0])
        (pr,) = self.prs()
        self.assertEqual(pr["headRefName"], "run/20260912-1200-codex")
        self.assertEqual(pr["baseRefName"], "main")
        self.assertEqual(pr["body"], self.git("show", "run/20260912-1200-codex:runs/20260912-1200-codex/README.md"))
        self.assertEqual(pr["title"], "Fake done")

        # the ledger row and state, committed on main, tree clean, still on main
        self.assertEqual(self.rows(), [inbox.Row("20260912-1200-codex", "codex", "Fake done", "needs-review", "")])
        state = load_state(self.repo / "state.json")
        self.assertEqual(state["codex"]["last_run_id"], "20260912-1200-codex")
        self.assertEqual(state["codex"]["last_pr"], url)
        self.assertNotIn("unpublished", state)
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "main")
        self.assertIn("publish 20260912-1200-codex: https://", self.git("log", "-1", "--format=%s"))

        # nothing to sync yet
        self.assertEqual(inbox.sync(self.config, self.logs.append), 0)

        # the user merges with a comment: the row becomes approved with the note
        pr["state"] = "MERGED"
        pr["comments"] = [{"author": {"login": "you"}, "body": "nice, ship it", "createdAt": "2026-09-13T00:00:00Z"}]
        self.db.write_text(json.dumps([pr]))
        self.assertEqual(inbox.sync(self.config, self.logs.append), 1)
        self.assertEqual(self.rows(), [inbox.Row("20260912-1200-codex", "codex", "Fake done", "approved", "nice, ship it")])
        self.assertIn("inbox: sync 1 row(s)", self.git("log", "-1", "--format=%s"))
        self.assertEqual(self.git("status", "--porcelain").strip(), "")

        # publishing again is idempotent: same PR, the synced verdict is kept
        self.assertEqual(publish.pr(r.run_dir, self.config, self.logs.append), url)
        self.assertEqual(len(self.prs()), 1)
        self.assertEqual(self.rows()[0].status, "approved")

    def test_abandoned_run_gets_pr_and_abandoned_row(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "nodone"}):
            r = self.execute("20260912-1300-codex")
        # the fake finalize writes "status: trimmed"; force abandoned to exercise the row status
        self.git("checkout", "-q", r.branch)
        readme = r.run_dir / "README.md"
        readme.write_text(readme.read_text().replace("status: trimmed", "status: abandoned"))
        self.git("commit", "-qam", "abandon")
        self.git("checkout", "-q", "main")
        publish.pr(r.run_dir, self.config, self.logs.append)
        self.assertEqual(self.prs()[0]["title"], "Fake trimmed [abandoned]")
        self.assertEqual(self.rows()[0].status, "abandoned")
        # closing the PR keeps it abandoned rather than calling it rejected
        prs = self.prs()
        prs[0]["state"] = "CLOSED"
        self.db.write_text(json.dumps(prs))
        inbox.sync(self.config, self.logs.append)
        self.assertEqual(self.rows()[0].status, "abandoned")

    def test_failure_is_remembered_and_retried(self):
        r = self.execute("20260912-1400-codex")
        with mock.patch.dict(os.environ, {"FAKE_GH_FAIL": "1"}):
            self.assertIsNone(publish.pr(r.run_dir, self.config, self.logs.append))
        state = load_state(self.repo / "state.json")
        self.assertEqual(state["unpublished"]["20260912-1400-codex"]["attempts"], 1)
        self.assertIn("api.github.com", state["unpublished"]["20260912-1400-codex"]["error"])
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        self.assertTrue(any("publish 20260912-1400-codex failed" in l for l in self.logs))

        publish.retry_unpublished(self.config, self.logs.append)
        self.assertNotIn("unpublished", load_state(self.repo / "state.json"))
        self.assertEqual(self.rows()[0].id, "20260912-1400-codex")
        self.assertEqual(len(self.prs()), 1)

    def test_sync_recovers_row_for_pr_without_one(self):
        self.db.write_text(json.dumps([{"number": 7, "url": "https://x/pull/7", "state": "CLOSED", "title": "Old post",
                                        "headRefName": "run/20260901-0100-claude",
                                        "comments": [{"body": "not this", "createdAt": "1"}], "reviews": []},
                                       {"number": 8, "url": "https://x/pull/8", "state": "OPEN", "title": "unrelated",
                                        "headRefName": "feature/x", "comments": [], "reviews": []}]))
        self.assertEqual(inbox.sync(self.config, self.logs.append), 1)
        self.assertEqual(self.rows(), [inbox.Row("20260901-0100-claude", "claude", "Old post", "rejected", "not this")])

    def branches_on_origin(self) -> str:
        return self.git("ls-remote", "--heads", str(self.origin))

    def test_public_origin_gets_nothing(self):
        r = self.execute("20260912-1500-codex")
        main_on_origin = self.git("ls-remote", str(self.origin), "main")
        with mock.patch.dict(os.environ, {"FAKE_GH_VISIBILITY": "PUBLIC"}):
            self.assertIsNone(publish.pr(r.run_dir, self.config, self.logs.append))
            self.assertEqual(inbox.sync(self.config, self.logs.append), 0)
        self.assertNotIn("run/", self.branches_on_origin())
        self.assertEqual(self.git("ls-remote", str(self.origin), "main"), main_on_origin)  # not even main
        error = load_state(self.repo / "state.json")["unpublished"]["20260912-1500-codex"]["error"]
        self.assertTrue(error.startswith("origin example/remainderbot is public, and a run branch carries"), error)
        self.assertIn("ALLOW_PUBLIC_REPO=1", error)
        self.assertTrue(any(l.startswith("push main refused: origin example/remainderbot is public")
                            for l in self.logs), self.logs)
        self.assertEqual(self.prs(), [])

    def test_gh_that_cannot_answer_gets_nothing_pushed(self):
        r = self.execute("20260912-1510-codex")
        with mock.patch.dict(os.environ, {"FAKE_GH_FAIL": "1"}):
            self.assertIsNone(publish.pr(r.run_dir, self.config, self.logs.append))
        self.assertNotIn("run/", self.branches_on_origin())
        error = load_state(self.repo / "state.json")["unpublished"]["20260912-1510-codex"]["error"]
        self.assertTrue(error.startswith("cannot tell whether origin is private"), error)

    def test_internal_origin_and_allow_public_repo_publish(self):
        r = self.execute("20260912-1520-codex")
        with mock.patch.dict(os.environ, {"FAKE_GH_VISIBILITY": "INTERNAL"}):
            self.assertIsNotNone(publish.pr(r.run_dir, self.config, self.logs.append))
        self.config.allow_public_repo = True
        r = self.execute("20260912-1530-codex")
        with mock.patch.dict(os.environ, {"FAKE_GH_VISIBILITY": "PUBLIC"}):
            self.assertIsNotNone(publish.pr(r.run_dir, self.config, self.logs.append))
        self.assertIn("refs/heads/run/20260912-1530-codex", self.branches_on_origin())

    def test_gh_is_asked_once_and_every_pr_call_names_origin(self):
        # with an `upstream` remote, gh's own default repo would be upstream, not origin
        upstream = self.td / "upstream.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(upstream)], check=True)
        self.git("remote", "add", "upstream", str(upstream))
        calls = self.td / "gh_calls.jsonl"
        r = self.execute("20260912-1540-codex")
        with mock.patch.dict(os.environ, {"FAKE_GH_CALLS": str(calls)}):
            publish.pr(r.run_dir, self.config, self.logs.append)
            inbox.sync(self.config, self.logs.append)
        args = [json.loads(l) for l in calls.read_text().splitlines()]
        self.assertEqual(sum(a[:2] == ["repo", "view"] for a in args), 1)
        pr_calls = [a for a in args if a[0] == "pr"]
        self.assertEqual(len(pr_calls), 3)  # list --head, create, list for sync
        for a in pr_calls:
            self.assertEqual(a[a.index("--repo") + 1], str(self.origin), a)

    def test_every_push_url_must_be_private(self):
        # `git push origin` pushes to every pushurl; get-url without --all shows only the first
        mirror = self.td / "mirror.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(mirror)], check=True)
        self.git("remote", "set-url", "--add", "--push", "origin", str(self.origin))
        self.git("remote", "set-url", "--add", "--push", "origin", str(mirror))
        public = json.dumps({str(mirror): {"nameWithOwner": "example/mirror", "visibility": "PUBLIC"}})
        r = self.execute("20260912-1550-codex")
        with mock.patch.dict(os.environ, {"FAKE_GH_REPOS": public}):
            self.assertIsNone(publish.pr(r.run_dir, self.config, self.logs.append))
        for repo in (self.origin, mirror):
            self.assertNotIn("run/", self.git("ls-remote", "--heads", str(repo)))
        error = load_state(self.repo / "state.json")["unpublished"]["20260912-1550-codex"]["error"]
        self.assertTrue(error.startswith("example/mirror, one of origin's 2 push URLs, is public"), error)

        publish.retry_unpublished(self.config, self.logs.append)  # both private now
        for repo in (self.origin, mirror):
            self.assertIn("refs/heads/run/20260912-1550-codex", self.git("ls-remote", "--heads", str(repo)))
        self.assertEqual(self.prs()[0]["headRefName"], "run/20260912-1550-codex")

    def test_origin_url_drops_credentials(self):
        self.git("remote", "set-url", "origin", "https://x-access-token:secret@github.com/you/bot.git")
        self.assertEqual(origin.url(self.config), "https://github.com/you/bot.git")
        self.git("remote", "set-url", "origin", "git@github.com:you/bot.git")
        self.assertEqual(origin.url(self.config), "git@github.com:you/bot.git")

    def test_sync_gh_failure_raises(self):
        with mock.patch.dict(os.environ, {"FAKE_GH_FAIL": "1"}):
            with self.assertRaises(RuntimeError):
                inbox.sync(self.config, self.logs.append)


class PullMain(unittest.TestCase):
    """The bot's checkout and a second writer (the user's laptop) sharing a bare origin."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.origin = self.td / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.repo, self.other = self.td / "repo", self.td / "other"
        for d in (self.repo, self.other):
            subprocess.run(["git", "clone", "-q", str(self.origin), str(d)], check=True, capture_output=True)
            self.git(d, "config", "user.email", "t@example.com")
            self.git(d, "config", "user.name", "t")
            self.git(d, "checkout", "-q", "-B", "main")
        self.commit(self.other, "state.json", '{"claude": "2112"}\n', "init")
        self.git(self.other, "push", "-q", "-u", "origin", "main")
        self.git(self.repo, "pull", "-q", "origin", "main")
        self.config = Config(repo_dir=self.repo)
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def git(self, d, *a, check=True):
        return subprocess.run(["git", "-C", str(d), *a], check=check, capture_output=True, text=True).stdout

    def commit(self, d, name, text, msg):
        (d / name).write_text(text)
        self.git(d, "add", name)
        self.git(d, "commit", "-qm", msg)

    def diverge(self):
        """The bot commits state.json and cannot push; the other writer pushes its own edit."""
        self.commit(self.repo, "state.json", '{"claude": "2120"}\n', "tick: claim claude")
        self.commit(self.other, "state.json", '{"claude": "2153"}\n', "publish 2153")
        self.git(self.other, "push", "-q", "origin", "main")

    def rebasing(self):
        return publish._rebase_in_progress(self.config)

    def test_conflicting_pull_is_aborted(self):
        self.diverge()
        before = self.git(self.repo, "rev-parse", "main")
        self.assertFalse(publish.pull_main(self.config, self.logs.append))
        self.assertFalse(self.rebasing())
        self.assertEqual(self.git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip(), "main")
        self.assertEqual(self.git(self.repo, "rev-parse", "main"), before)
        self.assertEqual(self.git(self.repo, "status", "--porcelain").strip(), "")
        self.assertIn("pull main failed: CONFLICT", self.logs[0])
        self.assertIn("state.json", self.logs[0])

    def test_rebase_left_in_progress_is_dropped(self):
        # seen on a server: a plain pull stopped on the conflict, the next tick ran `checkout -f
        # main`, and every pull after that failed on the leftover rebase-merge directory
        self.diverge()
        self.git(self.repo, "pull", "-q", "--rebase", "origin", "main", check=False)
        self.git(self.repo, "checkout", "-q", "-f", "main")
        self.git(self.repo, "reset", "-q", "--hard", "origin/main")  # what the user did by hand
        self.assertTrue(self.rebasing())
        self.commit(self.other, "GOALS.md", "# goals\n", "edit goals")
        self.git(self.other, "push", "-q", "origin", "main")

        self.assertTrue(publish.pull_main(self.config, self.logs.append))
        self.assertFalse(self.rebasing())
        self.assertEqual(self.git(self.repo, "rev-parse", "main"), self.git(self.other, "rev-parse", "main"))
        self.assertIn("dropped a rebase left in progress", self.logs[0])

    def test_git_error_keeps_the_cause_not_the_advice(self):
        stuck = ("fatal: It seems that there is already a rebase-merge directory, and\n"
                 "I wonder if you are in the middle of another rebase.  If that is the\n"
                 "and run me again.  I am stopping in case you still have something\n"
                 "valuable there.\n")
        self.assertEqual(publish._git_error(stuck),
                         "fatal: It seems that there is already a rebase-merge directory, and")
        rejected = (" ! [rejected]        main -> main (fetch first)\n"
                    "error: failed to push some refs to 'origin'\n"
                    "hint: Updates were rejected because the remote contains work that you do\n")
        self.assertEqual(publish._git_error(rejected), "error: failed to push some refs to 'origin'")
        self.assertEqual(publish._git_error(""), "?")


if __name__ == "__main__":
    unittest.main()
