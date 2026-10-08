import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from remainderbot import decide, usage
from remainderbot.config import Config

FIX = Path(__file__).parent / "fixtures"


def cfg(**kw) -> Config:
    base = dict(window_hours=4, min_remaining=10, max_run_minutes=180, min_rerun_minutes=60,
                providers=["claude", "codex"], deadline_buffer_minutes=15)
    base.update(kw)
    return Config(**base)


def win(used, resets_at):
    return usage.Window(used_pct=used, resets_at=int(resets_at.timestamp()))


def u(provider, now, weekly_used=50, weekly_in=timedelta(hours=2), fh_used=10, fh_in=timedelta(hours=3)):
    return usage.Usage(provider=provider, plan="test",
                       five_hour=win(fh_used, now + fh_in), weekly=win(weekly_used, now + weekly_in))


class ParseFixtures(unittest.TestCase):
    def test_codex_fixture(self):
        got = usage.parse_codex(json.loads((FIX / "codex_ratelimits.json").read_text()))
        self.assertEqual(got.provider, "codex")
        self.assertEqual(got.plan, "plus")
        self.assertEqual(got.five_hour, usage.Window(3.0, 1789265015))
        self.assertEqual(got.weekly, usage.Window(1.0, 1789832305))
        self.assertEqual(got.weekly.remaining_pct, 99.0)

    def test_claude_fixture(self):
        got = usage.parse_claude(json.loads((FIX / "claude_usage.json").read_text()))
        self.assertEqual(got.provider, "claude")
        self.assertEqual(got.five_hour.used_pct, 12.5)
        self.assertEqual(got.weekly.used_pct, 58)
        self.assertEqual(got.weekly.resets_at, int(datetime(2026, 9, 13, 1, 30, tzinfo=timezone.utc).timestamp()))

    def test_claude_bad_shape(self):
        with self.assertRaises(usage.UsageError):
            usage.parse_claude({"five_hour": {}})

    def test_roundtrip(self):
        got = usage.parse_codex(json.loads((FIX / "codex_ratelimits.json").read_text()))
        self.assertEqual(usage.Usage.from_dict(got.to_dict()), got)


class Rule(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

    def test_fires_inside_window_with_quota(self):
        d, reasons = decide.evaluate({"codex": u("codex", self.now)}, {}, cfg(providers=["codex"]), self.now)
        self.assertIsNotNone(d)
        self.assertEqual(d.provider, "codex")
        self.assertEqual(d.size, "large")  # 50% left
        # deadline = min(reset in 2h, now+180m) - 15m = now + 1h45
        self.assertEqual(d.deadline_utc, self.now + timedelta(hours=1, minutes=45))
        self.assertIn("eligible", reasons[0])

    def test_outside_window(self):
        d, reasons = decide.evaluate({"codex": u("codex", self.now, weekly_in=timedelta(hours=5))}, {},
                                     cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("window", reasons[0])

    def test_not_enough_weekly(self):
        d, reasons = decide.evaluate({"codex": u("codex", self.now, weekly_used=95)}, {},
                                     cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("weekly left", reasons[0])

    def test_five_hour_gate(self):
        d, reasons = decide.evaluate({"codex": u("codex", self.now, fh_used=95)}, {},
                                     cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("5h window", reasons[0])

    def test_unknown_usage_skips(self):
        d, reasons = decide.evaluate({"codex": usage.UsageError("codex: HTTP 429")}, {},
                                     cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("unknown", reasons[0])

    def test_missing_provider_is_unknown(self):
        d, reasons = decide.evaluate({}, {}, cfg(providers=["claude"]), self.now)
        self.assertIsNone(d)
        self.assertIn("unknown", reasons[0])

    def test_claim_blocks_until_outcome_known(self):
        us = {"codex": u("codex", self.now)}
        state = decide.claim({}, "codex", us["codex"].weekly.resets_at, "20260912-1200-codex")
        self.assertEqual(state["codex"]["last_outcome"], "running")
        d, reasons = decide.evaluate(us, state, cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("still marked running", reasons[0])
        # next period: a new resets_at means a fresh claim
        later = self.now + timedelta(days=7)
        d, _ = decide.evaluate({"codex": u("codex", later)}, state, cfg(providers=["codex"]), later)
        self.assertIsNotNone(d)

    def test_failed_outcomes_block_rerun(self):
        us = {"codex": u("codex", self.now)}
        for outcome in ("timeout", "quota", "crashed", "abandoned"):
            state = decide.record_outcome({}, "codex", us["codex"].weekly.resets_at, "r1", outcome)
            d, reasons = decide.evaluate(us, state, cfg(providers=["codex"]), self.now)
            self.assertIsNone(d, outcome)
            self.assertIn(f"ended {outcome}", reasons[0])

    def test_done_allows_rerun_while_quota_and_time_remain(self):
        us = {"codex": u("codex", self.now)}  # 50% left, reset in 2h -> 1h45 to the deadline
        state = decide.claim({}, "codex", us["codex"].weekly.resets_at, "r1")
        state = decide.record_outcome(state, "codex", us["codex"].weekly.resets_at, "r1", "done")
        d, reasons = decide.evaluate(us, state, cfg(providers=["codex"]), self.now)
        self.assertIsNotNone(d)
        self.assertIn("eligible", reasons[0])
        # quota is still the gate: a done run that left too little quota does not rerun
        d, reasons = decide.evaluate({"codex": u("codex", self.now, weekly_used=95)}, state,
                                     cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("weekly left", reasons[0])
        # and a second claim counts runs
        state = decide.claim(state, "codex", us["codex"].weekly.resets_at, "r2")
        self.assertEqual(state["codex"]["runs"], 2)
        self.assertEqual(state["codex"]["last_outcome"], "running")

    def test_done_but_too_little_time_left(self):
        us = {"codex": u("codex", self.now, weekly_in=timedelta(minutes=70))}  # 55 min to deadline
        state = decide.record_outcome({}, "codex", us["codex"].weekly.resets_at, "r1", "done")
        d, reasons = decide.evaluate(us, state, cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("not rerunning", reasons[0])
        d, _ = decide.evaluate(us, state, cfg(providers=["codex"], min_rerun_minutes=30), self.now)
        self.assertIsNotNone(d)

    def test_unknown_outcome_rejected(self):
        with self.assertRaises(ValueError):
            decide.record_outcome({}, "codex", 1, "r1", "partial")

    def test_both_eligible_picks_more_quota(self):
        us = {"claude": u("claude", self.now, weekly_used=30), "codex": u("codex", self.now, weekly_used=60)}
        d, reasons = decide.evaluate(us, {}, cfg(), self.now)
        self.assertEqual(d.provider, "claude")
        self.assertEqual(d.size, "large")
        self.assertIn("both eligible", reasons[-1])

    def test_sizes(self):
        for used, size in ((90, "small"), (81, "small"), (80, "medium"), (75, "medium"), (70, "medium"), (69, "large"), (0, "large")):
            d, _ = decide.evaluate({"codex": u("codex", self.now, weekly_used=used)}, {}, cfg(providers=["codex"]), self.now)
            self.assertEqual(d.size, size, used)

    def test_deadline_capped_by_max_run(self):
        d, _ = decide.evaluate({"codex": u("codex", self.now, weekly_in=timedelta(hours=3, minutes=59))}, {},
                               cfg(providers=["codex"]), self.now)
        self.assertEqual(d.deadline_utc, self.now + timedelta(minutes=165))

    def test_deadline_too_close(self):
        d, reasons = decide.evaluate({"codex": u("codex", self.now, weekly_in=timedelta(minutes=20))}, {},
                                     cfg(providers=["codex"]), self.now)
        self.assertIsNone(d)
        self.assertIn("too close", reasons[0])

    def test_always_fire_thresholds(self):
        """Thresholds set to always fire, as in build-order step 1."""
        c = cfg(providers=["codex"], window_hours=24 * 8, min_remaining=0)
        d, _ = decide.evaluate({"codex": u("codex", self.now, weekly_used=99, weekly_in=timedelta(days=6))}, {}, c, self.now)
        self.assertIsNotNone(d)
        self.assertEqual(d.size, "small")


class State(unittest.TestCase):
    def test_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            self.assertEqual(decide.load_state(p), {})
            decide.save_state(p, decide.claim({}, "claude", 123, "id1"))
            self.assertEqual(decide.load_state(p), {"claude": {"last_reset_seen": 123, "runs": 1,
                                                               "last_run_id": "id1", "last_outcome": "running"}})
            decide.save_state(p, decide.record_outcome(decide.load_state(p), "claude", 123, "id1", "done"))
            self.assertEqual(decide.load_state(p)["claude"]["last_outcome"], "done")
            p.write_text("not json")
            self.assertEqual(decide.load_state(p), {})


if __name__ == "__main__":
    unittest.main()
