# Money Agent Deployment Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only local preflight that turns one reviewed commit into transparent, recoverable upgrade and rollback commands without executing them.

**Architecture:** A standalone Bash script validates the reviewed SHA, reads only the bounded installed release marker, classifies release state, and shell-escapes every value used in printed commands. A dedicated shell test places fail-fast command stubs first on `PATH` to prove the preflight invokes no mutating or network tool.

**Tech Stack:** Bash 4+, GitHub Actions, existing Money Agent installer and release marker.

---

### Task 1: Specify read-only behavior with failing tests

**Files:**
- Create: `tests/test_deploy_preflight.sh`
- Modify: `.github/workflows/ci.yml`

- [ ] Write a shell test that expects current/outdated/dirty/unknown states, exact reviewed and rollback commits, shell-escaped paths, and no calls to fake `git`, `curl`, `sudo`, or `systemctl` executables.
- [ ] Run `bash tests/test_deploy_preflight.sh` and confirm it fails because `money-agent-deploy-preflight.sh` does not exist.

### Task 2: Implement the bounded preflight

**Files:**
- Create: `money-agent-deploy-preflight.sh`

- [ ] Require exactly one full commit SHA and exit `2` with usage for invalid input.
- [ ] Read at most one bounded marker line with shell built-ins and classify it without treating a prefix or mutable name as current.
- [ ] Print quoted upgrade commands and print rollback commands only when a distinct clean installed SHA is available.
- [ ] Print `NO_ACTIONS_EXECUTED: true` and never evaluate any displayed command.
- [ ] Run `bash tests/test_deploy_preflight.sh` and confirm it passes.

### Task 3: Document and integrate verification

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_source_layout.py`

- [ ] Document the preflight invocation, output meaning, owner-approval boundary, and exact distinction between printed commands and executed work.
- [ ] Add shell syntax and test steps to CI and assert their presence in the source-layout test.
- [ ] Run the complete Python, installer, preflight, syntax, and diff checks.
- [ ] Commit the implementation and update `HANDOFF.md` with verified results and the next safe action.
