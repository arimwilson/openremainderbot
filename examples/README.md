# Examples

Four real runs from a demo instance, on 2026-10-08. The instance belongs to a made-up
founder, Sam, who builds Fernhill, a booking app for dog groomers, alone. The goals,
issues, notes, salons and people are all fictional. The runs are not: real Codex and
Claude sessions on real subscription quota, through the same `tick` that cron runs.

| | Run | What it chose | Time | Verdict |
|---|---|---|---|---|
| 1 | [groomer-time-off](groomer-time-off/) (Codex) | Fernhill issue #4: one-off and weekly time off for groomers, with a staff screen. It tied the issue to six trial salons that left saying they couldn't block their lunch. | 22 min | approved; the patch was applied |
| 2 | [csv-export-rejected](csv-export-rejected/) (Codex) | Issue #1, CSV export for a bookkeeper, built as a separate reporting app with previews and pagination | 22 min | **rejected**, with a note saying what to change |
| 3 | [csv-export-redo](csv-export-redo/) (Claude) | Issue #1 again, rebuilt the way the note asked: one route and one module on the staff screen from run 1, 292 lines | 8 min | approved; the patch was applied |
| 4 | [trial-conversion](trial-conversion/) (Claude) | "Find out why salons that finish the trial don't pay": a tested analyzer plus a report with options, not decisions | 13 min | left open for review |

Things worth looking at:

- **The feedback loop.** Run 2's PR was closed with a comment
  ([screenshot](csv-export-rejected/pr.png)). The next run read the comment from
  `INBOX.md`, redid the task as asked, and said so in its PR
  ([screenshot](csv-export-redo/pr.png)).
- **No repeats.** Run 2 skipped issue #4 because `INBOX.md` showed run 1's PR on it still
  open.
- **Housekeeping.** Each README ends with what looked stale in the sources. Run 4 caught
  two real inconsistencies in the demo's own made-up data: a salon name used twice, and
  a TODO line that the trial export contradicts.

## What each folder holds

- `README.md`: the run's README, which is also its PR body, as written. Links to files
  that aren't copied here are plain text.
- `PLAN.md`: what it chose, its reality check, the definition of done, and the fallback,
  committed before it built anything.
- `pr.png`: the PR on GitHub.
- The deliverable: `artifact.patch` (a `git am` patch against Fernhill) for runs 1–3; the
  report, analyzer and tests for run 4. Plus the screenshots the run took to verify itself.

[instance/](instance/) has what the bot was given and what it recorded:
[GOALS.md](instance/GOALS.md), [sources.toml](instance/sources.toml), the
[notes](instance/notes/) the `file` source read, and the final
[INBOX.md](instance/INBOX.md) ([screenshot](instance/inbox.png)). The Fernhill repo
itself, with its ten issues and ROADMAP.md, was a private throwaway and isn't included.

## How these were run

On a laptop, from a fresh clone set up exactly as the README says, with these
departures from a cron install:

- `WINDOW_HOURS=200`, so the trigger fired with six days left in the week instead of
  waiting for the reset; `MAX_RUN_MINUTES=60`, for 45-minute deadlines.
- `PROVIDERS=codex` for the first tick, `PROVIDERS=claude` for the next two, to get two
  runs from each.
- A tick reruns after a run that finishes, so the Codex tick went straight on to run 2.
  To get a verdict in before each Claude run, the first Claude tick had
  `MIN_RERUN_MINUTES=999`. A watcher stopped the Codex tick after its second run
  published, and the last Claude tick after its first.
- `CLAUDE_FALLBACK_MODEL=` (empty), so the Claude runs were Opus 5.5 or nothing.

The verdicts were given by hand, playing Sam, and the approved patches were applied to
Fernhill, so later runs saw those features shipped. Models: Codex `gpt-6-astra` and Claude
`claude-opus-5-5`, both at `xhigh`. Each README's *Run* section has its quota before and
after. The two subscriptions are on different plans, so don't compare their percentages.

A laptop is not the recommended home. The agent runs with full access, and one run here
opened Numbers through `osascript` to check its CSV. It closed the file without saving,
but that is why the README says to use a dedicated machine.
