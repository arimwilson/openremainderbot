"""Sources on this machine: file (globs of local files) and command (a shell command's stdout)."""
from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

from . import adapter
from ._util import SourceError, glob_re, truncate


# --- file: local files, each under its path -----------------------------------

_MAGIC = re.compile(r"[*?]")


def _globs(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def _check_file(src: dict) -> str | None:
    if not _globs(src["paths"]):
        return "`paths` is empty"
    return None


@adapter("file", required={"paths": (str, list)}, optional={"exclude": (str, list)}, check=_check_file,
         description="Local files, each under its path",
         recheck="read the file again: is the item still there, and does what it points at already exist?")
def local_files(src: dict, ctx) -> str:
    excluded = [glob_re(_absolute(p, ctx.repo_dir).as_posix()) for p in _globs(src.get("exclude"))]
    files: dict[Path, None] = {}  # in pattern order, each file once
    for pattern in _globs(src["paths"]):
        matched = _matches(pattern, ctx.repo_dir)
        if not matched:
            raise SourceError(f"no file matches {pattern}")
        files.update((p, None) for p in matched if not any(g.fullmatch(p.as_posix()) for g in excluded))
    out = [f"# Files: {', '.join(_globs(src['paths']))}", ""]
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise SourceError(f"{_shown(p, ctx.repo_dir)}: {e.strerror}") from None
        out += [f"## {_shown(p, ctx.repo_dir)}", "", truncate(text).rstrip(), ""]
    return "\n".join(out)


def _absolute(pattern: str, repo_dir: Path) -> Path:
    """`~/…` is the home directory, a relative path is relative to the repo."""
    p = Path(pattern).expanduser()
    return p if p.is_absolute() else repo_dir / p


def _matches(pattern: str, repo_dir: Path) -> list[Path]:
    """The files a glob names, sorted; the same `*`/`**` rules as gh-markdown's parts. The walk
    starts at the last directory before the first wildcard, and without `**` it goes no
    deeper than the pattern does."""
    parts = _absolute(pattern, repo_dir).parts
    first = next((i for i, part in enumerate(parts) if _MAGIC.search(part)), None)
    if first is None:
        path = Path(*parts)
        return [path] if path.is_file() else []
    base, rest = Path(*parts[:first]), parts[first:]
    rx = glob_re("/".join(rest))
    deep = any("**" in part for part in rest)
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        rel = Path(dirpath).relative_to(base)
        if not deep and len(rel.parts) >= len(rest) - 1:
            dirnames[:] = []
        out += [Path(dirpath, f) for f in filenames if rx.fullmatch((rel / f).as_posix())]
    return sorted(out)


def _shown(path: Path, repo_dir: Path) -> str:
    """The path as a source config would write it: relative to the repo, or under `~/`."""
    if path.is_relative_to(repo_dir):
        return path.relative_to(repo_dir).as_posix()
    home = Path.home()
    if path.is_relative_to(home):
        return "~/" + path.relative_to(home).as_posix()
    return path.as_posix()


# --- command: a shell command's stdout ----------------------------------------

def _check_command(src: dict) -> str | None:
    if not src["run"].strip():
        return "`run` is empty"
    if src.get("timeout", 1) < 1:
        return "`timeout` must be at least 1"
    return None


@adapter("command", required={"run": str}, optional={"timeout": int}, check=_check_command,
         description="The output of a local command",
         recheck="run the source's `run` command from sources.toml again and look for the item")
def shell_command(src: dict, ctx) -> str:
    """`run` goes to /bin/sh in the repo directory, with no stdin. Its stdout is the file,
    verbatim; a nonzero exit or the timeout (60s by default) is an error, so the file
    keeps its last content under a `stale:` header."""
    run, timeout = src["run"], src.get("timeout", 60)
    label = run if len(run) <= 40 else run[:39] + "…"
    # its own process group, so a timeout also kills what the shell started
    proc = subprocess.Popen(["/bin/sh", "-c", run], cwd=ctx.repo_dir, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                            errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.wait()  # a process that left the group still holds the pipe; stop reading it
        raise SourceError(f"`{label}`: timed out after {timeout}s") from None
    if proc.returncode != 0:
        lines = (err or out).strip().splitlines()
        raise SourceError(f"`{label}`: exit {proc.returncode}: {lines[-1] if lines else ''}")
    return out if out.strip() else f"# {src['name']}\n\n(the command printed nothing)\n"
