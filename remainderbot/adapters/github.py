"""GitHub sources through the `gh` CLI: gh-issues, gh-roadmaps, gh-markdown."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from . import ListOf, adapter
from ._util import SourceError, _gh_file, _gh_tree, _json, frontmatter, glob_re, md_section, truncate


# --- gh-issues ----------------------------------------------------------------

def _check_issues(src: dict) -> str | None:
    if ("owner" in src) == ("repos" in src):
        return "set either `owner` (every repo it owns) or `repos`, not both"
    if "repos" in src and not src["repos"]:
        return "`repos` is empty"
    if src.get("limit", 1) < 1:
        return "`limit` must be at least 1"
    return None


@adapter("gh-issues", optional={"owner": str, "repos": list, "assignee": str, "labels": list, "limit": int},
         check=_check_issues, description="Open GitHub issues, grouped by repo",
         recheck="`gh issue view`: still open? does a linked PR or a recent commit already fix it?")
def gh_issues(src: dict, ctx) -> str:
    cmd = ["gh", "search", "issues", "--state", "open", "--limit", str(src.get("limit", 200)),
           "--json", "repository,number,title,url,updatedAt,labels"]
    if "owner" in src:
        cmd += ["--owner", src["owner"]]
        scope = src["owner"]
    else:
        for repo in src["repos"]:
            cmd += ["--repo", repo]
        scope = ", ".join(src["repos"])
    if src.get("assignee"):
        cmd += ["--assignee", src["assignee"]]
    for label in src.get("labels") or []:
        cmd += ["--label", label]
    issues = _json(cmd)
    by_repo: dict[str, list] = {}
    for i in issues:
        by_repo.setdefault(i["repository"]["nameWithOwner"], []).append(i)
    out = [f"# Open GitHub issues across {scope} ({len(issues)})", ""]
    for repo in sorted(by_repo):
        out.append(f"## {repo}")
        out.append("")
        for i in sorted(by_repo[repo], key=lambda i: i["updatedAt"], reverse=True):
            labels = ", ".join(l["name"] for l in i.get("labels") or [])
            out.append(f"- #{i['number']} {i['title']} (updated {i['updatedAt'][:10]}"
                       + (f", {labels}" if labels else "") + f") {i['url']}")
        out.append("")
    return "\n".join(out)


# --- gh-roadmaps: README heads and roadmap files ------------------------------

_ROADMAP_RE = re.compile(r"(^|[/_-])(todo|roadmap|plan|plans|planning|ideation)([_-]|\.md$|/)", re.I)
_SKIP_DIRS = ("node_modules/", "vendor/", ".git/", "dist/", "build/")


def _check_roadmaps(src: dict) -> str | None:
    if not src["repos"]:
        return "`repos` is empty"
    if "pattern" in src:
        try:
            re.compile(src["pattern"])
        except re.error as e:
            return f"`pattern` is not a valid regular expression: {e}"
    if src.get("readme_lines", 0) < 0:
        return "`readme_lines` must be 0 or more"
    return None


@adapter("gh-roadmaps", required={"repos": list}, optional={"pattern": str, "readme_lines": int},
         check=_check_roadmaps, description="README head and roadmap files of each repo, in priority order",
         recheck="roadmap files lag the code: `gh api` the repo's recent commits and its tree at HEAD before trusting an open item")
def gh_roadmaps(src: dict, ctx) -> str:
    pattern = re.compile(src["pattern"], re.I) if "pattern" in src else _ROADMAP_RE
    readme_lines = src.get("readme_lines", 40)
    what = f"files matching `{src['pattern']}`" if "pattern" in src else "TODO/ROADMAP/PLAN/ideation files"
    out = [f"# Repos: README head plus {what} (verbatim)", ""]
    errors = []
    for repo in src["repos"]:
        out += [f"## {repo}", ""]
        try:
            paths = _gh_tree(repo)
        except SourceError as e:
            out += [f"stale: {e}", ""]
            errors.append(str(e))
            continue
        readme = next((p for p in paths if p.lower() in ("readme.md", "readme")), None)
        if readme and readme_lines:
            head = "\n".join(_gh_file(repo, readme).splitlines()[:readme_lines])
            out += [f"### {readme} (first {readme_lines} lines)", "", head, ""]
        for p in paths:
            if not p.lower().endswith(".md") or any(s in p for s in _SKIP_DIRS):
                continue
            if pattern.search(p):
                out += [f"### {p}", "", truncate(_gh_file(repo, p)), ""]
    if errors and len(errors) == len(src["repos"]):
        raise SourceError("; ".join(errors))
    return "\n".join(out)


# --- gh-markdown: chosen parts of a repo of Markdown --------------------------

def _globs(value) -> list[re.Pattern]:
    return [glob_re(g) for g in ([value] if isinstance(value, str) else value or [])]


def _check_part(part: dict) -> str | None:
    if "sections" in part and "frontmatter" in part:
        return "set `sections` or `frontmatter`, not both"
    for key in ("sections", "frontmatter"):
        if key in part and not part[key]:
            return f"`{key}` is empty"
    return None


_PART = ListOf(required={"include": (str, list)},
               optional={"exclude": (str, list), "title": str, "latest": bool, "sections": list,
                         "frontmatter": list},
               check=_check_part)


def _check_markdown(src: dict) -> str | None:
    if not src["parts"]:
        return "`parts` is empty; add a [[sources.parts]] table"
    return None


@adapter("gh-markdown", required={"repo": str, "parts": _PART}, check=_check_markdown,
         description="Selected sections, frontmatter, and files from a repo of Markdown",
         recheck="is there a newer file in the repo that answers it?")
def gh_markdown(src: dict, ctx) -> str:
    repo = src["repo"]
    paths = sorted(_gh_tree(repo))
    out = [f"# {src['name']} ({'private, ' if src.get('private') else ''}{repo})", ""]
    if src.get("description"):
        out += [src["description"], ""]
    for part in src["parts"]:
        out += _part_md(repo, paths, part)
    return "\n".join(out)


def _part_md(repo: str, paths: list[str], part: dict) -> list[str]:
    """Each matching file under `## <title>: <path>` with the chosen sections, or the whole
    file; with `frontmatter`, one `- <stem>: key=value, ...` line per file under `## <title>`."""
    include, exclude = _globs(part["include"]), _globs(part.get("exclude"))
    matched = [p for p in paths if any(g.fullmatch(p) for g in include)
               and not any(g.fullmatch(p) for g in exclude)]
    if part.get("latest"):
        matched = matched[-1:]
    if not matched:
        return []
    title = part.get("title")
    if "frontmatter" in part:
        out = [f"## {title or ', '.join(_listed(part['include']))}", ""]
        for p in matched:
            fm = frontmatter(_gh_file(repo, p))
            fields = ", ".join(f"{k}={fm[k]}" for k in part["frontmatter"] if fm.get(k))
            out.append(f"- {PurePosixPath(p).stem}: {fields}")
        return out + [""]
    out = []
    for p in matched:
        text = _gh_file(repo, p)
        out += [f"## {title}: {p}" if title else f"## {p}", ""]
        if "sections" not in part:
            out += [truncate(text), ""]
            continue
        for sec in part["sections"]:
            body = md_section(text, sec)
            if body is not None:
                out += [f"### {sec}", "", body, ""]
    return out


def _listed(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)
