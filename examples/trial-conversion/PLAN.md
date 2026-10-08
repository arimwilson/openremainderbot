# Plan — run 20261008-0431-claude

## Task

Find out why salons that finish the Fernhill trial don't pay, from the Oct 1 trial export,
and deliver it as (1) a re-runnable, stdlib-only analyzer with tests and (2) the report it
produces: evidence and options, not decisions.

Sources:
- `GOALS.md`, Priorities (a)1: "Find out why salons that finish the trial don't pay. The latest trial export is `notes/trials.csv`."
- `runs/20261008-0431-claude/snapshot/notes.md` (notes/TODO.md): "- [ ] Why don't trial salons convert? Export from the admin page is in trials.csv (Oct 1)."

Why this over the `customer` issues: it is item 1 of tier (a), ranked above item 2
(customer features), and no run has done it (`INBOX.md` has #4, #1, #1-redo only; run
20261008-0422-claude listed it as the obvious follow-up). It also tells Sam which
customer issue to do next, which the issue list alone cannot.

## Reality check

- `notes/TODO.md` item is still open (unchecked) in this tick's snapshot; `notes/trials.csv` is present (55 rows, Oct 1 export).
- Searched this repo's `runs/*/README.md` for "convert"/"trials.csv": prior runs only used the exit-survey lunch complaints to justify #4; no conversion analysis exists.
- `gh api` fernhill tree at HEAD (d1a04d0): no admin/trials/analytics module; the export comes from an admin page outside the repo, so the analyzer belongs in this run's `artifact/`, not as a Fernhill patch.
- Context the report must account for: #4 (time off, fixes "couldn't block my lunch") shipped as 92f08a3 *after* every finished trial in the export; #7 (giant size) and #3 are still open.

## Definition of done

- `artifact/trials_report.py`: `python3 trials_report.py notes/trials.csv > REPORT.md` — stdlib only; parses the export, splits finished vs in-trial, conversion by segment (clients entered, online bookings, reminders, groomers), codes exit-survey answers into themes, maps themes to shipped/open Fernhill issues, flags in-trial salons at risk.
- `artifact/test_trials_report.py`: unit tests on fixtures (parsing, theme coding, segment rates, at-risk rules); `python3 -m unittest` passes.
- `artifact/REPORT.md`: generated from the real export, plus a hand-written summary and options section on top. No invented numbers: every figure traces to the CSV.
- Verified by: tests pass; regenerating the report from `notes/trials.csv` reproduces the committed tables byte-for-byte; numbers spot-checked by an independent one-liner.

## Sam's single next step

Merge this run's PR (the report and the analyzer land in the repo); after each new admin
export, rerun `python3 runs/20261008-0431-claude/artifact/trials_report.py notes/trials.csv`.

## Times and fallback

- Start 04:31:13Z, deadline 05:16:13Z.
- **Half-way mark: 04:53:43Z.** If the analyzer and tests are not passing by then, cut to the
  fallback: a single script that prints the tables (no tests, no at-risk rules) plus the
  hand-written REPORT.md.
- Phase 3 (README, final verification) starts no later than 05:09:30Z.
