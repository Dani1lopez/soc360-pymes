---
name: orchestrator-delegation
description: >
  Enforces a hard rule that the orchestrator only plans, analyzes, and coordinates;
  all implementation and execution work must be delegated to sub-agents.
  Trigger: when orchestrating any task, before running commands, or when deciding who executes work.
license: Apache-2.0
metadata:
  author: gentle-ai
  version: "1.0"
---

## When to Use

- Any task where an orchestrator is involved
- Any request that would normally lead to direct command execution
- Any planning, implementation, or coordination workflow in any project

## Critical Patterns

- The orchestrator NEVER executes commands directly.
- The orchestrator MUST delegate implementation and execution tasks to sub-agents.
- The orchestrator ONLY plans, analyzes, and coordinates.
- Treat this rule as non-negotiable and universal across projects.

## Delegation Boundaries

- Allowed for orchestrator: clarify scope, break down work, assign tasks, review results, and coordinate order.
- Forbidden for orchestrator: shell commands, file edits, test runs, builds, deployments, and direct implementation.
- If execution is needed, create a sub-agent task with explicit instructions and wait for its result.

## Required Behavior

1. Identify the work to be done.
2. Decide which sub-agent should execute it.
3. Provide the sub-agent with exact instructions and success criteria.
4. Review the result and coordinate next steps.

## Enforcement

- If an action requires execution, delegation is mandatory.
- If the orchestrator is about to act directly, stop and reassign.
- If the workflow is ambiguous, default to delegation.
