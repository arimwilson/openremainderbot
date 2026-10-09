# remainderbot — design

An hourly cron job that notices when a Claude or Codex subscription period is about to
reset with a meaningful amount of quota unused, and spends that quota on **one finished
unit of work** the user can review and ship with a single next step.

The design goal is low complexity: one small Python package (standard library only,
invoked by cron as `python3 -m remainderbot tick`), two prompt files, and a git repo as
the only database and the only UI.

---

## 1. The four challenges, and the one idea for each

| Challenge | Mechanism |
|---|---|
| **When to run** | Ask each CLI for its own rate-limit snapshot. Fire when `time_to_weekly_reset <= 4h` and `weekly_remaining >= 10%` and `5h_remaining >= 10%`, again after a run that hit DONE while quota and at least 20 minutes remain, never after a failed one. The weekly window is the only trigger; the 5-hour window is a gate, never a reason to run. No estimation, no token counting. |
| **What to work on** | A human-written `GOALS.md` (rules + manual goals) plus a machine-generated `goals/snapshot/` (your sources: Google Tasks and Docs, GitHub issues and repos, local files, anything with a command line) plus `INBOX.md` (ledger of past runs and the user's verdicts). The agent picks ONE task, spends a few minutes checking it is not already done, and writes `PLAN.md` with a definition of done *before* building. |
| **Finishing** | A hard wall-clock deadline derived from the reset time, a prompt that forbids starting anything that cannot be done by the deadline, and a second short "finalize" invocation that runs if the main run ends without a `DONE` marker. Finalize may only cut scope and write documentation, never add features. |
| **Explaining itself** | Every run produces `runs/<id>/README.md` from a fixed template (what / why / how verified / how to try / the one next step) and opens a pull request. GitHub's PR email is the notification; merging is approval; a one-line comment is feedback the next run reads. |

---

## 2. Trigger: is it the right time and budget?

### 2.1 Reading the quotas

Both CLIs expose the same two windows: a ~5-hour window and a weekly window, each with
`used_percent` and `resets_at`. The helpers normalize both into one JSON shape:

```json
{"provider":"codex","plan":"plus",
 "five_hour":{"used_pct":3,"resets_at":1789245505},
 "weekly":{"used_pct":1,"resets_at":1789832305}}
```

**Codex** — `usage.codex()` spawns `codex app-server` on stdio, sends `initialize`,
`initialized`, then `account/rateLimits/read`. The response has `rateLimits.primary`
(300 min) and `rateLimits.secondary` (10080 min), each with `usedPercent` and `resetsAt`
(unix seconds). Codex owns auth; nothing to copy.

**Claude** — `usage.claude()` calls `GET https://api.anthropic.com/api/oauth/usage`
with `Authorization: Bearer <access token>` and `anthropic-beta: oauth-2025-04-20`. The
response has `five_hour` and `seven_day`, each with `utilization` (0–100) and `resets_at`
(ISO 8601). On Linux the token lives in `~/.claude/.credentials.json`
(`claudeAiOauth.accessToken`); Claude Code refreshes it whenever it runs, so a 401 means the
bot has not run the CLI in a while and `usage.claude()` runs it once and retries (7). This endpoint is
what community status-line and menu-bar tools use, but it is not an official API and it
has been seen to return 429 under polling. Treat any error as "unknown" and skip the tick;
never guess.

### 2.2 The rule

Evaluated per provider, every hour, by `decide.evaluate()`:

```
eligible =
      weekly.resets_at - now      <= WINDOW_HOURS   (default 4h)
  and 100 - weekly.used_pct       >= MIN_REMAINING  (default 10)
  and 100 - five_hour.used_pct    >= MIN_REMAINING  (5h window must not be the binding limit)
  and the previous run in this period, if any, ended with DONE
  and (if there was a previous run) deadline - now >= MIN_RERUN_MINUTES (default 20)
  and no other tick currently running (the tick-level lock in 6.4)
```

State is `state.json`, one entry per provider:
`{ "codex": {"last_reset_seen": 1789832305, "runs": 1, "last_run_id": "...", "last_outcome": "done"} }`.
The period is claimed with `last_outcome: "running"` before the CLI starts and updated to
`done`, `timeout`, `quota`, `crashed`, or `abandoned` when it returns.

Quota is the resource; the outcome is the memory. There is no fixed cap on runs per
period. A run that hit DONE may be followed by another while quota is still above the
threshold and MIN_RERUN_MINUTES remain, so a small artifact finished early does not strand the rest
of the quota; the tick re-evaluates the rule and starts the next run immediately rather
than waiting for the next hourly tick. Any other outcome blocks the period, because a run that failed fast used
almost no quota and a quota-only rule would relaunch it every hour until the reset. A tick
that dies mid-run leaves `running` behind, which blocks the same way.

Leftover 5-hour windows are deliberately not spent: the 5-hour check only prevents starting
a run that would stall immediately. Keying on `resets_at` is what makes the rule idempotent
across the several hourly ticks that fall inside the 4-hour window. The tick-level lock
(6.4) prevents overlap. If both providers are eligible in the same
tick, the one with more remaining quota runs first; the other is re-evaluated next hour.

### 2.3 Turning quota into a work size

The agent cannot count its own tokens, so the wrapper converts the numbers into two
things the prompt can act on:

- **Deadline** = `min(weekly.resets_at, now + MAX_RUN_MINUTES) - 15 min`. Passed as an
  absolute UTC timestamp and enforced with `timeout`.
- **Size** = `small` (10–20% left), `medium` (20–30%), `large` (>30%). The prompt maps
  size to task ambition: small = a document, a blog post draft, a one-file fix; medium =
  a feature with tests; large = a prototype app.

If the run does hit the quota wall anyway, the CLI exits; the finalize step (section 4)
still runs on a tiny budget and either documents what works or marks the run abandoned.

---

## 3. Task selection: what should it work on?

### 3.1 Inputs

1. **`GOALS.md`** (human-written, the only file the user must maintain). Three sections,
   plus an optional fourth (`GOALS.example.md` shows them all):
   - *Priorities* — the ranked "what am I trying to achieve" list, in tiers.
   - *Rules* — the user's additions to the worker prompt's Defaults: what is in, what is
     out, and in what order to prefer things.
   - *Manual goals* — anything not in another source.
   - *What to take off my plate* (optional) — which work to hand over and which to keep.
2. **`goals/snapshot/`** (generated each tick by `snapshot.refresh()`; gitignored on
   `main` because it mirrors private sources and would churn hourly, but copied into
   `runs/<id>/snapshot/` by `run.execute()` so the PR shows exactly what the agent read).
   One `<name>.md` per `[[sources]]` table in `sources.toml`, written by the adapter its
   `type` names (`remainderbot/adapters/`); the whole file is checked before anything is
   fetched, and an error names the source. The adapters cover Google Tasks and Docs
   (through `gws`), GitHub issues, roadmap files, and repos of Markdown notes (through
   `gh api`, read-only, no clone at snapshot time), local files, and any command whose
   stdout is Markdown. A source marked `private` is named in the prompt's privacy rule.
   Every field is in [docs/sources.md](docs/sources.md).
3. **`INBOX.md`** — one line per prior run: id, provider, task, status
   (`needs-review` / `approved` / `rejected` / `abandoned`), and the user's one-line
   comment. This is the feedback loop and the anti-repeat list.

How the three interact:

- **`GOALS.md` is the only file written for the bot.** Its *Rules* always apply, on top
  of the worker prompt's *Defaults* (no errands, drafted never sent, one action to ship,
  no repeats, nothing that needs the user's credentials to verify, what "shippable"
  means); where the two conflict the Rules win, but never over the prompt's *Never* list
  or its README template. Its
  *Manual goals* are a queue that outranks everything else: if one is open, the bot works
  on it. A manual goal counts as open until `INBOX.md` shows an `approved` run for it or
  the user strikes it through.
- **`goals/snapshot/` is a read-only mirror of sources the user already maintains for
  other reasons.** When the manual queue is empty, which is the normal state, the bot
  picks from the snapshot using the ranking in *Rules*. The bot never edits these
  sources; if it thinks one is stale it says so in the README (see 3.3).
- **`INBOX.md` filters both.** Approved and needs-review tasks are excluded; rejected
  ones are excluded unless the user's note says what to change.

### 3.2 What makes a good source

The best sources are the ones the user already keeps for their own reasons: a task list,
a planning doc, issue trackers, a repo of notes. They hold the most current thinking about
next steps, and nobody has to write it down again for the bot. They are also mixed. A
task list holds errands (the dentist, a car title) next to a few real deliverables (a
plan to draft, a page to build); a notes repo's "next" list is mostly things only the user
can do (reply, call, decide), with a few questions an artifact could answer. So:

- **Rules must filter.** The worker prompt's Defaults rule out errands and anything only
  the user can do; the *Rules* in GOALS.md say which kinds of items the user wants, and
  in what order.
- **Breadth beats curation.** A source does not have to be cleaned up for the bot.
  Selection and the reality check (3.3) skip what is not artifact-shaped or already
  done, and the README's *Housekeeping* section reports what looked stale.
- **Private stays private.** A source with names, customers, or unannounced plans is
  marked `private`: its content may inform a document for the user's eyes, never
  anything meant for publication.
- **Read-only and quick.** A source is fetched every tick, so it should take seconds,
  need only read access, and fail on its own: a failed fetch keeps its last content
  under a `stale:` header while the other sources refresh.

Illustrative tasks, one per size, each with the one step that ships it:

- **small** — An open task "write the v2.3 release notes" and a repo with merged PRs
  since v2.2. Artifact: `release-notes.md`, grouped by user-facing change, each line
  linked to its PR. Next step: paste it into the GitHub release.
- **medium** — An open issue "export to CSV", labeled `customer`, in a repo the
  roadmaps source lists. Artifact: the feature with tests, on a branch of a clone under
  `artifact/`, plus `artifact.patch`. Next step: `git am`.
- **large** — A ROADMAP.md item "status page for the API" with no code yet. Artifact: a
  working static prototype that polls the API's health endpoint, checked in a headless
  browser. Next step: deploy it.

Roadmap files use strikethrough or checkboxes for finished items; the snapshot keeps
them verbatim so the agent can tell done from open without a separate parser.

### 3.3 The selection step inside the run

Selection is not a separate agent; it is the first mandatory phase of the single worker
run. It has two steps.

**Step 1, pick a candidate** from the sources in ranked order.

**Step 2, reality check** (a few minutes and a handful of read-only calls per candidate,
at most three candidates before falling back to the manual queue).
The snapshot is fresh as of the tick, but the *sources* can be stale: a plan file with no
checkboxes, a task nobody closed, an open question answered in a call that was never
ingested. The check depends on the kind of task:

| Task kind | Cheap check |
|---|---|
| Feature or fix in a repo | `gh api` the recent commits and the tree at HEAD; grep for the feature's names in the repo, not in the plan. |
| Something with a live URL | `curl` it. Does the page, route, or content exist? |
| Document or plan | `gws drive files list` by name; `gws docs documents get` and look for the section. |
| Open question in a repo | Is there a newer file in the repo that answers it? |
| Google Task | Is it still open in the fresh snapshot? Does its due date or notes point at something that already exists? |

The prompt's table keeps the first three kinds, which hold for any source, and adds one
row per source in the snapshot with that source's `recheck` hint from `sources.toml` (or
its adapter's default); the last two rows above are the `gh-markdown` and `gws-tasks`
defaults.

If the check says done, the bot moves to the next candidate and records the finding.
Worked example: a site's migration plan reads as open work (no checkboxes, last edited
a month ago), but `curl https://example.com/archive` returns 200 on the new stack and the
page's source file is in the repo at HEAD. Two calls, one minute, and a wasted run
avoided.

Findings from the check are themselves useful output. The README template has a
*Housekeeping* section listing sources that look stale and the one-line edit that would
fix each, so the user can strike a task or update a plan file. The bot never makes those
edits itself.

**Step 3, commit the plan.** The prompt requires the agent to write `runs/<id>/PLAN.md`
within its first few minutes containing:

- the chosen task and the source line it came from (file + quote),
- what the reality check looked at and why the task is still open,
- the definition of done (what will exist, how it will be verified),
- the single next step the user will take,
- the fallback: what smaller version it will cut to if it is behind at the half-way mark.

`PLAN.md` is committed immediately so that even a run that dies leaves a legible trace.

---

## 4. Execution and finishing

### 4.1 Running the agent

`run.execute(decision)`, all subprocess calls from Python:

1. Create branch `run/<id>` in the remainderbot clone, where `<id>` is
   `YYYYMMDD-HHMM-<provider>`, and the directory `runs/<id>/log/`.
2. Render `prompts/worker.md` with `{id, provider, deadline_utc, size}` and the goal file
   paths; write it to `runs/<id>/prompt.md` so the exact prompt is part of the record.
3. Launch the CLI headless with `subprocess.run(..., timeout=seconds_to_deadline)`, the
   prompt on stdin, stdout captured to `runs/<id>/log/<provider>.jsonl`. The machine itself
   is the sandbox (a dedicated server; README.md, "Security"):
   - Claude: `claude -p --model claude-opus-5-5 --effort <effort> --dangerously-skip-permissions
     --output-format stream-json --verbose` (must run as a non-root user).
   - Codex: `codex exec -m gpt-6-astra -c model_reasoning_effort="<effort>"
     --dangerously-bypass-approvals-and-sandbox -C <repo> --json
     -o runs/<id>/log/last.txt -`.
   Model and effort per size are in 4.4.
   On `TimeoutExpired` the process group is killed and the run continues to step 4.
4. Check for `runs/<id>/DONE` (written by the agent as its last action, after
   `README.md` is complete).
5. If `DONE` is missing (timeout, quota wall, crash): launch the same CLI with
   `prompts/finalize.md` and a 10-minute timeout. Finalize reads `PLAN.md`, the git diff,
   and the log tail, and must do exactly one of: (a) trim to the working subset, make it
   pass, write `README.md` honestly; or (b) write `README.md` with status `abandoned` and
   why. It may not add features.
6. Commit whatever is in the run directory, then hand the branch to `publish.pr()`
   (section 6.1, phase 7), which pushes, opens the PR with the README as the body, and
   writes the `needs-review` row to `INBOX.md` on main.

### 4.2 What the worker prompt says (summary of `prompts/worker.md`)

- You have until `<deadline>` UTC and a `<size>` budget. Check the clock with `date -u`
  before each phase.
- Phase 1 (≤10% of time): read `GOALS.md`, `goals/snapshot/*`, `INBOX.md`. Pick ONE task.
  Check it is not already done using read-only calls (section 3.3); if it is, note why and
  pick the next. Write and commit `PLAN.md`.
- Phase 2: build in `runs/<id>/artifact/`. If the natural home is another repo, clone it
  into `artifact/`, work on a branch, and also emit `artifact.patch` via
  `git format-patch origin/main` so the next step is `git am`. Verify (run tests, build,
  render the doc, open the page with a headless browser if it is a UI).
- Half-way checkpoint: if the definition of done is not on track, switch to the fallback
  in `PLAN.md` now. Partial ambitious work is worth less than complete modest work.
- Phase 3 (last 15% of time): write `README.md` from the template, run the final
  verification once more, `touch DONE`, commit.
- Never: push to any repo other than remainderbot, send mail, deploy, spend money, or
  edit `GOALS.md`, `INBOX.md` history, or `state.json`.

### 4.3 Artifact location

```
runs/<id>/
  snapshot/        the goals/snapshot/ the agent read, copied in by the wrapper
  PLAN.md          written first
  README.md        the explanation (template below)
  DONE             marker written last by the agent
  artifact/        the deliverable (site, patch, post, doc, prototype)
  artifact.patch   present when the deliverable belongs in another repo
  log/             raw CLI JSONL, kept for debugging, gitignored beyond 5 MB
```

---

### 4.4 Models, effort, and CLI settings

The quota being spent would expire anyway, so token cost is not the constraint; wall-clock
time to a finished artifact is. That argues for the most capable model on each
subscription at high effort, dropping to a lower effort only when the deadline is tight.

| | Claude | Codex |
|---|---|---|
| Model | `--model claude-opus-5-5` (Claude Opus 5.5, pinned by ID since the `opus` alias may lag; `--fallback-model claude-sonnet-5-5` for overload, also pinned since the `sonnet` alias resolved to Sonnet 5) | `-m gpt-6-astra` (the account's default) |
| Effort, size `small` | `--effort high` | `-c model_reasoning_effort="high"` |
| Effort, `medium` / `large` | `--effort xhigh` | `-c model_reasoning_effort="xhigh"` |
| Effort, finalize pass | `--effort medium` | `-c model_reasoning_effort="medium"` |
| Permissions | `--dangerously-skip-permissions` (non-root user) | `--dangerously-bypass-approvals-and-sandbox` |
| Output | `-p --output-format stream-json --verbose` | `exec --json -o runs/<id>/log/last.txt` |
| Working dir | `cd` into the run branch checkout | `-C <repo>` |

Effort is mapped from size rather than fixed because `xhigh` on a `small` budget tends
to spend the whole window thinking about a task that should take an hour. Codex's `ultra`
level delegates to sub-agents automatically; it is not used, because it makes the run's
pace unpredictable against a hard deadline. Both effort scales are `low / medium / high /
xhigh / max`, so the same `size -> effort` table in `config.py` serves both providers.

Per-provider settings on the server, kept out of the repo:

- `~/.codex/config.toml`: `model`, `model_reasoning_effort`, `approval_policy = "never"`,
  `sandbox_mode = "danger-full-access"`, and a `[projects."<REPO_DIR>"] trust_level =
  "trusted"` entry. A desktop-only setting such as a `notify` hook does not belong there.
- `~/.claude/settings.json`: `model` only. Everything else is passed as flags so the
  invocation is fully visible in the run log.

Two further settings matter and are recorded in the README's *Run* section:

- **Usage after the run.** The wrapper re-reads both providers' usage after the CLI exits
  and records before/after percentages. Over a few periods this calibrates the
  `size` thresholds against what a run actually consumes.

  Calibration log (from `runs/<id>/run.json`):

  | run | provider, model, effort | size | wall clock | weekly | 5-hour | outcome |
  |---|---|---|---|---|---|---|
  | the first run (a local dry run, 20-min deadline) | codex, gpt-6-astra, high | small | 9.5 min of 20 | 1% → 5% | 3% → 31% | DONE, no finalize; a memo with reproducible inputs |

  Reading: a `small` run at `high` effort cost ~4 points of the Codex Plus weekly window
  and ~28 points of the 5-hour window in under ten minutes. So the weekly `small` band
  (10–35% left) has room for several such runs, and the 5-hour window, not the weekly
  one, is what a longer run would exhaust first — which is why `MIN_REMAINING` gates on
  both. One data point; do not retune thresholds until a `medium` or `large` run and a
  Claude run are on the table.
- **Quota exhaustion mid-run.** If the log's last event is a rate-limit error, the
  finalize pass cannot run on the same provider until `resets_at`. The wrapper then
  sleeps until the reset (at most the 15-minute buffer) and runs finalize on fresh quota
  at `medium` effort with a 10-minute cap. That is the only case where the bot spends
  quota from the new period, and it is bounded.

## 5. Explaining itself

`runs/<id>/README.md` template (the PR body is this file verbatim; the agent writes it through
`## Run`, and the wrapper appends the quota footer and the closing `## Chat about this run`):

```
# <title>                                   status: complete | trimmed | abandoned

**Task** — one sentence. Source: runs/<id>/snapshot/<file>: "<quoted line>"
**Why this one** — two sentences: fit to GOALS.md priorities and to the budget.

## What exists now
- bullets: files, features, pages. Link each.

## How I verified it
- exact commands run and their result (tests passed, build succeeded, screenshot at ...).
- what is NOT verified and why.

## Your one next step
`<command>` or "<paste text> to <place>". If more than one step is unavoidable, list
them, shortest first, and say why it could not be one.

## If you want more
- 3 bullets max of what a follow-up run would do. Not started.

## Housekeeping
- sources that looked stale during selection, one line each, with the edit that fixes it
  (e.g. "migration-plan.md: the archive section is done; strike it").

## Run
provider, size, start/deadline, finished with DONE or via finalize, quota before/after.

## Chat about this run
Same harness and model, from any clone of the repo:

    gh pr checkout run/<id> && <claude|codex> <the run's model and effort> "<prompt pointing at runs/<id>/>"
```

The chat line is written by `run.execute` next to the quota footer, so it is in the run record
itself, not only in the PR. It carries no repo path: `gh pr checkout` finds the branch through
the PR, before or after the merge.

*Your one next step* starts the same way when it uses a file from the run directory. The
user's clone is on `main`, and so is the server's once the run ends, and `runs/<id>/` is not
there until the merge. So a patch ships with
`gh pr checkout run/<id> && git -C <target checkout> am "$PWD/runs/<id>/artifact.patch"`,
not with a `git am` of a path that exists only while the run branch is checked out.

`INBOX.md` (root, on main) is the ledger:

```
| id | provider | task | status | your note |
|----|----------|------|--------|-----------|
| 20260919-0300-codex | codex | v2.3 release notes: "..." | needs-review | |
```

The user's loop: read the PR email, try the artifact, then either merge (status →
`approved`) or close with a one-line comment. `inbox.sync()` (the first step of every
tick) copies PR state and the last comment into `INBOX.md` so the next run sees it.
That is the entire feedback mechanism; no separate memory store.

---

## 6. Implementation: phases, package, repo layout

### 6.1 Phases and their inputs and outputs

One tick of the cron job walks these phases in order. Phases 1–3 and 7–8 are plain
Python; phases 4–6 happen inside the headless agent, which the Python wrapper launches,
times, and inspects but does not steer.

| # | Phase | Inputs | Outputs | Stops the tick when |
|---|---|---|---|---|
| 1 | **Sync feedback** (`inbox.sync`) | open and closed PRs on this repo, their state and last comment, via `gh` | `INBOX.md` rows updated to `approved` / `rejected` + note | never; errors are logged and the stale ledger is used |
| 2 | **Refresh snapshot** (`snapshot.refresh`) | `sources.toml`; per source, its adapter: `gws` (Tasks, Docs), `gh` (issues, roadmap files, Markdown repos), local files, or a command | `goals/snapshot/<name>.md` on disk (gitignored), and files of removed sources deleted; `run.execute` copies it to `runs/<id>/snapshot/` on the run branch | `sources.toml` is invalid: the error is logged and the tick ends before the snapshot. A source fails: that file keeps its previous content and gets a `stale: <error>` header |
| 3 | **Read usage + decide** (`usage.*`, `decide.evaluate`) | provider rate-limit snapshots, `state.json`, config thresholds | a `Decision(provider, deadline_utc, size)` or a one-line "skip: <reason>" log entry; `state.json` updated with the reset period being claimed (`running`), and after the run with its outcome | no provider is eligible, or usage is unknown |
| 4 | **Select** (agent, phase 1 of `prompts/worker.md`) | `GOALS.md`, `runs/<id>/snapshot/`, `INBOX.md`, read-only `gh`/`gws`/`curl` for the reality check | `runs/<id>/PLAN.md`, committed on branch `run/<id>` | agent finds nothing eligible: it writes an `abandoned` README explaining why |
| 5 | **Build** (agent, phase 2) | `PLAN.md`, the deadline, the size, the server's toolchain | `runs/<id>/artifact/` and, when the work belongs in another repo, `artifact.patch`; verification results | deadline or quota wall: the wrapper's `timeout` kills the process |
| 6 | **Finish** (agent, phase 3; or `prompts/finalize.md` if `DONE` is missing) | `PLAN.md`, `git diff`, log tail | `runs/<id>/README.md` from the template, `DONE` marker, final commit | never; finalize always produces a README, even one that says `abandoned` |
| 7 | **Publish** (`publish.pr`) | the run branch, `README.md` | pushed branch, a PR whose body is the README, a `needs-review` row in `INBOX.md` on main | push or PR creation fails: retried next tick from the run directory's state |
| 8 | **Review** (the user, asynchronously) | the PR email | merge or close with a comment, picked up by phase 1 of a later tick | |

The contract between phase 3 and phase 4 is the rendered prompt: the wrapper substitutes
`{id}`, `{provider}`, `{deadline_utc}`, `{size}`, and the relative paths of the goal files.
The contract between phases 5–6 and phase 7 is the run directory: `PLAN.md`, `README.md`,
`DONE`, `artifact/`. The wrapper reads nothing else from the agent.

### 6.2 Package

```
remainderbot/                 Python package, standard library only, Python 3.11+
  __main__.py                 argparse CLI: tick | usage | snapshot | decide | run | sync-inbox
                              | doctor
  config.py                   dataclass loaded from env vars with defaults (section 6.4)
  usage.py                    codex() via app-server stdio, claude() via the OAuth usage
                              endpoint; both return Usage(provider, five_hour, weekly)
  decide.py                   evaluate(usages, state, config) -> Decision | None;
                              state.json read/write
  snapshot.py                 refresh(): runs each source's adapter, writes
                              goals/snapshot/<name>.md, marks failures stale
  sources.py                  loads sources.toml (tomllib) and checks every source against
                              its adapter
  adapters/                   one function per source type, registered with @adapter:
                              google.py (gws-tasks, gws-doc with the Docs-JSON-to-Markdown
                              conversion), github.py (gh-issues, gh-roadmaps, gh-markdown),
                              local.py (file, command)
  run.py                      execute(decision): branch, render prompt, launch CLI under
                              timeout, detect DONE, run finalize, commit
  publish.py                  pr(run_dir): push, gh pr create, INBOX.md row, state update
  origin.py                   check(): refuses a public origin before any push; url() for
                              gh's --repo
  inbox.py                    sync(): PR state and last comment -> INBOX.md
  doctor.py                   doctor(): one line per check that an instance is ready to run
  prompts/worker.md
  prompts/finalize.md
tests/                        unit tests against fake gh, gws, and codex CLIs and recorded
                              JSON fixtures; no network
```

Every subcommand is runnable on its own for debugging: `python3 -m remainderbot usage`
prints the normalized JSON for both providers; `decide --dry-run` prints the decision it
would make; `run --provider codex --deadline-minutes 20 --size small` exercises the whole
agent path locally with a short deadline. `tick` is the composition of them all.

### 6.3 Repo layout

```
remainderbot/
  DESIGN.md               this file
  README.md               setup, operation, privacy, security
  docs/sources.md         every source type and field
  GOALS.example.md        copied to GOALS.md when an instance is set up
  sources.example.toml    copied to sources.toml
  remainderbot/           the package (6.2)
  tests/

  GOALS.md                yours: priorities, rules, manual goals
  sources.toml            yours: what the snapshot reads
  INBOX.md                written by the bot: ledger of runs and verdicts
  state.json              written by the bot: per provider, period claimed, run count,
                          last run id and outcome
  goals/snapshot/         generated each tick, gitignored
  runs/                   one directory per run, on its run branch
```

The files below the blank line belong to an instance. They are committed in each user's
private repo and never exist upstream, so pulling engine updates never conflicts with
anyone's goals or ledger.

### 6.4 Cron and configuration

Cron on a dedicated server, as a dedicated non-root user with `claude` and/or `codex`,
`gh`, `git`, `python3`, and `gws` if a source needs it:

```
0 * * * * cd $HOME/remainderbot && python3 -m remainderbot tick >> $HOME/remainderbot.log 2>&1
```

Ticks must not overlap: a run can last three hours while cron fires every hour, and a
second tick would refresh the snapshot underneath the agent or start the other provider
alongside it. `tick` therefore takes a non-blocking `fcntl.flock` on
`<REPO_DIR>/.tick.lock` as its first action and logs "skip: previous tick still running"
if it cannot. The kernel releases the lock when the process exits, however it exits, so a
killed run never leaves a stale lock. Configuration is a handful of environment variables
read by `config.py` with defaults: `WINDOW_HOURS=4`, `MIN_REMAINING=10`,
`MAX_RUN_MINUTES=45`, `MIN_RERUN_MINUTES=20`, `PROVIDERS=claude,codex`, and `REPO_DIR`
(the checkout containing the package). README.md has the full table.

## 7. Failure modes and how they are handled

| Failure | Handling |
|---|---|
| Usage endpoint errors or 429 | Tick is skipped; nothing runs on a guess. Log the error. |
| Claude usage endpoint returns 401 (the stored token only refreshes when Claude Code runs, and a quiet week leaves it expired) | `usage.claude()` runs `claude -p` once from `$HOME` so the CLI refreshes `~/.claude/.credentials.json`, re-reads the token and retries once. A second 401 or a failed refresh (logged out) is logged as unknown and the tick is skipped; `CLAUDE_OAUTH_TOKEN` is never refreshed. |
| Both providers eligible at once | Run the one with more quota; the other is reconsidered next tick if still in window. |
| Agent picks a personal errand | The worker prompt's Defaults forbid it, and `GOALS.md` *Rules* can narrow further; the reviewer closes the PR with a note, and the note is in `INBOX.md` for the next run. |
| Agent runs out of time or quota mid-build | `DONE` absent → finalize trims or abandons and still produces a README and PR. |
| Agent tries to act outside the repo | On a server set up as README.md's "Security" says, it has no credentials beyond read-only `gws`/`gh` and write access to this one repo; the prompt's *Never* list also forbids it. |
| Content from a `private` source ends up in something meant to be public | The prompt's privacy rule names every `private` source and forbids it; the run's README says which sources it drew on; the reviewer closes the PR. |
| `origin` is a public repo | Every run branch would publish the snapshot and the agent's log, so nothing is pushed: `tick` checks first and stops before spending quota, and `publish.push()` refuses again. `ALLOW_PUBLIC_REPO=1` overrides. |
| Source is stale and the task is already done | Reality check in phase 1 (3.3); at worst a few minutes lost, and the README's Housekeeping section tells the user which source to fix. |
| Same task picked twice | `INBOX.md` is in the prompt and repeats are disallowed unless `rejected` with guidance. |
| Run leaves the repo dirty | Every run is its own branch; main only receives `state.json` and `INBOX.md` updates. `goals/snapshot/` is gitignored. |
| Reset time drifts (Claude's weekly window has been observed resetting earlier than 7 days) | Irrelevant: the rule uses the provider-reported `resets_at`, not a calendar. |
| The pull at the start of a tick brings new code or prompts | Prompts are read from disk at run time, but the modules were imported before the pull. If the pull changed anything under `remainderbot/`, the tick re-execs itself once (`REMAINDERBOT_REEXEC=1` marks the restarted process). Merged runs and `GOALS.md` edits do not trigger it. |

---

## 8. What is deliberately left out

- No planner/worker split, no multi-agent orchestration, no vector memory. One worker
  run plus a fixed finalize prompt is enough for one artifact per period.
- No spending of leftover 5-hour windows. Only the weekly window triggers a run.
- No token accounting inside the run. Time and the provider's own percentage are the
  only budget signals.
- No email or chat notifications. The PR is the notification.
- No writing back to any source. The user updates those.
- No use of Codex "rate limit reset credits" or Claude extra-usage billing; the bot only
  spends quota that would otherwise expire.
