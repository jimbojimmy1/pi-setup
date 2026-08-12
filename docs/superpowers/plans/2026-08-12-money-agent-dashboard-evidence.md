# Dashboard evidence visibility implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show safe inbox counts and the latest public availability evidence on the existing dashboard.

**Architecture:** `money_agent/app.py` will count only regular `.json` entries in the four fixed inbox directories and summarize the newest `public_http`/`public_availability` observation already returned by the store. The API will expose counts and a status/time summary, never filenames, evidence references, or payloads. The existing template will render those fields without adding a new endpoint or database table.

**Tech stack:** Python 3.11, Flask, SQLite, vanilla HTML/JavaScript, `unittest`.

---

### Task 1: Add safe dashboard summaries

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `money_agent/app.py`

- [ ] **Step 1: Write the failing API test**

Create inbox files in each fixed directory, add a newer `public_http` observation with metric `public_availability`, request `/api/state`, and assert exact counts plus `{available, observed_at, age}`. Assert filenames, payload text, and `evidence_ref` are absent from the response.

- [ ] **Step 2: Run the focused test and verify RED**

Run `python -m unittest tests.test_dashboard.DashboardStateTest.test_state_exposes_inbox_counts_and_latest_availability_without_file_details -v`.

Expected: failure because `inbox` and `availability` are absent.

- [ ] **Step 3: Add minimal server-side summaries**

Add `_inbox_counts()` that inspects only `observation-inbox/{incoming,processing,accepted,rejected}`, counts non-symlink regular `.json` files, and returns zero for missing/unreadable directories. Add `_latest_availability(observations)` that selects the first newest `public_http` observation whose metric is `public_availability` and returns only `available`, `observed_at`, and `age`. Include both summaries in `/api/state`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the same focused command. Expected: one passing test.

### Task 2: Render dashboard evidence

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `money_agent/templates/index.html`

- [ ] **Step 1: Write the failing template contract test**

Read the template and assert it includes `INBOX EVIDENCE`, the four count fields, `PUBLIC AVAILABILITY`, and explicit `available`/`unavailable` labels.

- [ ] **Step 2: Run the focused test and verify RED**

Run `python -m unittest tests.test_dashboard.DashboardStateTest.test_template_renders_inbox_and_availability_summaries -v`.

Expected: failure because the panels do not exist.

- [ ] **Step 3: Add minimal read-only panels**

Add one panel for incoming/processing/accepted/rejected counts and one panel showing the latest public availability state and observation age. Escape all displayed values through the existing `esc` helper.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the same focused command. Expected: one passing test.

### Task 3: Verify and hand off

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Document the dashboard fields and their limits**

State that counts are local file metadata, availability is uptime-only, and neither proves traffic, conversion, checkout, or revenue.

- [ ] **Step 2: Run complete verification**

Run Git Bash installer syntax and migration checks, the complete Python suite, and `git diff --check`. Expected: all commands exit zero.

- [ ] **Step 3: Commit and push to PR #1**

Stage only the planned files, commit with a scoped message, push the current branch, and wait for GitHub CI. Keep the PR open and draft.
