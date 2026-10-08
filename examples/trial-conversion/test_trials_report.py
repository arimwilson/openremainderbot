"""Tests for trials_report.py.  Run from this directory: python3 -m unittest -v"""
import io
import unittest
from datetime import date
from math import isclose
from pathlib import Path

import trials_report as tr

HEADER = ("salon_id,salon,city,signup,trial_end,groomers,clients_entered,bookings_in_trial,"
          "online_bookings,reminders_on,converted,plan,exit_survey\n")


def export(*rows: str) -> list:
    return tr.load(io.StringIO(HEADER + "".join(r + "\n" for r in rows)))


FIXTURE = export(
    "A1,Paid Big,Bend,2026-06-01,2026-06-15,3,300,40,30,yes,yes,studio,",
    "A2,Paid Small,Bend,2026-06-02,2026-06-16,1,2,6,1,no,yes,solo,",
    "A3,Left Typing,Salem,2026-07-01,2026-07-15,1,4,5,3,no,no,,Typing in all my clients took too long",
    "A4,Left Lunch,Salem,2026-07-02,2026-07-16,2,120,30,20,yes,no,,\"Couldn't block my lunch, people booked over it\"",
    "A5,Left Blank,Eugene,2026-07-03,2026-07-17,1,0,3,0,no,no,,",
    "B1,Still Here,Tacoma,2026-09-28,2026-10-12,1,0,4,0,no,in trial,,",
    "B2,Doing Fine,Tacoma,2026-09-29,2026-10-13,2,200,30,25,yes,in trial,,",
)


class LoadTest(unittest.TestCase):
    def test_types_and_status(self):
        a1 = FIXTURE[0]
        self.assertEqual(a1.signup, date(2026, 6, 1))
        self.assertEqual((a1.groomers, a1.clients_entered), (3, 300))
        self.assertTrue(a1.reminders_on and a1.finished and a1.converted and a1.client_list_in)
        self.assertEqual(FIXTURE[3].exit_survey, "Couldn't block my lunch, people booked over it")
        self.assertFalse(FIXTURE[5].finished)

    def test_unknown_status_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "Z1"):
            export("Z1,X,Y,2026-06-01,2026-06-15,1,0,0,0,no,maybe,,")


class ThemeTest(unittest.TestCase):
    def theme(self, answer):
        found = tr.theme_of(answer)
        return found and found[0]

    def test_every_answer_in_the_oct_1_export(self):
        cases = {
            "Couldn't block my lunch, people booked over it": "time_off",
            "Typing in all my clients took too long": "setup",
            "Too much to enter by hand": "setup",
            "Never got my client list in, so I didn't use it": "setup",
            "Setup was more work than I had time for in two weeks": "setup",
            "Older clients won't book online": "offline_clients",
            "My clients just call or text me": "offline_clients",
            "$29 a month is a lot for just me": "price",
            "Big dogs needed two appointments": "big_dogs",
        }
        for answer, key in cases.items():
            with self.subTest(answer):
                self.assertEqual(self.theme(answer), key)

    def test_blank_and_unknown(self):
        self.assertIsNone(tr.theme_of("  "))
        self.assertEqual(self.theme("We moved to another town"), "other")


class FisherTest(unittest.TestCase):
    def test_known_values(self):
        # The tea-tasting table: p = 0.4857 two-sided.
        self.assertTrue(isclose(tr.fisher_exact(3, 1, 1, 3), 0.4857, abs_tol=1e-4))
        # Perfect separation of 5 vs 5: p = 2 / C(10, 5).
        self.assertTrue(isclose(tr.fisher_exact(5, 0, 0, 5), 2 / 252))
        self.assertEqual(tr.fisher_exact(1, 1, 1, 1), 1.0)


class RiskTest(unittest.TestCase):
    def test_solo_with_no_clients_and_no_bookings(self):
        self.assertEqual(tr.risks(FIXTURE[5]), [
            "client list not in (0 entered)", "one groomer", "no online bookings yet"])

    def test_salon_that_looks_like_the_payers(self):
        self.assertEqual(tr.risks(FIXTURE[6]), [])


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.md = tr.render(FIXTURE, date(2026, 10, 12))

    def test_headline(self):
        self.assertIn("7 trials: 5 finished, 2 still in trial", self.md)
        self.assertIn("Finished trials that paid: **2/5 (40%)**", self.md)

    def test_segments(self):
        self.assertIn("| Client list | 50+ clients entered | 1/2 (50%) | under 50 entered | 1/3 (33%) |", self.md)
        self.assertIn("| 1 groomer | 0/0 (–) | 1/3 (33%) |", self.md)

    def test_themes_and_blank_answers(self):
        self.assertIn("3 finished trials did not pay; 2 answered the exit survey, 1 left it blank", self.md)
        self.assertIn("| Setup: getting the client list in | 1 | 1 of 1 |", self.md)
        self.assertNotIn("Big dogs", self.md)

    def test_cells_escape_pipes_and_dollars(self):
        md = tr.render(export("D1,A|B,Y,2026-06-01,2026-06-15,1,0,0,0,no,no,,$29 is a lot"),
                       date(2026, 10, 1))
        self.assertIn("“\\$29 is a lot”", md)
        self.assertNotIn("A|B", tr.table(["x"], [["A|B"]])[2])

    def test_non_payers_with_client_list(self):
        self.assertIn("| Left Lunch (A4) | Salem | 2 | 120 | 20 / 30 | on |", self.md)

    def test_in_trial_days_left(self):
        self.assertIn("| Still Here (B1) | Tacoma | 2026-10-12 | ends today |", self.md)
        self.assertIn("| Doing Fine (B2) | Tacoma | 2026-10-13 | 1 day left |", self.md)
        self.assertIn("ended 2 days ago", tr.render(FIXTURE, date(2026, 10, 15)))
        self.assertIn("| none of these risk signs |", self.md)

    def test_online_split_shown_only_when_it_differs(self):
        # In the fixture A2 has 1 online booking and 2 clients, A4 20 and 120: same split.
        self.assertNotIn("| Clients booked online |", self.md)
        self.assertIn("are exactly the 2 with 50+ clients entered", self.md)
        odd = export("C1,X,Y,2026-06-01,2026-06-15,1,0,0,12,no,no,,")
        self.assertIn("| Clients booked online |", tr.render(odd, date(2026, 10, 1)))


class RealExportTest(unittest.TestCase):
    """The committed tables.md is exactly what the script makes from the Oct 1 export."""

    def test_tables_md_is_reproducible(self):
        here = Path(__file__).resolve().parent
        export_csv = here.parents[2] / "notes" / "trials.csv"
        if not export_csv.exists():
            self.skipTest("notes/trials.csv not found")
        with export_csv.open(newline="", encoding="utf-8") as f:
            md = tr.render(tr.load(f), date(2026, 10, 8), "`notes/trials.csv`")
        self.assertEqual(md, (here / "tables.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
