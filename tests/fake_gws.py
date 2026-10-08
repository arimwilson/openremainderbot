#!/usr/bin/env python3
"""Stand-in for `gws` used by tests/test_adapters.py.

Data lives in the JSON file named by FAKE_GWS_DB: {"tasklists": [{"id", "title"}],
"tasks": {list id: [task, ...]}, "docs": {doc id: {"title", "tabs": [...]}}}. Docs are
stored with their tabs; without `includeTabsContent` the fake answers the way the Docs API
does, with only the first tab's body and lists, at the top level.
"""
import json
import os
import sys

args = sys.argv[1:]
params = json.loads(args[args.index("--params") + 1]) if "--params" in args else {}
with open(os.environ["FAKE_GWS_DB"]) as f:
    db = json.load(f)

if args[:3] == ["tasks", "tasklists", "list"]:
    out = {"items": db.get("tasklists", [])}
elif args[:3] == ["tasks", "tasks", "list"]:
    items = db.get("tasks", {}).get(params["tasklist"], [])
    if not params.get("showCompleted", True):
        items = [t for t in items if t.get("status") != "completed"]
    out = {"items": items}
elif args[:3] == ["docs", "documents", "get"]:
    out = db.get("docs", {}).get(params["documentId"])
    if out is None:
        print("Requested entity was not found. (404)", file=sys.stderr)
        sys.exit(1)
    if not params.get("includeTabsContent"):
        first = out["tabs"][0]["documentTab"]
        out = {"title": out["title"], "body": first.get("body", {}), "lists": first.get("lists", {})}
else:
    print(f"fake gws: unsupported {args}", file=sys.stderr)
    sys.exit(2)
print(json.dumps(out))
