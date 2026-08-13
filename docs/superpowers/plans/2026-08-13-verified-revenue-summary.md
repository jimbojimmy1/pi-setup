# Verified Revenue Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the owner an explicit all-time verified-revenue answer derived only from deduplicated permitted payment evidence.

**Architecture:** Add one aggregate SQLite query over the complete observation ledger, then expose its bounded fields through the existing state API and dashboard. Keep evidence filtering at storage and presentation copy conservative so uptime, analytics, forecasts, and spend cannot become revenue.

**Tech Stack:** Python 3.11, SQLite, Flask, vanilla JavaScript, unittest.

---

### Task 1: Specify the full-ledger aggregate

**Files:**
- Modify: `tests/test_observation_store.py`
- Modify: `money_agent/store.py`

- [ ] Add a failing test that inserts two permitted payment observations, a duplicate evidence reference, and disallowed analytics/public rows, then expects total `378.0`, count `2`, and the latest permitted timestamp.
- [ ] Run the focused test and confirm it fails because `verified_revenue_summary` does not exist.
- [ ] Implement one parameterized SQLite aggregate filtering positive revenue and the two permitted source kinds.
- [ ] Run the focused storage suite and confirm it passes.

### Task 2: Expose and render verified revenue

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `money_agent/app.py`
- Modify: `money_agent/templates/index.html`

- [ ] Add failing API tests for an empty zero summary and a positive summary whose age is deterministic.
- [ ] Add a failing template test for the `VERIFIED REVENUE` header/panel, amount, payment count, and conservative “recorded” copy.
- [ ] Add the summary to `/api/state`, rounding currency to cents and calculating age without exposing evidence references.
- [ ] Render the header and panel from `d.verified_revenue`, including a clear zero-evidence state.
- [ ] Run the dashboard suite and confirm it passes.

### Task 3: Document, verify, and hand off

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] Document exactly which evidence contributes to the total and which signals are excluded.
- [ ] Run all Python tests, both shell suites, shell syntax checks, and `git diff --check`.
- [ ] Commit the focused changes, request code review, address every Critical or Important finding, and repeat verification.
- [ ] Update the durable handoff, push PR #1, and wait for GitHub Actions success.
