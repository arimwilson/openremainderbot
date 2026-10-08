"""sources.toml: what the snapshot reads, checked in full before anything is fetched
(docs/sources.md).

The file is TOML, read with the standard library's tomllib: `version = 1`, then one
[[sources]] table per source. A syntax error names the line. Every other error names the
source: an unknown `type`, a missing required field, an unknown field, a wrong type, a
duplicate `name`, or an unsupported `version`. A tick never runs on a half-understood
config.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass

from .adapters import ADAPTERS, ListOf
from .config import Config

VERSION = 1
DEFAULT_MAX_CHARS = 60_000
_NAME_RE = re.compile(r"[a-z0-9-]+")
_AT_LINE = re.compile(r"(.*) \(at line (\d+), column \d+\)", re.S)

# fields every source accepts, on top of its adapter's own (3.1)
COMMON_REQUIRED = {"name": str, "type": str}
COMMON_OPTIONAL = {"description": str, "private": bool, "recheck": str, "enabled": bool, "max_chars": int}
_TYPE_NAMES = {str: "a string", int: "an integer", bool: "true or false", list: "an array of strings"}


class ConfigError(Exception):
    """sources.toml is missing or invalid; the message starts with the file's name."""


@dataclass
class Source:
    name: str
    type: str
    fields: dict  # the whole [[sources]] table; what the adapter gets
    description: str
    private: bool
    recheck: str
    enabled: bool
    max_chars: int

    @property
    def filename(self) -> str:
        return f"{self.name}.md"


def load(config: Config) -> list[Source]:
    path = config.sources_path
    label = str(path.relative_to(config.repo_dir)) if path.is_relative_to(config.repo_dir) else str(path)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"{label}: not found") from None
    except OSError as e:
        raise ConfigError(f"{label}: {e.strerror}") from None
    try:
        text = data.decode("utf-8")  # TOML is UTF-8 whatever the locale says
    except UnicodeDecodeError as e:
        line = data.count(b"\n", 0, e.start) + 1
        raise ConfigError(f"{label}:{line}: not valid UTF-8 ({e.reason})") from None
    return parse(text, label)


def parse(text: str, label: str = "sources.toml") -> list[Source]:
    def fail(msg: str):
        raise ConfigError(f"{label}: {msg}")

    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        m = _AT_LINE.fullmatch(str(e))
        raise ConfigError(f"{label}:{m[2]}: {m[1]}" if m else f"{label}: {e}") from None
    for key in doc:
        if key not in ("version", "sources"):
            fail(f"unknown key {key!r}; the top level has `version` and `sources`")
    if "version" not in doc:
        fail("missing `version = 1`")
    version = doc["version"]
    if type(version) is not int or version != VERSION:
        fail(f"unsupported version {version!r}; this remainderbot reads version {VERSION}")
    if "sources" not in doc:
        fail("missing `sources`; add a [[sources]] table for each source")
    entries = doc["sources"]
    if not isinstance(entries, list):
        fail("`sources` must be an array of tables, one [[sources]] per source")

    out: list[Source] = []
    seen: dict[str, int] = {}
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            fail(f"source {i} must be a table ([[sources]])")
        src = _source(entry, i, fail)
        if src.name in seen:
            fail(f"duplicate name {src.name!r} (sources {seen[src.name]} and {i})")
        seen[src.name] = i
        out.append(src)
    return out


def _source(entry: dict, i: int, fail) -> Source:
    for key in ("name", "type"):
        if key not in entry:
            fail(f"source {i} is missing `{key}`")
    name = entry["name"]
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        fail(f"source {i}: name {name!r} must be lowercase letters, digits, and dashes")
    what = f"source {name!r}"
    type_ = entry["type"]
    if not isinstance(type_, str) or type_ not in ADAPTERS:
        fail(f"{what}: unknown type {type_!r}; known types: {', '.join(sorted(ADAPTERS))}")
    ad = ADAPTERS[type_]
    _check_fields(entry, {**COMMON_REQUIRED, **ad.required}, {**COMMON_OPTIONAL, **ad.optional}, ad.check, fail, what)
    if entry.get("max_chars", 1) < 1:
        fail(f"{what}: `max_chars` must be at least 1")
    return Source(
        name=name, type=type_, fields=entry,
        description=entry.get("description") or ad.description,
        private=entry.get("private", False), recheck=entry.get("recheck") or ad.recheck,
        enabled=entry.get("enabled", True), max_chars=entry.get("max_chars", DEFAULT_MAX_CHARS),
    )


def _check_fields(table: dict, required: dict, optional: dict, check, fail, what: str) -> None:
    """Unknown fields first (a typo reads better as `unknown field` than `missing`), then
    types, then missing required fields, then the adapter's own check."""
    allowed = {**optional, **required}
    for key in table:
        if key not in allowed:
            fail(f"{what}: unknown field {key!r}; allowed: {', '.join(sorted(allowed))}")
    for key, value in table.items():
        _check_value(value, allowed[key], fail, f"{what}: `{key}`")
    for key in required:
        if key not in table:
            fail(f"{what}: missing `{key}`")
    problem = check(table) if check else None
    if problem:
        fail(f"{what}: {problem}")


def _check_value(value, spec, fail, what: str) -> None:
    if isinstance(spec, ListOf):
        if not isinstance(value, list):
            fail(f"{what} must be an array of tables")
        for i, item in enumerate(value, 1):
            if not isinstance(item, dict):
                fail(f"{what} item {i} must be a table")
            _check_fields(item, spec.required, spec.optional, spec.check, fail, f"{what} item {i}")
        return
    specs = spec if isinstance(spec, tuple) else (spec,)
    if not any(_is(value, t) for t in specs):
        fail(f"{what} must be {' or '.join(_TYPE_NAMES[t] for t in specs)}")


def _is(value, t) -> bool:
    if t is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if t is list:
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return isinstance(value, t)
