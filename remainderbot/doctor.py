"""doctor: whether this instance is ready to run (README.md, "Try it").

One line per check of what a first tick depends on; exits nonzero if any check fails.
Without it, a missing login or a public origin shows up an hour later as one line in the
cron log.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import origin
from . import sources as sources_mod
from . import usage as usage_mod
from .config import PACKAGE_DIR, Config
from .run import git

EXAMPLES_DIR = PACKAGE_DIR.parent
GOALS_EXAMPLE = EXAMPLES_DIR / "GOALS.example.md"
SOURCES_EXAMPLE = EXAMPLES_DIR / "sources.example.toml"
UPSTREAM_URL = "https://github.com/arimwilson/openremainderbot"
# doctor's dry-run push names a branch that is never created
PROBE_REF = "refs/heads/remainderbot-doctor-check"
LOGIN_HINT = {"claude": "run `claude` and log in with your subscription", "codex": "run `codex login`"}

OK, WARN, FAIL, INFO = "ok", "warn", "FAIL", "info"


def _rel(config: Config, path: Path) -> str:
    return str(path.relative_to(config.repo_dir)) if path.is_relative_to(config.repo_dir) else str(path)


def doctor(config: Config, out=print) -> int:
    failed = False

    def report(status: str, what: str, detail: str) -> None:
        nonlocal failed
        out(f"{status:<4}  {what}: {detail}")
        failed = failed or status == FAIL

    for check in (_python, _tools, _providers, _sources, _goals, _checkout, _origin, _upstream):
        try:
            for status, what, detail in check(config):
                report(status, what, detail)
        except Exception as e:  # noqa: BLE001 - one broken check must not hide the others
            report(FAIL, check.__name__.strip("_"), f"the check itself failed: {type(e).__name__}: {e}")
    return 1 if failed else 0


def _run(cmd: list[str], timeout: float = 60) -> tuple[int, str]:
    """(exit code, stdout and stderr). git and ssh never prompt: cron has no terminal."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env=env)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not on PATH"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:.0f}s"
    return p.returncode, "\n".join(s for s in (p.stdout.strip(), p.stderr.strip()) if s)


def _last(output: str) -> str:
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    return lines[-1] if lines else "no output"


def _same(path: Path, example: Path) -> bool:
    return path.exists() and example.exists() and path.read_bytes() == example.read_bytes()


def _some(names: list[str], limit: int = 3) -> str:
    more = len(names) - limit
    return ", ".join(names[:limit]) + (f", and {more} more" if more > 0 else "")


def _python(config: Config):
    # an older Python never gets here: remainderbot/__init__.py exits first
    yield OK, "python", f"{sys.version.split()[0]} ({sys.executable})"


def _tools(config: Config):
    code, output = _run(["git", "--version"])
    yield (OK, "git", output) if code == 0 else (FAIL, "git", _last(output))
    if shutil.which("gh") is None:
        yield FAIL, "gh", "not on PATH; the bot opens its PRs with it (https://cli.github.com)"
        return
    code, output = _run(["gh", "auth", "status"])
    if code != 0:
        yield FAIL, "gh", f"not logged in ({_last(output)}); run `gh auth login`"
        return
    who = next((l.strip(" ✓-") for l in output.splitlines() if "Logged in to" in l), "logged in")
    yield OK, "gh", who


def _providers(config: Config):
    if not config.providers:
        yield FAIL, "PROVIDERS", "empty; set it to claude, codex, or both"
    for p in config.providers:
        if p not in usage_mod.READERS:
            yield FAIL, p, f"unknown provider; known: {', '.join(usage_mod.READERS)}"
        elif shutil.which(p) is None:
            yield FAIL, p, "not on PATH; install it, or leave it out of PROVIDERS"
        else:
            u = usage_mod.read_all([p])[p]
            if isinstance(u, usage_mod.Usage):
                yield OK, p, (f"quota readable: {u.weekly.remaining_pct:.0f}% of the week left, "
                              f"resets {usage_mod.fmt_reset(u.weekly.resets_at)}")
            else:
                yield FAIL, p, f"cannot read quota ({u}); {LOGIN_HINT.get(p, 'log in')}"


def _sources(config: Config):
    what = config.sources_file
    try:
        srcs = sources_mod.load(config)
    except sources_mod.ConfigError as e:
        hint = f"; copy {SOURCES_EXAMPLE.name} to it" if not config.sources_path.exists() else ""
        yield FAIL, what, f"{e}{hint}"
        return
    if _same(config.sources_path, SOURCES_EXAMPLE):
        yield FAIL, what, "still the example; point it at your own sources"
        return
    enabled = [s for s in srcs if s.enabled]
    if not enabled:
        yield WARN, what, "no enabled sources; runs see only GOALS.md and INBOX.md"
        return
    yield OK, what, f"{len(enabled)} enabled: " + ", ".join(f"{s.name} ({s.type})" for s in enabled)
    gws = [s.name for s in enabled if s.type.startswith("gws-")]
    if gws:
        found = shutil.which("gws")
        yield (OK, "gws", found) if found else (FAIL, "gws", f"not on PATH; {', '.join(gws)} need it")


def _goals(config: Config):
    path, what = config.goals_path, _rel(config, config.goals_path)
    if not path.exists():
        yield FAIL, what, f"missing; copy {GOALS_EXAMPLE.name} to it and write your own"
    elif _same(path, GOALS_EXAMPLE):
        yield FAIL, what, "still the example; write your own priorities, rules, and manual goals"
    else:
        yield OK, what, "written, not the example"


def _checkout(config: Config):
    # the server runs on what was pushed, and `run` starts only on a clean tree
    owned = [p for p in (config.goals_path, config.sources_path, config.inbox_path)
             if p.exists() and p.is_relative_to(config.repo_dir)]
    untracked = [_rel(config, p) for p in owned
                 if not git(config, "ls-files", "--", str(p)).strip()]
    if untracked:
        yield FAIL, "checkout", f"{_some(untracked)} not committed; the server's clone has only what you push"
    dirty = [l[3:] for l in git(config, "status", "--porcelain", "--untracked-files=no").splitlines()]
    if dirty:
        yield FAIL, "checkout", f"uncommitted changes to {_some(dirty)}; `run` refuses to start on a dirty tree"
    if not untracked and not dirty:
        yield OK, "checkout", "clean"


def _origin(config: Config):
    try:
        urls = origin.push_urls(config)
    except RuntimeError:
        yield FAIL, "origin", "no origin remote; push this checkout to a new private GitHub repo"
        return
    # `git push origin` pushes to each of them, so each one gets its own line
    for u in urls:
        try:
            name, vis = origin.visibility(config, u)
        except RuntimeError as e:
            yield FAIL, "origin", f"cannot tell whether {u} is private ({e})"
            continue
        if vis in origin.ALLOWED_VISIBILITY:
            yield OK, "origin", f"{name} is {vis.lower()}"
        elif config.allow_public_repo:
            yield WARN, "origin", (f"{name} is {vis.lower()}, and ALLOW_PUBLIC_REPO=1: every run's snapshot "
                                   f"and agent log will be published there")
        else:
            yield FAIL, "origin", (f"{name} is {vis.lower()}; the bot will not push there. Make it private "
                                   f"(a fork of a public repo cannot be: push a clone to a new private repo), "
                                   f"or set ALLOW_PUBLIC_REPO=1")
    code, output = _run(["git", "-C", str(config.repo_dir), "push", "--dry-run", "-q", "origin", f"HEAD:{PROBE_REF}"])
    yield (OK, "push", "origin accepts pushes") if code == 0 else (FAIL, "push", f"git push --dry-run: {_last(output)}")


def _upstream(config: Config):
    if "upstream" not in git(config, "remote").split():
        yield INFO, "upstream", f"no upstream remote; for engine updates: git remote add upstream {UPSTREAM_URL}"
        return
    code, output = _run(["git", "-C", str(config.repo_dir), "fetch", "-q", "upstream", "main"])
    if code != 0:
        yield WARN, "upstream", f"fetch failed: {_last(output)}"
        return
    behind = int(git(config, "rev-list", "--count", "HEAD..FETCH_HEAD").strip())
    if behind:
        yield INFO, "upstream", f"{behind} commit{'' if behind == 1 else 's'} behind upstream/main; read CHANGELOG.md, then git merge upstream/main"
    else:
        yield OK, "upstream", "up to date with upstream/main"
