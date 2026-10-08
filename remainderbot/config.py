"""Configuration: a handful of environment variables with defaults (DESIGN.md 6.4)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_DIR = PACKAGE_DIR.parent

# size -> CLI effort level; both providers use the same low/medium/high/xhigh/max scale (4.4)
EFFORT_BY_SIZE = {"small": "high", "medium": "xhigh", "large": "xhigh"}
FINALIZE_EFFORT = "medium"

# size thresholds on weekly remaining percent (2.3)
SIZE_MEDIUM_MIN = 20
SIZE_LARGE_MIN = 30


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass
class Config:
    window_hours: float = 4
    min_remaining: int = 10
    max_run_minutes: int = 45
    # a second run in the same weekly period is allowed only after a run that hit DONE,
    # and only if at least this many minutes remain before the deadline (2.2)
    min_rerun_minutes: int = 20
    providers: list[str] = field(default_factory=lambda: ["claude", "codex"])
    repo_dir: Path = DEFAULT_REPO_DIR
    run_disabled: bool = False
    deadline_buffer_minutes: int = 15
    finalize_minutes: int = 10
    # agents get unrestricted tool access on the VPS (the VPS is the sandbox, 4.1);
    # set AGENT_FULL_ACCESS=0 for a local dry run to keep the CLI's own sandbox on
    agent_full_access: bool = True
    claude_model: str = "claude-opus-5-5"
    claude_fallback_model: str = "claude-sonnet-5-5"
    codex_model: str = "gpt-6-astra"
    # what the snapshot reads; a relative path is relative to repo_dir
    sources_file: str = "sources.toml"
    # pushing to a public origin publishes every snapshot and agent log (origin.py)
    allow_public_repo: bool = False
    log_max_bytes: int = 5 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Config":
        providers = [p.strip() for p in os.environ.get("PROVIDERS", "claude,codex").split(",") if p.strip()]
        return cls(
            window_hours=float(os.environ.get("WINDOW_HOURS", 4)),
            min_remaining=_env_int("MIN_REMAINING", 10),
            max_run_minutes=_env_int("MAX_RUN_MINUTES", 45),
            min_rerun_minutes=_env_int("MIN_RERUN_MINUTES", 20),
            providers=providers,
            repo_dir=Path(os.environ.get("REPO_DIR", DEFAULT_REPO_DIR)).resolve(),
            run_disabled=_env_bool("RUN_DISABLED", False),
            deadline_buffer_minutes=_env_int("DEADLINE_BUFFER_MINUTES", 15),
            finalize_minutes=_env_int("FINALIZE_MINUTES", 10),
            agent_full_access=_env_bool("AGENT_FULL_ACCESS", True),
            claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
            claude_fallback_model=os.environ.get("CLAUDE_FALLBACK_MODEL", "claude-sonnet-5-5"),
            codex_model=os.environ.get("CODEX_MODEL", "gpt-6-astra"),
            sources_file=os.environ.get("SOURCES_FILE") or "sources.toml",
            allow_public_repo=_env_bool("ALLOW_PUBLIC_REPO", False),
            log_max_bytes=_env_int("LOG_MAX_BYTES", 5 * 1024 * 1024),
        )

    # paths
    @property
    def state_path(self) -> Path:
        return self.repo_dir / "state.json"

    @property
    def goals_path(self) -> Path:
        return self.repo_dir / "GOALS.md"

    @property
    def inbox_path(self) -> Path:
        return self.repo_dir / "INBOX.md"

    @property
    def sources_path(self) -> Path:
        return self.repo_dir / Path(self.sources_file).expanduser()

    @property
    def snapshot_dir(self) -> Path:
        return self.repo_dir / "goals" / "snapshot"

    @property
    def runs_dir(self) -> Path:
        return self.repo_dir / "runs"

    @property
    def lock_path(self) -> Path:
        return self.repo_dir / ".tick.lock"

    @property
    def prompts_dir(self) -> Path:
        return PACKAGE_DIR / "prompts"


def size_for(weekly_remaining_pct: float) -> str:
    if weekly_remaining_pct > SIZE_LARGE_MIN:
        return "large"
    if weekly_remaining_pct >= SIZE_MEDIUM_MIN:
        return "medium"
    return "small"
