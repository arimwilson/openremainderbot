"""INBOX.md: the ledger of runs and verdicts, and sync() which copies PR state and the
last comment into it (DESIGN.md 5, 6.1 phase 1).

The table is the only feedback channel: merged -> approved, closed -> rejected, and the
last PR comment becomes the note the next run reads.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import origin
from .config import Config

# what heads INBOX.md when the first publish creates it; the file is never shipped upstream
PREAMBLE = """# INBOX

One row per run. Status: `needs-review` (PR open) / `approved` (merged) / `rejected`
(closed) / `abandoned`. The note column is copied from the last PR comment by
`inbox.sync()`; write there what should change if you reject something."""

COLUMNS = ["id", "provider", "task", "status", "your note"]
HEADER = "| " + " | ".join(COLUMNS) + " |"
SEPARATOR = "|" + "|".join("-" * (len(c) + 2) for c in COLUMNS) + "|"
STATUS_BY_PR_STATE = {"MERGED": "approved", "CLOSED": "rejected"}
MAX_TASK_CHARS = 100
MAX_NOTE_CHARS = 300
PR_LIST_LIMIT = 200
_ID_RE = re.compile(r"^\d{8}-\d{4}-(claude|codex)$")


@dataclass
class Row:
    id: str
    provider: str
    task: str
    status: str
    note: str = ""

    def render(self) -> str:
        cells = [_cell(v) for v in (self.id, self.provider, self.task, self.status, self.note)]
        return "|" + "|".join(f" {c} " if c else " " for c in cells) + "|"


# --- the table ----------------------------------------------------------------

def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _uncell(text: str) -> str:
    return text.strip().replace("\\|", "|")


def _split_row(line: str) -> list[str]:
    # split on unescaped pipes; the line starts and ends with one
    parts = re.split(r"(?<!\\)\|", line.strip())
    return [_uncell(p) for p in parts[1:-1]]


def parse(text: str) -> tuple[str, list[Row]]:
    """Return (preamble above the table, rows). A file without a table has no rows."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and [c.lower() for c in _split_row(line)[:5]] == COLUMNS:
            preamble = "\n".join(lines[:i]).rstrip("\n")
            rows = []
            for raw in lines[i + 1:]:
                if not raw.startswith("|") or re.fullmatch(r"\|[-| :]+\|", raw.strip()):
                    continue
                cells = _split_row(raw)
                if len(cells) < 4 or not cells[0]:
                    continue
                cells += [""] * (5 - len(cells))
                rows.append(Row(*cells[:5]))
            return preamble, rows
    return text.rstrip("\n"), []


def render(preamble: str, rows: list[Row]) -> str:
    out = [preamble.rstrip("\n"), "", HEADER, SEPARATOR] if preamble.strip() else [HEADER, SEPARATOR]
    out += [r.render() for r in rows]
    return "\n".join(out) + "\n"


def load(path: Path) -> tuple[str, list[Row]]:
    return parse(path.read_text()) if path.exists() else (PREAMBLE, [])


def upsert(rows: list[Row], row: Row) -> list[Row]:
    """Replace the row with the same id or append; the list stays sorted by id (chronological)."""
    rows = [r for r in rows if r.id != row.id] + [row]
    rows.sort(key=lambda r: r.id)
    return rows


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- sync ---------------------------------------------------------------------

def _gh_json(cmd: list[str], cwd: Path, timeout: float = 60):
    p = subprocess.run(["gh", *cmd], capture_output=True, text=True, cwd=str(cwd), timeout=timeout)
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip().splitlines()
        raise RuntimeError(f"gh {' '.join(cmd[:2])}: exit {p.returncode}: {err[-1] if err else ''}")
    return json.loads(p.stdout or "null")


def list_run_prs(config: Config) -> list[dict]:
    """Every PR whose head is a run branch, newest first, with its comments and reviews."""
    prs = _gh_json(["pr", "list", "--repo", origin.url(config), "--state", "all", "--limit", str(PR_LIST_LIMIT),
                    "--json", "number,url,state,title,headRefName,comments,reviews"], config.repo_dir)
    return [p for p in prs or [] if p.get("headRefName", "").startswith("run/")]


def last_comment(pr: dict) -> str:
    """The most recent comment or review body on the PR, or ''."""
    items = [(c.get("createdAt", ""), c.get("body", "")) for c in pr.get("comments") or []]
    items += [(r.get("submittedAt", ""), r.get("body", "")) for r in pr.get("reviews") or []]
    items = [(t, b) for t, b in items if (b or "").strip()]
    if not items:
        return ""
    return max(items)[1]


def apply_pr(rows: list[Row], pr: dict) -> tuple[list[Row], str | None]:
    """Fold one PR into the rows. Returns (rows, change description or None)."""
    run_id = pr["headRefName"][len("run/"):]
    existing = next((r for r in rows if r.id == run_id), None)
    status = STATUS_BY_PR_STATE.get(pr.get("state", ""))
    note = truncate(last_comment(pr), MAX_NOTE_CHARS)
    if existing is None:
        # a run whose publish step failed before writing its row: recover it from the PR
        provider = run_id.rsplit("-", 1)[-1] if _ID_RE.match(run_id) else "?"
        row = Row(run_id, provider, truncate(pr.get("title", ""), MAX_TASK_CHARS), status or "needs-review", note)
        return upsert(rows, row), f"{run_id}: added from PR #{pr.get('number')} as {row.status}"
    new_status = existing.status
    # an abandoned run stays abandoned when its PR is simply closed; a merge still approves it
    if status and not (status == "rejected" and existing.status == "abandoned"):
        new_status = status
    new_note = note or existing.note
    if new_status == existing.status and new_note == existing.note:
        return rows, None
    row = Row(existing.id, existing.provider, existing.task, new_status, new_note)
    return upsert(rows, row), f"{run_id}: {existing.status} -> {new_status}" + (", note updated" if new_note != existing.note else "")


def sync(config: Config, log=print) -> int:
    """Copy PR state and the last comment into INBOX.md, commit on main. Returns rows changed."""
    from .publish import commit_on_main  # late import: publish imports this module
    prs = list_run_prs(config)
    preamble, rows = load(config.inbox_path)
    changes = []
    for pr in prs:
        rows, change = apply_pr(rows, pr)
        if change:
            changes.append(change)
    if not changes:
        log(f"inbox sync: {len(prs)} run PRs, nothing changed")
        return 0
    config.inbox_path.write_text(render(preamble, rows))
    for c in changes:
        log(f"inbox sync: {c}")
    commit_on_main(config, [config.inbox_path], f"inbox: sync {len(changes)} row(s) from PRs", log)
    return len(changes)
