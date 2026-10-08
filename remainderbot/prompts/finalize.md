# remainderbot finalize pass for run `{id}`

The main worker run for `{id}` ended without writing `runs/{id}/DONE` (deadline,
quota wall, or crash). You have **{finalize_minutes} minutes** and a hard kill at
{deadline_utc}. Run `date -u` first.

You may do exactly one of these two things, and nothing else:

**(a) Trim to what works.** Read `runs/{id}/PLAN.md`, `git status`, `git diff HEAD`,
`git log --oneline -20`, and the tail of `runs/{id}/log/*.jsonl` (`tail -c 20000`). If a
coherent, verifiable subset of the work exists, cut everything that does not work (delete
half-finished files, revert broken edits), run the verification once, and write
`runs/{id}/README.md` from the template below with `status: trimmed`. Be honest about
what is missing.

**(b) Abandon.** If nothing verifiable exists, write `runs/{id}/README.md` with
`status: abandoned`, saying what was attempted, how far it got, and what stopped it, so
the user and the next run learn from it. Keep whatever is on disk for reference.

You may **not** add features, start new work, fetch new sources, or continue the build.
Documentation and deletion only. No pushes, no PRs, no branch switches, nothing outside
`runs/{id}/`.

Template (the PR body is this file verbatim):

```
# <title>                                   status: trimmed | abandoned

**Task** — one sentence. Source: {snapshot_dir}/<file>: "<quoted line>"
**Why this one** — two sentences: fit to GOALS.md priorities and to the budget.

## What exists now
- bullets: files, features, pages. Link each (paths relative to the repo root).

## How I verified it
- exact commands run and their result.
- what is NOT verified and why.

## Your one next step
`<command>` or "<paste text> to <place>", or "nothing; see abandoned reason".

## If you want more
- 3 bullets max of what a follow-up run would do. Not started.

## Housekeeping
- sources that looked stale during selection, one line each, with the fixing edit.

## Run
provider {provider}, size {size}, deadline {deadline_utc}, finished via finalize
(main run ended without DONE), quota before: {quota_before}.
```

Finish with `git add -A runs/{id} && git commit -m "run {id}: finalize"`.
