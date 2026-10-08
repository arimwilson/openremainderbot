"""Execute one run: branch, render prompt, launch the CLI under a timeout, detect DONE,
finalize if needed, commit (DESIGN.md 4.1, 4.4)."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import sources as sources_mod
from . import usage as usage_mod
from .config import EFFORT_BY_SIZE, FINALIZE_EFFORT, Config
from .decide import Decision

MIN_TIMEOUT_S = 60.0  # never hand the CLI less than this, whatever the arithmetic says
_RATE_LIMIT_RE = re.compile(r"rate.?limit|usage limit|429|quota|out of extra usage|limit reached", re.I)


@dataclass
class RunResult:
    id: str
    branch: str
    run_dir: Path
    done: bool
    finalized: bool
    exit_code: int | None
    timed_out: bool
    readme_exists: bool
    quota_wall: bool = False

    @property
    def outcome(self) -> str:
        """One of decide.OUTCOMES; only "done" lets the period run again."""
        if self.done:
            return "done"
        if self.quota_wall:
            return "quota"
        if self.timed_out:
            return "timeout"
        if self.exit_code not in (0, None):
            return "crashed"
        return "abandoned"


# --- helpers ------------------------------------------------------------------

def git(config: Config, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(config.repo_dir), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def current_branch(config: Config) -> str:
    return git(config, "rev-parse", "--abbrev-ref", "HEAD").strip()


def render(template: str, mapping: dict[str, str]) -> str:
    """Substitute `{key}` for the given keys only; other braces are left alone."""
    for k, v in mapping.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def _sources_by_file(config: Config) -> dict[str, sources_mod.Source]:
    """sources.toml by snapshot file name, in its order; empty if it does not load (it may
    not, on a --no-snapshot run)."""
    try:
        return {s.filename: s for s in sources_mod.load(config)}
    except sources_mod.ConfigError:
        return {}


def _snapshot_files(snapshot_dir: Path) -> dict[str, Path]:
    return {p.name: p for p in snapshot_dir.glob("*.md")}


def _in_order(srcs: dict, files: dict) -> list[str]:
    """The snapshot's files in sources.toml order, then the ones it does not name, sorted."""
    return [f for f in srcs if f in files] + sorted(f for f in files if f not in srcs)


def sources_block(config: Config, snapshot_dir: Path) -> str:
    """The worker prompt's list of snapshot files, nested under its step 2: one line per
    file in `snapshot_dir`, in sources.toml order, with its description and whether it is
    private or stale. Files sources.toml does not name are listed after the others,
    without a description and as private (see private_sources)."""
    srcs = _sources_by_file(config)
    files = _snapshot_files(snapshot_dir)
    lines = []
    for name in _in_order(srcs, files):
        src = srcs.get(name)
        line = f"   - `{name}`"
        if src is None:
            line += " (private: not in sources.toml)"
        elif src.private:
            line += " (private)"
        if src:
            line += f" — {src.description.rstrip('.')}"
        with open(files[name]) as f:
            if f.readline().startswith("stale: "):
                line += ". Stale: its last refresh failed, so this is older content; its first line says why"
        lines.append(line)
    return "\n".join(lines) if lines else "   - (none: the snapshot is empty)"


def recheck_rows(config: Config, snapshot_dir: Path) -> str:
    """Rows appended to the worker prompt's reality-check table: each source in the
    snapshot with its `recheck` hint (its own, or its adapter's), in sources.toml order."""
    files = _snapshot_files(snapshot_dir)
    rows = []
    for name, src in _sources_by_file(config).items():
        if name in files and src.recheck.strip():
            hint = " ".join(src.recheck.split()).replace("|", "\\|")
            rows.append(f"| An item from `{name}` | {hint} |")
    return "\n".join(rows)


def private_sources(config: Config, snapshot_dir: Path) -> str:
    """The snapshot files the worker prompt's privacy rule names: "`a.md`", "`a.md` and
    `b.md`", or "none". That is the files of sources marked `private`, and every file
    sources.toml does not describe, since nothing says it is safe to publish: a removed or
    renamed source's leftover on a --no-snapshot run, or every file when sources.toml
    does not load."""
    srcs = _sources_by_file(config)
    files = _snapshot_files(snapshot_dir)
    names = [f"`{name}`" for name in _in_order(srcs, files) if name not in srcs or srcs[name].private]
    if len(names) > 2:
        return ", ".join(names[:-1]) + ", and " + names[-1]
    return " and ".join(names) or "none"


def make_id(provider: str, now: datetime | None = None) -> str:
    now = now or datetime.now(tz=timezone.utc)
    return f"{now:%Y%m%d-%H%M}-{provider}"


def usage_summary(usages: dict) -> str:
    parts = []
    for p, u in sorted(usages.items()):
        if isinstance(u, usage_mod.Usage):
            parts.append(f"{p} 5h {u.five_hour.used_pct:.0f}% / weekly {u.weekly.used_pct:.0f}% used")
        else:
            parts.append(f"{p} unknown")
    return "; ".join(parts) or "unknown"


# gh checks out the run branch by PR (number, url or branch name all work), so the run
# directory is present whether or not the PR has merged; no repo path is baked in.
_CHAT_PROMPT = ("This is remainderbot run {id}. Read runs/{id}/README.md, prompt.md and run.json, "
                "then the log under runs/{id}/log/ if it is there, and take my questions.")


def chat_command(provider: str, run_id: str, model: str, effort: str) -> str:
    """One shell line that opens an interactive session on the same harness and model as the
    run, checked out on the run's PR branch and pointed at the run record (DESIGN.md 5)."""
    prompt = _CHAT_PROMPT.format(id=run_id)
    if provider == "claude":
        cmd = ["claude", "--model", model, "--effort", effort]
    elif provider == "codex":
        cmd = ["codex", "-m", model, "-c", f'model_reasoning_effort="{effort}"']
    else:
        raise ValueError(f"unknown provider {provider}")
    return f"gh pr checkout run/{run_id} && {shlex.join(cmd)} {shlex.quote(prompt)}"


def chat_section(config: Config, provider: str, run_id: str, effort: str) -> str:
    """The README's closing section (DESIGN.md 5), appended by the wrapper after the agent."""
    model = config.claude_model if provider == "claude" else config.codex_model
    return ("\n## Chat about this run\nSame harness and model, from any clone of the repo:\n\n"
            f"```\n{chat_command(provider, run_id, model, effort)}\n```\n")


def agent_command(config: Config, provider: str, effort: str, run_id: str) -> list[str]:
    """The exact CLI invocation, fully visible in the run log (4.4)."""
    if provider == "claude":
        cmd = ["claude", "-p", "--model", config.claude_model, "--effort", effort,
               "--output-format", "stream-json", "--verbose"]
        if config.claude_fallback_model:
            cmd += ["--fallback-model", config.claude_fallback_model]
        if config.agent_full_access:
            cmd.append("--dangerously-skip-permissions")
        else:
            cmd += ["--permission-mode", "acceptEdits"]
        return cmd
    if provider == "codex":
        cmd = ["codex", "exec", "-m", config.codex_model,
               "-c", f'model_reasoning_effort="{effort}"',
               "-c", 'approval_policy="never"',
               "-C", str(config.repo_dir), "--json",
               "-o", str(config.runs_dir / run_id / "log" / "last.txt")]
        if config.agent_full_access:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            cmd += ["-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true"]
        cmd.append("-")
        return cmd
    raise ValueError(f"unknown provider {provider}")


def launch(cmd: list[str], prompt: str, log_path: Path, cwd: Path, timeout_s: float,
           log=print) -> tuple[int | None, bool]:
    """Run the CLI with the prompt on stdin, stdout+stderr to log_path. Returns (exit code, timed out)."""
    log(f"launch ({int(timeout_s)}s): {shlex.join(cmd)}")
    with open(log_path, "ab") as out:
        out.write(f"# {datetime.now(tz=timezone.utc).isoformat()} {shlex.join(cmd)}\n".encode())
        out.flush()
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT,
                                cwd=str(cwd), start_new_session=True)
        timed_out = False
        try:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            log("deadline reached; killing the process group")
            _kill_group(proc)
    return (None if timed_out else proc.returncode), timed_out


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def hit_quota_wall(log_path: Path) -> bool:
    """True if the last few log events look like a rate-limit error."""
    if not log_path.exists():
        return False
    with open(log_path, "rb") as f:
        f.seek(max(0, log_path.stat().st_size - 8000))
        tail = f.read().decode("utf-8", errors="replace")
    lines = [l for l in tail.splitlines() if l.strip()][-5:]
    return any(_RATE_LIMIT_RE.search(l) and re.search(r"error", l, re.I) for l in lines)


def _seconds_until(deadline: datetime) -> float:
    return (deadline - datetime.now(tz=timezone.utc)).total_seconds()


# --- execute ------------------------------------------------------------------

def execute(decision: Decision, config: Config, log=print,
            usage_before: dict | None = None, run_id: str | None = None) -> RunResult:
    run_id = run_id or make_id(decision.provider)
    branch = f"run/{run_id}"
    run_dir = config.runs_dir / run_id
    log_dir = run_dir / "log"
    provider = decision.provider
    started = datetime.now(tz=timezone.utc)

    if usage_before is None:
        usage_before = usage_mod.read_all(config.providers)
    before_str = usage_summary(usage_before)

    # 1. branch + directory
    if git(config, "status", "--porcelain", "--untracked-files=no").strip():
        raise RuntimeError("repo has uncommitted changes; refusing to start a run")
    git(config, "checkout", "-q", "-b", branch)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        # the snapshot the agent reads is copied into the run so the PR shows exactly what
        # it saw; goals/snapshot/ itself is gitignored on main
        run_snapshot = run_dir / "snapshot"
        if config.snapshot_dir.is_dir():
            shutil.copytree(config.snapshot_dir, run_snapshot, dirs_exist_ok=True)
        else:
            run_snapshot.mkdir(exist_ok=True)

        # 2. render the prompt and keep it in the record
        mapping = {
            "id": run_id, "provider": provider, "deadline_utc": decision.deadline_str,
            "size": decision.size, "quota_before": before_str,
            "goals_path": _rel(config, config.goals_path),
            "snapshot_dir": _rel(config, run_snapshot),
            "sources": sources_block(config, run_snapshot),
            "recheck_rows": recheck_rows(config, run_snapshot),
            "private_sources": private_sources(config, run_snapshot),
            "inbox_path": _rel(config, config.inbox_path),
            "finalize_minutes": str(config.finalize_minutes),
        }
        prompt = render((config.prompts_dir / "worker.md").read_text(), mapping)
        (run_dir / "prompt.md").write_text(prompt)
        (run_dir / "run.json").write_text(json.dumps({
            "id": run_id, "provider": provider, "size": decision.size,
            "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "deadline_utc": decision.deadline_str, "usage_before": _usage_json(usage_before),
        }, indent=2) + "\n")
        git(config, "add", str(run_dir / "prompt.md"), str(run_dir / "run.json"), str(run_snapshot))
        git(config, "commit", "-q", "-m", f"run {run_id}: start ({provider}, {decision.size})")

        # 3. main run under the deadline
        effort = EFFORT_BY_SIZE[decision.size]
        cmd = agent_command(config, provider, effort, run_id)
        timeout_s = max(MIN_TIMEOUT_S, _seconds_until(decision.deadline_utc))
        main_log = log_dir / f"{provider}.jsonl"
        exit_code, timed_out = launch(cmd, prompt, main_log, config.repo_dir, timeout_s, log)
        log(f"main run ended: exit={exit_code} timed_out={timed_out}")

        # 4. DONE?
        done = (run_dir / "DONE").exists()
        finalized = False
        quota_wall = False
        if not done:
            # 5. finalize on a small budget, waiting out a quota wall if that is what stopped us
            quota_wall = hit_quota_wall(main_log)
            if quota_wall:
                wait = min(_seconds_until(_reset_time(decision)), config.deadline_buffer_minutes * 60)
                if wait > 0:
                    log(f"quota wall detected; sleeping {int(wait)}s until the reset")
                    time.sleep(wait)
            fin_deadline = datetime.now(tz=timezone.utc) + timedelta(minutes=config.finalize_minutes)
            fin_mapping = dict(mapping, deadline_utc=fin_deadline.strftime("%Y-%m-%dT%H:%M:%SZ"))
            fin_prompt = render((config.prompts_dir / "finalize.md").read_text(), fin_mapping)
            (run_dir / "finalize-prompt.md").write_text(fin_prompt)
            fin_cmd = agent_command(config, provider, FINALIZE_EFFORT, run_id)
            fin_log = log_dir / f"{provider}-finalize.jsonl"
            launch(fin_cmd, fin_prompt, fin_log, config.repo_dir, config.finalize_minutes * 60, log)
            finalized = True
            log("finalize ended")

        # usage after, appended to the README's Run section and run.json
        usage_after = usage_mod.read_all(config.providers)
        after_str = usage_summary(usage_after)
        readme = run_dir / "README.md"
        if readme.exists():
            with open(readme, "a") as f:
                f.write(f"\nquota before: {before_str}\nquota after: {after_str}\n"
                        f"finished: {'DONE' if done else 'via finalize'}; "
                        f"main run exit={exit_code} timed_out={timed_out}\n")
        else:
            readme.write_text(_placeholder_readme(run_id, provider, decision, before_str, after_str,
                                                  exit_code, timed_out))
            log("no README.md from the agent; wrote an abandoned placeholder")
        with open(readme, "a") as f:
            f.write(chat_section(config, provider, run_id, effort))
        info = json.loads((run_dir / "run.json").read_text())
        info.update({
            "ended_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "done": done, "finalized": finalized, "exit_code": exit_code, "timed_out": timed_out,
            "quota_wall": quota_wall,
            "usage_after": _usage_json(usage_after), "command": shlex.join(cmd),
        })
        (run_dir / "run.json").write_text(json.dumps(info, indent=2) + "\n")

        # 6. commit whatever is in the run directory (large logs stay out of git)
        _ignore_big_logs(log_dir, config.log_max_bytes)
        git(config, "add", "-A", str(run_dir))
        if git(config, "status", "--porcelain", str(run_dir)).strip():
            git(config, "commit", "-q", "-m", f"run {run_id}: {'done' if done else 'finalized'}")
        return RunResult(run_id, branch, run_dir, done, finalized, exit_code, timed_out,
                         readme.exists(), quota_wall)
    finally:
        # before leaving the branch: the run's own .gitignore files vanish with it
        _clean_ignored(config, run_dir, log)
        stray = git(config, "status", "--porcelain", check=False).strip()
        if stray:
            log(f"stray changes outside the run directory are discarded:\n{stray}")
        git(config, "checkout", "-q", "-f", "main", check=False)


def _clean_ignored(config: Config, run_dir: Path, log=print) -> None:
    """Delete the run's gitignored files (node_modules, caches, clones): the branch has everything
    that matters, and left in place they pile up to gigabytes across runs. log/ is kept, since a
    transcript over the size cap is ignored and exists nowhere else."""
    rel = _rel(config, run_dir)
    out = git(config, "clean", "-ffdX", "--", rel, f":(exclude){rel}/log", check=False).strip()
    if out:
        log(f"cleaned ignored files from {rel}:\n{out}")


def _rel(config: Config, p: Path) -> str:
    try:
        return str(p.relative_to(config.repo_dir))
    except ValueError:
        return str(p)


def _reset_time(decision: Decision) -> datetime:
    return datetime.fromtimestamp(decision.weekly_resets_at, tz=timezone.utc)


def _usage_json(usages: dict) -> dict:
    return {p: (u.to_dict() if isinstance(u, usage_mod.Usage) else {"error": str(u)})
            for p, u in usages.items()}


def _ignore_big_logs(log_dir: Path, limit: int) -> None:
    big = [p.name for p in log_dir.iterdir() if p.is_file() and p.stat().st_size > limit]
    if big:
        (log_dir / ".gitignore").write_text("".join(f"{n}\n" for n in big))


def _placeholder_readme(run_id: str, provider: str, decision: Decision, before: str, after: str,
                        exit_code: int | None, timed_out: bool) -> str:
    return (f"# Run {run_id}                                   status: abandoned\n\n"
            f"**Task** — unknown: the agent produced no README.md.\n\n"
            f"## What exists now\n- see `runs/{run_id}/` (PLAN.md if the agent got that far, and log/).\n\n"
            f"## How I verified it\n- nothing verified.\n\n## Your one next step\n"
            f"- nothing; read `runs/{run_id}/log/` to see what happened.\n\n"
            f"## Run\nprovider {provider}, size {decision.size}, deadline {decision.deadline_str}, "
            f"main run exit={exit_code} timed_out={timed_out}, finalize also produced no README.\n"
            f"quota before: {before}\nquota after: {after}\n")
