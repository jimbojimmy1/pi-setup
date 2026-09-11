# Money Agent Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fail-closed experiment monitoring that records deduplicated evidence, blocks experiments without a trustworthy measurement source, and never treats traffic as revenue.

**Architecture:** Extend SQLite with a measurement source on experiments and a structured observation ledger. A focused `monitoring.py` module validates source types and public URLs, records evidence idempotently, and applies conservative state transitions. The daemon runs monitoring before exporting or researching work; the dashboard exposes only sanitized observations and blockers.

**Tech Stack:** Python 3 standard library, SQLite, Flask, `unittest`

---

### Task 1: Persist measurement sources and observations

**Files:**
- Modify: `money_agent/store.py`
- Create: `tests/test_observation_store.py`

- [ ] **Step 1: Write the failing schema and idempotency tests**

Test an additive migration, `add_observation`, duplicate `evidence_ref` handling, `list_observations`, and `update_experiment_status` with a temporary SQLite database.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_observation_store -v`

Expected: fail because the observation functions and columns do not exist.

- [ ] **Step 3: Add the additive schema and store functions**

Add `measurement_source TEXT NOT NULL DEFAULT ''` to `experiments`. Add an `observations` table containing experiment, source kind, metric, numeric value, revenue, evidence reference, observed time, and created time. Enforce `UNIQUE(experiment_id, source_kind, evidence_ref)`. Store functions must return an existing observation ID on a duplicate rather than insert twice.

- [ ] **Step 4: Run the focused and full suites**

Run: `python3 -m unittest tests.test_observation_store -v && python3 -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
git add money_agent/store.py tests/test_observation_store.py
git commit -m "feat: persist trusted experiment observations"
```

### Task 2: Add fail-closed monitoring policy

**Files:**
- Create: `money_agent/monitoring.py`
- Create: `tests/test_monitoring.py`

- [ ] **Step 1: Write failing policy tests**

Test that private, loopback, link-local, reserved, non-HTTPS, credential-bearing, and non-default-port URLs are rejected. Test that an experiment with no source becomes `blocked`, an allowed matching observation becomes `measuring`, duplicate evidence remains one row, and revenue is rejected unless the source is `payment_provider_readonly` or `owner_verified`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_monitoring -v`

Expected: fail because `money_agent.monitoring` does not exist.

- [ ] **Step 3: Implement the policy**

Use `urllib.parse`, `socket.getaddrinfo`, and `ipaddress.ip_address`. Allow only these evidence source types: `analytics_readonly`, `payment_provider_readonly`, `owner_verified`, and `public_http`. Unknown types fail closed. Public HTTP evidence records availability only; it cannot carry revenue or mark a sale. Missing sources generate one deduplicated blocker event.

- [ ] **Step 4: Run the focused and full suites**

Run: `python3 -m unittest tests.test_monitoring -v && python3 -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
git add money_agent/monitoring.py tests/test_monitoring.py
git commit -m "feat: enforce fail-closed experiment monitoring"
```

### Task 3: Wire monitoring into the agent and dashboard

**Files:**
- Modify: `money_agent/agent.py`
- Modify: `money_agent/app.py`
- Modify: `money_agent/templates/index.html`
- Modify: `setup-money-agent.sh`
- Modify: `tests/test_agent_experiments.py`
- Modify: `tests/test_dashboard.py`
- Modify: `tests/test_installer.sh`

- [ ] **Step 1: Write failing integration tests**

Require `measurement_source` in promoted experiment output, verify missing sources become blocked before new research, expose sanitized observations in `/api/state`, and require `monitoring.py` in an installed runtime.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -m unittest tests.test_agent_experiments tests.test_dashboard -v && bash tests/test_installer.sh`

- [ ] **Step 3: Add the minimal integration**

Extend the judge schema and prompt, persist the source, call monitoring at the start of a tick, add public observation fields to the dashboard, and include `monitoring.py` in installer validation.

- [ ] **Step 4: Run all verification**

Run: `bash -n setup-money-agent.sh && bash tests/test_installer.sh && python3 -m unittest discover -s tests -v && git diff --check`

- [ ] **Step 5: Commit**

```bash
git add money_agent/agent.py money_agent/app.py money_agent/templates/index.html setup-money-agent.sh tests
git commit -m "feat: surface evidence-backed experiment monitoring"
```

### Task 4: Refresh the handoff and pull request

**Files:**
- Modify: `HANDOFF.md`
- Modify: `MONEY_AGENT.md`

- [ ] **Step 1: Document source types and evidence semantics**

State that observation import is read-only, payment/analytics connectors remain unconfigured, public health cannot prove revenue, and checkout still needs owner authentication.

- [ ] **Step 2: Run fresh verification and update exact results**

Run: `bash -n setup-money-agent.sh && bash tests/test_installer.sh && python3 -m unittest discover -s tests -v && git diff --check`

- [ ] **Step 3: Commit, push, and update PR #1**

```bash
git add HANDOFF.md MONEY_AGENT.md
git commit -m "docs: hand off evidence-backed monitoring"
git push origin claude/money-making-agent-debate-fp1ag2
```

Keep the PR draft. Record the next safe step without claiming revenue.
