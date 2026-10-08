# Groomer time off and breaks                                   status: complete

**Task** — Finish Fernhill #4 with one-off and weekly time off, booking enforcement, and a usable local staff screen. Source: runs/20261008-0337-codex/snapshot/issues.md: "- #4 Groomer time off and breaks (updated 2026-10-08, customer) https://github.com/arimwilson/fernhill/issues/4"
**Why this one** — Customer-requested features rank first in GOALS.md Rules, and six non-converting salons in the Oct 1 trial export specifically reported that they could not block lunch. The large budget fit a complete working feature with a staff interface, persistence, tests, and a verified patch rather than just an implementation plan.

## What exists now
- [One-commit Fernhill patch](artifact.patch): adds one-off and weekly blocks, removes overlapping slots, rejects direct bookings during time off, preserves existing appointments, and serializes booking/block writes. Blocks never create appointments or reminders; billing code is unchanged.
- [Staff screen, desktop preview](staff-desktop.png): groomer/date selection, appointment and break agenda, creation form, saved blocks, and confirmed removal. It runs with `python3 -m fernhill --db fernhill.db staff` on localhost:8001, separately from the public booking app; use the same database as the booking server.
- [Mobile preview](staff-mobile.png), [removal dialog](staff-mobile-confirmation.png), and [public booking page](booking-slots.png). All are captured from the actual patched app with demo data.
- Patch manifest: base commit, patch commit, tree, SHA-256, and the ten changed files. The patch includes `docs/time-off.md`, README instructions, and 40 new tests, for 62 total.
- Repeatable clean-checkout verifier, browser runner, and browser checks. The disposable working clone is intentionally ignored; the patch, evidence, and screenshots are retained.

## How I verified it
- From the Fernhill checkout: `python3.11 -m unittest -v` — **62 passed** on Python 3.11.15, including recurrence, exact boundaries, conflicts with future bookings, cancellation/completion handling, reminders, legacy database upgrades, two-connection write races, validation, public/staff route separation, and request protections. Log.
- `python3 -m unittest -v` — **62 passed** on Python 3.14.6. It reports unclosed-database ResourceWarnings from existing upstream tests; those warnings also occur on the unmodified 22-test baseline with `python3 -W always::ResourceWarning -m unittest -v`. Patched log, baseline log.
- `python3.11 -m compileall -q fernhill tests` and `git diff --check HEAD^ HEAD` — passed. This standard-library app has no separate build system or new runtime dependencies.
- From remainderbot: `NODE_PATH="$HOME/.cache/remainderbot/browser-check/node_modules" python3.11 runs/20261008-0337-codex/verification/verify-patch.py runs/20261008-0337-codex/artifact/fernhill` — passed. The script created a fresh checkout outside this repository at upstream `1394db984af8d8e19ed90d206442cf50794dff29`, applied the delivered patch with `git am`, matched its tree to the reviewed source, repeated both test suites and compilation, confirmed the billing-file hash was unchanged, and ran the browser checks against that fresh patched checkout. Full command/results log.
- Headless Chrome 154 with Playwright 1.56.1 — **11 browser checks passed**, no JavaScript errors. Verified creating weekly and one-off blocks, rejecting a conflict, reload persistence, groomer isolation, cancelled/confirmed removal, public slot filtering, and a 390px mobile layout. Desktop and mobile screenshots were visually inspected; the narrow date picker found in the first pass was fixed. Results. The in-app browser had no available connection, so verification used isolated headless Chrome; it did not use a signed-in browser session.
- Not verified: a live salon database, deployment, Safari/Firefox, or physical mobile devices. Staff access is deliberately local-only because Fernhill has no staff authentication. Running booking processes must be restarted after installing the code; table creation is automatic. No production services were changed, and all test servers were stopped.

## Your one next step
From a clean Fernhill checkout based on the recorded upstream commit, apply the feature:

`git am /Users/ariw/code/remainderbot-demo/runs/20261008-0337-codex/artifact.patch`

This is one commit, already tested through that exact patch-application path. The operator guide is included in the patch at `docs/time-off.md`.

## If you want more
- Add an end date and single-date exceptions for a weekly series. Not started.
- Add authenticated staff access for remote use. Not started.

## Housekeeping
- No completed/stale candidate was selected: #4 was OPEN, had no linked closing PR, and the live code had no time-off support. `INBOX.md` is absent, so there were no prior verdicts to repeat; let the normal review workflow create the first entry.
- `notes/trials.csv` is still the Oct 1 export and labels Oct 3 trial endings as “in trial”; refresh it before making a current conversion analysis. Only its historical lunch complaints informed this selection.
- Snapshot privacy metadata says “none,” but GitHub marks both Fernhill and this run repository private. Update the source classifier to retain that distinction; this deliverable remains a patch for the private source repository, with private review evidence. No sources were edited.

## Run
Provider: **codex**. Size: **large**. Start: **2026-10-08T03:37:07Z**. Deadline: **2026-10-08T04:22:07Z**. Finished with **DONE**; full definition of done completed before the **2026-10-08T03:59:37Z** halfway checkpoint, so no fallback was needed. Finish verification began at 03:55 UTC, before the 04:15:22 UTC latest finish-phase start.

Quota before: **codex 5h 8% / weekly 4% used**. Quota after: appended by the wrapper.

Sources: this run's `snapshot/issues.md` (#4), `snapshot/repos.md` (Fernhill structure and roadmap), `snapshot/notes.md` and original `notes/trials.csv` (historical selection evidence), plus live Fernhill issue/PR/commit/tree checks and source at the recorded base. Declared private sources in the prompt: **none**; actual live GitHub repository metadata: **private**. Code and demo previews are retained for private review only. No pushes, PRs, messages, deployments, or billing changes were made.

quota before: codex 5h 8% / weekly 4% used
quota after: codex 5h 52% / weekly 10% used
finished: DONE; main run exit=0 timed_out=False

## Chat about this run
Same harness and model, from any clone of the repo:

```
gh pr checkout run/20261008-0337-codex && codex -m gpt-6-astra -c 'model_reasoning_effort="xhigh"' 'This is remainderbot run 20261008-0337-codex. Read runs/20261008-0337-codex/README.md, prompt.md and run.json, then the log under runs/20261008-0337-codex/log/ if it is there, and take my questions.'
```
