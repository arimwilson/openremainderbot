"""Turn usage snapshots + state.json into a Decision or a skip reason (DESIGN.md 2.2, 2.3)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config, size_for
from .usage import Usage, UsageError, fmt_reset


@dataclass(frozen=True)
class Decision:
    provider: str
    deadline_utc: datetime
    size: str
    weekly_resets_at: int
    weekly_remaining_pct: float
    five_hour_remaining_pct: float

    @property
    def deadline_str(self) -> str:
        return self.deadline_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "deadline_utc": self.deadline_str,
            "size": self.size,
            "weekly_resets_at": self.weekly_resets_at,
            "weekly_remaining_pct": self.weekly_remaining_pct,
            "five_hour_remaining_pct": self.five_hour_remaining_pct,
        }


# --- state.json ---------------------------------------------------------------

def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text() or "{}")
    except ValueError:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


# outcomes a run can end with; only "done" (the agent wrote DONE) permits another run in
# the same period. "running" is what a claim leaves behind until the run reports back, so
# a tick that dies mid-run also blocks a retry.
OUTCOMES = ("running", "done", "timeout", "quota", "crashed", "abandoned")


def period_entry(state: dict, provider: str, resets_at: int) -> dict | None:
    """The provider's state entry if it belongs to this weekly period, else None."""
    entry = state.get(provider) or {}
    return entry if entry.get("last_reset_seen") == resets_at else None


def runs_in_period(state: dict, provider: str, resets_at: int) -> int:
    entry = period_entry(state, provider, resets_at)
    return int(entry.get("runs", 1)) if entry else 0


def record_outcome(state: dict, provider: str, resets_at: int, run_id: str, outcome: str) -> dict:
    """Record how the run for this period ended (called after run.execute returns)."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    entry = dict(state.get(provider) or {})
    if entry.get("last_reset_seen") != resets_at:
        entry = {"last_reset_seen": resets_at, "runs": 1}
    entry["last_run_id"] = run_id
    entry["last_outcome"] = outcome
    state[provider] = entry
    return state


def claim(state: dict, provider: str, resets_at: int, run_id: str | None = None) -> dict:
    """Record that a run for this provider's current weekly period has been started."""
    entry = dict(state.get(provider) or {})
    if entry.get("last_reset_seen") == resets_at:
        entry["runs"] = int(entry.get("runs", 1)) + 1
    else:
        entry = {"last_reset_seen": resets_at, "runs": 1}
    if run_id:
        entry["last_run_id"] = run_id
    entry["last_outcome"] = "running"
    state[provider] = entry
    return state


# --- the rule -----------------------------------------------------------------

def compute_deadline(now: datetime, weekly_resets_at: int, config: Config) -> datetime:
    reset = datetime.fromtimestamp(weekly_resets_at, tz=timezone.utc)
    cap = now + timedelta(minutes=config.max_run_minutes)
    return min(reset, cap) - timedelta(minutes=config.deadline_buffer_minutes)


def check(provider: str, usage: Usage | UsageError, state: dict, config: Config,
          now: datetime) -> tuple[Decision | None, str]:
    """Evaluate one provider. Returns (decision, reason); reason explains a skip or the pick."""
    if isinstance(usage, UsageError):
        return None, f"{provider}: usage unknown ({usage})"
    u = usage
    hours_to_reset = (u.weekly.resets_at - now.timestamp()) / 3600
    if hours_to_reset > config.window_hours:
        return None, (f"{provider}: weekly reset in {hours_to_reset:.1f}h "
                      f"(> {config.window_hours}h window), {u.weekly.remaining_pct:.0f}% left")
    if hours_to_reset <= 0:
        return None, f"{provider}: weekly reset {fmt_reset(u.weekly.resets_at)} already passed; stale snapshot"
    if u.weekly.remaining_pct < config.min_remaining:
        return None, (f"{provider}: only {u.weekly.remaining_pct:.0f}% weekly left "
                      f"(< {config.min_remaining}%)")
    if u.five_hour.remaining_pct < config.min_remaining:
        return None, (f"{provider}: only {u.five_hour.remaining_pct:.0f}% of the 5h window left "
                      f"(< {config.min_remaining}%); would stall")
    deadline = compute_deadline(now, u.weekly.resets_at, config)
    minutes_left = (deadline - now).total_seconds() / 60
    if minutes_left <= 10:
        return None, f"{provider}: deadline {deadline:%H:%MZ} too close to do anything"
    prior = period_entry(state, provider, u.weekly.resets_at)
    if prior:
        outcome = prior.get("last_outcome", "running")
        last_id = prior.get("last_run_id", "?")
        if outcome == "running":
            return None, (f"{provider}: run {last_id} is still marked running this period "
                          f"(tick died mid-run?); not retrying")
        if outcome != "done":
            return None, (f"{provider}: run {last_id} ended {outcome}; not retrying this period "
                          f"(reset {fmt_reset(u.weekly.resets_at)})")
        if minutes_left < config.min_rerun_minutes:
            return None, (f"{provider}: run {last_id} was done, but only {minutes_left:.0f} min "
                          f"left before the deadline (< {config.min_rerun_minutes}); not rerunning")
    d = Decision(
        provider=provider,
        deadline_utc=deadline,
        size=size_for(u.weekly.remaining_pct),
        weekly_resets_at=u.weekly.resets_at,
        weekly_remaining_pct=u.weekly.remaining_pct,
        five_hour_remaining_pct=u.five_hour.remaining_pct,
    )
    return d, (f"{provider}: eligible, {u.weekly.remaining_pct:.0f}% weekly left, "
               f"reset in {hours_to_reset:.1f}h, size {d.size}, deadline {d.deadline_str}")


def evaluate(usages: dict[str, Usage | UsageError], state: dict, config: Config,
             now: datetime | None = None) -> tuple[Decision | None, list[str]]:
    """Pick at most one provider. If several are eligible, the one with more weekly quota left."""
    now = now or datetime.now(tz=timezone.utc)
    reasons: list[str] = []
    candidates: list[Decision] = []
    for provider in config.providers:
        usage = usages.get(provider, UsageError(f"{provider}: not read"))
        d, reason = check(provider, usage, state, config, now)
        reasons.append(reason)
        if d:
            candidates.append(d)
    if not candidates:
        return None, reasons
    candidates.sort(key=lambda d: d.weekly_remaining_pct, reverse=True)
    if len(candidates) > 1:
        reasons.append(f"both eligible; {candidates[0].provider} has more quota, "
                       f"{candidates[1].provider} is reconsidered next tick")
    return candidates[0], reasons
