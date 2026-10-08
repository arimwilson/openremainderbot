"""Why don't trial salons pay? Tables from a Fernhill admin trial export.

    python3 trials_report.py notes/trials.csv --as-of 2026-10-08 > tables.md

Standard library only. Reads the CSV the admin page exports (one row per trial salon) and
prints Markdown: conversion by segment, exit-survey themes, and the salons still in trial
with what looks like it is in their way. Every number comes from the CSV.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from math import comb

# Below this many clients entered, a salon never got its client list in. In the Oct 1
# export the counts split cleanly: every salon has 8 or fewer, or 73 or more.
CLIENT_LIST_IN = 50

# Exit-survey themes, checked in order; the first theme with a matching phrase wins.
# (key, heading, phrases, where it stands in Fernhill)
THEMES = [
    ("setup", "Setup: getting the client list in",
     ("typing", "enter", "client list", "setup"),
     "No issue filed. Clients are entered one at a time; there is no import."),
    ("time_off", "Couldn't block lunch or breaks",
     ("lunch", "block", "break"),
     "Shipped on Oct 8 as #4 (92f08a3), after every trial in this export had ended."),
    ("offline_clients", "Clients don't book online",
     ("book online", "call or text", "phone"),
     "No issue filed. The staff screen has no way to enter a phone booking."),
    ("price", "Price for a one-groomer salon",
     ("$", "price", "a lot for", "expensive"),
     "Pricing: Sam's decision. Solo is $29/month, Studio $79/month (billing.py)."),
    ("big_dogs", "Big dogs",
     ("big dog", "giant", "two appointments"),
     "Open: #7 (a giant size)."),
]
OTHER = ("other", "Other", (), "")


@dataclass(frozen=True)
class Trial:
    salon_id: str
    salon: str
    city: str
    signup: date
    trial_end: date
    groomers: int
    clients_entered: int
    bookings_in_trial: int
    online_bookings: int
    reminders_on: bool
    status: str          # "yes", "no", or "in trial"
    plan: str
    exit_survey: str

    @property
    def finished(self) -> bool:
        return self.status in ("yes", "no")

    @property
    def converted(self) -> bool:
        return self.status == "yes"

    @property
    def client_list_in(self) -> bool:
        return self.clients_entered >= CLIENT_LIST_IN


def load(lines) -> list[Trial]:
    """Parse the export. `lines` is an open file or any iterable of CSV lines."""
    trials = []
    for row in csv.DictReader(lines):
        status = row["converted"].strip().lower()
        if status not in ("yes", "no", "in trial"):
            raise ValueError(f"{row['salon_id']}: unknown converted value {row['converted']!r}")
        trials.append(Trial(
            salon_id=row["salon_id"].strip(),
            salon=row["salon"].strip(),
            city=row["city"].strip(),
            signup=date.fromisoformat(row["signup"].strip()),
            trial_end=date.fromisoformat(row["trial_end"].strip()),
            groomers=int(row["groomers"]),
            clients_entered=int(row["clients_entered"]),
            bookings_in_trial=int(row["bookings_in_trial"]),
            online_bookings=int(row["online_bookings"]),
            reminders_on=row["reminders_on"].strip().lower() == "yes",
            status=status,
            plan=row["plan"].strip(),
            exit_survey=row["exit_survey"].strip(),
        ))
    return trials


def theme_of(answer: str) -> tuple[str, str, tuple[str, ...], str] | None:
    """The theme an exit-survey answer belongs to, OTHER if none fits, None if blank."""
    text = answer.strip().lower()
    if not text:
        return None
    for theme in THEMES:
        if any(phrase in text for phrase in theme[2]):
            return theme
    return OTHER


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for the 2x2 table [[a, b], [c, d]]."""
    row1, col1, n = a + b, a + c, a + b + c + d

    def p(x: int) -> float:
        return comb(col1, x) * comb(n - col1, row1 - x) / comb(n, row1)

    observed = p(a)
    lo, hi = max(0, row1 + col1 - n), min(row1, col1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= observed * (1 + 1e-9)))


def rate(trials: list[Trial]) -> tuple[int, int]:
    return sum(t.converted for t in trials), len(trials)


def pct(paid: int, total: int) -> str:
    return f"{paid}/{total} ({round(100 * paid / total)}%)" if total else "0/0 (–)"


def split(trials, test, yes_label, no_label):
    """Two rows of a segment table plus the Fisher p-value comparing them."""
    yes = [t for t in trials if test(t)]
    no = [t for t in trials if not test(t)]
    (a, n1), (c, n2) = rate(yes), rate(no)
    return [(yes_label, a, n1), (no_label, c, n2)], fisher_exact(a, n1 - a, c, n2 - c)


def risks(t: Trial) -> list[str]:
    """What, in the finished trials' pattern, puts an in-trial salon at risk.

    Reminders are left out on purpose: on vs off made no clear difference (p 0.36).
    """
    out = []
    if not t.client_list_in:
        out.append(f"client list not in ({t.clients_entered} entered)")
    if t.groomers == 1 and not t.client_list_in:
        out.append("one groomer")
    if t.online_bookings == 0:
        out.append("no online bookings yet")
    return out


def cell(value) -> str:
    """A table cell: a pipe would end the cell, and two dollar signs make GitHub render math."""
    return str(value).replace("|", "\\|").replace("$", "\\$")


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return lines


def render(trials: list[Trial], as_of: date, source: str = "the export") -> str:
    done = [t for t in trials if t.finished]
    live = [t for t in trials if not t.finished]
    paid, total = rate(done)
    lost = [t for t in done if not t.converted]
    out = [
        "# Trial conversion tables",
        "",
        f"Generated by `trials_report.py` from {source}, as of {as_of.isoformat()}.",
        f"{len(trials)} trials: {total} finished, {len(live)} still in trial "
        f"(as marked in the export). Finished trials that paid: **{pct(paid, total)}**.",
        "",
        "## What separates salons that paid",
        "",
        "Finished trials only. *p* is a two-sided Fisher exact test on the two rows: "
        "below 0.05 is unlikely to be chance, above 0.2 could easily be.",
        "",
    ]
    splits = [
        ("Client list", lambda t: t.client_list_in,
         f"{CLIENT_LIST_IN}+ clients entered", f"under {CLIENT_LIST_IN} entered"),
        ("Salon size", lambda t: t.groomers >= 2, "2+ groomers", "1 groomer"),
        ("Reminder texts", lambda t: t.reminders_on, "on", "off"),
    ]
    busy = {t.salon_id for t in done if t.online_bookings >= 10}
    if busy != {t.salon_id for t in done if t.client_list_in}:
        splits.append(("Clients booked online", lambda t: t.online_bookings >= 10,
                       "10+ online bookings", "under 10"))
    rows = []
    for name, test, yes_label, no_label in splits:
        (r1, r2), p = split(done, test, yes_label, no_label)
        rows.append([name, r1[0], pct(r1[1], r1[2]), r2[0], pct(r2[1], r2[2]), f"{p:.3f}"])
    out += table(["Segment", "Group", "Paid", "vs group", "Paid", "p"], rows)

    if busy == {t.salon_id for t in done if t.client_list_in}:
        out += ["", f"The {len(busy)} finished salons with 10+ online bookings are exactly the "
                f"{len(busy)} with {CLIENT_LIST_IN}+ clients entered, so the export can't tell "
                "the two apart."]

    out += ["", "### Client list by salon size", ""]
    rows = []
    for size_label, size_test in (("1 groomer", lambda t: t.groomers == 1),
                                  ("2+ groomers", lambda t: t.groomers >= 2)):
        group = [t for t in done if size_test(t)]
        rows.append([size_label,
                     pct(*rate([t for t in group if t.client_list_in])),
                     pct(*rate([t for t in group if not t.client_list_in]))])
    out += table(["Salon size", f"{CLIENT_LIST_IN}+ clients entered",
                  f"under {CLIENT_LIST_IN} entered"], rows)

    out += ["", "### By signup month", ""]
    months = sorted({t.signup.strftime("%Y-%m") for t in done})
    out += table(["Signup month", "Paid"],
                 [[m, pct(*rate([t for t in done if t.signup.strftime("%Y-%m") == m]))]
                  for m in months])

    out += ["", "### Plans chosen", ""]
    plans = sorted({t.plan for t in done if t.converted})
    out += table(["Plan", "Salons", "Groomers"],
                 [[p, sum(t.plan == p for t in done if t.converted),
                   ", ".join(str(t.groomers) for t in done if t.converted and t.plan == p)]
                  for p in plans])

    answered = [t for t in lost if t.exit_survey]
    out += [
        "",
        "## Why the others say they left",
        "",
        f"{len(lost)} finished trials did not pay; {len(answered)} answered the exit survey, "
        f"{len(lost) - len(answered)} left it blank. Answers grouped by theme "
        "(phrase match, see `THEMES`).",
        "",
    ]
    rows = []
    for theme in THEMES + [OTHER]:
        hits = [t for t in answered if theme_of(t.exit_survey) == theme]
        if not hits:
            continue
        quotes = sorted({t.exit_survey for t in hits})
        solo = sum(t.groomers == 1 for t in hits)
        rows.append([theme[1], len(hits), f"{solo} of {len(hits)}",
                     "<br>".join(f"“{q}”" for q in quotes), theme[3]])
    out += table(["Theme", "Salons", "One-groomer", "What they wrote", "In Fernhill"], rows)

    silent = [t for t in lost if not t.exit_survey]
    out += [
        "",
        f"The {len(silent)} who left no answer: "
        f"{sum(t.client_list_in for t in silent)} had their client list in, "
        f"{sum(t.groomers == 1 for t in silent)} were one-groomer salons, "
        f"{sum(t.online_bookings == 0 for t in silent)} had no online bookings.",
        "",
        "### Non-payers who did get their client list in",
        "",
        "The salons that did the setup work and still left; the most useful people to ask.",
        "",
    ]
    out += table(["Salon", "City", "Groomers", "Clients", "Online / all bookings",
                  "Reminders", "Exit survey"],
                 [[f"{t.salon} ({t.salon_id})", t.city, t.groomers, t.clients_entered,
                   f"{t.online_bookings} / {t.bookings_in_trial}",
                   "on" if t.reminders_on else "off", t.exit_survey or "–"]
                  for t in lost if t.client_list_in])

    out += [
        "",
        "## Salons still in trial",
        "",
        "Status as the export marks it. Days left are counted from the as-of date; a trial "
        "that ended after the export was taken shows as ended and needs a fresh export.",
        "",
    ]
    rows = []
    for t in sorted(live, key=lambda t: t.trial_end):
        left = (t.trial_end - as_of).days
        when = ("ends today" if left == 0 else
                f"{left} day{'s' * (left != 1)} left" if left > 0 else
                f"ended {-left} day{'s' * (left != -1)} ago")
        rows.append([f"{t.salon} ({t.salon_id})", t.city, t.trial_end.isoformat(), when,
                     t.groomers, t.clients_entered,
                     f"{t.online_bookings} / {t.bookings_in_trial}",
                     "; ".join(risks(t)) or "none of these risk signs"])
    out += table(["Salon", "City", "Trial ends", "As of " + as_of.isoformat(), "Groomers",
                  "Clients", "Online / all bookings", "Risk signs"], rows)
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", help="trial export from the admin page")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                        help="date to count days left from (YYYY-MM-DD, default today)")
    args = parser.parse_args(argv)
    with open(args.csv, newline="", encoding="utf-8") as f:
        trials = load(f)
    sys.stdout.write(render(trials, args.as_of, f"`{args.csv}`"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
