# Checkout dashboard status implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the newest checkout-readiness observation and keep the missing-link blocker until matching positive evidence exists.

**Architecture:** `money_agent/app.py` will join public observations to checkout-readiness experiments by experiment ID, return only project, readiness, observation time, and age, and derive the missing-link blocker from that same matched evidence. Missing or zero evidence keeps the blocker; a positive value removes only that blocker. The template will render a named status and repeat that readiness does not prove a payment.

**Tech stack:** Python 3.11, Flask, SQLite, vanilla HTML/JavaScript, `unittest`.

---

### Task 1: Add evidence-aware API status

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `money_agent/app.py`

- [ ] Write failing tests for missing, zero, and positive checkout evidence. Assert zero/missing evidence keeps the FunnelSleuth link blocker, positive matching evidence removes only that blocker, and unrelated observations cannot clear it.
- [ ] Run focused dashboard tests and confirm they fail because `checkout_readiness` is absent and blockers are static.
- [ ] Add a project-scoped checkout summary and pass it to `_owner_blockers`.
- [ ] Run focused tests and confirm they pass.

### Task 2: Render the named status

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `money_agent/templates/index.html`

- [ ] Write a failing template contract test for `CHECKOUT READINESS`, ready/not-ready/no-evidence states, observation age, and the “not a payment” boundary.
- [ ] Add the minimal panel and escaped client rendering.
- [ ] Run the focused test and confirm it passes.

### Task 3: Verify and hand off

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] Document blocker behavior and state that readiness does not prove an active account, successful checkout, payment, or revenue.
- [ ] Run installer syntax, installer preservation, all Python tests, and `git diff --check`.
- [ ] Commit only planned files, push the existing branch, wait for GitHub CI, and keep PR #1 open and draft.
