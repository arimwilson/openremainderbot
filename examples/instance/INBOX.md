# INBOX

One row per run. Status: `needs-review` (PR open) / `approved` (merged) / `rejected`
(closed) / `abandoned`. The note column is copied from the last PR comment by
`inbox.sync()`; write there what should change if you reject something.

| id | provider | task | status | your note |
|----|----------|------|--------|-----------|
| 20261008-0337-codex | codex | Finish Fernhill #4 with one-off and weekly time off, booking enforcement, and a usable local staff… | approved | Applied to Fernhill as 92f08a3 and closed #4. This is the one the trial salons kept asking for. The staff screen stays local-only until there's a staff login. |
| 20261008-0358-codex | codex | Finish Fernhill #1 with a local staff export app, appointment previews, CSV downloads, and a matchi… | rejected | Too much for what Rosa asked. She wants a Download CSV button, not a second server on its own port that every salon has to run. Redo it as a Download CSV link on the staff screen from #4 (already local-only): one route, a date range, one module plus tests, a few hundred lines at most. Keep the CSV… |
| 20261008-0422-claude | claude | Redo the CSV export for bookkeepers as one Download CSV form on the existing localhost staff screen… | approved | This is what I asked for. Applied as 9122d36, closed #1, and moved #1 and #4 to Done on the roadmap. I'll write to Rosa myself. |
| 20261008-0431-claude | claude | Find out why salons that finish the Fernhill trial don't pay, as a written report with options plus… | needs-review | |
