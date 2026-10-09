# <img src="docs/logo-blink.png" alt="RemainderBot logo: a percent sign whose top circle is a smiling face" width="72" align="center"> RemainderBot

Your Claude or Codex subscription resets every week, and whatever quota you didn't use is
gone. RemainderBot notices when a reset is a few hours away with quota left, and spends
it on finished, easily reviewable pieces of work: pull requests in your own private repo.

<picture>
  <source srcset="https://www.ariwilson.com/images/posts/openremainderbot/loop-anim-dark.webp" media="(prefers-color-scheme: dark)">
  <img src="https://www.ariwilson.com/images/posts/openremainderbot/loop-anim.webp" width="640" alt="A cartoon robot walks through one RemainderBot run for Fernhill, a made-up dog-grooming scheduler: it checks the weekly quota is under 4 hours from reset with 41% left, reads a GOALS.md aiming for 50 paying salons, picks an open customer issue, builds a groomer time-off feature and passes 62 tests, opens a pull request, and a person merges it.">
</picture>

_One run, illustrated, for a made-up founder's dog-grooming scheduler. The real run it's
drawn from is in [examples/groomer-time-off](examples/groomer-time-off/), with its
[pull request](examples/groomer-time-off/pr.png), plan, and patch. Three more runs,
including a rejected one and the run that redid it from the rejection note, are in
[examples/](examples/)._

## How it works

- **Trigger.** An hourly cron job reads each CLI's own quota numbers. When the weekly
  reset is less than 4 hours away and at least 10% is left, it runs.
  ([DESIGN.md §2](DESIGN.md#2-trigger-is-it-the-right-time-and-budget))
- **Select.** The agent reads three things. A fresh snapshot of your sources (the task
  lists, issues, docs, and notes you already keep) supplies the candidate tasks. Your
  `GOALS.md` says which of those matter and in what order, since your sources mix
  errands with real work and don't rank anything. The verdicts on past runs keep it from
  repeating itself. It picks one task, checks that the task isn't already done, and
  commits a plan before building anything.
  ([§3](DESIGN.md#3-task-selection-what-should-it-work-on))
- **Build.** It works against a hard deadline set from the reset time, sized to the quota
  left: a document, a feature with tests, or a prototype.
  ([§4](DESIGN.md#4-execution-and-finishing))
- **Finish.** If the run ends without a done marker, a short finalize pass may only cut
  scope and write up what works, never add to it.
- **PR and feedback.** Every run opens a PR whose body says what was built, how it was
  verified, and the one step that ships it. Merge means approved; close with a comment
  means rejected, and the next run reads your comment. ([§5](DESIGN.md#5-explaining-itself))

## What you need

- **A dedicated machine**, such as a small VPS. The agent runs there with every
  permission check off, so that machine is the sandbox (see [Security](#security)).
- Python 3.11 or newer, `git`, and [`gh`](https://cli.github.com).
- Claude Code (`claude`) and/or the Codex CLI (`codex`), logged in with a subscription.
- [`gws`](https://www.npmjs.com/package/@googleworkspace/cli), only if you use Google
  Tasks or Docs as sources.

RemainderBot is a small Python package with no dependencies outside the standard library.

## Set up your private instance

Every instance is a **private** repo. A run branch carries a copy of everything the agent
read and its whole log, so the code refuses to publish to a public repo
([Privacy](#privacy)).

On your own computer (anywhere `gh` can create a repo):

```sh
git clone https://github.com/arimwilson/openremainderbot.git remainderbot
cd remainderbot
git remote rename origin upstream
gh repo create remainderbot --private --source . --remote origin --push
cp -n GOALS.example.md GOALS.md
cp -n sources.example.toml sources.toml
```

**Don't fork.** A GitHub fork of a public repo can't be private. Don't use "Use this
template" either: a template copy has unrelated history, so your first update would
conflict on every file. A clone with `upstream` as a second remote gets updates with a
plain `git merge` ([Updating](#updating)).

Edit `GOALS.md` and `sources.toml` (the next two sections), then commit and push them:

```sh
git add GOALS.md sources.toml
git commit -m "My goals and sources"
git push
```

The bot creates `INBOX.md` and `state.json` itself.

## Tell it what matters

Your sources say what _could_ be done; `GOALS.md` says what _should_ be. Of everything a
run reads, it's the only thing you write for the bot (`sources.toml` just points at
things you already keep), and every run reads it first. `GOALS.example.md` is a complete
example for a made-up founder. It has four sections:

- **Priorities**: what the work is for, in tiers. A modest artifact in a high tier beats
  an impressive one in a low tier.
- **What to take off my plate** (optional): the work you would hand to an assistant,
  and the work you'd rather keep.
- **Rules**: your additions to the defaults built into the prompt. The defaults are: no
  errands, drafted never sent, one action to ship, no repeats, and nothing that needs
  your credentials to verify. For example:

  ```markdown
  ## Rules

  - Prefer, in tier order: (a) issues labeled `customer`; (b) newsletter drafts from
    my outline notes; (c) anything in the repos' TODO files.
  - Never change billing code; I write every change there myself.
  ```

- **Manual goals**: one-off requests. An open one outranks everything else.

Edit it whenever you like and push. Each tick pulls `main` first.

## Connect your sources

`sources.toml` says what the snapshot reads. Each `[[sources]]` table becomes
`goals/snapshot/<name>.md`, written by the adapter its `type` names:

```toml
version = 1

[[sources]]
name = "issues"
type = "gh-issues"
owner = "your-github-user"

[[sources]]
name = "todo"
type = "file"
paths = ["~/notes/TODO.md"]

[[sources]]
name = "notes"
type = "gh-markdown"
repo = "your-github-user/notes"
private = true            # nothing drawn from it goes into anything meant for publication

  [[sources.parts]]       # belongs to the [[sources]] table above it, however it's indented
  include = "projects/*.md"
  sections = ["Open questions", "Next"]
```

| Type          | Reads                                                                        |
| ------------- | ---------------------------------------------------------------------------- |
| `gws-tasks`   | open Google Tasks                                                            |
| `gws-doc`     | a Google Doc, as Markdown                                                    |
| `gh-issues`   | open GitHub issues across an owner or a list of repos                        |
| `gh-roadmaps` | each repo's README head plus its TODO/ROADMAP/PLAN files                     |
| `gh-markdown` | chosen sections, frontmatter, or whole files from a repo of Markdown         |
| `file`        | local files, by glob                                                         |
| `command`     | the stdout of any command: an export from Linear, Notion, or your own script |

Every field, each adapter's output, and the access each one needs are in
[docs/sources.md](docs/sources.md). A source whose fetch fails keeps its last content
under a `stale:` header; the others still refresh.

## Try it

Do this on the machine that will run the bot. A run there has full access, and that is
by design. Install the CLIs, then log in to each one as the user the bot will run as:

```sh
gh auth login            # see Security for a least-privilege token
gh auth setup-git        # lets git push over HTTPS with that login
claude                   # log in with your subscription, then exit; and/or: codex login
gws auth login --readonly -s tasks,docs,drive    # only for gws-* sources

gh repo clone your-github-user/remainderbot ~/remainderbot
cd ~/remainderbot
```

Then:

```sh
python3 -m remainderbot doctor
python3 -m remainderbot snapshot          # writes goals/snapshot/*.md; read them
python3 -m remainderbot decide --dry-run  # what the trigger rule would do now; claims nothing
python3 -m remainderbot run --provider claude --deadline-minutes 20 --size small
```

`doctor` prints one line per check and exits nonzero if any check fails. It checks:

- the CLIs, their logins, and whether it can read your quota;
- that `sources.toml` is valid and `GOALS.md` is no longer the example;
- that your edits are committed;
- that `origin` is private and accepts a push (a `git push --dry-run`, which creates
  nothing).

`run` launches a real agent session on a branch `run/<id>`. That spends real quota: a
small run typically uses a few percent of the week and much of the 5-hour window. When it
ends, `run` goes back to `main`. Nothing is pushed unless you add `--publish`. To read
what it made:

```sh
git show run/<id>:runs/<id>/README.md
git checkout run/<id>     # look around, then: git checkout main
```

## Install on a server

Run `crontab -e` and add two lines:

```
PATH=/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin
0 * * * * cd $HOME/remainderbot && RUN_DISABLED=1 python3 -m remainderbot tick >> $HOME/remainderbot.log 2>&1
```

Cron's own `PATH` is only `/usr/bin:/bin`. For the `PATH=` line, paste the output of
`echo $PATH` from your login shell, since cron does not expand variables there.
`RUN_DISABLED=1` makes each tick log its decision without running anything. Each hour
the log should show something like this:

```
2026-10-08 02:00:01Z tick start
2026-10-08 02:00:07Z snapshot issues.md: ok
2026-10-08 02:00:08Z usage: claude 5h 3% / weekly 41% used; codex 5h 0% / weekly 12% used
2026-10-08 02:00:08Z claude: weekly reset in 51.2h (> 4.0h window), 59% left
2026-10-08 02:00:08Z codex: weekly reset in 101.7h (> 4.0h window), 88% left
2026-10-08 02:00:08Z skip: no provider eligible
2026-10-08 02:00:08Z tick end
```

Inside the window, the tick logs `RUN_DISABLED=1: would run now` instead. After a day of
clean ticks, take `RUN_DISABLED=1` off the crontab line.

## Review runs

- **The PR is the notification.** The bot opens PRs with your `gh` login, and GitHub
  doesn't email you about your own actions by default. Turn on _Include your own updates_
  in GitHub's email notification settings, or give the bot its own account.
- **Each run's README** (the PR body) says what exists now, how it was verified, and your
  one next step: merge, `git am` a patch, paste a draft, or run one command. The work
  itself is in `runs/<id>/artifact/`, or in `artifact.patch` when it belongs in another
  repo.
- **Merge** means approved. **Close** means rejected. The last PR comment or review is
  the note the next run reads, so before you close a PR, say what should change.
- **`INBOX.md`** is the ledger on `main`: one row per run, with its status and your note.
  Each tick updates it from the PRs, and the agent reads it so it never repeats a task.
  Steer the bot through `GOALS.md` and PR comments, not by editing INBOX.md.

## Privacy

| Data                                     | Where it goes                                             | Who can read it                               |
| ---------------------------------------- | --------------------------------------------------------- | --------------------------------------------- |
| Your sources                             | read by `gws`, `gh`, local files, or your command         | unchanged                                     |
| `goals/snapshot/`                        | the server's disk; gitignored on `main`                   | the server                                    |
| `runs/<id>/snapshot/`, `PLAN.md`, `log/` | committed on the run branch                               | anyone with read access to your instance repo |
| The PR and `INBOX.md`                    | your instance repo                                        | same                                          |
| The agent's session                      | Anthropic or OpenAI, as with any Claude Code or Codex use | the provider                                  |

- **The public-repo guard.** Before the first push in a process, `gh repo view` must say
  that every URL `origin` pushes to is private (or internal). If it can't tell, the push
  is refused and tried again next tick. `tick` checks this right after its pull, before
  it syncs or runs anything, so a public instance never spends quota.
  `ALLOW_PUBLIC_REPO=1` turns the guard off; use it only for a repo meant to be public,
  with sources that are all public.
- **`private` sources.** The worker prompt names every source marked `private`. Nothing
  drawn from them may go into anything meant for publication (a post, a landing page),
  and each run's README says which sources it used.

## Security

The agent runs as `claude --dangerously-skip-permissions` or `codex
--dangerously-bypass-approvals-and-sandbox`. It can read any file the bot's user can
read, run any command, use any credential on the machine, and reach the network. The
prompt forbids pushing anywhere but your instance repo, sending mail, deploying, and
spending money. A prompt is not a sandbox, though: **the machine is.** Set it up so that
the worst thing a confused agent could do is small:

- [ ] A dedicated machine, and a dedicated non-root user on it.
- [ ] A fine-grained GitHub token for `gh auth login` with only the instance repo
      selected, and Contents and Pull requests set to read and write. Fine-grained tokens can
      always read every public repo, so public sources need nothing more.
- [ ] Know what a private source repo costs. Every `gh-*` source reads with that same
      login, and a fine-grained token gives the same permissions to every repo it selects,
      all owned by one user or organization. A private source repo therefore has to be
      selected in that token (with Issues read added for `gh-issues`), which lets the agent
      write to it too. A private repo with a different owner than the instance repo can't be
      read at all. (A classic token spans owners, but its `repo` scope writes to every
      private repo you can reach.) If that is too much, keep such repos out of
      `sources.toml`.
- [ ] Read-only Google scopes (`gws auth login --readonly`), and only the services your
      sources use.
- [ ] No other credentials on the box: no SSH keys to other machines, no cloud CLIs, no
      password manager.

What RemainderBot itself reads, and where it sends it:

- **Claude quota.** It reads Claude Code's OAuth token from `~/.claude/.credentials.json`
  (or the macOS keychain, or `CLAUDE_OAUTH_TOKEN`). It sends the token only to
  `api.anthropic.com`, to read your quota.
- **Codex quota** comes from `codex app-server`. RemainderBot never reads Codex's
  credentials.
- **Everything else goes through the CLIs:** `gh`, `gws`, `claude`, `codex`, `git`.

## Updating

On your own computer:

```sh
git fetch upstream
git merge upstream/main      # or a release tag: git merge v0.2.0
git push
```

The server picks up the update at its next tick: the tick pulls `main` and restarts
itself on the new code. Before merging, read [CHANGELOG.md](CHANGELOG.md): any entry
that needs an edit to `GOALS.md` or `sources.toml` has an **Action required** section.
`doctor` reports how many commits behind `upstream` you are.

## Commands

```
python3 -m remainderbot doctor                # is this instance ready to run? exits 1 on a failure
python3 -m remainderbot usage                 # normalized quota JSON for each provider
python3 -m remainderbot decide --dry-run      # what the rule would do right now
python3 -m remainderbot snapshot [--source NAME]
                                              # refresh goals/snapshot/; --source refreshes only that one
python3 -m remainderbot run --provider claude --deadline-minutes 20 --size small [--publish]
                                              # one run with an explicit budget; --publish also
                                              # pushes, opens the PR, and writes the INBOX.md row
python3 -m remainderbot sync-inbox            # copy PR state and last comments into INBOX.md
python3 -m remainderbot tick [--no-snapshot]  # what cron runs: sync, snapshot, decide, run, publish
python3 -m unittest discover -s tests         # the tests; no network
```

`run` needs a clean tree (tracked files unmodified). Ticks never overlap: a tick that
finds another still running logs `skip: previous tick still running`.

## Configuration

Environment variables, set on the crontab line or as `NAME=value` lines above it:

| Variable                       | Default                             | Meaning                                                                                                                 |
| ------------------------------ | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `WINDOW_HOURS`                 | 4                                   | run only when the weekly reset is this close                                                                            |
| `MIN_REMAINING`                | 10                                  | percent of the weekly (and the 5-hour) quota that must be left                                                          |
| `MAX_RUN_MINUTES`              | 45                                  | cap on a run; deadline = min(reset, now + cap) − 15 min                                                                 |
| `MIN_RERUN_MINUTES`            | 20                                  | after a run that finished, run again in the same period only if this much time is left                                  |
| `PROVIDERS`                    | `claude,codex`                      | which providers to read and run                                                                                         |
| `REPO_DIR`                     | the checkout containing the package | where `GOALS.md`, `state.json`, and `runs/` live                                                                        |
| `SOURCES_FILE`                 | `sources.toml`                      | what the snapshot reads; relative to `REPO_DIR`                                                                         |
| `RUN_DISABLED`                 | unset                               | log the decision and stop without claiming the period                                                                   |
| `ALLOW_PUBLIC_REPO`            | unset                               | push and open PRs even when `origin` is public                                                                          |
| `AGENT_FULL_ACCESS`            | 1                                   | pass the bypass-permissions flags to the CLI; with 0, Codex's sandbox makes `.git` read-only and the run's commits fail |
| `CLAUDE_MODEL` / `CODEX_MODEL` | `claude-opus-5-5` / `gpt-6-astra`   | models ([DESIGN.md §4.4](DESIGN.md#44-models-effort-and-cli-settings))                                                  |
| `CLAUDE_FALLBACK_MODEL`        | `claude-sonnet-5-5`                 | `--fallback-model` for Claude; empty to omit the flag                                                                   |
| `CLAUDE_OAUTH_TOKEN`           | unset                               | overrides `~/.claude/.credentials.json` and the macOS keychain                                                          |
| `CLAUDE_REFRESH_MODEL`         | `haiku`                             | model for the one-shot `claude -p` that refreshes a stored token after a 401                                            |
| `DEADLINE_BUFFER_MINUTES`      | 15                                  | how long before the reset a run must end                                                                                |
| `FINALIZE_MINUTES`             | 10                                  | time limit for the finalize pass                                                                                        |
| `LOG_MAX_BYTES`                | 5 MB                                | a run's agent log larger than this is not committed                                                                     |

## Troubleshooting

- **A check passes by hand but cron fails.** Cron has a minimal environment. Run
  `doctor` the way cron would:

  ```sh
  CRONPATH=$(crontab -l | sed -n 's/^PATH=//p' | tail -1)
  env -i HOME="$HOME" PATH="${CRONPATH:-/usr/bin:/bin}" \
    sh -c 'cd ~/remainderbot && python3 -m remainderbot doctor'
  ```

- **`usage: claude unknown`** (or `codex unknown`). The tick skips rather than guess.
  `python3 -m remainderbot usage` shows the error; usually the fix is to log in again.
- **A source shows `stale:`.** Its fetch failed, so the file kept its last content. The
  error is on the `snapshot <name>.md:` line of the log. To retry just that source, run
  `snapshot --source <name>`.
- **A run says it used a different model.** After a model change, update the CLIs on
  the server (`claude update`, or reinstall `codex`). An older Claude Code doesn't fail
  on a model it doesn't support; it quietly runs the whole session on
  `--fallback-model`. The model that actually answered is in the run log:

  ```sh
  grep '"type":"assistant"' runs/<id>/log/claude.jsonl | grep -o '"model":"[^"]*"' | sort | uniq -c
  ```

  The log's `init` line names the requested model even after a fallback, so don't rely
  on it.

- **A run is listed under `"unpublished"` in `state.json`.** Its push or `gh pr create`
  failed (the log says why), and every tick retries it. Run `doctor`.
- **`pull main failed: CONFLICT`.** Something else pushed to `main` while the server had
  commits of its own there, typically a manual `run --publish` or `tick` from another
  checkout. The tick goes on with its local `main` and pushes nothing until the conflict
  is resolved. Before a manual `--publish` run, comment out the crontab line, and restore
  it afterwards. To reconcile, as the bot's user in the checkout, not near the top of
  the hour:

  ```sh
  git fetch -q origin
  git log --oneline origin/main..main   # the server-only commits; INBOX rows rebuild from PRs
  git branch stuck-$(date +%Y%m%d) main # keep a copy
  git reset --hard origin/main
  ```

- **A period is blocked: "still marked running".** A tick died mid-run, so the bot won't
  retry that period. It clears at the next weekly reset.

## FAQ

**Does it cost money?** No. It spends only subscription quota that would otherwise
expire. It never uses extra-usage billing, API keys, or reset credits. You do pay for
the server.

**Does it send or post anything?** No. It pushes to your private instance repo and opens
PRs there. Messages, posts, and deploys come as drafts, with the exact text or command
for you to use.

**Do I need both subscriptions?** No. By default each tick checks both and runs whichever
is near its reset. If you have only one, set `PROVIDERS=claude` (or `codex`) so `doctor`
doesn't fail on the other and the log doesn't call it unreadable every hour.

**Is unattended use allowed under my plan?** Read your provider's terms: Anthropic's
[Consumer Terms](https://www.anthropic.com/legal/consumer-terms) and OpenAI's
[Terms of Use](https://openai.com/policies/terms-of-use/).

**What if the quota numbers stop working?** Neither provider documents the quota
endpoints RemainderBot reads. For Claude it's the OAuth usage endpoint that Claude Code
uses; for Codex, `account/rateLimits/read` on `codex app-server`. Either can change
without notice. If one stops answering, the tick skips that provider and logs why.
Nothing runs on a guess.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md): the tests need no network, a new source type is
one function and one test, and a change to a prompt needs a test like any other code
change. Licensed under [MIT](LICENSE).
