"""origin: the GitHub repo this instance publishes to, and whether it may (README.md, "Privacy").

A run branch carries the snapshot of every source and the agent's whole log, and main
carries INBOX.md, so nothing is pushed to a public origin unless ALLOW_PUBLIC_REPO=1.
`git push origin` pushes to every push URL origin has (several `pushurl`s, or several
`url`s without one), so every one of them must be private. Once `gh repo view` says a URL
is private, that holds for the rest of the process. When gh cannot answer, the push is
refused (fail closed) and the next push asks again; publishing is retried on the next
tick anyway.

Every gh call about PRs names origin with `--repo`. Without it gh picks its own default,
and with an `upstream` remote that default is upstream: `gh pr list` would read the
engine repo's PRs and `gh pr create` would aim at it.
"""
from __future__ import annotations

import json
import re
import subprocess

from .config import Config
from .run import git

ALLOWED_VISIBILITY = ("PRIVATE", "INTERNAL")
_CREDENTIALS_RE = re.compile(r"^(https?://)[^/@]*@")
# push URLs that gh said are private or internal, in this process
_allowed: set[str] = set()


class PublicRepoError(RuntimeError):
    """origin is public, or its visibility is unknown, and ALLOW_PUBLIC_REPO is not set."""


def push_urls(config: Config) -> list[str]:
    """Every URL `git push origin` pushes to, without any credentials in them. Raises
    RuntimeError if there is no origin."""
    out = git(config, "remote", "get-url", "--push", "--all", "origin")
    return [_CREDENTIALS_RE.sub(r"\1", line.strip()) for line in out.splitlines() if line.strip()]


def url(config: Config) -> str:
    """The first of origin's push URLs: the repo whose PRs gh's `--repo` names."""
    return push_urls(config)[0]


def visibility(config: Config, repo_url: str | None = None) -> tuple[str, str]:
    """(owner/name, PUBLIC | PRIVATE | INTERNAL) for one of origin's push URLs, the first by
    default. Raises RuntimeError."""
    try:
        p = subprocess.run(["gh", "repo", "view", repo_url or url(config), "--json", "nameWithOwner,visibility"],
                           capture_output=True, text=True, cwd=str(config.repo_dir), timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"gh repo view: {e}") from None
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip().splitlines()
        raise RuntimeError(f"gh repo view: exit {p.returncode}: {err[-1] if err else ''}")
    try:
        data = json.loads(p.stdout)
        return data["nameWithOwner"], data["visibility"].upper()
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(f"gh repo view: unexpected answer: {e}") from None


def check(config: Config) -> None:
    """Return if the bot may push to origin; raise PublicRepoError with the reason if not."""
    if config.allow_public_repo:
        return
    try:
        urls = push_urls(config)
    except RuntimeError as e:
        raise PublicRepoError(f"no origin to push to ({e})") from None
    for u in urls:
        if u in _allowed:
            continue
        try:
            name, vis = visibility(config, u)
        except RuntimeError as e:
            what = "origin" if len(urls) == 1 else f"{u}, one of origin's {len(urls)} push URLs,"
            raise PublicRepoError(f"cannot tell whether {what} is private ({e}); "
                                  f"not pushing until gh can answer") from None
        if vis not in ALLOWED_VISIBILITY:
            what = f"origin {name}" if len(urls) == 1 else f"{name}, one of origin's {len(urls)} push URLs,"
            raise PublicRepoError(f"{what} is {vis.lower()}, and a run branch carries every source's snapshot "
                                  f"and the agent's log; make the repo private, or set ALLOW_PUBLIC_REPO=1")
        _allowed.add(u)
