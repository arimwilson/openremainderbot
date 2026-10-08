"""Each adapter against a fake `gh` and `gws` on PATH (or local files and commands), and the
Markdown helpers they share."""
import json
import os
import shutil
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from remainderbot import sources
from remainderbot.adapters import ADAPTERS, Context, SourceError, github, google
from remainderbot.adapters._util import frontmatter, md_section

HERE = Path(__file__).parent
FIX = HERE / "fixtures"


class FakeCLIs(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)
        bin_dir = self.td / "bin"
        bin_dir.mkdir()
        for src, name in (("fake_gh.py", "gh"), ("fake_gws.py", "gws")):
            shutil.copy(HERE / src, bin_dir / name)
            os.chmod(bin_dir / name, 0o755)
        self.gh_db, self.gws_db, self.calls = self.td / "gh.json", self.td / "gws.json", self.td / "calls.jsonl"
        env = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GH_SOURCES": str(self.gh_db),
                                           "FAKE_GWS_DB": str(self.gws_db), "FAKE_GH_CALLS": str(self.calls)})
        env.start()
        self.addCleanup(env.stop)
        self.logs = []

    def gh(self, repos=None, issues=None):
        self.gh_db.write_text(json.dumps({"repos": repos or {}, "issues": issues or []}))

    def gws(self, **db):
        self.gws_db.write_text(json.dumps(db))

    def run_source(self, table: str) -> str:
        """Validate one [[sources]] table, as a tick would, and run its adapter."""
        [src] = sources.parse("version = 1\n[[sources]]\n" + textwrap.dedent(table))
        return ADAPTERS[src.type].fn(src.fields, Context(self.td, src.max_chars, self.logs.append))

    def gh_calls(self) -> list[list[str]]:
        return [json.loads(l) for l in self.calls.read_text().splitlines()]


def doc_tab(title, text, children=()):
    body = {"content": [{"paragraph": {"elements": [{"textRun": {"content": text + "\n"}}]}}]}
    return {"tabProperties": {"title": title}, "documentTab": {"body": body}, "childTabs": list(children)}


class GwsTasks(FakeCLIs):
    def setUp(self):
        super().setUp()
        self.gws(tasklists=[{"id": "L1", "title": "Inbox"}, {"id": "L2", "title": "Work"}],
                 tasks={"L1": [{"title": "Buy stamps", "position": "2"},
                               {"title": "Draft the release notes", "position": "1", "due": "2026-10-09T00:00:00Z",
                                "notes": "for v0.2\nlink in the issue"},
                               {"title": "Done already", "status": "completed", "position": "0"}],
                        "L2": [{"title": "Review the roadmap", "position": "1"}]})

    def test_every_open_task_with_due_dates_and_notes(self):
        self.assertEqual(self.run_source('name = "tasks"\ntype = "gws-tasks"\n'), textwrap.dedent("""\
            # Google Tasks (open)

            ## Inbox (2 open)

            - Draft the release notes (due 2026-10-09)
              for v0.2
              link in the issue
            - Buy stamps

            ## Work (1 open)

            - Review the roadmap
            """))

    def test_chosen_lists_without_notes(self):
        out = self.run_source('name = "tasks"\ntype = "gws-tasks"\nlists = ["Inbox"]\nnotes = false\n')
        self.assertIn("- Draft the release notes (due 2026-10-09)\n- Buy stamps", out)
        self.assertNotIn("Work", out)
        self.assertNotIn("for v0.2", out)

    def test_a_list_that_is_not_there_is_an_error(self):
        with self.assertRaisesRegex(SourceError, "no task list titled Errands"):
            self.run_source('name = "tasks"\ntype = "gws-tasks"\nlists = ["Inbox", "Errands"]\n')


class GwsDoc(FakeCLIs):
    def setUp(self):
        super().setUp()
        self.gws(docs={
            "one": {"title": "Plans", "tabs": [doc_tab("Tab 1", "only tab")]},
            "many": {"title": "Notes", "tabs": [doc_tab("Ideas", "idea text", [doc_tab("Old ideas", "old text")]),
                                                doc_tab("Log", "log text")]},
        })

    def test_one_tab_reads_as_a_plain_document(self):
        self.assertEqual(self.run_source('name = "doc"\ntype = "gws-doc"\ndoc_id = "one"\n'), "# Plans\n\nonly tab\n")

    def test_every_tab_by_default(self):
        out = self.run_source('name = "doc"\ntype = "gws-doc"\ndoc_id = "many"\n')
        self.assertEqual(out, "# Notes\n\n## Tab: Ideas\n\nidea text\n\n## Tab: Old ideas\n\nold text\n\n"
                              "## Tab: Log\n\nlog text\n")

    def test_chosen_tabs_wherever_they_are_nested(self):
        out = self.run_source('name = "doc"\ntype = "gws-doc"\ndoc_id = "many"\ntabs = ["Old ideas", "Log"]\n')
        self.assertEqual(out, "# Notes\n\n## Tab: Old ideas\n\nold text\n\n## Tab: Log\n\nlog text\n")
        out = self.run_source('name = "doc"\ntype = "gws-doc"\ndoc_id = "many"\ntabs = ["Log"]\n')
        self.assertEqual(out, "# Notes\n\nlog text\n")

    def test_a_tab_that_is_not_there_is_an_error(self):
        with self.assertRaisesRegex(SourceError, "no tab titled Drafts"):
            self.run_source('name = "doc"\ntype = "gws-doc"\ndoc_id = "many"\ntabs = ["Drafts"]\n')

    def test_a_missing_doc_is_an_error(self):
        with self.assertRaisesRegex(SourceError, "exit 1"):
            self.run_source('name = "doc"\ntype = "gws-doc"\ndoc_id = "nope"\n')


class GhIssues(FakeCLIs):
    def setUp(self):
        super().setUp()
        self.gh(issues=[
            {"repo": "you/app", "number": 3, "title": "Crash on save", "updatedAt": "2026-10-01T10:00:00Z",
             "labels": ["bug"], "assignees": ["you"]},
            {"repo": "you/app", "number": 5, "title": "Dark mode", "updatedAt": "2026-10-03T10:00:00Z"},
            {"repo": "you/site", "number": 1, "title": "Broken link", "updatedAt": "2026-09-01T10:00:00Z",
             "labels": ["bug"]},
            {"repo": "someone/else", "number": 9, "title": "Not yours", "updatedAt": "2026-10-04T10:00:00Z"},
        ])

    def test_every_repo_of_an_owner(self):
        self.assertEqual(self.run_source('name = "issues"\ntype = "gh-issues"\nowner = "you"\n'), textwrap.dedent("""\
            # Open GitHub issues across you (3)

            ## you/app

            - #5 Dark mode (updated 2026-10-03) https://github.com/you/app/issues/5
            - #3 Crash on save (updated 2026-10-01, bug) https://github.com/you/app/issues/3

            ## you/site

            - #1 Broken link (updated 2026-09-01, bug) https://github.com/you/site/issues/1
            """))

    def test_chosen_repos_labels_and_assignee(self):
        out = self.run_source('name = "issues"\ntype = "gh-issues"\nrepos = ["you/app", "you/site"]\n'
                              'labels = ["bug"]\nassignee = "you"\nlimit = 5\n')
        self.assertIn("across you/app, you/site (1)", out)
        self.assertIn("#3 Crash on save", out)
        [call] = self.gh_calls()
        self.assertEqual(call[:2], ["search", "issues"])
        for flag, value in (("--repo", "you/app"), ("--repo", "you/site"), ("--label", "bug"),
                            ("--assignee", "you"), ("--limit", "5"), ("--state", "open")):
            self.assertIn([flag, value], [call[i:i + 2] for i in range(len(call))])


class GhRoadmaps(FakeCLIs):
    def setUp(self):
        super().setUp()
        readme = "\n".join(f"readme line {n}" for n in range(1, 51)) + "\n"
        self.gh(repos={
            "you/app": {"README.md": readme, "ROADMAP.md": "- [ ] export\n", "docs/todo.md": "- tidy\n",
                        "docs/guide.md": "a guide\n", "node_modules/x/TODO.md": "vendored\n",
                        "src/main.py": "print()\n"},
            "you/site": {"PLAN.md": "1. launch\n"},
        })

    def test_readme_head_and_roadmap_files_in_repo_order(self):
        out = self.run_source('name = "repos"\ntype = "gh-roadmaps"\nrepos = ["you/site", "you/app"]\n')
        self.assertTrue(out.startswith("# Repos: README head plus TODO/ROADMAP/PLAN/ideation files (verbatim)\n"))
        self.assertLess(out.index("## you/site"), out.index("## you/app"))
        self.assertIn("### PLAN.md\n\n1. launch\n", out)
        self.assertIn("### README.md (first 40 lines)\n\nreadme line 1\n", out)
        self.assertIn("readme line 40\n", out)
        self.assertNotIn("readme line 41", out)
        self.assertIn("### ROADMAP.md\n\n- [ ] export\n", out)
        self.assertIn("### docs/todo.md\n\n- tidy\n", out)
        self.assertNotIn("guide", out)
        self.assertNotIn("vendored", out)

    def test_pattern_and_readme_lines(self):
        out = self.run_source('name = "repos"\ntype = "gh-roadmaps"\nrepos = ["you/app"]\n'
                              'pattern = "guide"\nreadme_lines = 0\n')
        self.assertTrue(out.startswith("# Repos: README head plus files matching `guide` (verbatim)\n"))
        self.assertIn("### docs/guide.md", out)
        self.assertNotIn("README.md", out)
        self.assertNotIn("ROADMAP.md", out)

    def test_a_missing_repo_is_marked_stale_in_place(self):
        out = self.run_source('name = "repos"\ntype = "gh-roadmaps"\nrepos = ["you/gone", "you/site"]\n')
        self.assertIn("## you/gone\n\nstale: gh api repos/you/gone/git/trees/HEAD?recursive=1: exit 1:", out)
        self.assertIn("### PLAN.md", out)

    def test_every_repo_missing_is_an_error(self):
        with self.assertRaisesRegex(SourceError, "you/gone"):
            self.run_source('name = "repos"\ntype = "gh-roadmaps"\nrepos = ["you/gone"]\n')


NOTES_TREE = {
    "notes/weekly/2026-09-01.md": "# Week\n\n## Do next\n\n- old item\n",
    "notes/weekly/2026-09-08.md": "# Week\n\n## Do next\n\n- ship the release notes\n\n## Context\n\n"
                                    "Context text.\n\n## Not wanted\n\nskip me\n",
    "notes/weekly/archive/2026-08-01.md": "# Archived\n\n## Do next\n\n- archived\n",
    "notes/projects/app.md": "# App\n\n## Open questions\n\n- q1\n\n### detail\n- q1a\n\n## Current focus\n\nfocus\n",
    "notes/projects/site.md": "# Site\n\n## Open questions\n\n- q2\n",
    "notes/bets/h-one.md": "---\nstatus: testing\nlast_evidence: 2026-09-02\nstatement: \"Users want X\"\n---\n\nbody\n",
    "notes/bets/h-two.md": "---\nstatus: untested\n---\n",
    "notes/decisions.md": "# Decisions\n\n## d-001 Keep it small\n",
    "notes/people/pat.md": "# Pat\n\nphone 555\n",
    "raw/interview.md": "raw notes\n",
}

NOTES_SOURCE = """\
name = "notes"
type = "gh-markdown"
repo = "you/notes"
private = true
description = "Weekly notes, projects, bets, and decisions."

  [[sources.parts]]
  include = "notes/weekly/*.md"
  latest = true
  title = "This week"
  sections = ["Do next", "Context"]

  [[sources.parts]]
  include = "notes/projects/*.md"
  title = "Project"
  sections = ["Open questions", "Current focus"]

  [[sources.parts]]
  include = "notes/bets/*.md"
  title = "Bets (status from frontmatter)"
  frontmatter = ["status", "last_evidence", "statement"]

  [[sources.parts]]
  include = "notes/decisions.md"
"""


class GhMarkdown(FakeCLIs):
    def setUp(self):
        super().setUp()
        self.gh(repos={"you/notes": NOTES_TREE})

    def test_golden_four_kinds_of_parts(self):
        self.assertEqual(self.run_source(NOTES_SOURCE), textwrap.dedent("""\
            # notes (private, you/notes)

            Weekly notes, projects, bets, and decisions.

            ## This week: notes/weekly/2026-09-08.md

            ### Do next

            - ship the release notes

            ### Context

            Context text.

            ## Project: notes/projects/app.md

            ### Open questions

            - q1

            ### detail
            - q1a

            ### Current focus

            focus

            ## Project: notes/projects/site.md

            ### Open questions

            - q2

            ## Bets (status from frontmatter)

            - h-one: status=testing, last_evidence=2026-09-02, statement=Users want X
            - h-two: status=untested

            ## notes/decisions.md

            # Decisions

            ## d-001 Keep it small

            """))

    def test_whole_files_exclude_and_globstar(self):
        out = self.run_source('name = "notes"\ntype = "gh-markdown"\nrepo = "you/notes"\n[[sources.parts]]\n'
                              'include = "notes/**/*.md"\nexclude = ["notes/people/**", "notes/bets/*"]\n')
        self.assertTrue(out.startswith("# notes (you/notes)\n\n## notes/decisions.md\n\n# Decisions\n"))
        self.assertIn("## notes/weekly/2026-09-01.md\n\n# Week\n", out)
        self.assertIn("## notes/weekly/archive/2026-08-01.md", out)
        self.assertNotIn("Pat", out)
        self.assertNotIn("h-one", out)
        self.assertNotIn("raw notes", out)

    def test_a_part_with_no_match_is_left_out(self):
        out = self.run_source('name = "notes"\ntype = "gh-markdown"\nrepo = "you/notes"\n[[sources.parts]]\n'
                              'include = ["docs/*.md"]\ntitle = "Docs"\nfrontmatter = ["status"]\n')
        self.assertEqual(out, "# notes (you/notes)\n")

    def test_glob(self):
        cases = [("wiki/*.md", "wiki/a.md", True), ("wiki/*.md", "wiki/x/a.md", False),
                 ("wiki/**/*.md", "wiki/a.md", True), ("wiki/**/*.md", "wiki/x/y/a.md", True),
                 ("wiki/**", "wiki/x/a.md", True), ("**/*.md", "a.md", True), ("**/*.md", "a/b.md", True),
                 ("a?.md", "ab.md", True), ("a?.md", "a/.md", False), ("a.md", "aXmd", False)]
        for pattern, path, want in cases:
            self.assertEqual(bool(github.glob_re(pattern).fullmatch(path)), want, (pattern, path))


class LocalFile(FakeCLIs):
    def setUp(self):
        super().setUp()
        self.home = Path(tempfile.mkdtemp())  # outside the repo, as usual
        self.addCleanup(shutil.rmtree, self.home, True)
        for rel, text in {"TODO.md": "- [ ] ship it\n", "notes/a.md": "# A\n", "notes/b.txt": "b\n",
                          "notes/deep/c.md": "# C\n"}.items():
            (self.td / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.td / rel).write_text(text)
        for rel in ("vault/Projects/app.md", "vault/inbox.md", "vault/.trash/old.md", "vault/.obsidian/x.json"):
            (self.home / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.home / rel).write_text(f"text of {rel}\n")
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def test_repo_relative_and_home_paths_each_under_its_path(self):
        out = self.run_source('name = "local"\ntype = "file"\npaths = ["TODO.md", "~/vault/**/*.md"]\n'
                              'exclude = "~/vault/.trash/**"\n')
        self.assertEqual(out, textwrap.dedent("""\
            # Files: TODO.md, ~/vault/**/*.md

            ## TODO.md

            - [ ] ship it

            ## ~/vault/Projects/app.md

            text of vault/Projects/app.md

            ## ~/vault/inbox.md

            text of vault/inbox.md
            """))

    def test_star_stays_in_one_directory_and_each_file_appears_once(self):
        out = self.run_source('name = "local"\ntype = "file"\npaths = ["notes/*.md", "notes/**"]\n')
        self.assertEqual([l for l in out.splitlines() if l.startswith("## ")],
                         ["## notes/a.md", "## notes/b.txt", "## notes/deep/c.md"])
        out = self.run_source('name = "local"\ntype = "file"\npaths = "notes/*"\n')
        self.assertNotIn("deep", out)

    def test_a_path_that_matches_nothing_is_an_error(self):
        with self.assertRaisesRegex(SourceError, r"^no file matches ~/vault/Archive/\*\.md$"):
            self.run_source('name = "local"\ntype = "file"\npaths = ["TODO.md", "~/vault/Archive/*.md"]\n')
        with self.assertRaisesRegex(SourceError, r"^no file matches DONE\.md$"):
            self.run_source('name = "local"\ntype = "file"\npaths = "DONE.md"\n')

    def test_empty_paths(self):
        with self.assertRaisesRegex(sources.ConfigError, "source 'local': `paths` is empty"):
            self.run_source('name = "local"\ntype = "file"\npaths = []\n')


class Command(FakeCLIs):
    def test_stdout_verbatim_from_the_repo_directory(self):
        (self.td / "issues.md").write_text("- LIN-1 Ship it\n")
        out = self.run_source('name = "linear"\ntype = "command"\nrun = "echo \'# Linear\'; cat issues.md; '
                              'echo noise >&2"\n')
        self.assertEqual(out, "# Linear\n- LIN-1 Ship it\n")

    def test_no_output(self):
        self.assertEqual(self.run_source('name = "quiet"\ntype = "command"\nrun = "true"\n'),
                         "# quiet\n\n(the command printed nothing)\n")

    def test_a_nonzero_exit_is_an_error_with_the_last_stderr_line(self):
        with self.assertRaisesRegex(SourceError, r"^`echo out; echo a >&2; echo b >&2; exit 3`: exit 3: b$"):
            self.run_source('name = "c"\ntype = "command"\nrun = "echo out; echo a >&2; echo b >&2; exit 3"\n')
        with self.assertRaisesRegex(SourceError, r"^`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa…`: exit 127: "):
            self.run_source('name = "c"\ntype = "command"\nrun = "' + "a" * 50 + '"\n')

    def test_a_timeout_kills_everything_the_command_started(self):
        start = time.monotonic()
        with self.assertRaisesRegex(SourceError, r"timed out after 1s$"):
            # the background sleep holds stdout open; only killing the group lets the read end
            self.run_source('name = "slow"\ntype = "command"\nrun = "(sleep 30; echo late) & sleep 30"\ntimeout = 1\n')
        self.assertLess(time.monotonic() - start, 10)

    def test_checks(self):
        with self.assertRaisesRegex(sources.ConfigError, "source 'c': `timeout` must be at least 1"):
            self.run_source('name = "c"\ntype = "command"\nrun = "true"\ntimeout = 0\n')
        with self.assertRaisesRegex(sources.ConfigError, "source 'c': `run` is empty"):
            self.run_source('name = "c"\ntype = "command"\nrun = " "\n')


class DocsToMarkdown(unittest.TestCase):
    def setUp(self):
        self.md = google.docs_to_markdown(json.loads((FIX / "doc.json").read_text()))

    def test_headings(self):
        self.assertIn("# Roadmap & ideas\n", self.md)
        self.assertIn("\n# Goals\n", self.md)
        self.assertIn("\n## Ideas\n", self.md)

    def test_ordered_list_with_nesting_and_styles(self):
        self.assertIn("1. Ship the mobile app\n2. Grow the **newsletter**\n  1. sub item\n3. ~~Old idea~~", self.md)

    def test_bullets_and_links(self):
        self.assertIn("Some prose with a [link](https://example.com).", self.md)
        self.assertIn("- offline mode\n  - sync on reconnect", self.md)

    def test_table(self):
        self.assertIn("| Name | Status |\n|---|---|\n| example.org | open \\| todo |", self.md)

    def test_no_triple_blank_lines(self):
        self.assertNotIn("\n\n\n", self.md)


class SectionsAndFrontmatter(unittest.TestCase):
    text = "---\nstatus: testing\nstatement: \"A claim\"\n---\n\n# T\n\n## Open questions\n- q1\n\n### sub\n- q2\n\n## Current focus\nfocus\n"

    def test_section(self):
        self.assertEqual(md_section(self.text, "Open questions"), "- q1\n\n### sub\n- q2")
        self.assertEqual(md_section(self.text, "current focus"), "focus")
        self.assertIsNone(md_section(self.text, "Nope"))

    def test_frontmatter(self):
        self.assertEqual(frontmatter(self.text), {"status": "testing", "statement": "A claim"})
        self.assertEqual(frontmatter("# no fm"), {})

    def test_roadmap_regex(self):
        yes = ["docs/process/todo.md", "ROADMAP.md", "v2/docs/EXTENSION_AUTOFILL_PLAN.md", "docs/ideation/board.md",
               "migration-structuring-plan.md", "PLAN.md"]
        no = ["README.md", "docs/explanation.md", "src/planner.md", "airplane.md"]
        for p in yes:
            self.assertTrue(github._ROADMAP_RE.search(p), p)
        for p in no:
            self.assertFalse(github._ROADMAP_RE.search(p), p)


if __name__ == "__main__":
    unittest.main()
