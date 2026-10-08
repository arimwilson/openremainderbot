# Sources

`sources.toml` says what the snapshot reads at the start of each tick. Each
`[[sources]]` table becomes one file, `goals/snapshot/<name>.md`, written by the adapter
its `type` names. Every run gets a copy of those files in `runs/<id>/snapshot/`, and the
worker prompt lists them with their descriptions.

- [The file](#the-file)
- [Fields every source takes](#fields-every-source-takes)
- [What `private` changes](#what-private-changes)
- Adapters: [`gws-tasks`](#gws-tasks) · [`gws-doc`](#gws-doc) · [`gh-issues`](#gh-issues) ·
  [`gh-roadmaps`](#gh-roadmaps) · [`gh-markdown`](#gh-markdown) · [`file`](#file) ·
  [`command`](#command)
- [Writing a `command` source](#writing-a-command-source)
- [Recipes](#recipes)

## The file

```toml
version = 1

[[sources]]
name = "issues"
type = "gh-issues"
owner = "your-github-user"

[[sources]]
name = "notes"
type = "gh-markdown"
repo = "your-github-user/notes"
private = true

  [[sources.parts]]          # belongs to the [[sources]] table above it
  include = "projects/*.md"
  sections = ["Open questions", "Next"]
```

`version = 1` is required. A `[[sources.parts]]` table belongs to the `[[sources]]` table
above it, however it is indented: that is TOML's rule for arrays of tables.

The file is read with Python's standard `tomllib` and checked in full before anything is
fetched. A syntax error names the line. Any other error names the source:

- an unknown `type`;
- a missing required field, an unknown field, or a field of the wrong type;
- a duplicate `name`;
- an unsupported `version`.

`snapshot` exits 2 on an invalid file, and `tick` logs the error and stops before the
snapshot and the run: it never runs on a half-understood config. `doctor` checks the file
too.

When a fetch fails, the source's file keeps its last content, and a first line
`stale: <time>: <error>` says why. The other sources still refresh, and the prompt tells
the agent which files are stale. When you remove a source, or set `enabled = false`, its
file is deleted at the next full refresh, so later runs don't copy it.
`snapshot --source <name>` refreshes only that source, which helps while you get a new
one working.

## Fields every source takes

| Field | Default | Meaning |
|---|---|---|
| `name` | required | `[a-z0-9-]+`, unique; the file is `goals/snapshot/<name>.md` |
| `type` | required | one of the adapters below |
| `description` | the adapter's own | one line shown to the agent next to the file's name, e.g. "Open Google Tasks; mostly errands, a few deliverables" |
| `private` | `false` | see below |
| `recheck` | the adapter's own | a one-line hint for the prompt's reality-check table: how to confirm an item from this source is still open |
| `enabled` | `true` | `false` keeps the entry without fetching it |
| `max_chars` | 60000 | the whole file is cut off after this many characters |

A good `description` tells the agent how to read the source, not only what it is. "Mostly
errands, a few deliverables" helps it filter better than "my tasks" does.

## What `private` changes

Content from a `private` source may inform work for your eyes, never anything meant for
publication. Concretely:

- The prompt lists the file as `(private)`.
- The prompt's privacy rule names every private file. Nothing drawn from them (content,
  names, company names) may go into a blog post, a landing page, or anything else meant
  for publication.
- Each run's README says which sources the work drew on.

A snapshot file that `sources.toml` doesn't describe also counts as private. That
happens with a renamed source's leftover file on a `--no-snapshot` run, or with every
file if `sources.toml` doesn't load.

`private` doesn't keep anything out of the run branch: every source is in
`runs/<id>/snapshot/` either way. That is why the instance repo itself must be private.

## Adapters

### `gws-tasks`

Open Google Tasks, per list, with due dates and notes.

| Field | Default | Meaning |
|---|---|---|
| `lists` | every list | titles of the task lists to include; a title that doesn't exist is an error |
| `notes` | `true` | include each task's notes |

```toml
[[sources]]
name = "tasks"
type = "gws-tasks"
lists = ["My Tasks", "Work"]
description = "Open Google Tasks; mostly errands, a few deliverables"
```

Output: `## <list> (<n> open)`, then `- <title> (due YYYY-MM-DD)`, with the notes
indented below. It reads up to 100 lists and up to 100 open tasks per list.

Needs: [`gws`](https://www.npmjs.com/package/@googleworkspace/cli) logged in with Tasks
read access (`gws auth login --readonly -s tasks`).

### `gws-doc`

A Google Doc, as Markdown.

| Field | Default | Meaning |
|---|---|---|
| `doc_id` | required | the long id in the doc's URL, `docs.google.com/document/d/<doc_id>/edit` |
| `tabs` | every tab | titles of the tabs to include, with their child tabs; a title that doesn't exist is an error |

```toml
[[sources]]
name = "roadmap"
type = "gws-doc"
doc_id = "1AbC...xyz"
tabs = ["Now", "Next"]
```

Output: headings, ordered and bulleted lists (nested), bold, strikethrough, links, and
tables. Images come out as `[image]`. A doc with one tab reads as a plain document. With
several tabs, each starts with `## Tab: <title>`.

Needs: `gws` with Docs read access (`-s docs`). The default `recheck` tells the agent to
find docs by name with `gws drive files list`, so add `drive` as well:
`gws auth login --readonly -s docs,drive`.

### `gh-issues`

Open GitHub issues, grouped by repo, most recently updated first.

| Field | Default | Meaning |
|---|---|---|
| `owner` | | a user or organization: every repo it owns. Set `owner` or `repos`, not both |
| `repos` | | `["owner/name", ...]` |
| `assignee` | anyone | only issues assigned to this login |
| `labels` | any | only issues that have all of these labels |
| `limit` | 200 | at most this many issues |

```toml
[[sources]]
name = "issues"
type = "gh-issues"
owner = "your-github-user"
labels = ["customer"]
```

Output: `## owner/name`, then `- #<n> <title> (updated YYYY-MM-DD, <labels>) <url>`.

Needs: `gh`, logged in with read access to those repos' issues (for a private repo, see
README.md, "Security"). It uses GitHub's issue search, which only finds what the login can
read.

### `gh-roadmaps`

For each repo, in the order you list them: the first lines of its README, plus every
Markdown file whose path looks like a roadmap, verbatim.

| Field | Default | Meaning |
|---|---|---|
| `repos` | required | `["owner/name", ...]`, in priority order |
| `pattern` | TODO, ROADMAP, PLAN, plans, planning, ideation | a regular expression, matched case-insensitively against each `.md` file's path |
| `readme_lines` | 40 | how much of the README to include; 0 leaves it out |

```toml
[[sources]]
name = "repos"
type = "gh-roadmaps"
repos = ["your-github-user/app", "your-github-user/site"]
description = "README head and roadmap files, repos in priority order"
```

The default pattern matches a word in a file name (`TODO.md`, `docs/release-plan.md`) or
a directory (`plans/q4.md`). Files under `node_modules/`, `vendor/`, `.git/`, `dist/`,
and `build/` are skipped, and each file is cut off after 60000 characters. Done items
keep their strikethrough or checkboxes, so the agent can tell done from open.

A repo that can't be read gets a `stale:` line in its own section. The source fails only
when no repo can be read.

Needs: `gh` with contents read access to each repo (for a private repo, see README.md,
"Security"). Nothing is cloned.

### `gh-markdown`

Chosen parts of a repo of Markdown notes: sections under given headings, frontmatter
keys, or whole files. This is the adapter for a notes or wiki repo, where you want the
open questions and next steps but not the people.

| Field | Default | Meaning |
|---|---|---|
| `repo` | required | `owner/name` |
| `parts` | required | one or more `[[sources.parts]]` tables, below |

Each part takes:

| Field | Default | Meaning |
|---|---|---|
| `include` | required | a glob or an array of globs, relative to the repo root |
| `exclude` | none | globs to leave out |
| `title` | the path | the heading for this part's files |
| `latest` | `false` | keep only the last match in sorted order, e.g. the newest dated note |
| `sections` | | headings whose bodies to keep (any level, case-insensitive) |
| `frontmatter` | | frontmatter keys to keep, one line per file |

Set `sections` or `frontmatter`, not both. With neither, each file is kept whole (up to
60000 characters). In globs, `*` and `?` stay within one directory, and `**` crosses
directories: `notes/**/*.md` matches `notes/a.md` and `notes/x/y/a.md`.

```toml
[[sources]]
name = "notes"
type = "gh-markdown"
repo = "your-github-user/notes"
private = true
description = "This week's note, open questions per project, and decisions"

  [[sources.parts]]
  include = "weekly/*.md"
  latest = true
  title = "This week"
  sections = ["Next", "Context"]

  [[sources.parts]]
  include = "projects/**/*.md"
  exclude = "projects/archive/**"
  title = "Project"
  sections = ["Open questions", "Current focus"]

  [[sources.parts]]
  include = "bets/*.md"
  title = "Bets"
  frontmatter = ["status", "statement"]

  [[sources.parts]]
  include = "decisions.md"
```

Output, from the example above:

```markdown
# notes (private, your-github-user/notes)

This week's note, open questions per project, and decisions

## This week: weekly/2026-10-05.md

### Next
...

## Project: projects/app.md

### Open questions
...

## Bets

- pricing: status=testing, statement=Salons pay more for reminders

## decisions.md

<the whole file>
```

Needs: `gh` with contents read access to the repo (for a private repo, see README.md,
"Security"). Nothing is cloned.

### `file`

Local files, each under its path. Use it for a `TODO.md`, an Obsidian vault, or anything
else that is on the server's disk.

| Field | Default | Meaning |
|---|---|---|
| `paths` | required | a glob or an array of globs: relative to the instance repo, absolute, or under `~/` |
| `exclude` | none | globs to leave out, written the same way |

```toml
[[sources]]
name = "todo"
type = "file"
paths = ["~/notes/TODO.md", "~/notes/projects/**/*.md"]
```

Globs follow the same rules as `gh-markdown`'s. Each pattern that matches no file is an
error, so a typo or a missing mount shows up as `stale:` instead of as silence. Files
come in pattern order, each once, under `## <path>`, and each is cut off after 60000
characters.

Needs: the files, readable by the bot's user on the server.

### `command`

The standard output of a shell command, verbatim. This is the adapter for everything
else: an issue tracker's CLI, an export script, an API call through `curl`.

| Field | Default | Meaning |
|---|---|---|
| `run` | required | the command, run by `/bin/sh` in the instance repo's directory |
| `timeout` | 60 | seconds before it's killed |

```toml
[[sources]]
name = "tracker"
type = "command"
run = "./scripts/tracker-to-md.sh --assignee me"
timeout = 120
recheck = "run ./scripts/tracker-to-md.sh again and look for the item's id"
```

Needs: whatever the command needs, available to the bot's user under cron (see below).

## Writing a `command` source

- **Print Markdown on stdout.** It goes into the file as is, so start with a `#` heading
  and give each item a line the agent can quote. Include ids or URLs, so that the
  reality check and your review can find the item again.
- **Exit nonzero on failure.** A nonzero exit marks the file stale with the last line of
  stderr (or stdout) as the error, and the last good content stays. Exit 0 with nothing
  printed is not an error: the file says the command printed nothing.
- **Finish within `timeout`.** On timeout the whole process group is killed, so child
  processes don't outlive it. The file then goes stale.
- **Read only.** The command runs every hour, unattended. It must not change anything.
- **Expect cron's environment.** The command runs with the tick's environment, so it
  gets the crontab's `PATH`, not your login shell's. It gets no terminal and no stdin, so
  a command that prompts for anything fails. Test it the way cron will run it (README.md,
  "Troubleshooting"), then with `snapshot --source <name>`.
- **Set `recheck`.** The default tells the agent to run your command again. If your tool
  has a cheaper way to check a single item, say so.
- **Mark it `private`** if it returns anything you wouldn't publish.

## Recipes

A recipe is listed here only after it has been run end to end.

### An Obsidian vault (`file`)

An Obsidian vault is a folder of Markdown files, so `file` reads it directly, provided
the vault is on the server's disk (for example through Syncthing). If the vault is a
GitHub repo (for example through the Obsidian Git plugin), use `gh-markdown` instead.

```toml
[[sources]]
name = "vault"
type = "file"
private = true
description = "My Obsidian vault: the TODO list and project notes"
paths = ["~/vault/TODO.md", "~/vault/Projects/**/*.md"]
exclude = ["~/vault/.trash/**", "~/vault/Templates/**"]
```

Leave out `.trash/`: Obsidian moves deleted notes there, and they are still `.md`
files. Leave out `Templates/` too: templates are placeholders, not plans. `.obsidian/`
holds only settings, none of them `.md`, so `**/*.md` never picks it up. For the whole
vault, use `paths = ["~/vault/**/*.md"]`, and add daily notes to `exclude` unless you
want them read.
