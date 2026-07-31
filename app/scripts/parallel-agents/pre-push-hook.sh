#!/usr/bin/env bash
set -euo pipefail

deny() { printf 'parallel-agents: denied: %s\n' "$1" >&2; exit 1; }
[[ $# -eq 2 ]] || deny "pre-push requires remote name and URL"
m=${PARALLEL_MANIFEST_PATH:-}
[[ -n "$m" && "$m" == /* ]] || deny "PARALLEL_MANIFEST_PATH must be absolute"
[[ -f "$m" ]] || deny "manifest does not exist"
r=$(git rev-parse --show-toplevel 2>/dev/null) || deny "not inside a Git worktree"
c=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || deny "cannot resolve Git authority"
c=$(dirname "$(realpath "$c")")
b=$(git symbolic-ref --quiet --short HEAD 2>/dev/null) || deny "detached HEAD"
u=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || deny "branch has no tracking branch"
h=$(git rev-parse HEAD) || deny "cannot resolve HEAD"
n=0
while IFS=' ' read -r lr ls rr rs extra; do
    [[ -z "$lr" ]] && continue
    ((n += 1))
    [[ -z "$extra" && -n "$ls" && -n "$rr" && -n "$rs" ]] || deny "malformed ref update"
    [[ "$lr" == "refs/heads/$b" ]] || deny "pushed ref does not match branch"
    [[ "$ls" == "$h" ]] || deny "pushed SHA does not match HEAD"
    [[ "$rs" != "0000000000000000000000000000000000000000" ]] || deny "first push is denied"
done
((n > 0)) || deny "pre-push received no ref update"

python3 - "$m" "$r" "$c" "$b" push "$u" <<'PY'
import fnmatch, hashlib, json, os, subprocess, sys
from pathlib import Path

def deny(reason):
    print(f"parallel-agents: denied: {reason}", file=sys.stderr)
    raise SystemExit(1)

def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

mf, root, common, branch, action, _upstream = sys.argv[1:7]
try:
    text = Path(mf).read_text(encoding="utf-8")
    data = json.loads(text)
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    deny(f"invalid manifest: {exc}")
if not isinstance(data, dict) or text != compact(data):
    deny("manifest is not canonical JSON")
unsigned = {key: value for key, value in data.items() if key != "manifest_hash"}
if data.get("manifest_hash") != hashlib.sha256(compact(unsigned).encode()).hexdigest():
    deny("manifest hash mismatch")
if os.path.realpath(data.get("worktree_root", "")) != os.path.realpath(root):
    deny("worktree root mismatch")
if os.path.realpath(data.get("repository_root", "")) not in {os.path.realpath(root), os.path.realpath(common)}:
    deny("repository root mismatch")
if data.get("branch") != branch:
    deny("branch mismatch")
base = data.get("base_sha")
if not isinstance(base, str):
    deny("base SHA is missing")
for command, reason in ((["git", "-C", root, "cat-file", "-e", f"{base}^{{commit}}"], "base SHA is not present"), (["git", "-C", root, "merge-base", "--is-ancestor", base, "HEAD"], "stale base SHA")):
    if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        deny(reason)
gates = data.get("action_gates", {})
if not isinstance(gates, dict) or gates.get(action) is not True:
    deny(f"{action} action is not declared")
if gates.get("human_delivery_required") is not True or not data.get("human_gate_id"):
    deny("human delivery gate is closed")
paths = subprocess.check_output(["git", "-C", root, "diff", "--name-only", f"{base}...HEAD"], text=True).splitlines()
paths += subprocess.check_output(["git", "-C", root, "ls-files", "--others", "--exclude-standard"], text=True).splitlines()
for path in paths:
    if any(fnmatch.fnmatchcase(path, pattern) for pattern in data.get("forbidden_paths", [])):
        deny(f"forbidden changed path: {path}")
    if not any(fnmatch.fnmatchcase(path, pattern) for pattern in data.get("allowed_writes", [])):
        deny(f"undeclared changed path: {path}")
PY
