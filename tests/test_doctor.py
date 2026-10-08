"""doctor reports each failure on its own line and exits nonzero; the example files a new
instance copies are valid, and a missing INBOX.md starts with its preamble. A fake `gh`
and `codex` on a PATH of their own; no network."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from remainderbot import doctor, inbox, sources, usage
from remainderbot.config import Config

HERE = Path(__file__).parent
FIX = HERE / "fixtures"
GOALS = doctor.GOALS_EXAMPLE.read_text().replace("Fernhill", "Kestrel")  # edited, so not the example
SOURCES = 'version = 1\n\n[[sources]]\nname = "issues"\ntype = "gh-issues"\nowner = "you"\n'


class Examples(unittest.TestCase):
    def test_sources_example_loads_with_one_source_enabled(self):
        srcs = sources.parse(doctor.SOURCES_EXAMPLE.read_text(), "sources.example.toml")
        self.assertEqual([(s.name, s.type) for s in srcs], [("issues", "gh-issues")])

    def test_every_commented_out_source_is_valid(self):
        # uncomment the TOML (a table header or `key = ` after "# "), not the prose
        text = re.sub(r"(?m)^# (\s*(?:\[\[|[a-z_]+ = ))", r"\1", doctor.SOURCES_EXAMPLE.read_text())
        srcs = sources.parse(text, "sources.example.toml, uncommented")
        self.assertEqual([s.type for s in srcs],
                         ["gh-issues", "gh-roadmaps", "file", "gws-tasks", "gws-doc", "gh-markdown", "command"])
        self.assertEqual(len(srcs[5].fields["parts"]), 1)

    def test_a_missing_inbox_starts_with_the_preamble(self):
        self.assertEqual(inbox.load(Path(tempfile.gettempdir()) / "no-such-INBOX.md"), (inbox.PREAMBLE, []))
        self.assertEqual(inbox.parse(inbox.render(inbox.PREAMBLE, [])), (inbox.PREAMBLE, []))


class Doctor(unittest.TestCase):
    """A committed instance with a bare origin; PATH holds only the fakes, git, and python3."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)
        self.origin = self.td / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.repo = self.td / "repo"
        self.repo.mkdir()
        g = self.git
        g("init", "-q", "-b", "main")
        g("config", "user.email", "t@example.com")
        g("config", "user.name", "t")
        g("remote", "add", "origin", str(self.origin))
        (self.repo / "GOALS.md").write_text(GOALS)
        (self.repo / "sources.toml").write_text(SOURCES)
        (self.repo / "INBOX.md").write_text(inbox.render(inbox.PREAMBLE, []))
        g("add", "-A")
        g("commit", "-qm", "init")
        g("push", "-q", "-u", "origin", "main")

        bin_dir = self.td / "bin"
        bin_dir.mkdir()
        for src, name in (("fake_gh.py", "gh"), ("fake_codex.py", "codex")):
            shutil.copy(HERE / src, bin_dir / name)
            os.chmod(bin_dir / name, 0o755)
        (bin_dir / "git").symlink_to(shutil.which("git"))
        (bin_dir / "python3").symlink_to(sys.executable)
        env = mock.patch.dict(os.environ, {"PATH": str(bin_dir), "FAKE_GH_DB": str(self.td / "prs.json")})
        env.start()
        self.addCleanup(env.stop)
        codex = usage.parse_codex(json.loads((FIX / "codex_ratelimits.json").read_text()))
        self.read_all = mock.patch.object(doctor.usage_mod, "read_all", lambda ps: {p: codex for p in ps})
        self.read_all.start()
        self.addCleanup(self.read_all.stop)
        self.config = Config(repo_dir=self.repo, providers=["codex"])

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True, text=True).stdout

    def doctor(self) -> tuple[int, list[str]]:
        out = []
        return doctor.doctor(self.config, out.append), out

    def lines(self, out: list[str], status: str) -> dict[str, str]:
        """{what: detail} for the lines with this status."""
        found = {}
        for line in out:
            st, rest = line.split(None, 1)
            if st == status:
                what, detail = rest.split(": ", 1)
                found[what] = detail
        return found

    def test_a_ready_instance_passes(self):
        code, out = self.doctor()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertEqual(list(self.lines(out, "ok")),
                         ["python", "git", "gh", "codex", "sources.toml", "GOALS.md", "checkout", "origin", "push"])
        ok = self.lines(out, "ok")
        self.assertEqual(ok["gh"], "Logged in to github.com account example (keyring)")
        self.assertTrue(ok["codex"].startswith("quota readable: "), ok["codex"])
        self.assertEqual(ok["sources.toml"], "1 enabled: issues (gh-issues)")
        self.assertEqual(ok["origin"], "example/remainderbot is private")
        self.assertIn("git remote add upstream", self.lines(out, "info")["upstream"])
        self.assertFalse(self.git("ls-remote", str(self.origin), doctor.PROBE_REF).strip())  # dry run only

    def test_each_failure_is_reported(self):
        (self.repo / "sources.toml").write_text(SOURCES + '\n[[sources]]\nname = "tasks"\ntype = "gws-tasks"\n')
        self.git("remote", "set-url", "--push", "origin", str(self.td / "nowhere.git"))
        failing = usage.UsageError("codex: app-server exited before answering")
        with mock.patch.dict(os.environ, {"FAKE_GH_LOGGED_OUT": "1", "FAKE_GH_VISIBILITY": "PUBLIC"}), \
                mock.patch.object(doctor.usage_mod, "read_all", lambda ps: {p: failing for p in ps}):
            code, out = self.doctor()
        self.assertEqual(code, 1)
        fail = self.lines(out, "FAIL")
        self.assertEqual(sorted(fail), ["checkout", "codex", "gh", "gws", "origin", "push"], "\n".join(out))
        self.assertIn("gh auth login", fail["gh"])
        self.assertIn("app-server exited before answering", fail["codex"])
        self.assertIn("codex login", fail["codex"])
        self.assertEqual(fail["gws"], "not on PATH; tasks need it")
        self.assertIn("uncommitted changes to sources.toml", fail["checkout"])
        self.assertIn("example/remainderbot is public; the bot will not push there", fail["origin"])
        self.assertTrue(fail["push"].startswith("git push --dry-run: "), fail["push"])

    def test_missing_or_example_files_fail(self):
        shutil.copy(doctor.GOALS_EXAMPLE, self.repo / "GOALS.md")
        shutil.copy(doctor.SOURCES_EXAMPLE, self.repo / "sources.toml")
        (self.repo / "INBOX.md").unlink()
        self.git("add", "-A")
        self.git("commit", "-qm", "the examples")
        code, out = self.doctor()
        self.assertEqual(code, 1)
        fail = self.lines(out, "FAIL")
        self.assertIn("still the example", fail["GOALS.md"])
        self.assertIn("still the example", fail["sources.toml"])
        (self.repo / "GOALS.md").unlink()
        (self.repo / "sources.toml").unlink()
        fail = self.lines(self.doctor()[1], "FAIL")
        self.assertIn("missing; copy GOALS.example.md to it", fail["GOALS.md"])
        self.assertIn("not found; copy sources.example.toml to it", fail["sources.toml"])

    def test_untracked_files_fail(self):
        self.git("rm", "-q", "--cached", "sources.toml")
        self.git("commit", "-qm", "untrack")
        fail = self.lines(self.doctor()[1], "FAIL")
        self.assertIn("sources.toml not committed", fail["checkout"])

    def test_each_push_url_is_checked(self):
        mirror = self.td / "mirror.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(mirror)], check=True)
        self.git("remote", "set-url", "--add", "origin", str(mirror))  # a second url, no pushurl
        public = json.dumps({str(mirror): {"nameWithOwner": "example/mirror", "visibility": "PUBLIC"}})
        with mock.patch.dict(os.environ, {"FAKE_GH_REPOS": public}):
            code, out = self.doctor()
        self.assertEqual(code, 1)
        lines = [l for l in out if l.split(None, 2)[1] == "origin:"]
        self.assertEqual(lines[0], "ok    origin: example/remainderbot is private")
        self.assertTrue(lines[1].startswith("FAIL  origin: example/mirror is public; the bot will not push there"),
                        lines)

    def test_allow_public_repo_turns_the_failure_into_a_warning(self):
        self.config.allow_public_repo = True
        with mock.patch.dict(os.environ, {"FAKE_GH_VISIBILITY": "PUBLIC"}):
            code, out = self.doctor()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertIn("ALLOW_PUBLIC_REPO=1", self.lines(out, "warn")["origin"])

    def test_counts_commits_behind_upstream(self):
        upstream = self.td / "upstream.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.origin), str(upstream)], check=True)
        other = self.td / "other"
        subprocess.run(["git", "clone", "-q", str(upstream), str(other)], check=True)
        for i in range(2):
            subprocess.run(["git", "-C", str(other), "-c", "user.email=t@example.com", "-c", "user.name=t",
                            "commit", "-q", "--allow-empty", "-m", f"engine {i}"], check=True)
        subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "main"], check=True)
        self.git("remote", "add", "upstream", str(upstream))
        self.assertEqual(self.lines(self.doctor()[1], "info")["upstream"],
                         "2 commits behind upstream/main; read CHANGELOG.md, then git merge upstream/main")
        self.git("merge", "-q", "--ff-only", "FETCH_HEAD")
        self.assertEqual(self.lines(self.doctor()[1], "ok")["upstream"], "up to date with upstream/main")


if __name__ == "__main__":
    unittest.main()
