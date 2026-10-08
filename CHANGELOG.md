# Changelog

One entry per release tag. An entry that needs an edit to your `GOALS.md` or
`sources.toml` has an **Action required** section: read it before you merge the tag
(README.md, "Updating").

## v0.1.0 (unreleased)

The first public release.

- **Trigger.** An hourly `tick` reads Claude Code's and Codex's own quota numbers. It runs
  when the weekly reset is within `WINDOW_HOURS` and at least `MIN_REMAINING` percent of
  the weekly and 5-hour quota is left. After a run that finishes, it runs again in the
  same period if quota and time remain.
- **Runs.** One task per run, picked from `GOALS.md`, the source snapshot, and the
  verdicts in `INBOX.md`. The agent checks that the task is still open, and commits
  `PLAN.md` before building. Each run has a hard deadline, sized to the quota left. A
  finalize pass may only cut scope.
- **Publishing.** Each run opens a PR in your private instance repo, with the run's
  README as its body. `INBOX.md` follows the PRs: merged means approved, closed means
  rejected, and the last comment is the note the next run reads. A failed publish is
  retried every tick.
- **Sources.** `sources.toml` (`version = 1`) with seven adapters: `gws-tasks`,
  `gws-doc`, `gh-issues`, `gh-roadmaps`, `gh-markdown`, `file`, and `command`.
  `private` sources are named in the prompt's privacy rule.
- **Safety.** `doctor` checks that an instance is ready to run. A public-repo guard
  refuses to push to a public `origin` unless `ALLOW_PUBLIC_REPO=1`. A tick restarts
  itself when its pull changed the code.
