#!/usr/bin/env python3
"""Stand-in for `gh` used by tests/test_publish.py and tests/test_adapters.py.

PRs live in the JSON file named by FAKE_GH_DB (a list of dicts shaped like `gh pr list
--json` output). Supports `pr create` and `pr list`; tests edit the file directly to
merge, close, or comment. FAKE_GH_FAIL=1 makes every call fail like a network error.
`repo view` answers from FAKE_GH_REPOS ({repo argument: {"nameWithOwner", "visibility"}})
when it names the repo, else with example/remainderbot and FAKE_GH_VISIBILITY (default
PRIVATE); `auth status` succeeds unless FAKE_GH_LOGGED_OUT=1.

Sources live in the JSON file named by FAKE_GH_SOURCES: {"repos": {"owner/name": {path:
text}}, "issues": [{"repo", "number", "title", "updatedAt", "labels", "assignees"}]}.
Supports `api` for a repo's tree and its files' contents (a repo or file that is not
there answers 404) and `search issues`. FAKE_GH_CALLS, if set, names a file that gets
each call's arguments as one JSON line.
"""
import base64
import json
import os
import re
import sys

args = sys.argv[1:]

if os.environ.get("FAKE_GH_CALLS"):
    with open(os.environ["FAKE_GH_CALLS"], "a") as f:
        f.write(json.dumps(args) + "\n")

if os.environ.get("FAKE_GH_FAIL") == "1":
    print("error connecting to api.github.com", file=sys.stderr)
    sys.exit(1)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default


def opts(name):
    return [args[i + 1] for i, a in enumerate(args) if a == name]


def not_found():
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)


if args[:1] == ["api"]:
    repos = load(os.environ["FAKE_GH_SOURCES"])["repos"]
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/(git/trees/HEAD\?recursive=1|contents/(.+))", args[1])
    if not m or m.group(1) not in repos:
        not_found()
    files = repos[m.group(1)]
    if m.group(3) is None:
        dirs = {p.rsplit("/", 1)[0] for p in files if "/" in p}
        tree = [{"path": d, "type": "tree"} for d in dirs] + [{"path": p, "type": "blob"} for p in files]
        print(json.dumps({"tree": sorted(tree, key=lambda t: t["path"])}))
    elif m.group(3) not in files:
        not_found()
    elif "Accept: application/vnd.github.raw+json" in args:
        sys.stdout.write(files[m.group(3)])
    else:
        content = base64.b64encode(files[m.group(3)].encode()).decode()
        print(json.dumps({"path": m.group(3), "encoding": "base64", "content": content}))
elif args[:2] == ["repo", "view"]:
    repos = json.loads(os.environ.get("FAKE_GH_REPOS", "{}"))
    print(json.dumps(repos.get(args[2]) or {"nameWithOwner": "example/remainderbot",
                                            "visibility": os.environ.get("FAKE_GH_VISIBILITY", "PRIVATE")}))
elif args[:2] == ["auth", "status"]:
    if os.environ.get("FAKE_GH_LOGGED_OUT") == "1":
        print("You are not logged into any GitHub hosts. To log in, run: gh auth login", file=sys.stderr)
        sys.exit(1)
    print("github.com\n  \u2713 Logged in to github.com account example (keyring)")
elif args[:2] == ["search", "issues"]:
    issues = load(os.environ["FAKE_GH_SOURCES"])["issues"]
    owner, repos, labels, assignee = opt("--owner"), opts("--repo"), opts("--label"), opt("--assignee")
    out = [i for i in issues if (owner is None or i["repo"].split("/")[0] == owner)
           and (not repos or i["repo"] in repos) and set(labels) <= set(i.get("labels", []))
           and (assignee is None or assignee in i.get("assignees", []))]
    out = [{"repository": {"nameWithOwner": i["repo"]}, "number": i["number"], "title": i["title"],
            "url": f"https://github.com/{i['repo']}/issues/{i['number']}", "updatedAt": i["updatedAt"],
            "labels": [{"name": l} for l in i.get("labels", [])]} for i in out]
    print(json.dumps(out[: int(opt("--limit", "30"))]))
elif args[:2] == ["pr", "create"]:
    db_path = os.environ["FAKE_GH_DB"]
    prs = load(db_path)
    with open(opt("--body-file")) as f:
        body = f.read()
    number = max([p["number"] for p in prs], default=0) + 1
    prs.append({"number": number, "url": f"https://github.com/example/remainderbot/pull/{number}",
                "state": "OPEN", "title": opt("--title"), "headRefName": opt("--head"),
                "baseRefName": opt("--base"), "body": body, "comments": [], "reviews": []})
    with open(db_path, "w") as f:
        json.dump(prs, f, indent=1)
    print(prs[-1]["url"])
elif args[:2] == ["pr", "list"]:
    prs = load(os.environ["FAKE_GH_DB"])
    head = opt("--head")
    state = opt("--state", "open").upper()
    out = [p for p in prs if (head is None or p["headRefName"] == head)
           and (state == "ALL" or p["state"] == state)]
    out = out[::-1][: int(opt("--limit", "30"))]
    fields = opt("--json", "").split(",")
    print(json.dumps([{k: p.get(k) for k in fields} for p in out]))
else:
    print(f"fake gh: unsupported {args}", file=sys.stderr)
    sys.exit(2)
