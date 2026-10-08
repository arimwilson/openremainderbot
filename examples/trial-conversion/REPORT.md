# Why trial salons don't pay

From the Oct 1 admin export (`notes/trials.csv`). The tables behind every number here are
in [tables.md](tables.md), made by [trials_report.py](trials_report.py). This is evidence
and options; the choices are yours.

## The short answer

**The strongest marker of a salon that leaves is that it never got its client list into
Fernhill.** 27 of the 35 salons that finished a trial and didn't pay entered 8 clients or
fewer. Setup is also the most common reason given in the exit survey: 8 salons. Seven of
them named client entry outright ("Typing in all my clients took too long", "Too much to
enter by hand", "Never got my client list in, so I didn't use it"), and one said "Setup was
more work than I had time for in two weeks". Lunch breaks come next with 6. One of the
eight, Lather Leash, typed in 153 clients and still called it too much.

Salons that got their list in paid at 50% (8 of 16). Salons that didn't paid at 18% (6 of
33). Fisher exact p = 0.04. That's borderline given that I tried five splits, and it is a
marker, not proof of a cause (see *What this can't tell you*).

## What the export shows

Out of 55 trials, 49 had finished by Oct 1 and 14 of those paid: **29%**.

**The client list.** The export splits cleanly. Every salon entered either 8 clients or
fewer, or 73 or more. Nobody is in between. Salons seem to either enter a whole list or
stop early.

**Usage splits the same salons.** The 16 salons with their list in are exactly the 16 with
10 or more online bookings, and exactly the 16 with 27 or more bookings in all. Salons
without a list still got bookings (up to 21 in all and up to 9 online; 29 of the 33 had
some online), but fewer. From this export you can't say which of the three matters. They
are one group of salons that used Fernhill for real.

**Salon size: a gap, but not one you can tell from chance.** Two-plus-groomer salons paid
at 37% (10 of 27), one-groomer salons at 18% (4 of 22), p = 0.21. Split by client list:

| | List in | List not in |
|---|---|---|
| 1 groomer | 3 of 8 | 1 of 14 |
| 2+ groomers | 5 of 8 | 5 of 19 |

The size gap shows in both rows, but neither row's gap stands out from chance. One thing worth
asking about: five of the six salons that paid without a client list had 2–4 groomers
(Rosie's Leash, Otis & Hound, Happy Hound, Willow Pup Spa, Wag Grooming). The export can't
say what they used Fernhill for. A shared schedule for the groomers is one guess.

**Reminder texts made no clear difference.** 35% paid with reminders on, 22% with them off,
p = 0.36. The export has no no-show data, so it can't say whether reminders cut no-shows.
That matters for newsletter #14.

**No trend by signup month** that survives the small numbers: June 4/14, July 1/13,
August 5/14, September 4/8.

## Exit survey: 24 of 35 answered

| Reason | Salons | Where it stands |
|---|---|---|
| Setup: getting the client list in | 8 | No issue filed, no import |
| Couldn't block lunch | 6 | Shipped Oct 8 (#4), after all six had left |
| Clients won't book online (4 "older clients", 1 "call or text me") | 5 | No issue filed; the staff screen can't take a phone booking |
| "\$29 a month is a lot for just me" | 4 | Pricing, your call |
| Big dogs needed two appointments | 1 | #7, open |

Three things in that table are easy to misread:

- **Lunch.** Five of the six lunch salons also never got their client list in, so #4 alone
  might not have kept them. All six left by July 31 and #4 landed on Oct 8, so none of them
  has seen the fix. Salons can't set their own time off yet either. The staff screen only
  answers on 127.0.0.1 (`staff.py` returns 403 to any other host).
- **Price.** All four were one-groomer salons, and three of the four had entered 0–2
  clients. Only Thistle Hound (191 clients) said it after setting up. For the other three,
  "\$29 is a lot" may mean "\$29 is a lot for something I never got running".
- **Silence.** 11 left no answer. Three of them had done the setup work and still left:
  Pampered Pup Spa (349 clients), Fluff Paws (210), Puddle Hound (361). Of everyone in the
  export, they are the three most worth a short email asking why.

## Salons marked "in trial" in the Oct 1 export

All figures are a week old. Two of these trials have since ended, and anyone who signed up
after Oct 1 is missing. "Paid" figures are for finished trials of the same size and
list status.

| Salon | Trial ends | Groomers | Clients | Finished trials like it |
|---|---|---|---|---|
| Maple Grooming | Oct 3 (ended) | 1 | 243 | 3 of 8 paid |
| Juniper Grooming | Oct 3 (ended) | 1 | 5 | 1 of 14 paid |
| Thistle Pup Spa | Oct 8 (today) | 2 | 2 | 5 of 19 paid |
| Cedar Tails | Oct 11 | 3 | 94 | 5 of 8 paid |
| Sudsy Hound (Tacoma, Dana) | Oct 12 | 3 | 210 | 5 of 8 paid; 30 of 37 bookings online |
| Tidy Coat Co. | Oct 13 | 2 | 0 | 5 of 19 paid |

Dana's salon is set up and busy. If she doesn't pay, it isn't for lack of setup. Her
question about texting from the salon's own number may be the blocker, and your TODO
already says to ask what else is in the way. Tidy Coat Co. is the only salon still in trial
with no list and days left for setup help to land.

## Options

Rough order, cheapest first. None of them is a pricing or roadmap decision made for you.

1. **Ask the three silent set-up salons why** (Pampered Pup Spa, Fluff Paws, Puddle Hound).
   Three emails. Nothing in the export says what stopped them.
2. **Offer to load the client list (no code, your time).** Offer it to trial salons on day
   2 or 3, from whatever they have: a spreadsheet, an export from their old system, a card
   file. With no import, that means typing it in yourself. On its own this can't prove the
   list *causes* paying, because the salons that accept are self-selected. Offering it to
   alternate signups only would give a rough comparison, but at 8–14 finished trials a
   month expect months, not weeks. Draft A below is for Tidy Coat Co.
3. **Tell the lunch six that #4 exists.** Each of them named it as the reason. Salons can't
   reach the staff screen themselves today, so Draft B offers to set their blocks for them
   rather than promising self-service. If two or three reply, the fix is worth announcing
   more widely.
4. **A client import in Fernhill** (roadmap). There is no issue for it yet. Setup is the
   most common exit reason, and option 2 would tell you what formats salons actually have
   before you build it.
5. **Phone bookings on the staff screen** (roadmap). Five salons said their clients won't
   book online. The staff screen has time off, a day view and the CSV export, but no way to
   enter a booking.
6. **Solo pricing** (yours). The evidence is thinner than it looks: four salons, three of
   which never set up. Options 1 and 2 would tell you more before you decide.

## What this can't tell you

- **Cause.** Salons that meant to switch may also be the ones willing to type in a whole
  client list. Only a comparison, like the alternate-signup version of option 2, separates
  the two.
- **Small numbers.** 49 finished trials, and the client-list split is borderline once you
  count the other splits tried. In the smaller groups (8 to 16 salons), one salon moves a
  percentage by 6 to 13 points.
- **The 19 paying salons.** GOALS.md counts 19 paying; this export has 14 conversions, all
  from June–September signups. The others aren't in it, so this says nothing about them.
- **Since Oct 1.** Rerun on a fresh export:
  `python3 runs/20261008-0431-claude/artifact/trials_report.py notes/trials.csv`.

## Drafts (not sent)

### A. Setup help, to Tidy Coat Co. (trial ends Oct 13)

Only if you choose option 2. First check in the admin page that their client list is
still empty. The 0 is from Oct 1.

> Subject: Want me to put your clients in for you?
>
> Hi,
>
> Your Fernhill trial runs to Oct 13, and your client list isn't in yet. That's the step
> most salons get stuck on, and the salons that got past it were far more likely to stay.
>
> Send me what you have, in any form. A spreadsheet, an export from your old system, a
> photo of your card file. I'll put it in for you and tell you when it's done.
>
> Sam

### B. Lunch breaks, to the six salons who left over them

Bramble Grooming, Pebble Grooming, Pebble Scrub Club, Tidy Mutt Cuts, Maple Coat Co.,
Tidy Paws. It promises only that you'll set their blocks. Whether they get a new trial, and
whether their old data is still there, are yours to decide before you send.

> Subject: You can block your lunch now
>
> Hi,
>
> When you tried Fernhill this summer, you told me clients were booking over your lunch.
> You were right, and you weren't the only one.
>
> Fernhill can now block a groomer's time off, one-off or every week, and the booking page
> won't offer those times. Lunch, school pickup, a standing Tuesday off.
>
> If you'd like to give it another look, reply with your groomers' breaks and I'll set them
> up for you.
>
> Sam
