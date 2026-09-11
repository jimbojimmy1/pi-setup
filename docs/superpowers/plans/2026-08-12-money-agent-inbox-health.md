# Money Agent Inbox and Public Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the daemon safely consume locally deposited observation files and record bounded public availability evidence without confusing uptime with conversions or revenue.

**Architecture:** Add an `inbox.py` module that atomically claims JSON files inside the configured artifact root, delegates parsing and policy to existing modules, and archives accepted/rejected inputs with restrictive permissions. Extend `monitoring.py` with a direct-IP HTTPS probe that validates every resolved address, follows no redirects, caps work, and records one idempotent availability observation per time bucket. The agent runs both before exporting or researching work.

**Tech Stack:** Python 3 standard library, SQLite, TLS sockets, `unittest`

---

### Task 1: Atomic observation inbox

**Files:**
- Create: `money_agent/inbox.py`
- Create: `tests/test_inbox.py`
- Modify: `setup-money-agent.sh`
- Modify: `tests/test_installer.sh`

- [ ] Write failing tests for root containment, atomic claim/archive, accepted/rejected separation, symlink rejection, bounded file count, idempotency, and secret-free result summaries.
- [ ] Run `python3 -m unittest tests.test_inbox -v` and verify RED.
- [ ] Implement `process_inbox(artifact_root, limit=25)` using only `observation-inbox/{incoming,processing,accepted,rejected}` under the resolved root.
- [ ] Run focused and full tests, then commit `feat: process atomic observation inbox`.

### Task 2: Bounded public-health observations

**Files:**
- Modify: `money_agent/monitoring.py`
- Modify: `tests/test_monitoring.py`

- [ ] Write failing tests for direct validated-IP connection, no redirects, timeout/response limits, one observation per bucket, availability-only values, and no terminal or revenue effects.
- [ ] Run `python3 -m unittest tests.test_monitoring -v` and verify RED.
- [ ] Implement the minimal TLS `HEAD` probe and `collect_public_health` policy.
- [ ] Run focused and full tests, then commit `feat: collect bounded public health evidence`.

### Task 3: Agent integration and operations

**Files:**
- Modify: `money_agent/agent.py`
- Modify: `tests/test_agent_experiments.py`
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] Write failing integration tests proving inbox processing and health collection happen before export/research.
- [ ] Add bounded calls to the start of `Agent.tick` with errors recorded but not allowed to kill the daemon.
- [ ] Document deposit paths, archive behavior, public-health semantics, and remaining connector/payment blockers.
- [ ] Run `bash -n setup-money-agent.sh`, `bash tests/test_installer.sh`, `python3 -m unittest discover -s tests -v`, and `git diff --check`.
- [ ] Commit, push, update PR #1, and keep it draft.
