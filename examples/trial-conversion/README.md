# Why trial salons don't pay: analysis of the Oct 1 trial export          status: complete

**Task** — Find out why salons that finish the Fernhill trial don't pay, as a written report with options plus a re-runnable, tested analyzer for the next export. Source: runs/20261008-0431-claude/snapshot/notes.md: "- [ ] Why don't trial salons convert? Export from the admin page is in trials.csv (Oct 1)."
**Why this one** — It is item 1 of tier (a) in GOALS.md ("Find out why salons that finish the trial don't pay"), ranked above the customer features, and no earlier run had done it. A large budget covers the analysis plus a tool you can rerun on every export, so this doesn't have to be a one-off memo.

## What exists now
- [runs/20261008-0431-claude/artifact/REPORT.md](REPORT.md): the findings and their evidence, six options in rough cost order (none of them decided for you), what the data can't tell you, and two unsent email drafts in your voice. The short version:
  - **The strongest marker of a salon that leaves is that it never got its client list in.** 27 of the 35 non-payers entered 8 clients or fewer. Salons that got their list in paid at 50% (8/16), the rest at 18% (6/33), Fisher p = 0.04. That's borderline after five splits, and it's a marker, not a proven cause. Total bookings (27+) and online bookings (10+) split exactly the same salons.
  - Setup is the most common exit-survey reason (8 salons, 7 naming client entry), ahead of lunch breaks (6).
  - The six "couldn't block my lunch" salons all left before #4 landed today, and five of them had also never loaded their clients. Salons can't reach the staff screen themselves yet; it only answers on 127.0.0.1.
  - Three of the four "\$29 is a lot" answers came from salons that had entered 0–2 clients.
  - Salon size and reminders: gaps, but neither stands out from chance (p = 0.21 and 0.36).
  - Salons marked in trial on Oct 1: Thistle Pup Spa (ends today) and Tidy Coat Co. (Oct 13) have no client list. Sudsy Hound (Dana) and Cedar Tails are set up, and 5 of 8 salons like them paid.
- [runs/20261008-0431-claude/artifact/trials_report.py](trials_report.py): a stdlib-only analyzer. `python3 trials_report.py <export.csv> [--as-of YYYY-MM-DD]` prints Markdown: conversion by segment with Fisher exact p-values, a crosstab of client list by salon size, results by signup month, plans chosen, exit-survey themes mapped to where each stands in Fernhill, non-payers who did the setup, and in-trial salons with risk signs.
- [runs/20261008-0431-claude/artifact/tables.md](tables.md): its output on `notes/trials.csv` as of 2026-10-08. Every number in REPORT.md comes from here.
- [runs/20261008-0431-claude/artifact/test_trials_report.py](test_trials_report.py): 15 unit tests (parsing, theme coding of every answer in the export, Fisher p against known values, risk rules, rendering, Markdown escaping, and a byte-for-byte reproduction of tables.md).
- [runs/20261008-0431-claude/evidence/numbers_check.py](numbers_check.py) and its output [numbers-check.txt](numbers-check.txt): an independent recount of every figure quoted in REPORT.md. It doesn't import the analyzer and uses brute-force exact-fraction Fisher p-values.

## How I verified it
- `cd runs/20261008-0431-claude/artifact && python3 -m unittest -v`: 15 tests, OK.
- Clean clone of the run branch into a temp directory, then the same tests (OK) and `python3 -I runs/20261008-0431-claude/artifact/trials_report.py notes/trials.csv --as-of 2026-10-08 | diff - runs/20261008-0431-claude/artifact/tables.md`: no diff.
- `python3 -I runs/20261008-0431-claude/evidence/numbers_check.py notes/trials.csv`: every figure in REPORT.md matches, including the three p-values (0.040, 0.207, 0.360).
- `pandoc -f gfm -t html` on REPORT.md, tables.md and this README: all render without warnings. An earlier render caught `$29 … $29` being read as TeX math; dollar signs and pipes are now escaped.
- Fernhill facts in the report come from read-only `gh api` calls: plan prices from `fernhill/billing.py` (`PLANS`), staff-screen routes from `fernhill/staff.py`, how time off is set from `docs/time-off.md`, and #4's commit 92f08a3 dated 2026-10-08.
- A second agent fact-checked REPORT.md against the CSV, the snapshots and the Fernhill source, about 75 claims in all. Most numbers held. It caught four wrong claims, which are now fixed:
  - "nothing else comes close": total bookings split the same salons.
  - "clients only booked online at salons whose list was in": 29 of 33 salons without a list had online bookings.
  - "five salons said their clients call or text": one said that; four said older clients won't book online.
  - "in trial now": these are Oct 1 figures.
  It also flagged overstatements, which are now softened or removed: causal wording, "looks like the payers" for a one-groomer salon, and the p = 0.04 with no word on how many splits were tried. And it flagged promises in the drafts: Draft B said salons can block their own lunch, but the staff screen is loopback-only, and it offered a new trial that nothing establishes. The new figures it raised are in the independent recount.
- **Not verified:** anything after the Oct 1 export (S1050 and S1051 ended Oct 3, so their outcomes are unknown), and anything causal. The data shows the client list goes with paying, not that loading it makes a salon pay. Option 2 in the report says how to test that, slowly. No emails were sent.

## Your one next step
Merge this PR. After that, rerun the analyzer on each new admin export:
`python3 runs/20261008-0431-claude/artifact/trials_report.py notes/trials.csv`.
Time-sensitive, if you take option 2: Draft A in REPORT.md is written for Tidy Coat Co., whose trial ends Oct 13.

## If you want more
- Rerun on a fresh admin export and add the date the client list went in, if the admin page has it. That would show whether early setup predicts paying better than setup at any point.
- Draft the three "why did you leave?" emails to the salons that set up and still went quiet (Pampered Pup Spa, Fluff Paws, Puddle Hound), option 1.
- If you pick option 4, write the client-import issue and patch for Fernhill (CSV import with tests), using whatever formats option 2 turns up.

## Housekeeping
- notes/TODO.md: "Why don't trial salons convert?" is answered in REPORT.md. Check it off, or change it to the option you pick.
- notes/trials.csv: the Oct 1 export still marks S1050 and S1051 "in trial", but both ended Oct 3, and S1052 ends today. Replace it with a fresh export before acting on the in-trial list.
- notes/trials.csv: two rows are named "Sudsy Hound": S1010 (Portland, June, didn't pay) and S1053 (Tacoma, ends Oct 12). Dana's, per notes/TODO.md, is S1053.
- notes/newsletter.md #14: "Use real numbers if we have them". The trial export has no no-show data, and reminders on vs off showed no clear difference in conversion. Add a note there so a draft doesn't cite trials.csv for no-shows.
- Fernhill TODO.md: "The booking page doesn't book yet: the time buttons do nothing" conflicts with the export, where 45 of 49 finished trials have online bookings. If the live booking page books, strike or reword the line.
- Fernhill docs/time-off.md and ROADMAP.md ("Groomer time off and breaks (#4), on the local staff screen") are accurate, but a salon can't use #4 itself until the staff screen has a login. Worth a line in the roadmap's Now or Next if you want the lunch win-back (option 3) to be self-service.
- issues: nothing is filed for a client import or for staff-entered phone bookings, the two most-cited exit reasons with nothing shipped or filed. Those are roadmap calls (options 4 and 5), so they're listed here rather than filed.

## Run
Provider claude, size large. Started 2026-10-08T04:31:13Z, deadline 2026-10-08T05:16:13Z. Finished with DONE. Quota before: claude 5h 9% / weekly 5% used.
Sources: GOALS.md; this run's snapshot/notes.md (`notes/TODO.md`, `notes/newsletter.md`, `notes/trials.csv`), snapshot/issues.md and snapshot/repos.md; read-only `gh api` reads of arimwilson/fernhill (billing.py, staff.py, docs/time-off.md, commit 92f08a3). The fact-check agent also read the local Fernhill checkout at ~/code/fernhill, read-only. Private sources this run: none declared. Both arimwilson/fernhill and this repo are private on GitHub, so the salon names and plan prices in the report stay private. No pushes, sends, or billing changes.

quota before: claude 5h 9% / weekly 5% used
quota after: claude 5h 11% / weekly 5% used
finished: DONE; main run exit=0 timed_out=False

## Chat about this run
Same harness and model, from any clone of the repo:

```
gh pr checkout run/20261008-0431-claude && claude --model claude-opus-5-5 --effort xhigh 'This is remainderbot run 20261008-0431-claude. Read runs/20261008-0431-claude/README.md, prompt.md and run.json, then the log under runs/20261008-0431-claude/log/ if it is there, and take my questions.'
```
