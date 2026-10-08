"""Publish one run: push the branch, open the PR with the README as its body, write the
ledger row to INBOX.md on main, record state (DESIGN.md 4.1 step 6, 6.1 phase 7).

The README lives on the run branch; the wrapper is back on main when this runs, so it is
read with `git show`. A failed publish is remembered in state.json ("unpublished") and
retried at the start of the next tick. Nothing is pushed to a public origin (origin.py).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from . import decide as decide_mod
from . import inbox
from . import origin
from .config import Config
from .run import git

_TITLE_RE = re.compile(r"^#\s+(?P<title>.*?)\s*(?:status:\s*(?P<status>[a-z]+))?\s*$")
_TASK_RE = re.compile(r"\*\*Task\*\*\s*[—–-]*\s*(?P<task>.*?)(?:\s+Source:|\s*$)", re.S)


# --- README -------------------------------------------------------------------

def readme_summary(text: str) -> tuple[str, str, str]:
    """(title, status, task sentence) from a README written to the template in DESIGN.md 5."""
    lines = [l for l in text.splitlines() if l.strip()]
    title, status = "untitled run", "unknown"
    if lines:
        m = _TITLE_RE.match(lines[0])
        if m:
            title = m.group("title") or title
            status = m.group("status") or status
        else:
            title = lines[0].lstrip("# ").strip() or title
    task = ""
    for i, line in enumerate(lines):
        if line.lstrip().startswith("**Task**"):
            para = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith("**") or nxt.startswith("#"):
                    break
                para.append(nxt)
            m = _TASK_RE.search(" ".join(para))
            task = m.group("task") if m else ""
            break
    return title.strip(), status.strip().lower(), inbox.truncate(task, inbox.MAX_TASK_CHARS)


def pr_title(title: str, status: str) -> str:
    return title if status in ("complete", "unknown") else f"{title} [{status}]"


# --- git / gh -----------------------------------------------------------------

def _gh(config: Config, *args: str, timeout: float = 120) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True, cwd=str(config.repo_dir), timeout=timeout)
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip().splitlines()
        raise RuntimeError(f"gh {' '.join(args[:2])}: exit {p.returncode}: {err[-1] if err else ''}")
    return p.stdout


def _git_remote(config: Config, what: str, *args: str, log=print) -> bool:
    """A push or pull that may fail (no remote, no network); logged, not fatal."""
    p = subprocess.run(["git", "-C", str(config.repo_dir), *args], capture_output=True, text=True)
    if p.returncode != 0:
        err = _git_error("\n".join((p.stderr, p.stdout)))
        log(f"{what} failed: {err}")
        return False
    return True


def _git_error(output: str) -> str:
    """The line(s) of git's output that say what went wrong. git puts the cause first and
    advice last, so the last line is often noise ("...something valuable there.")."""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    conflicts = [l for l in lines if l.startswith("CONFLICT")]
    if conflicts:
        return "; ".join(conflicts)
    return next((l for l in lines if l.startswith(("fatal:", "error:"))), lines[-1] if lines else "?")


def push(config: Config, ref: str, log=print) -> bool:
    """Every push the bot makes goes through here, so none reaches a public origin."""
    try:
        origin.check(config)
    except origin.PublicRepoError as e:
        log(f"push {ref} refused: {e}")
        return False
    return _git_remote(config, f"push {ref}", "push", "-q", "-u", "origin", ref, log=log)


def _rebase_in_progress(config: Config) -> bool:
    paths = git(config, "rev-parse", "--git-path", "rebase-merge", "--git-path", "rebase-apply").split()
    return any((config.repo_dir / p).is_dir() for p in paths)


def pull_main(config: Config, log=print) -> bool:
    """Bring main up to date before the tick commits to it (the user may have edited GOALS.md).

    A pull that stops on a conflict is aborted, leaving main as it was. A rebase left in
    progress makes every later pull fail before it starts, and the tick's `checkout -f main`
    does not end one: that once kept a server on a stale main for five days.
    """
    if _rebase_in_progress(config):
        # --quit, not --abort: abort would move main back to where it was before that rebase
        git(config, "rebase", "--quit", check=False)
        log("pull main: dropped a rebase left in progress; main is unchanged")
    if _git_remote(config, "pull main", "pull", "-q", "--rebase", "origin", "main", log=log):
        return True
    if _rebase_in_progress(config):
        git(config, "rebase", "--abort", check=False)
        log("pull main: rebase aborted; main is as it was before the pull")
    return False


def commit_on_main(config: Config, paths: list[Path], message: str, log=print) -> None:
    """Commit the given files on main and push it; a failed push is logged, not fatal."""
    git(config, "add", *[str(p) for p in paths])
    if git(config, "status", "--porcelain", "--", *[str(p) for p in paths]).strip():
        git(config, "commit", "-q", "-m", message)
    push(config, "main", log)


def existing_pr(config: Config, branch: str) -> dict | None:
    out = _gh(config, "pr", "list", "--repo", origin.url(config), "--head", branch, "--state", "all",
              "--limit", "1", "--json", "number,url,state")
    prs = json.loads(out or "[]")
    return prs[0] if prs else None


def create_pr(config: Config, branch: str, title: str, body: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        body_path = f.name
    try:
        out = _gh(config, "pr", "create", "--repo", origin.url(config), "--base", "main", "--head", branch,
                  "--title", title, "--body-file", body_path)
    finally:
        Path(body_path).unlink(missing_ok=True)
    urls = [l.strip() for l in out.splitlines() if l.strip().startswith("http")]
    return urls[-1] if urls else out.strip()


# --- state --------------------------------------------------------------------

def _mark_unpublished(config: Config, run_id: str, error: str, log=print) -> None:
    state = decide_mod.load_state(config.state_path)
    pending = state.setdefault("unpublished", {})
    pending[run_id] = {"attempts": int(pending.get(run_id, {}).get("attempts", 0)) + 1, "error": error[:200]}
    decide_mod.save_state(config.state_path, state)
    commit_on_main(config, [config.state_path], f"publish {run_id}: failed, will retry", log)


def _mark_published(config: Config, run_id: str, provider: str, url: str) -> None:
    state = decide_mod.load_state(config.state_path)
    state.get("unpublished", {}).pop(run_id, None)
    if not state.get("unpublished"):
        state.pop("unpublished", None)
    entry = dict(state.get(provider) or {})
    entry.update({"last_run_id": run_id, "last_pr": url})
    state[provider] = entry
    decide_mod.save_state(config.state_path, state)


# --- pr -----------------------------------------------------------------------

def pr(run_dir: Path, config: Config, log=print) -> str | None:
    """Push run/<id>, open (or find) its PR, write the INBOX.md row, commit on main.
    Returns the PR URL, or None if the publish failed (it will be retried next tick)."""
    run_id = run_dir.name
    branch = f"run/{run_id}"
    try:
        return _pr(run_id, branch, config, log)
    except Exception as e:  # noqa: BLE001 - the run is committed locally; never lose it
        log(f"publish {run_id} failed: {e}")
        _mark_unpublished(config, run_id, str(e), log)
        return None


def _pr(run_id: str, branch: str, config: Config, log=print) -> str:
    rel = f"runs/{run_id}"
    readme = git(config, "show", f"{branch}:{rel}/README.md")
    try:
        provider = json.loads(git(config, "show", f"{branch}:{rel}/run.json")).get("provider")
    except RuntimeError:
        provider = None
    provider = provider or run_id.rsplit("-", 1)[-1]
    title, status, task = readme_summary(readme)
    # a refusal is the reason recorded under "unpublished", not a failed push of the branch
    origin.check(config)

    # main first so the PR diff is only the run, then the branch, then the PR
    push(config, "main", log)
    if not push(config, branch, log):
        raise RuntimeError(f"could not push {branch}")
    found = existing_pr(config, branch)
    if found:
        url = found["url"]
        log(f"publish {run_id}: PR already exists: {url}")
    else:
        url = create_pr(config, branch, pr_title(title, status), readme)
        log(f"publish {run_id}: opened {url}")

    preamble, rows = inbox.load(config.inbox_path)
    row_status = "abandoned" if status == "abandoned" else "needs-review"
    row = inbox.Row(run_id, provider, task or title, row_status, "")
    existing = next((r for r in rows if r.id == run_id), None)
    if existing:  # a retry after the row was already written: keep any verdict already synced
        row = inbox.Row(run_id, existing.provider, existing.task or row.task, existing.status, existing.note)
    config.inbox_path.write_text(inbox.render(preamble, inbox.upsert(rows, row)))
    _mark_published(config, run_id, provider, url)
    commit_on_main(config, [config.inbox_path, config.state_path], f"publish {run_id}: {url}", log)
    return url


def retry_unpublished(config: Config, log=print) -> None:
    """Publish runs whose earlier publish failed (state.json 'unpublished')."""
    pending = decide_mod.load_state(config.state_path).get("unpublished") or {}
    for run_id in sorted(pending):
        log(f"publish {run_id}: retrying (attempt {pending[run_id].get('attempts', 0) + 1})")
        pr(config.runs_dir / run_id, config, log)
