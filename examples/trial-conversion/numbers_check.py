"""Independent check of every figure quoted in REPORT.md. Does not import trials_report.

    python3 runs/20261008-0431-claude/evidence/numbers_check.py notes/trials.csv
"""
import csv
import sys
from fractions import Fraction
from math import factorial

rows = list(csv.DictReader(open(sys.argv[1], newline="")))
n = lambda r, k: int(r[k])
fin = [r for r in rows if r["converted"] != "in trial"]
paid = [r for r in fin if r["converted"] == "yes"]
lost = [r for r in fin if r["converted"] == "no"]
listin = lambda r: n(r, "clients_entered") >= 50


def frac(group):
    return f"{sum(r['converted'] == 'yes' for r in group)}/{len(group)}"


def fisher(a, b, c, d):  # brute force over every table with the same margins, exact fractions
    def h(x):
        y, z, w = a + b - x, a + c - x, d - a + x
        if min(y, z, w) < 0:
            return None
        f = factorial
        return Fraction(f(a + b) * f(c + d) * f(a + c) * f(b + d),
                        f(a + b + c + d) * f(x) * f(y) * f(z) * f(w))
    obs = h(a)
    return float(sum(p for p in (h(x) for x in range(0, a + b + 1)) if p is not None and p <= obs))


def two(group_a, group_b):
    a, c = sum(r["converted"] == "yes" for r in group_a), sum(r["converted"] == "yes" for r in group_b)
    return f"{frac(group_a)} vs {frac(group_b)}, p={fisher(a, len(group_a) - a, c, len(group_b) - c):.3f}"


print("trials / finished / paid:", len(rows), len(fin), len(paid), f"{100 * len(paid) / len(fin):.0f}%")
print("non-payers with <=8 clients:", sum(n(r, "clients_entered") <= 8 for r in lost), "of", len(lost))
print("clients entered, gap:", max(n(r, "clients_entered") for r in rows if not listin(r)),
      "..", min(n(r, "clients_entered") for r in rows if listin(r)))
print("list in vs not:", two([r for r in fin if listin(r)], [r for r in fin if not listin(r)]))
print("online>=10 same set as list in:",
      {r["salon_id"] for r in fin if n(r, "online_bookings") >= 10} == {r["salon_id"] for r in fin if listin(r)})
print("max online bookings without list:", max(n(r, "online_bookings") for r in fin if not listin(r)))
print("27+ bookings same set as list in:",
      {r["salon_id"] for r in fin if n(r, "bookings_in_trial") >= 27} == {r["salon_id"] for r in fin if listin(r)},
      "| max bookings without list:", max(n(r, "bookings_in_trial") for r in fin if not listin(r)))
print("no-list salons with any online bookings:", sum(n(r, "online_bookings") > 0 for r in fin if not listin(r)),
      "of", sum(not listin(r) for r in fin))
print("finished with any online bookings:", sum(n(r, "online_bookings") > 0 for r in fin), "of", len(fin))
print("2+ groomers vs 1:", two([r for r in fin if n(r, "groomers") >= 2], [r for r in fin if n(r, "groomers") == 1]))
print("reminders on vs off:", two([r for r in fin if r["reminders_on"] == "yes"], [r for r in fin if r["reminders_on"] == "no"]))
for g, test in (("1 groomer", lambda r: n(r, "groomers") == 1), ("2+ groomers", lambda r: n(r, "groomers") >= 2)):
    print(f"{g}: list in {frac([r for r in fin if test(r) and listin(r)])},"
          f" not in {frac([r for r in fin if test(r) and not listin(r)])}")
print("paid without list:", [(r["salon"], r["groomers"]) for r in paid if not listin(r)])
for m in ("06", "07", "08", "09"):
    print(f"signup 2026-{m}:", frac([r for r in fin if r["signup"][5:7] == m]))
ans = [r for r in lost if r["exit_survey"]]
print("exit survey answered:", len(ans), "of", len(lost))
for label, words in (("setup", ("typing", "enter", "client list", "setup")), ("lunch", ("lunch",)),
                     ("offline", ("book online", "call or text")), ("price", ("$29",)), ("big dogs", ("big dogs",))):
    hits = [r for r in ans if any(w in r["exit_survey"].lower() for w in words)]
    print(f"  {label}: {len(hits)}; one-groomer {sum(n(r, 'groomers') == 1 for r in hits)};"
          f" list in: {[(r['salon'], n(r, 'clients_entered')) for r in hits if listin(r)]}")
print("silent with list in:", [(r["salon"], n(r, "clients_entered")) for r in lost if not r["exit_survey"] and listin(r)])
print("latest trial_end among lunch answers:", max(r["trial_end"] for r in ans if "lunch" in r["exit_survey"]))
for r in rows:
    if r["converted"] == "in trial":
        like = [x for x in fin if listin(x) == listin(r) and (n(x, "groomers") == 1) == (n(r, "groomers") == 1)]
        print(f"  like {r['salon']}: {frac(like)} paid")
print("in trial:", [(r["salon"], r["trial_end"], n(r, "clients_entered"), f"{r['online_bookings']}/{r['bookings_in_trial']}")
                    for r in rows if r["converted"] == "in trial"])
