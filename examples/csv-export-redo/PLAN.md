# PLAN — run 20261008-0422-claude

## Task

Redo Fernhill #1, "CSV export of appointments for bookkeepers", the way the rejection of
run 20261008-0358-codex asked.

- Source: `runs/20261008-0422-claude/snapshot/issues.md`:
  "#1 CSV export of appointments for bookkeepers (updated 2026-10-08, customer)"
- Rejection note (`INBOX.md`, full text from remainderbot-demo PR #2): "Redo it as a Download
  CSV link on the staff screen from #4 (already local-only): one route, a date range, one
  module plus tests, a few hundred lines at most. Keep the CSV quoting and formula-safe
  names. Drop the preview pages, pagination and shortcuts."

Why this one: GOALS.md Rules rank `customer` issues first in tier (a); #1 is in ROADMAP "Now"
with four salons asking, and the user has already said exactly what the redo should be.
A `rejected` row may be repeated when its note says what to change; this run changes it.

## Reality check

- `gh issue view 1 -R arimwilson/fernhill`: OPEN, label customer, no comments, no linked PR.
- `gh api repos/arimwilson/fernhill/commits`: HEAD is 92f08a3 (time off + staff screen, #4).
  Three commits total; none mention CSV or export.
- Cloned HEAD and grepped `fernhill/` and `tests/` for `csv` and `export`: no matches.
- The staff screen from #4 exists: `fernhill/staff.py` (localhost-only WSGI app with host check)
  and `fernhill/staff.html`.

## Definition of done

- `fernhill/export.py` (one module): date-range validation, the query (one row per
  appointment: date, start, end, groomer, client, dog, service, price, status), CSV with
  UTF-8 BOM + CRLF + standard quoting, formula-safe names.
- One route in `fernhill/staff.py`: `GET /export.csv?from=YYYY-MM-DD&to=YYYY-MM-DD` that
  returns `text/csv` with `Content-Disposition: attachment`.
- A small "Download CSV" form on `fernhill/staff.html` (two date inputs + button, a plain
  GET form, no JS).
- `tests/test_export.py`: module and route tests (range, columns, commas/quotes/accents,
  formula prefixing, BOM, headers, bad ranges, localhost check still applies).
- README line for the new link. No changes to billing.
- Whole diff a few hundred lines at most. `python3 -m unittest` passes.
- Patch at `runs/20261008-0422-claude/artifact.patch` via `git format-patch origin/main --stdout`.
- Headless screenshot of the staff screen with the form, plus a sample CSV, in the run dir.

## Your one next step

`git am runs/20261008-0422-claude/artifact.patch` inside a fernhill checkout, then push.

## Fallback

Half-way mark: **2026-10-08T04:44:30Z**. If the route + module + tests are not passing by
then, cut the screenshot and the HTML form polish: ship the module + route + tests and a
plain link, and say so in the README. Phase 3 starts no later than 05:00Z.
