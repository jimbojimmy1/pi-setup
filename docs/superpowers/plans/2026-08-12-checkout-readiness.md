# Checkout readiness implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect whether an owned public page presents a recognized Stripe or PayPal checkout destination without opening or modifying checkout.

**Architecture:** Extend `money_agent/monitoring.py` with one bounded direct-IP HTTPS GET that reuses public-address validation, TLS hostname verification, time limits, byte limits, and no redirects. Parse only HTML anchor `href` and form `action` attributes, accept narrow HTTPS provider patterns, and store one `checkout_readiness` observation per hour. Bootstrap a separate zero-cost public experiment per owned project and dispatch it alongside availability checks.

**Tech stack:** Python 3.11 standard library (`ssl`, `socket`, `html.parser`, `urllib.parse`), SQLite, `unittest`.

---

### Task 1: Detect provider destinations safely

**Files:**
- Modify: `tests/test_monitoring.py`
- Modify: `money_agent/monitoring.py`

- [ ] Write failing tests proving only HTTPS anchor/form destinations on `buy.stripe.com`, `book.stripe.com`, `donate.stripe.com`, `paypal.me`, or PayPal's hosted payment-link path are accepted; provider words, scripts, HTTP URLs, lookalike hosts, and unrelated PayPal pages are rejected.
- [ ] Run the focused tests and confirm they fail because the detector does not exist.
- [ ] Add an `HTMLParser` collector and exact provider-pattern classifier.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Fetch one bounded owned page

**Files:**
- Modify: `tests/test_monitoring.py`
- Modify: `money_agent/monitoring.py`

- [ ] Write failing tests proving one validated direct-IP GET is made with TLS hostname verification, no redirect follow, a 10-second default timeout capped at 30 seconds, and a 64 KiB response cap.
- [ ] Add the minimal TLS GET connector and `probe_checkout_readiness` result containing only page URL, HTTP status, readiness boolean, and provider name.
- [ ] Add an hourly, deduplicated `collect_checkout_readiness` observation that cannot report revenue or close an experiment.
- [ ] Run the monitoring suite and confirm it passes.

### Task 3: Bootstrap and schedule checks

**Files:**
- Modify: `tests/test_agent_experiments.py`
- Modify: `money_agent/agent.py`

- [ ] Write failing tests for one idempotent `AUTO_LOCAL` checkout-readiness experiment per valid owned-project URL and metric-based monitor dispatch.
- [ ] Import the collector, add the bootstrap method, call it before inbox processing, and dispatch `checkout_readiness` experiments to the new collector.
- [ ] Run the agent tests and confirm they pass.

### Task 4: Verify and hand off

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] Document exact provider patterns and state that readiness is not a sale, active provider account, successful checkout, or revenue.
- [ ] Run installer syntax, installer preservation, all Python tests, and `git diff --check`.
- [ ] Commit only planned files, push the existing branch, wait for GitHub CI, and keep PR #1 open and draft.
