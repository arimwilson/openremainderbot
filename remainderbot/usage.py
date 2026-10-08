"""Read each provider's own rate-limit snapshot and normalize it (DESIGN.md 2.1).

Any error is returned as UsageError and the caller must treat the provider as unknown.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


class UsageError(Exception):
    pass


@dataclass(frozen=True)
class Window:
    used_pct: float
    resets_at: int | None  # unix seconds; None while Claude's 5h window is idle

    @property
    def remaining_pct(self) -> float:
        return max(0.0, 100.0 - self.used_pct)


@dataclass(frozen=True)
class Usage:
    provider: str
    plan: str | None
    five_hour: Window
    weekly: Window

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Usage":
        return cls(
            provider=d["provider"],
            plan=d.get("plan"),
            five_hour=Window(**d["five_hour"]),
            weekly=Window(**d["weekly"]),
        )


# --- Codex --------------------------------------------------------------------

def codex(timeout: float = 30) -> Usage:
    """Spawn `codex app-server` on stdio and ask it for account/rateLimits/read."""
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"clientInfo": {"name": "remainderbot", "version": "0.1"}}},
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"},
    ]
    try:
        proc = subprocess.Popen(
            ["codex", "app-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as e:
        raise UsageError(f"codex: cannot start app-server: {e}") from e
    result = None
    try:
        for m in messages:
            proc.stdin.write(json.dumps(m) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UsageError(f"codex: app-server gave no rateLimits within {timeout}s")
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                raise UsageError(f"codex: app-server gave no rateLimits within {timeout}s")
            line = proc.stdout.readline()
            if not line:
                raise UsageError("codex: app-server exited before answering")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 2:
                if "error" in msg:
                    raise UsageError(f"codex: {msg['error']}")
                result = msg.get("result")
                break
    finally:
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait(timeout=5)
    if result is None:
        raise UsageError("codex: no rateLimits response from app-server")
    return parse_codex(result)


def parse_codex(result: dict) -> Usage:
    rl = result.get("rateLimits") or {}
    primary, secondary = rl.get("primary"), rl.get("secondary")
    if not primary or not secondary:
        raise UsageError(f"codex: missing primary/secondary windows in {result!r:.200}")
    return Usage(
        provider="codex",
        plan=rl.get("planType"),
        five_hour=Window(float(primary["usedPercent"]), int(primary["resetsAt"])),
        weekly=Window(float(secondary["usedPercent"]), int(secondary["resetsAt"])),
    )


# --- Claude -------------------------------------------------------------------

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# One-shot CLI call that makes Claude Code refresh ~/.claude/.credentials.json (2.1). The
# cheapest model the CLI accepts; an alias, so it never pins a dated model id.
CLAUDE_REFRESH_MODEL = os.environ.get("CLAUDE_REFRESH_MODEL", "haiku")
CLAUDE_REFRESH_TIMEOUT = 120


def claude_token() -> str:
    """Find the Claude Code OAuth access token: env, credentials file, then macOS keychain."""
    tok = os.environ.get("CLAUDE_OAUTH_TOKEN")
    if tok:
        return tok
    cred = Path(os.environ.get("CLAUDE_CREDENTIALS_FILE", Path.home() / ".claude" / ".credentials.json"))
    raw = None
    if cred.exists():
        raw = cred.read_text()
    elif sys.platform == "darwin":
        try:
            raw = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError) as e:
            raise UsageError(f"claude: keychain read failed: {e}") from e
    if not raw:
        raise UsageError(f"claude: no credentials at {cred} (set CLAUDE_OAUTH_TOKEN)")
    try:
        tok = json.loads(raw)["claudeAiOauth"]["accessToken"]
    except (ValueError, KeyError, TypeError) as e:
        raise UsageError(f"claude: credentials malformed: {e}") from e
    if not tok:
        raise UsageError("claude: empty access token")
    return tok


def refresh_claude_token() -> None:
    """Run the CLI once so it refreshes the stored OAuth token (it does so on every start).

    The prompt is trivial and the call is made from $HOME so no project settings apply.
    Raises UsageError if the CLI cannot be run or exits non-zero (typically: logged out).
    """
    cmd = ["claude", "-p", "reply with the single word ok", "--model", CLAUDE_REFRESH_MODEL]
    try:
        p = subprocess.run(cmd, cwd=Path.home(), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=CLAUDE_REFRESH_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        raise UsageError(f"claude: token refresh via CLI failed: {e}") from e
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-1:] or [""]
        raise UsageError(f"claude: token refresh via CLI exited {p.returncode}: {tail[0][:200]}")


def _fetch_claude_usage(token: str, timeout: float) -> dict:
    """One request; a 401 surfaces as UsageError('claude: HTTP 401 ...') either way."""
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "remainderbot/0.1",
    }
    try:
        return _get_json(CLAUDE_USAGE_URL, headers, timeout)
    except urllib.error.HTTPError as e:
        raise UsageError(f"claude: HTTP {e.code} from usage endpoint") from e
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise UsageError(f"claude: usage endpoint failed: {e}") from e
        # a Python without a CA bundle (python.org macOS builds); curl has the system roots
        return _curl_json(CLAUDE_USAGE_URL, headers, timeout)
    except (TimeoutError, ValueError) as e:
        raise UsageError(f"claude: usage endpoint failed: {e}") from e


def _is_401(e: UsageError) -> bool:
    return "HTTP 401" in str(e)


def claude(timeout: float = 30) -> Usage:
    """Read usage; on a 401 with a stored token, refresh it through the CLI and retry once.

    The stored token only refreshes when Claude Code runs, and the bot only runs it during
    a run, so a quiet week leaves an expired token behind (7). A token from
    CLAUDE_OAUTH_TOKEN is the caller's to manage and is never refreshed.
    """
    try:
        return parse_claude(_fetch_claude_usage(claude_token(), timeout))
    except UsageError as e:
        if not _is_401(e) or os.environ.get("CLAUDE_OAUTH_TOKEN"):
            raise
    refresh_claude_token()
    try:
        return parse_claude(_fetch_claude_usage(claude_token(), timeout))
    except UsageError as e:
        if _is_401(e):
            raise UsageError("claude: HTTP 401 from usage endpoint even after a CLI token refresh; "
                             "run `claude` on this host and log in again") from e
        raise


def _get_json(url: str, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _curl_json(url: str, headers: dict, timeout: float) -> dict:
    cmd = ["curl", "-sS", "-m", str(int(timeout)), "-w", "\\n%{http_code}"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    try:
        p = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout + 5, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        raise UsageError(f"claude: curl failed: {e}") from e
    body, _, code = p.stdout.rpartition("\n")
    if code != "200":
        raise UsageError(f"claude: HTTP {code} from usage endpoint")
    try:
        return json.loads(body)
    except ValueError as e:
        raise UsageError(f"claude: non-JSON usage body: {body[:120]!r}") from e


def _iso_to_unix(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def parse_claude(body: dict) -> Usage:
    fh, wk = body.get("five_hour"), body.get("seven_day")
    if not fh or not wk:
        raise UsageError(f"claude: missing five_hour/seven_day in {body!r:.200}")
    try:
        return Usage(
            provider="claude",
            plan=body.get("plan") or body.get("subscription_type"),
            # an idle 5-hour window (nothing used since the last one ended) has no reset time
            five_hour=Window(float(fh["utilization"]),
                             _iso_to_unix(fh["resets_at"]) if fh["resets_at"] is not None else None),
            weekly=Window(float(wk["utilization"]), _iso_to_unix(wk["resets_at"])),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise UsageError(f"claude: unexpected usage shape: {e}") from e


# --- all ----------------------------------------------------------------------

READERS = {"codex": codex, "claude": claude}


def read_all(providers: list[str]) -> dict[str, Usage | UsageError]:
    """Never raises; unknown providers and any failure become a UsageError value."""
    out: dict[str, Usage | UsageError] = {}
    for p in providers:
        reader = READERS.get(p)
        if reader is None:
            out[p] = UsageError(f"{p}: unknown provider")
            continue
        try:
            out[p] = reader()
        except UsageError as e:
            out[p] = e
        except Exception as e:  # noqa: BLE001 - a usage failure must never take the tick down
            out[p] = UsageError(f"{p}: {type(e).__name__}: {e}")
    return out


def fmt_reset(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
