# GOALS

The only file you write for the bot. Every run reads it first. Replace this example (a
made-up solo founder) with your own; `doctor` fails until you do.

> **What a run reads, in order**
>
> 1. **This file.** *Priorities* say what matters, *Rules* say what is in and out, and an
>    open *Manual goal* outranks everything.
> 2. **`goals/snapshot/`**: one file per source in `sources.toml`, refreshed at the start
>    of each tick.
> 3. **`INBOX.md`**: every past run, your verdict, and your note on its PR.
>
> The worker prompt's Defaults cover the general rules: no errands, drafted never sent,
> one action to ship, no repeats, nothing that needs your credentials to verify. Your
> Rules override them where the two conflict.

## Priorities

What these deliverables are for, in tiers, then in order within a tier. A modest
artifact in a high tier beats an impressive one in a low tier.

**(a) Get Fernhill to 50 paying salons by June.** Fernhill is my booking app for dog
groomers; I build and sell it alone.

1. Find out why salons that finish the trial don't pay.
2. Ship the two features customers ask for most (see `issues.md`).

**(b) Grow the audience that brings in trials.**

3. A newsletter post every two weeks on running a grooming business.
4. Talks and guest posts where salon owners gather.

**(c) Everything else.**

5. Internal tools that save me an hour a week.
6. Learning: Postgres performance, pricing.

## What to take off my plate

Optional. Which work you would hand to an assistant, and which you would rather do
yourself.

- Yes: legwork the outside world can answer: competitors' pricing and features, what
  salon owners say in public forums, trade-show dates.
- Yes: prep for calls on my calendar, and drafts of replies I owe.
- No: pricing and roadmap decisions. Bring me evidence and options, not the answer.

## Rules

Personal additions only; the Defaults in the worker prompt cover the rest.

- Prefer, in tier order: (a) issues labeled `customer`, and drafts for salons in their
  trial; (b) newsletter drafts from my outline notes; (c) anything in the repos' TODO
  files.
- Never change billing code; I write every change there myself.
- Newsletter drafts go in `artifact/` as Markdown, in my voice: short sentences, no
  exclamation marks.

## Manual goals

Open items here outrank everything in the snapshot. Strike one through when it is done,
like `~~Draft the v2.3 release notes~~`.

- (none)
