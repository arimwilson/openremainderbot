"""Source adapters: one function per `type` in sources.toml (docs/sources.md).

An adapter takes its validated [[sources]] table and a Context, and returns the Markdown
for goals/snapshot/<name>.md or raises SourceError. The decorator registers the type with
the fields a table may set; sources.py checks every table against them before anything
is fetched.

Field types: `str`, `int`, `bool`, `list` (an array of strings), a tuple of those (either
one), or `ListOf(...)` for an array of tables with fields of their own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ._util import SourceError  # noqa: F401 - adapters and snapshot.py raise and catch it

# a check gets the whole table once its fields have the right types; it returns what is
# wrong with it, or None
Check = Callable[[dict], "str | None"]


@dataclass(frozen=True)
class ListOf:
    """A field holding an array of tables, each checked against these fields."""
    required: dict
    optional: dict = field(default_factory=dict)
    check: Check | None = None


@dataclass
class Context:
    repo_dir: Path
    max_chars: int
    log: Callable[[str], None] = print


@dataclass(frozen=True)
class Adapter:
    type: str
    fn: Callable[[dict, Context], str]
    required: dict
    optional: dict
    description: str
    recheck: str
    check: Check | None


ADAPTERS: dict[str, Adapter] = {}


def adapter(type_: str, *, required: dict | None = None, optional: dict | None = None,
            description: str = "", recheck: str = "", check: Check | None = None):
    """Register the decorated function as the adapter for `type = "<type_>"`.

    `description` and `recheck` are the defaults for a source that sets neither: the line
    shown to the agent for this source, and the cheap check that its content is current.
    """
    def register(fn):
        if type_ in ADAPTERS:
            raise ValueError(f"adapter {type_!r} registered twice")
        ADAPTERS[type_] = Adapter(type_, fn, required or {}, optional or {}, description, recheck, check)
        return fn
    return register


# importing the modules registers their adapters
from . import github, google, local  # noqa: E402,F401
