"""Unit tests for the INBOX.md table, PR folding, and README summary extraction. No git, no network."""
import unittest

from remainderbot import inbox, publish

SAMPLE = """# INBOX

One row per run. Notes go in the last column.

| id | provider | task | status | your note |
|----|----------|------|--------|-----------|
| 20260919-0300-codex | codex | release notes draft: "a \\| b" | needs-review | |
| 20260920-0400-claude | claude | changelog summary | rejected | too long; cut in half |
"""

README = """# Release notes draft                                       status: complete

**Task** — Draft the v2.3 release notes from the merged PRs.
Source: runs/x/snapshot/tasks.md: "write the v2.3 release notes"
**Why this one** — top of the list; small fits a draft.

## What exists now
- `runs/x/artifact/post.md`

## Run
codex small
"""


class Table(unittest.TestCase):
    def test_parse_and_render_round_trip(self):
        preamble, rows = inbox.parse(SAMPLE)
        self.assertTrue(preamble.startswith("# INBOX"))
        self.assertEqual([r.id for r in rows], ["20260919-0300-codex", "20260920-0400-claude"])
        self.assertEqual(rows[0].task, 'release notes draft: "a | b"')  # escaped pipe survives
        self.assertEqual(rows[0].note, "")
        self.assertEqual(rows[1].note, "too long; cut in half")
        self.assertEqual(inbox.render(preamble, rows), SAMPLE)

    def test_empty_and_headerless_files(self):
        preamble, rows = inbox.parse("# INBOX\n\nsome text\n")
        self.assertEqual(rows, [])
        out = inbox.render(preamble, [inbox.Row("20260101-0000-codex", "codex", "t", "needs-review")])
        self.assertIn(inbox.HEADER, out)
        self.assertIn("| 20260101-0000-codex | codex | t | needs-review | |", out)
        self.assertEqual(inbox.parse("")[1], [])

    def test_upsert_replaces_and_sorts(self):
        rows = [inbox.Row("20260919-0300-codex", "codex", "a", "needs-review")]
        rows = inbox.upsert(rows, inbox.Row("20260101-0000-claude", "claude", "b", "needs-review"))
        rows = inbox.upsert(rows, inbox.Row("20260919-0300-codex", "codex", "a", "approved", "nice"))
        self.assertEqual([(r.id, r.status) for r in rows],
                         [("20260101-0000-claude", "needs-review"), ("20260919-0300-codex", "approved")])

    def test_cells_are_single_line(self):
        r = inbox.Row("id", "codex", "multi\nline | pipe", "needs-review", "a\n\nb")
        self.assertEqual(r.render(), "| id | codex | multi line \\| pipe | needs-review | a b |")
        self.assertEqual(inbox.truncate("x" * 10, 5), "xxxx…")


def pr(head, state="OPEN", comments=(), reviews=(), number=1, title="t"):
    return {"number": number, "url": f"https://x/pull/{number}", "state": state, "title": title,
            "headRefName": head, "comments": list(comments), "reviews": list(reviews)}


class ApplyPR(unittest.TestCase):
    def test_merge_approves_close_rejects_with_last_comment(self):
        rows = [inbox.Row("20260919-0300-codex", "codex", "post", "needs-review")]
        rows, change = inbox.apply_pr(rows, pr("run/20260919-0300-codex", "MERGED"))
        self.assertEqual(rows[0].status, "approved")
        self.assertIn("needs-review -> approved", change)
        comments = [{"body": "first", "createdAt": "2026-09-20T01:00:00Z"},
                    {"body": "shorter please", "createdAt": "2026-09-21T01:00:00Z"}]
        reviews = [{"body": "", "submittedAt": "2026-09-22T01:00:00Z"}]  # empty bodies are ignored
        rows = [inbox.Row("20260919-0300-codex", "codex", "post", "needs-review")]
        rows, change = inbox.apply_pr(rows, pr("run/20260919-0300-codex", "CLOSED", comments, reviews))
        self.assertEqual((rows[0].status, rows[0].note), ("rejected", "shorter please"))

    def test_open_pr_without_change_is_noop(self):
        rows = [inbox.Row("20260919-0300-codex", "codex", "post", "needs-review")]
        rows2, change = inbox.apply_pr(rows, pr("run/20260919-0300-codex"))
        self.assertIsNone(change)
        self.assertEqual(rows2, rows)

    def test_abandoned_stays_abandoned_when_closed(self):
        rows = [inbox.Row("20260919-0300-codex", "codex", "post", "abandoned")]
        rows, change = inbox.apply_pr(rows, pr("run/20260919-0300-codex", "CLOSED", [{"body": "ok", "createdAt": "1"}]))
        self.assertEqual((rows[0].status, rows[0].note), ("abandoned", "ok"))
        self.assertIn("note updated", change)

    def test_pr_without_row_is_recovered(self):
        rows, change = inbox.apply_pr([], pr("run/20260919-0300-codex", "MERGED", title="Release notes"))
        self.assertEqual(rows[0], inbox.Row("20260919-0300-codex", "codex", "Release notes", "approved", ""))
        self.assertIn("added from PR #1", change)


class ReadmeSummary(unittest.TestCase):
    def test_template_readme(self):
        title, status, task = publish.readme_summary(README)
        self.assertEqual(title, "Release notes draft")
        self.assertEqual(status, "complete")
        self.assertEqual(task, "Draft the v2.3 release notes from the merged PRs.")
        self.assertEqual(publish.pr_title(title, status), title)
        self.assertEqual(publish.pr_title(title, "trimmed"), "Release notes draft [trimmed]")

    def test_sloppy_readme(self):
        title, status, task = publish.readme_summary("# Just a heading\n\nno task line\n")
        self.assertEqual((title, status, task), ("Just a heading", "unknown", ""))
        title, status, task = publish.readme_summary("# Run 1   status: abandoned\n\n**Task** — unknown: no README.\n")
        self.assertEqual((status, task), ("abandoned", "unknown: no README."))


if __name__ == "__main__":
    unittest.main()
