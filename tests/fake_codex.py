#!/usr/bin/env python3
"""Stand-in for `codex exec` used by tests/test_run_execute.py.

Reads the prompt on stdin like the real CLI, finds the run id in it, and behaves per
FAKE_MODE: done (writes PLAN/README/DONE and commits), nodone (no README, no DONE),
hang (sleeps until killed), ratelimit (logs a rate-limit error and exits 1).
The finalize prompt is recognized by its title and always yields a trimmed README.
"""
import json
import os
import subprocess
import sys
import time

prompt = sys.stdin.read()
args = sys.argv[1:]
repo = args[args.index("-C") + 1]
run_id = prompt.split("`", 2)[1]
run_dir = os.path.join(repo, "runs", run_id)
mode = os.environ.get("FAKE_MODE", "done")
print(json.dumps({"type": "start", "args": args, "prompt_head": prompt[:40]}), flush=True)


def commit(msg):
    subprocess.run(["git", "-C", repo, "add", "-A", run_dir], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", msg], check=True)


if prompt.startswith("# remainderbot finalize pass"):
    with open(os.path.join(run_dir, "README.md"), "w") as f:
        f.write("# Fake trimmed                 status: trimmed\n\n## Run\nvia finalize\n")
    commit(f"run {run_id}: finalize")
    print(json.dumps({"type": "result", "finalize": True}))
    sys.exit(0)

with open(os.path.join(run_dir, "PLAN.md"), "w") as f:
    f.write("# plan\n")
commit(f"run {run_id}: plan")
if mode == "hang":
    time.sleep(3600)
if mode == "ratelimit":
    print(json.dumps({"type": "error", "message": "You have hit your usage limit; rate limit reached"}))
    sys.exit(1)
os.makedirs(os.path.join(run_dir, "artifact"), exist_ok=True)
with open(os.path.join(run_dir, "artifact", "thing.md"), "w") as f:
    f.write("the deliverable\n")
if os.environ.get("FAKE_JUNK"):  # ignored files the wrapper should clean up (all but log/)
    with open(os.path.join(run_dir, ".gitignore"), "w") as f:
        f.write("artifact/node_modules/\nartifact/clone/\n.cache/\nlog/kept.jsonl\n")
    for d in ("artifact/node_modules/pkg", ".cache/ab", "artifact/clone"):
        os.makedirs(os.path.join(run_dir, d), exist_ok=True)
    for p in ("artifact/node_modules/pkg/index.js", ".cache/ab/abc.json", "artifact/clone/x", "log/kept.jsonl"):
        open(os.path.join(run_dir, p), "w").close()
    subprocess.run(["git", "init", "-q", os.path.join(run_dir, "artifact", "clone")], check=True)
if mode == "done":
    with open(os.path.join(run_dir, "README.md"), "w") as f:
        f.write("# Fake done                 status: complete\n\n## Run\ncodex small\n")
    open(os.path.join(run_dir, "DONE"), "w").close()
commit(f"run {run_id}: {mode}")
print(json.dumps({"type": "result", "mode": mode}))
