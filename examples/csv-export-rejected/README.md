# Fernhill appointment export workspace                                   status: complete

**Task** — Finish Fernhill #1 with a local staff export app, appointment previews, CSV downloads, and a matching CLI. Source: runs/20261008-0358-codex/snapshot/issues.md: "- #1 CSV export of appointments for bookkeepers (updated 2026-10-08, customer) https://github.com/arimwilson/fernhill/issues/1"
**Why this one** — Four salons requested this feature, placing it in GOALS.md's first Rules tier for customer issues. A complete export app with tests and browser verification fits the large prototype budget without changing billing.

## What exists now
- [One-commit Fernhill patch](artifact.patch), based on `1394db984af8d8e19ed90d206442cf50794dff29`: a responsive local workspace with inclusive date ranges, shortcuts, status filters, counts, paginated previews, and complete CSV downloads; plus `python3 -m fernhill export` and 40 new tests.
- [Desktop preview](desktop.png), [mobile preview](mobile.png), and [320px layout](narrow-mobile.png). The app works without JavaScript, uses a separate loopback server, and opens the database read-only.
- [Actual downloaded sample CSV](sample-export.csv), containing synthetic data. Exports include all statuses by default, exact decimal catalog prices, Unicode/CSV quoting, and formula-safe names. **Prices are current service catalog prices, not historical charges or payments**; the app and Fernhill README explain this.
- Reusable browser check, synthetic fixture generator, and full verification record. The disposable clone is not part of the deliverable; its complete changes are in the patch.

## How I verified it
- `git -C /tmp/remainderbot-20261008-0358-verify am /Users/ariw/code/remainderbot-demo/runs/20261008-0358-codex/artifact.patch` — applied cleanly to a fresh checkout of the base commit. Its Git tree exactly matches the development checkout; setup commands and hashes are recorded.
- From that patched checkout: `python3.11 -m unittest -v` and `python3 -m unittest -v` — **62 tests pass on each runtime** (Python 3.11 and 3.14.6). 3.11 log, 3.14 log.
- `python3.11 -m compileall -q fernhill tests` and `git diff --check 1394db984af8d8e19ed90d206442cf50794dff29` — pass. `git diff --exit-code 1394db984af8d8e19ed90d206442cf50794dff29 -- fernhill/billing.py fernhill/db.py fernhill/scheduling.py fernhill/web.py` — no changes to those files.
- From remainderbot: `PLAYWRIGHT_BROWSERS_PATH=/Users/ariw/.cache/remainderbot/playwright node runs/20261008-0358-codex/checks/browser.mjs /tmp/remainderbot-20261008-0358-verify runs/20261008-0358-codex/evidence /tmp/remainderbot-20261008-0358-browser/node_modules` — **13 browser checks pass**, including real downloads, 125-row pagination, mobile layout, no-JavaScript forms, access guards, and an unchanged database. Results. Desktop/mobile axe audits report zero violations; screenshots were inspected.
- Not verified: native Excel/Google Sheets imports, Safari/Firefox, production data, or hosted access. No connected Browser instance was available, so browser checks used standalone headless Chromium. CSV round-trips, accents, commas, quotes, newlines, BOM, and formula markers are covered by tests. This is a local staff tool; Fernhill has no staff login yet.

## Your one next step
From your Fernhill checkout, apply the patch:

`git am /Users/ariw/code/remainderbot-demo/runs/20261008-0358-codex/artifact.patch`

The patch includes usage documentation for `python3 -m fernhill reports` and `python3 -m fernhill export`.

## If you want more
- Validate native spreadsheet imports across the salons' regional settings. Not started.
- Add a groomer filter if salons request it. Not started.
- Connect exports to a future authenticated staff portal. Not started.

## Housekeeping
- No stale selected source found: live issue #1 is open, no linked PR exists, and the export is absent from upstream HEAD. No source edits needed before this patch is applied.
- #4 was excluded because INBOX.md marks the earlier time-off run `needs-review`; this run does not repeat it.

## Run
Provider: codex. Size: large. Run: `20261008-0358-codex`. Observed start: 2026-10-08T03:59:07Z. Deadline: 2026-10-08T04:43:59Z. Finished with DONE, before the 04:21:30Z half-way checkpoint; the full planned scope was completed and the fallback was not used. Quota before: codex 5h 52% / weekly 10% used. The wrapper appends after-run quota.

Sources used: the public `arimwilson/fernhill` code at the base commit, live issue #1, and this run's issues/repos snapshots. GOALS.md and INBOX.md governed selection; notes.md was read for selection but not incorporated. Private sources this run: none. Demo records are synthetic. No pushes, PRs, deployments, or messages were sent.

quota before: codex 5h 52% / weekly 10% used
quota after: codex 5h 99% / weekly 18% used
finished: DONE; main run exit=0 timed_out=False

## Chat about this run
Same harness and model, from any clone of the repo:

```
gh pr checkout run/20261008-0358-codex && codex -m gpt-6-astra -c 'model_reasoning_effort="xhigh"' 'This is remainderbot run 20261008-0358-codex. Read runs/20261008-0358-codex/README.md, prompt.md and run.json, then the log under runs/20261008-0358-codex/log/ if it is there, and take my questions.'
```
