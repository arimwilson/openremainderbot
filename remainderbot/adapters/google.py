"""Google sources through the `gws` CLI: gws-tasks and gws-doc."""
from __future__ import annotations

import re

from . import adapter
from ._util import SourceError, _gws


# --- gws-tasks ----------------------------------------------------------------

@adapter("gws-tasks", optional={"lists": list, "notes": bool},
         description="Open Google Tasks with due dates and notes",
         recheck="still open in the fresh snapshot? do its notes or due date point at something that already exists?")
def gws_tasks(src: dict, ctx) -> str:
    lists = _gws(["tasks", "tasklists", "list"], {"maxResults": 100}).get("items", [])
    wanted = src.get("lists")
    if wanted is not None:
        missing = set(wanted) - {tl.get("title") for tl in lists}
        if missing:
            raise SourceError(f"no task list titled {', '.join(sorted(missing))}")
        lists = [tl for tl in lists if tl.get("title") in wanted]
    out = ["# Google Tasks (open)", ""]
    for tl in lists:
        items = _gws(["tasks", "tasks", "list"],
                     {"tasklist": tl["id"], "showCompleted": False, "maxResults": 100}).get("items", [])
        items = [t for t in items if t.get("status") != "completed"]
        out.append(f"## {tl.get('title', tl['id'])} ({len(items)} open)")
        out.append("")
        for t in sorted(items, key=lambda t: t.get("position", "")):
            line = f"- {t.get('title', '').strip()}"
            if t.get("due"):
                line += f" (due {t['due'][:10]})"
            out.append(line)
            notes = (t.get("notes") or "").strip() if src.get("notes", True) else ""
            if notes:
                for n in notes.splitlines():
                    out.append(f"  {n}")
        out.append("")
    return "\n".join(out)


# --- gws-doc: Google Docs -> Markdown -----------------------------------------

@adapter("gws-doc", required={"doc_id": str}, optional={"tabs": list},
         description="A Google Doc as Markdown",
         recheck="`gws drive files list` by name; `gws docs documents get` and look for the section")
def gws_doc(src: dict, ctx) -> str:
    doc = _gws(["docs", "documents", "get"], {"documentId": src["doc_id"], "includeTabsContent": True})
    tabs = doc.get("tabs") or []
    if src.get("tabs") is not None:
        missing = set(src["tabs"]) - _tab_titles(tabs)
        if missing:
            raise SourceError(f"no tab titled {', '.join(sorted(missing))}")
        tabs = _pick_tabs(tabs, set(src["tabs"]))
    if len(tabs) == 1 and not tabs[0].get("childTabs"):
        # one tab reads as a plain document, without a tab heading
        dt = tabs[0].get("documentTab") or {}
        doc = {"title": doc.get("title"), "body": dt.get("body") or {}, "lists": dt.get("lists") or {}}
    else:
        doc = {**doc, "tabs": tabs}
    return docs_to_markdown(doc)


def _tab_titles(tabs: list) -> set[str]:
    titles = set()
    for t in tabs:
        titles.add((t.get("tabProperties") or {}).get("title"))
        titles |= _tab_titles(t.get("childTabs") or [])
    return titles


def _pick_tabs(tabs: list, titles: set[str]) -> list:
    """The tabs with these titles, each with its child tabs, wherever they are nested."""
    out = []
    for t in tabs:
        if (t.get("tabProperties") or {}).get("title") in titles:
            out.append(t)
        else:
            out += _pick_tabs(t.get("childTabs") or [], titles)
    return out


_HEADING_LEVEL = {"TITLE": 1, "HEADING_1": 1, "HEADING_2": 2, "HEADING_3": 3,
                  "HEADING_4": 4, "HEADING_5": 5, "HEADING_6": 6, "SUBTITLE": 2}
_ORDERED_GLYPHS = {"DECIMAL", "ALPHA", "UPPER_ALPHA", "ROMAN", "UPPER_ROMAN", "ZERO_DECIMAL"}


def _run_text(el: dict) -> str:
    tr = el.get("textRun")
    if not tr:
        if "inlineObjectElement" in el:
            return "[image]"
        return ""
    text = tr.get("content", "")
    style = tr.get("textStyle") or {}
    stripped = text.rstrip("\n")
    trailing = text[len(stripped):]
    if not stripped.strip():
        return text
    if style.get("link", {}).get("url"):
        stripped = f"[{stripped}]({style['link']['url']})"
    if style.get("strikethrough"):
        stripped = f"~~{stripped}~~"
    if style.get("bold"):
        stripped = f"**{stripped}**"
    return stripped + trailing


def _paragraph_text(p: dict) -> str:
    return "".join(_run_text(el) for el in p.get("elements", [])).rstrip("\n")


def _is_ordered(lists: dict, list_id: str, level: int) -> bool:
    props = (lists.get(list_id) or {}).get("listProperties") or {}
    levels = props.get("nestingLevels") or []
    if level < len(levels):
        return levels[level].get("glyphType") in _ORDERED_GLYPHS
    return False


def _content_to_md(content: list, lists: dict, out: list[str], counters: dict) -> None:
    prev_list = None
    for item in content:
        if "paragraph" in item:
            p = item["paragraph"]
            text = _paragraph_text(p)
            style = (p.get("paragraphStyle") or {}).get("namedStyleType", "NORMAL_TEXT")
            bullet = p.get("bullet")
            if bullet:
                level = int(bullet.get("nestingLevel", 0))
                lid = bullet.get("listId", "")
                key = (lid, level)
                if prev_list != lid:
                    counters = {k: v for k, v in counters.items() if k[0] != lid}
                if _is_ordered(lists, lid, level):
                    counters[key] = counters.get(key, 0) + 1
                    marker = f"{counters[key]}."
                else:
                    marker = "-"
                # reset deeper counters when a shallower item appears
                for k in list(counters):
                    if k[0] == lid and k[1] > level:
                        del counters[k]
                out.append(f"{'  ' * level}{marker} {text.strip()}")
                prev_list = lid
                continue
            prev_list = None
            if style in _HEADING_LEVEL:
                if text.strip():
                    out.append("")
                    out.append(f"{'#' * _HEADING_LEVEL[style]} {text.strip()}")
                    out.append("")
                continue
            out.append(text)
        elif "table" in item:
            prev_list = None
            out.append("")
            for r, row in enumerate(item["table"].get("tableRows", [])):
                cells = []
                for cell in row.get("tableCells", []):
                    sub: list[str] = []
                    _content_to_md(cell.get("content", []), lists, sub, {})
                    cells.append(" ".join(s.strip() for s in sub if s.strip()).replace("|", "\\|"))
                out.append("| " + " | ".join(cells) + " |")
                if r == 0:
                    out.append("|" + "---|" * len(cells))
            out.append("")
        elif "sectionBreak" in item or "tableOfContents" in item:
            continue


def docs_to_markdown(doc: dict) -> str:
    """Convert a Docs API `documents.get` response to Markdown: headings, lists, tables, links."""
    out: list[str] = []
    title = doc.get("title")
    if title:
        out += [f"# {title}", ""]
    tabs = doc.get("tabs") or []
    if tabs:
        for tab in tabs:
            _tab_to_md(tab, out)
    else:
        body = (doc.get("body") or {}).get("content", [])
        _content_to_md(body, doc.get("lists") or {}, out, {})
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _tab_to_md(tab: dict, out: list[str]) -> None:
    props = tab.get("tabProperties") or {}
    dt = tab.get("documentTab") or {}
    if props.get("title"):
        out += ["", f"## Tab: {props['title']}", ""]
    _content_to_md((dt.get("body") or {}).get("content", []), dt.get("lists") or {}, out, {})
    for child in tab.get("childTabs") or []:
        _tab_to_md(child, out)
