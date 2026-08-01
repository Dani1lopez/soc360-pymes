# Parallel-agents coordination validation runbook

> **WARNING**: This runbook uses a fresh clone at `9203b87` (or any later main).
> **NEVER use the active `pr5b-metrics-outage-wiring` worktree — that is a
> separate in-progress change.** Create all validation worktrees as siblings of
> the fresh clone in a temporary directory.

## Purpose and safety boundary

These cases prove the coordination contract without changing the active project
or granting delivery authority. The manifest ledger remains RDD receipt input;
the runbook does not replace bounded review, exact receipts, or human delivery
authorization.

## Prerequisites

- Python 3.12, Git, and the globally installed skill at
  `~/.config/opencode/skills/parallel-agents-coordination/`.
- A clean shell outside the active PR5b worktree.
- Permission to create a temporary directory and sibling Git worktrees.
- The repository URL in `REPOSITORY_URL`.

Prepare an isolated validation clone:

```bash
export VALIDATION_TMP="$(mktemp -d)"
trap 'rm -rf "$VALIDATION_TMP"' EXIT
export REPOSITORY_URL="<repository-url>"
git clone "$REPOSITORY_URL" "$VALIDATION_TMP/main"
git -C "$VALIDATION_TMP/main" checkout --detach 9203b87
git -C "$VALIDATION_TMP/main" worktree add "$VALIDATION_TMP/pa-a" -b validation/pa-a 9203b87
git -C "$VALIDATION_TMP/main" worktree add "$VALIDATION_TMP/pa-b" -b validation/pa-b 9203b87
export SKILL_HOME="$HOME/.config/opencode/skills/parallel-agents-coordination"
```

Generate each manifest with the schema reference, a unique `agent_id` and
`launch_id`, the matching worktree root, branch, and `base_sha=9203b87`. Hash
the canonical JSON without `manifest_hash`; store the full canonical document in
an absolute path. Use `ack-manifest.py` only after the manifest is final.

## Case 1 — Disjoint ownership succeeds

### Prerequisites

Create manifest A for `pa-a` with `allowed_writes=["app/modules/auth/**"]` and
manifest B for `pa-b` with `allowed_writes=["app/modules/scans/**"]`. Both must
have valid ACKs and no delivery action enabled.

### Commands

```bash
export PARALLEL_MANIFEST_PATH="$VALIDATION_TMP/manifest-a.json"
python "$SKILL_HOME/scripts/ack-manifest.py" --manifest "$PARALLEL_MANIFEST_PATH"
export PARALLEL_MANIFEST_PATH="$VALIDATION_TMP/manifest-b.json"
python "$SKILL_HOME/scripts/ack-manifest.py" --manifest "$PARALLEL_MANIFEST_PATH"

git -C "$VALIDATION_TMP/pa-a" diff --name-only 9203b87...HEAD
git -C "$VALIDATION_TMP/pa-b" diff --name-only 9203b87...HEAD
```

Record both exact ACKs and grants in their Engram records. Report the changed
paths relative to each worktree before post-result validation.

### Expected outcome

Both launches are acknowledged and granted. Each report contains only its own
declared scope, and both results are eligible as RDD receipt input after exact
diff/status comparison.

### Red flags

- Either grant was issued before ACK comparison.
- One report contains a path owned by the other agent.
- A successful ACK is treated as a receipt or delivery authorization.
- A worktree other than `pa-a` or `pa-b` was modified.

## Case 2 — Overlapping ownership is rejected

### Prerequisites

Keep manifest A active. Prepare manifest B with an overlapping scope such as
`allowed_writes=["app/modules/auth/service.py"]` or `app/modules/auth/**`.

### Commands

```bash
# Register B through the coordinator's collision check; do not grant it.
export PARALLEL_MANIFEST_PATH="$VALIDATION_TMP/manifest-b-overlap.json"
python "$SKILL_HOME/scripts/ack-manifest.py" --manifest "$PARALLEL_MANIFEST_PATH"
git -C "$VALIDATION_TMP/pa-b" status --porcelain
```

Compare B's allowed globs with A using the concrete algorithm in

### Expected outcome

B transitions to `rejected` before a grant. `pa-b` remains clean and receives no
authorized edit. A transfer record, not a second ACK alone, is required before
the path can change owners.

### Red flags

- The coordinator relies only on currently existing files and grants an
  uncertain wildcard overlap.
- B is allowed to edit before transfer.
- The rejected worktree contains an authorized change.

## Case 3 — Missing or tampered ACK fails closed

### Prerequisites

Prepare a valid manifest C and record its exact bytes/hash, but do not record its
ACK. Then make a copy and alter a field without recomputing the registered hash.

### Commands

```bash
export PARALLEL_MANIFEST_PATH="$VALIDATION_TMP/manifest-c.json"
set +e
python "$SKILL_HOME/scripts/ack-manifest.py" --manifest "$PARALLEL_MANIFEST_PATH"
missing_ack_status=$?
set -e

python - "$VALIDATION_TMP/manifest-c.json" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
tampered = path.read_text(encoding="utf-8").replace('"owner":"agent-c"', '"owner":"agent-other"')
path.write_text(tampered, encoding="utf-8")
PY
set +e
python "$SKILL_HOME/scripts/ack-manifest.py" --manifest "$PARALLEL_MANIFEST_PATH"
tampered_status=$?
set -e
printf 'missing=%s tampered=%s\n' "$missing_ack_status" "$tampered_status"
```

The coordinator must also compare any captured ACK against the registered
`agent_id`, `launch_id`, and hash; do not accept a line copied from another
launch.

### Expected outcome

The missing-ACK launch never reaches `granted`. The altered manifest exits
non-zero and receives no grant, receipt input, or delivery authorization.

### Red flags

- A valid-looking ACK is accepted after manifest bytes changed.
- The coordinator rehashes the altered bytes instead of comparing the stored
  hash.
- Work starts while the ledger is only `registered`.

## Case 4 — Undeclared or cross-root path is denied

### Prerequisites

Use a manifest whose `allowed_writes` contains only `app/modules/auth/**`, whose
`commit` gate is true with an open human gate, and whose `worktree_root` matches
`pa-a`.

### Commands

```bash
export PARALLEL_MANIFEST_PATH="$VALIDATION_TMP/manifest-a.json"
git -C "$VALIDATION_TMP/pa-a" add README.sh
set +e
(cd "$VALIDATION_TMP/pa-a" && "$PWD/app/scripts/parallel-agents/pre-commit-hook.sh")
undeclared_status=$?
set -e
git -C "$VALIDATION_TMP/pa-a" reset -q README.sh

# Change only the manifest root, keep its hash internally consistent, and run
# the same hook from pa-a.
set +e
(cd "$VALIDATION_TMP/pa-a" && PARALLEL_MANIFEST_PATH="$VALIDATION_TMP/manifest-wrong-root.json" "$PWD/app/scripts/parallel-agents/pre-commit-hook.sh")
set -e
printf 'undeclared=%s cross-root=%s\n' "$undeclared_status" "$cross_root_status"
```

When the clone path differs from the installed hook path, replace `$PWD` above
with the fresh clone's absolute root.

### Expected outcome

Both invocations exit non-zero and print
`parallel-agents: denied: <reason>`. The staged undeclared path is not granted;
the root mismatch is denied before any path allowance is considered.

### Red flags

- The hook resolves a root from `PARALLEL_MANIFEST_PATH` instead of Git.
- `README.sh` is treated as documentation and bypasses the normal path gate.
- A relative or foreign worktree path is accepted.

## Case 5 — Unauthorized push or PR is denied

### Prerequisites

Use a manifest with `push=false`, no `human_gate_id`, or a branch/head that does
not match the current worktree. Configure a temporary bare remote only if the
pre-push adapter needs one.

### Commands

```bash
export PARALLEL_MANIFEST_PATH="$VALIDATION_TMP/manifest-a-no-push.json"
head_sha=$(git -C "$VALIDATION_TMP/pa-a" rev-parse HEAD)
base_sha=9203b87
set +e
printf 'refs/heads/validation/pa-a %s refs/heads/validation/pa-a %s\n' "$head_sha" "$base_sha" |
  (cd "$VALIDATION_TMP/pa-a" && "$PWD/app/scripts/parallel-agents/pre-push-hook.sh" origin ignored-url)
(cd "$VALIDATION_TMP/pa-a" && "$PWD/app/scripts/parallel-agents/pre-pr-check.sh" --head other-branch)
pr_status=$?
set -e
printf 'push=%s pr=%s\n' "$push_status" "$pr_status"
```

### Expected outcome

Both commands exit non-zero with the standard denial prefix. Neither action
creates a receipt or delivery authorization; a valid implementation must still
wait for native RDD human delivery authorization.

### Red flags

- A clean diff or successful ACK implicitly authorizes push/PR creation.
- A composed, environment-prefixed, or mismatched PR head is accepted.
- The hook creates an alternate delivery path around RDD branch protection.

## Cleanup and evidence

Save the nine hook results, five case outcomes, exact ACK lines, and the final
`git status --porcelain` output in the validation record. Then remove only the
temporary clone/worktrees. Never remove or reset the active
`pr5b-metrics-outage-wiring` worktree as part of cleanup.
