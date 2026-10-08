# Fernhill #1: Download CSV on the staff screen                                   status: complete

**Task** — Redo the CSV export for bookkeepers as one Download CSV form on the existing localhost staff screen, as your note on the rejected run asked. Source: runs/20261008-0422-claude/snapshot/issues.md: "#1 CSV export of appointments for bookkeepers (updated 2026-10-08, customer)"
**Why this one** — GOALS.md Rules put `customer` issues first in tier (a). #1 is in ROADMAP "Now" with four salons asking, and your rejection note on run 20261008-0358-codex said exactly what to change. The note also capped the work at "a few hundred lines at most", so the patch is deliberately small even though this was a large run: 292 lines added, 20 changed, in 5 files.

## What exists now
- [`runs/20261008-0422-claude/artifact.patch`](artifact.patch): one commit against `arimwilson/fernhill` at 92f08a3, ready for `git am`. It contains:
  - `fernhill/export.py` (85 lines), the one new module. It parses and checks the date range, then queries one row per appointment of every status: `date, start, end, groomer, client, dog, service, price, status`. The CSV is UTF-8 with a BOM, CRLF line endings and standard quoting. Names that start with `= + - @` or a control character get a leading `'`. Prices are formatted from cents with no float rounding.
  - `fernhill/staff.py`: one route on the existing staff app, `GET /export.csv?from=YYYY-MM-DD&to=YYYY-MM-DD`. It returns `text/csv` as an attachment named `fernhill-appointments-<from>-to-<to>.csv`, or a plain-text 400 such as "Pick a From date on or before the To date." It sits behind the same localhost check and headers as the time-off routes, with no new server or port. `reply()` gained an `extra` headers argument and accepts bytes.
  - `fernhill/staff.html`: a "For your bookkeeper" card under "Block some time" with From and To dates (defaulting to this calendar month) and a **Download CSV** button. It is a plain GET form plus one line of JS that keeps To on or after From.
  - `tests/test_export.py`: 11 tests covering:
    - the range including both end days, ordering and every status
    - an empty range, BOM and CRLF
    - commas, quotes, accents and line breaks round-tripping through `csv`
    - formula prefixing, exact prices, bad ranges and the month default
    - the route's headers and its 400s
    - that the localhost and token protections still apply
    - that the form is on the page
  - `README.md` (Fernhill): a "CSV export for bookkeepers" section, plus updated layout table and run lines.
- Dropped, as you asked: preview pages, pagination, shortcuts, the CLI and the second server.
- Kept from the rejected run: its CSV quoting, BOM, CRLF and formula-safe name logic, rewritten to fit in one module.
- Evidence:
  - [`evidence/staff-screen.png`](staff-screen.png): the staff screen with the new card.
  - [`evidence/sample-export.csv`](sample-export.csv) and `evidence/export-headers.txt`: a real download and its headers.
  - `evidence/numbers-check.txt`: the same file read back from Numbers.
  - `evidence/clean-checkout-tests.txt`: the test run on a fresh clone.
- Choices for you to check (all in the README section of the patch):
  - Cancelled and done appointments are included; there is a `status` column to filter on.
  - `price` is the service's *current* price, because Fernhill stores no charged amount.
  - The form defaults to the current calendar month.

## How I verified it
- `python3.11 -m unittest`, `python3.12 -m unittest` and `python3 -m unittest` (3.14.6) on a fresh clone of fernhill after `git am artifact.patch`: **73 tests, OK** on all three. That is the 62 existing tests plus 11 new ones. Log in `evidence/clean-checkout-tests.txt`.
- End to end against the real server:
  - Setup: `python3 -m fernhill --db demo.db seed`, then sqlite edits to make a client "Becker, Tom", a groomer "Zoë", a dog "=Moose" and one appointment done, then `python3 -m fernhill --db demo.db staff --port 8765`.
  - `curl "http://127.0.0.1:8765/export.csv?from=2026-10-01&to=2026-10-31"` returned 200 with `Content-Disposition: attachment; filename="fernhill-appointments-2026-10-01-to-2026-10-31.csv"`, the BOM `ef bb bf`, and 3 rows with `"Becker, Tom"` quoted and `'=Moose` prefixed.
  - A reversed range returned 400 "Pick a From date on or before the To date."
  - `Host: evil.example` returned 403.
- Opened that CSV in **Numbers** through `osascript` and read every cell back. "Zoë" was intact, "Becker, Tom" was one cell, prices were numbers, and `'=Moose` was text with no formula. Numbers wasn't running before the check; I closed the file without saving and quit Numbers.
- Headless Chrome screenshot at 1280px: `evidence/staff-screen.png`. The new card renders, and its dates default to 10/01–10/31.
- **Not verified:**
  - Excel and Google Sheets: Excel isn't installed and Sheets needs your login. The format is the standard one both read (UTF-8 with a BOM, RFC 4180 quoting), but I have only seen it open in Numbers. In Excel the `'` prefix stays visible too, which is the usual trade-off for formula safety.
  - A real browser click on the button: there's no Playwright here. The form's names and action are covered by a test, and curl hit the same URL the form builds.
  - The phone layout: headless Chrome clipped the 390px shot on the right for the top bar and time-off form too, which are unchanged, so the shot doesn't tell us anything.

## Your one next step
In your fernhill checkout: `git am /Users/ariw/code/remainderbot-demo/runs/20261008-0422-claude/artifact.patch && python3 -m unittest && git push`. Then close #1; the commit message references #1 without a closing keyword, as with #4.

## If you want more
- Store `price_cents` on each appointment at booking time, so past exports keep the price that was charged after you change the service catalog. This touches the schema, not billing.
- A one-line reply to Rosa and the three other salons that asked: where the button is, and that it is on the staff screen at port 8001.
- The trial-conversion analysis from `notes/trials.csv` (tier a, priority 1), which no run has done yet.

## Housekeeping
- INBOX.md: the note for 20261008-0358-codex is cut off at "Keep the CSV…". The rest ("…quoting and formula-safe names. Drop the preview pages, pagination and shortcuts.") exists only in the comment on remainderbot-demo PR #2. Lengthen the note or the sync's truncation limit so later runs see the whole instruction.
- fernhill ROADMAP.md ("Updated 2026-10-05"): "Groomer time off and breaks (#4)" is still under **Next**, but it shipped in 92f08a3 and #4 is closed. Move it to done, and move "CSV export of appointments for bookkeepers (#1)" there too once this patch lands.
- fernhill README.md: the run line calls `staff` a "local time-off manager". The patch already changes it to "local staff screen (time off, CSV export)", so nothing to do if you apply it.

## Run
- Provider: claude (Opus 5.5). Size: large.
- Started 2026-10-08T04:22:02Z; deadline 2026-10-08T05:07:02Z. Finished with DONE at about 04:30Z, with the definition of done met well before the 04:44:30Z half-way mark.
- Quota before: claude 5h 7% / weekly 5% used. The wrapper appends quota after.
- Sources the artifact drew on:
  - `snapshot/issues.md` (#1) and the live `gh issue view 1`
  - `INBOX.md` and the full rejection comment on remainderbot-demo PR #2
  - `snapshot/repos.md` and `arimwilson/fernhill` at 92f08a3
  - the CSV quoting and formula-safety code in the rejected run's `artifact.patch`
- Private sources declared for this run: none. Note that `arimwilson/fernhill` and `remainderbot-demo` are both private on GitHub, so this patch should stay in this private PR.
- No pushes to fernhill, no messages, no deploys, no billing changes.

quota before: claude 5h 7% / weekly 5% used
quota after: claude 5h 9% / weekly 5% used
finished: DONE; main run exit=0 timed_out=False

## Chat about this run
Same harness and model, from any clone of the repo:

```
gh pr checkout run/20261008-0422-claude && claude --model claude-opus-5-5 --effort xhigh 'This is remainderbot run 20261008-0422-claude. Read runs/20261008-0422-claude/README.md, prompt.md and run.json, then the log under runs/20261008-0422-claude/log/ if it is there, and take my questions.'
```
