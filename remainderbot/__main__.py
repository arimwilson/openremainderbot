"""CLI: tick | usage | snapshot | decide | run | sync-inbox | doctor (DESIGN.md 6.2)."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import decide as decide_mod
from . import doctor as doctor_mod
from . import inbox as inbox_mod
from . import origin as origin_mod
from . import publish as publish_mod
from . import run as run_mod
from . import snapshot as snapshot_mod
from . import sources as sources_mod
from . import usage as usage_mod
from .config import PACKAGE_DIR, Config

# set in the environment of a tick that restarted itself after a pull, so it restarts once
REEXEC_ENV = "REMAINDERBOT_REEXEC"


def log(msg: str) -> None:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    for line in str(msg).splitlines() or [""]:
        print(f"{ts} {line}", flush=True)


# --- subcommands --------------------------------------------------------------

def cmd_usage(config: Config, args) -> int:
    usages = usage_mod.read_all(config.providers)
    out = {p: (u.to_dict() if isinstance(u, usage_mod.Usage) else {"error": str(u)})
           for p, u in usages.items()}
    print(json.dumps(out, indent=2))
    return 0 if all(isinstance(u, usage_mod.Usage) for u in usages.values()) else 1


def cmd_snapshot(config: Config, args) -> int:
    try:
        status = snapshot_mod.refresh(config, log, only=args.source)
    except sources_mod.ConfigError as e:
        log(str(e))
        return 2
    return 0 if all(s == "ok" for s in status.values()) else 1


def cmd_decide(config: Config, args) -> int:
    usages = usage_mod.read_all(config.providers)
    state = decide_mod.load_state(config.state_path)
    decision, reasons = decide_mod.evaluate(usages, state, config)
    for r in reasons:
        log(r)
    if decision:
        log(f"decision: {json.dumps(decision.to_dict())}")
        if not args.dry_run:
            decide_mod.save_state(config.state_path, decide_mod.claim(state, decision.provider, decision.weekly_resets_at))
            log("state.json: period claimed")
    else:
        log("skip: no provider eligible")
    return 0


def cmd_run(config: Config, args) -> int:
    """Exercise the whole agent path with an explicit provider, deadline, and size."""
    now = datetime.now(tz=timezone.utc)
    deadline = now + timedelta(minutes=args.deadline_minutes)
    decision = decide_mod.Decision(
        provider=args.provider, deadline_utc=deadline.replace(microsecond=0), size=args.size,
        weekly_resets_at=int((deadline + timedelta(minutes=config.deadline_buffer_minutes)).timestamp()),
        weekly_remaining_pct=-1, five_hour_remaining_pct=-1,
    )
    log(f"run: {json.dumps(decision.to_dict())}")
    result = run_mod.execute(decision, config, log)
    log(f"run {result.id}: branch {result.branch}, outcome={result.outcome}, finalized={result.finalized}, "
        f"exit={result.exit_code}, timed_out={result.timed_out}, readme={result.readme_exists}")
    if args.publish:
        url = publish_mod.pr(result.run_dir, config, log)
        return 0 if url else 1
    return 0 if result.readme_exists else 1


def cmd_sync_inbox(config: Config, args) -> int:
    inbox_mod.sync(config, log)
    return 0


def cmd_doctor(config: Config, args) -> int:
    return doctor_mod.doctor(config)


def cmd_tick(config: Config, args) -> int:
    config.lock_path.touch(exist_ok=True)
    lock = open(config.lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("skip: previous tick still running")
        return 0
    try:
        return _tick(config, args)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def changed_code(config: Config, since: str, package_dir: Path) -> list[str]:
    """Files under the package (code or prompts) that differ between `since` and HEAD. Empty
    when the package does not live in REPO_DIR: pulling that repo cannot change the code."""
    try:
        rel = package_dir.resolve().relative_to(config.repo_dir.resolve())
    except ValueError:
        return []
    return run_mod.git(config, "diff", "--name-only", since, "HEAD", "--", str(rel)).split()


def _restart_if_code_changed(config: Config, started_at: str) -> None:
    """Prompts are read from disk when a run starts, but this process imported its modules
    before the pull; a run now could pair new prompts with old code. Start the tick over in
    a fresh interpreter, once."""
    changed = changed_code(config, started_at, PACKAGE_DIR)
    if not changed:
        return
    if os.environ.get(REEXEC_ENV):
        log(f"pull changed the code again after a restart ({len(changed)} files); going on")
        return
    log(f"pull changed {len(changed)} files under {PACKAGE_DIR.name}/; restarting the tick on the new code")
    sys.stdout.flush()
    sys.stderr.flush()
    # the lock file is not inheritable, so exec closes it and the new process takes it again
    os.execve(sys.executable, [sys.executable, "-m", "remainderbot", *sys.argv[1:]],
              {**os.environ, REEXEC_ENV: "1"})


def _tick(config: Config, args) -> int:
    log("tick start")
    # the code this process imported is the checkout as it was before the pull
    started_at = run_mod.git(config, "rev-parse", "HEAD").strip()
    branch = run_mod.current_branch(config)
    if branch != "main":
        log(f"on branch {branch}; returning to main")
        run_mod.git(config, "checkout", "-q", "-f", "main")

    # main must be current before anything is committed to it; a failure here is logged and
    # the tick goes on with the local main
    publish_mod.pull_main(config, log)
    _restart_if_code_changed(config, started_at)

    # nothing is pushed to a public origin, so a run there would spend quota on a PR that
    # can never open; checked before phase 1, which pushes too
    try:
        origin_mod.check(config)
    except origin_mod.PublicRepoError as e:
        log(f"not running: {e}")
        log("tick end")
        return 1

    # phase 1: sync feedback, then finish any publish that failed last time
    try:
        inbox_mod.sync(config, log)
    except Exception as e:  # noqa: BLE001 - never stops the tick
        log(f"inbox sync failed: {e}; using the stale ledger")
    publish_mod.retry_unpublished(config, log)

    # phase 2: refresh the snapshot (gitignored here; run.execute copies it into the run).
    # An invalid sources.toml ends the tick: never run on a half-understood config.
    if not args.no_snapshot:
        try:
            snapshot_mod.refresh(config, log)
        except sources_mod.ConfigError as e:
            log(f"{e}; skipping the snapshot and the run")
            log("tick end")
            return 1

    # phases 3-7, repeated while runs keep hitting DONE: a run that finishes early must not
    # strand the rest of the quota until the next hourly tick. The rule itself ends the
    # loop (no provider eligible, too little time left for a rerun).
    while True:
        # phase 3: usage + decide
        usages = usage_mod.read_all(config.providers)
        log("usage: " + run_mod.usage_summary(usages))
        state = decide_mod.load_state(config.state_path)
        decision, reasons = decide_mod.evaluate(usages, state, config)
        for r in reasons:
            log(r)
        if decision is None:
            log("skip: no provider eligible")
            break
        log(f"decision: {json.dumps(decision.to_dict())}")
        if config.run_disabled:
            log("RUN_DISABLED=1: would run now; not claiming the period")
            break

        decide_mod.save_state(config.state_path, decide_mod.claim(state, decision.provider, decision.weekly_resets_at))
        run_mod.git(config, "add", str(config.state_path))
        run_mod.git(config, "commit", "-q", "-m", f"tick: claim {decision.provider} period {decision.weekly_resets_at}")
        # the claim is committed before the run so that a tick which dies mid-run leaves
        # last_outcome = "running" behind, which blocks a retry this period

        # phases 4-6: the agent
        result = run_mod.execute(decision, config, log, usage_before=usages)
        log(f"run {result.id}: outcome={result.outcome} finalized={result.finalized} readme={result.readme_exists}")
        state = decide_mod.load_state(config.state_path)
        decide_mod.save_state(config.state_path, decide_mod.record_outcome(
            state, decision.provider, decision.weekly_resets_at, result.id, result.outcome))
        run_mod.git(config, "add", str(config.state_path))
        run_mod.git(config, "commit", "-q", "-m", f"tick: {decision.provider} run {result.id} ended {result.outcome}")

        # phase 7: publish; on failure the run is remembered in state.json and retried next tick
        url = publish_mod.pr(result.run_dir, config, log)
        if url is None:
            log(f"publish: failed; branch {result.branch} is committed locally and will be retried")
            break
        if result.outcome != "done":
            break
        log(f"run {result.id} hit DONE; re-evaluating for another run this tick")
    log("tick end")
    return 0


# --- main ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="remainderbot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("usage", help="print normalized usage for each provider")
    p = sub.add_parser("snapshot", help="refresh goals/snapshot/ (gitignored)")
    p.add_argument("--source", action="append", metavar="NAME",
                   help="refresh only this source, leaving the other files alone (repeatable)")
    p = sub.add_parser("decide", help="evaluate the rule against live usage")
    p.add_argument("--dry-run", action="store_true", help="do not claim the period in state.json")
    p = sub.add_parser("run", help="execute the agent path with an explicit budget")
    p.add_argument("--provider", required=True, choices=["claude", "codex"])
    p.add_argument("--deadline-minutes", type=int, required=True)
    p.add_argument("--size", required=True, choices=["small", "medium", "large"])
    p.add_argument("--publish", action="store_true", help="also push, open the PR, and write the INBOX.md row")
    sub.add_parser("sync-inbox", help="copy PR state and last comments into INBOX.md")
    p = sub.add_parser("tick", help="one cron tick: sync, snapshot, decide, run, publish")
    p.add_argument("--no-snapshot", action="store_true")
    sub.add_parser("doctor", help="check that this instance is ready to run; nonzero exit on any failure")
    args = ap.parse_args(argv)
    config = Config.from_env()
    return {
        "usage": cmd_usage, "snapshot": cmd_snapshot, "decide": cmd_decide,
        "run": cmd_run, "sync-inbox": cmd_sync_inbox, "tick": cmd_tick,
        "doctor": cmd_doctor,
    }[args.cmd](config, args)


if __name__ == "__main__":
    sys.exit(main())
