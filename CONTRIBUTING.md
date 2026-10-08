# Contributing

Thanks for helping. Two kinds of change are in scope:

- new source adapters;
- engine bugs and improvements: the trigger, runs, publishing, prompts, `doctor`.

Setup help for every platform is out of scope. If the README got something wrong or left
something out on your setup, though, that is a docs bug, and an issue is welcome.

## Ground rules

- **Standard library only, Python 3.11+.** No dependencies, so that installing
  remainderbot means cloning it.
- **Tests need no network.** Run them with `python3 -m unittest discover -s tests`.
  External CLIs are faked: `tests/fake_gh.py`, `tests/fake_gws.py`, and
  `tests/fake_codex.py` are put on `PATH` in place of the real ones.
- **Prompts are code.** A change to `remainderbot/prompts/*.md` needs a test, like any
  other code change. The tests already check that no `{placeholder}` survives
  rendering. Add an assertion for what your change relies on: text rendered from
  config, a rule that must be present. If the change fixes something you saw in real
  runs, describe what went wrong. Don't link the runs: your instance is private.
- **Nothing from an instance goes upstream.** `GOALS.md`, `sources.toml`, `INBOX.md`,
  `state.json`, and `runs/` exist only in instance repos. Upstream keeps the examples
  (`GOALS.example.md`, `sources.example.toml`) instead.

## Adding a source adapter

An adapter is one function in `remainderbot/adapters/` that returns the Markdown for
`goals/snapshot/<name>.md`:

```python
@adapter("gh-releases", required={"repos": list}, optional={"limit": int},
         check=_check_releases,
         description="Recent releases of each repo",
         recheck="`gh release view`: is it still the latest? does a newer one cover the item?")
def gh_releases(src: dict, ctx) -> str:
    ...  # raise SourceError("...") on failure; the file then goes stale
```

- **Fields.** `required` and `optional` declare the fields the source takes and their
  types. `sources.py` checks every `[[sources]]` table against them before anything is
  fetched. Use `check` for rules that span several fields (one of two, a non-empty list).
- **Defaults.** `description` and `recheck` are what the prompt shows for a source that
  doesn't set its own.
- **Errors.** Raise `SourceError` with a message that says what failed. It goes into the
  stale header and the log.
- **Shared helpers** are in `adapters/_util.py`: `_gh_api`, `_gh_file`, `_gh_tree`,
  `_gws`, `glob_re`, `md_section`, `frontmatter`, and `truncate`.

A new adapter needs four more things:

1. **A test against a fake CLI.** Follow `FakeCLIs` in `tests/test_adapters.py`. Cover
   the output, each validation error, and a failing CLI.
2. **A section in `docs/sources.md`.** Give its fields, its output, the access it needs,
   and an example.
3. **A commented-out example in `sources.example.toml`.** `tests/test_doctor.py` checks
   that every commented-out source in it is valid.
4. **A line in `CHANGELOG.md`.**

A recipe (a `command` or `file` setup for a particular tool) goes in `docs/sources.md`
only after it has been run end to end. Say in the PR what you ran it against.

## Changes that affect existing instances

`sources.toml` carries a `version`, and the readers of `INBOX.md` and `state.json` must
keep accepting every format they have shipped with. If your change needs users to edit a
file:

- add an **Action required** section to its `CHANGELOG.md` entry, with the exact edit;
- make `doctor` say what to change when it finds the old format.

## Sending a change

Work in a fork of openremainderbot, not in your instance repo. Start the branch from
`upstream/main`: your instance's `main` carries your goals and your ledger. Run the
tests, then open a PR that says what changed and why.

To report a security problem, use the repo's Security tab, not a public issue.
