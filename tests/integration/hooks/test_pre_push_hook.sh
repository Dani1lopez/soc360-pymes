#!/usr/bin/env bash
set -euo pipefail
P=$(git rev-parse --show-toplevel); H="$P/app/scripts/parallel-agents/pre-push-hook.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; S="$T/seed"; W="$T/worktree"; Q="$T/remote.git"; M="$T/manifest.json"
git init -q "$S"; git -C "$S" config user.name test; git -C "$S" config user.email test@example.invalid
printf 'base\n' > "$S/README.md"; git -C "$S" add .; git -C "$S" commit -qm base; git -C "$S" branch -M main
B=$(git -C "$S" rev-parse HEAD); git -C "$S" worktree add -q -b parallel/test "$W" HEAD; git clone -q --bare "$S" "$Q"
git -C "$W" remote add origin "$Q"; git -C "$W" update-ref refs/remotes/origin/parallel/test "$B"; git -C "$W" branch --set-upstream-to=origin/parallel/test >/dev/null; R=$(git -C "$W" rev-parse --show-toplevel)
write() {
    python3 - "$M" "$R" "$B" "$1" <<'PY'
import hashlib, json, sys
from pathlib import Path
p, root, base, action = sys.argv[1:]
g = {name: name == action for name in ("commit", "push", "merge", "rebase")}
m = {"manifest_version": 1, "agent_id": "11111111-1111-4111-8111-111111111111", "launch_id": "22222222-2222-4222-8222-222222222222", "repository_root": root, "worktree_root": root, "branch": "parallel/test", "base_sha": base, "owner": "test-agent", "allowed_writes": ["src/**"], "forbidden_paths": ["secrets/**"], "shared_files": {}, "action_gates": {**g, "human_delivery_required": True}, "human_gate_id": "gate-1"}
m["manifest_hash"] = hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); Path(p).write_text(json.dumps(m, sort_keys=True, separators=(",", ":")))
PY
}
reset() { git -C "$W" reset --hard -q "$B"; git -C "$W" clean -fdq; }
commit_file() { mkdir -p "$(dirname "$W/$1")"; printf change > "$W/$1"; git -C "$W" add "$1"; git -C "$W" commit -qm change; }
run() { printf 'refs/heads/parallel/test %s refs/heads/parallel/test %s\n' "$1" "$2" | (cd "$W" && PARALLEL_MANIFEST_PATH="$M" "$H" origin "$Q"); }
bad() { set +e; o=$(run "$1" "$2" 2>&1); s=$?; set -e; [[ $s -ne 0 && "$o" == *"parallel-agents: denied:"* ]]; }
reset; commit_file src/allowed.py; X=$(git -C "$W" rev-parse HEAD); write push; run "$X" "$B"
reset; X=$(git -C "$W" rev-parse HEAD); write none; bad "$X" "$B"
reset; commit_file README.md; X=$(git -C "$W" rev-parse HEAD); write push; bad "$X" "$B"
printf 'pre-push hook: 3 cases passed\n'
