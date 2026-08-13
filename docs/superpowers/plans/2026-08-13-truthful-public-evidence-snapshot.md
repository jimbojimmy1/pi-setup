# Truthful Public Evidence Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the dashboard available and truthful when historical public observations contain malformed values or valid checkout evidence falls outside the display window.

**Architecture:** Add one focused SQLite store query that returns the newest valid binary public observation for a metric and optional experiment. Sanitize all displayed observation values, and derive availability/checkout status from the focused query rather than the bounded display history.

**Tech Stack:** Python 3.11, SQLite, Flask, `unittest`.

---

### Task 1: Latest valid public binary observation query

**Files:**
- Modify: `money_agent/store.py`
- Test: `tests/test_observation_store.py`

- [ ] **Step 1: Write the failing store test**

Create two experiments and insert valid `public_http` 0/1 rows plus newer rows
with text, BLOB, infinity, out-of-domain values, invalid timestamps, the wrong
metric, and the wrong source. Assert:

```python
self.assertEqual(
    self.store.latest_public_binary_observation(
        "checkout_readiness", experiment_id=first_id
    )["evidence_ref"],
    "checkout:valid",
)
self.assertEqual(
    self.store.latest_public_binary_observation("public_availability")["evidence_ref"],
    "health:valid",
)
```

Also assert a missing metric returns `None` and blank metrics or Boolean
experiment IDs raise `ValueError`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m unittest tests.test_observation_store.ObservationStoreTest.test_latest_public_binary_observation_fails_closed_and_falls_back -v
```

Expected: error because `latest_public_binary_observation` does not exist.

- [ ] **Step 3: Implement the focused query**

Add `latest_public_binary_observation(metric, experiment_id=None)` to
`money_agent/store.py`. Require non-empty text for `metric`; if an experiment ID
is supplied, require a non-Boolean positive integer. Execute an ordered query
with these conditions:

```sql
source_kind='public_http'
AND metric=?
AND typeof(value) IN ('integer','real')
AND value IN (0,1)
AND typeof(observed_at) IN ('integer','real')
AND observed_at > 0
```

Optionally append `AND experiment_id=?`, order by `observed_at DESC, id DESC`,
and iterate the cursor. Return the first row whose native Python value and time
are `int`/`float` and finite; otherwise continue. Return `None` at exhaustion.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2. Expected: one passing test.

### Task 2: API value sanitization and independent status snapshots

**Files:**
- Modify: `money_agent/app.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing API regressions**

Add one test that inserts a valid checkout 1 followed by malformed BLOB, text,
infinite, and value 2 rows. Assert `/api/state` returns 200, malformed display
values are `null`, and checkout readiness falls back to the valid row.

Add another test that inserts valid checkout evidence, then 100 newer analytics
observations in another experiment. Assert the public `observations` list stays
at 100 while the checkout status still reports the valid project evidence.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_dashboard.DashboardStateTest.test_malformed_public_values_fail_closed_with_valid_fallback tests.test_dashboard.DashboardStateTest.test_checkout_snapshot_is_independent_of_display_window -v
```

Expected: the first test receives HTTP 500 or a false value, and the second
reports no checkout evidence.

- [ ] **Step 3: Sanitize displayed values**

In `_public_observation`, accept `value` only when its exact Python type is
`int` or `float` and `math.isfinite(float(value))`. For `public_http`
`public_availability` and `checkout_readiness`, additionally require the numeric
value to be exactly 0 or 1. Set every rejected value to `None`; normalize an
accepted value to `float`.

- [ ] **Step 4: Derive status from focused store snapshots**

Change `_latest_availability` to accept one already-sanitized observation or
`None`. Change `_checkout_readiness` to request and sanitize
`store.latest_public_binary_observation("checkout_readiness", experiment["id"])
` for each checkout experiment. In `api_state`, request and sanitize
`store.latest_public_binary_observation("public_availability")` separately from
the bounded observation list.

Consumers must treat `None` value/time as missing and must never coerce text or
BLOB data.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the command from Step 2. Expected: two passing tests.

### Task 3: Documentation, verification, and recoverable PR

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Document the trust boundary**

State that the 100-row observation list is display history only, status uses
the newest valid per-monitor snapshot, invalid public values fail closed, and
none of these signals proves checkout success or revenue.

- [ ] **Step 2: Run complete verification**

Run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q money_agent tests
git diff --check
```

Then run all shell syntax, preflight, and installer checks with Git Bash.
Expected: every command exits zero.

- [ ] **Step 3: Commit implementation and handoff separately**

Record the exact passing test count, unchanged `$0.00` verified revenue,
unknown Pi deployment state, owner approval boundary, and local/remote PR state.

- [ ] **Step 4: Push and confirm PR CI**

Push the existing feature branch and run:

```bash
gh pr view 1 --json state,isDraft,mergeable,headRefOid,statusCheckRollup,url
```

Expected: PR #1 remains open, draft, mergeable, and its successful CI head
matches local HEAD.

