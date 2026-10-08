"""Helpers shared by the adapters: running `gh`/`gws`, and reading Markdown."""
from __future__ import annotations

import base64
import json
import re
import subprocess

MAX_FILE_CHARS = 60_000  # one file embedded in a source's output is kept verbatim up to this size


class SourceError(Exception):
    pass


def _run(cmd: list[str], timeout: float = 60) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except OSError as e:
        raise SourceError(f"{cmd[0]}: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise SourceError(f"{cmd[0]}: timed out after {timeout}s") from e
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip().splitlines()
        raise SourceError(f"{' '.join(cmd[:3])}: exit {p.returncode}: {err[-1] if err else ''}")
    return p.stdout


def _json(cmd: list[str], timeout: float = 60) -> dict | list:
    out = _run(cmd, timeout)
    try:
        return json.loads(out)
    except ValueError as e:
        raise SourceError(f"{cmd[0]}: non-JSON output: {out[:120]!r}") from e


def _gws(args: list[str], params: dict) -> dict:
    return _json(["gws", *args, "--params", json.dumps(params)])


def _gh_api(path: str, raw: bool = False) -> str:
    cmd = ["gh", "api", path]
    if raw:
        cmd += ["-H", "Accept: application/vnd.github.raw+json"]
    return _run(cmd)


def _gh_file(repo: str, path: str) -> str:
    """Fetch one file's text from GitHub without cloning."""
    data = json.loads(_gh_api(f"repos/{repo}/contents/{path}"))
    if isinstance(data, dict) and data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return _gh_api(f"repos/{repo}/contents/{path}", raw=True)


def _gh_tree(repo: str) -> list[str]:
    data = json.loads(_gh_api(f"repos/{repo}/git/trees/HEAD?recursive=1"))
    return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]


def truncate(text: str, limit: int = MAX_FILE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated at {limit} chars ...]\n"


def glob_re(pattern: str) -> re.Pattern:
    """`*` and `?` stay within one path segment; `**` crosses directories, and `a/**/b`
    also matches `a/b`. (fnmatch's `*` crosses `/`; PurePath.full_match needs 3.13.)"""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def md_section(text: str, heading: str) -> str | None:
    """Return the body under a `## heading` (any level) up to the next heading of the same or higher level."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m and m.group(2).strip().lower() == heading.lower():
            level = len(m.group(1))
            body = []
            for l in lines[i + 1:]:
                m2 = re.match(r"^(#{1,6})\s+", l)
                if m2 and len(m2.group(1)) <= level:
                    break
                body.append(l)
            return "\n".join(body).strip()
    return None


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm
