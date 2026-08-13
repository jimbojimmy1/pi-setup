# Long-Ledger Evidence Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make observation retries exactly idempotent regardless of ledger length.

**Architecture:** Add a validated store lookup for the database's declared observation identity and use it before and after ingestion. Replace bounded history scans in public collectors with the same lookup while preserving bounded display APIs.

**Tech Stack:** Python 3.11, SQLite, `unittest`.

---

### Task 1: Exact observation identity lookup

**Files:**
- Modify: `money_agent/store.py`
- Test: `tests/test_observation_store.py`

- [ ] **Step 1: Write the failing lookup test**

Insert two observations with different identity triples and assert:

```python
found = self.store.find_observation(
    experiment_id, "analytics_readonly", "analytics:event-123"
)
self.assertEqual(found["id"], observation_id)
self.assertIsNone(
    self.store.find_observation(
        experiment_id, "analytics_readonly", "analytics:missing"
    )
)
```

Assert `ValueError` for Boolean/non-positive experiment IDs, blank source,
blank reference, source longer than 64 characters, and reference longer than
512 characters.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest tests.test_observation_store.ObservationStoreTest.test_find_observation_uses_exact_validated_identity -v
```

Expected: error because `find_observation` does not exist.

- [ ] **Step 3: Implement the exact lookup**

Validate inputs without coercing them, execute:

```sql
SELECT * FROM observations
WHERE experiment_id=? AND source_kind=? AND evidence_ref=?
LIMIT 1
```

and return `dict(row)` or `None`.

- [ ] **Step 4: Verify GREEN**

Run the command from Step 2. Expected: one passing test.

### Task 2: Idempotent ingestion beyond 100 rows

**Files:**
- Modify: `money_agent/monitoring.py`
- Test: `tests/test_monitoring.py`

- [ ] **Step 1: Write the failing long-ledger retry test**

Accept one analytics observation, accept 100 newer unique observations, record
the experiment status, result, event count, and lesson count, then retry the
oldest identity with different numeric fields and `outcome="won"`. Assert the
original row is returned and all recorded counts/state remain unchanged.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest tests.test_monitoring.MonitoringTest.test_old_evidence_retry_is_idempotent_beyond_history_window -v
```

Expected: `StopIteration` or a changed event/status count.

- [ ] **Step 3: Replace bounded scans in ingestion**

After structural validation of source, metric, and evidence reference, call:

```python
existing = store.find_observation(experiment_id, source_kind, evidence_ref)
if existing is not None:
    return existing
```

Keep numeric and outcome validation before this lookup so malformed retries do
not bypass the strict input contract. After `add_observation`, retrieve with
`find_observation`; raise `MonitoringError` if it unexpectedly returns `None`.

- [ ] **Step 4: Verify GREEN**

Run the command from Step 2. Expected: one passing test.

### Task 3: Collector exact lookup

**Files:**
- Modify: `money_agent/monitoring.py`
- Test: `tests/test_monitoring.py`

- [ ] **Step 1: Write a failing collector regression**

Patch `store.list_observations` to raise if called, create the current bucket
observation, and call `collect_public_health` and `collect_checkout_readiness`
for the same bucket. Assert both return their original rows without invoking a
network connector.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest tests.test_monitoring.MonitoringTest.test_collectors_use_exact_identity_lookup -v
```

Expected: failure because collectors call `list_observations`.

- [ ] **Step 3: Use `find_observation` in both collectors**

Replace each generator scan with:

```python
existing = store.find_observation(experiment_id, "public_http", evidence_ref)
```

Return it when non-`None`.

- [ ] **Step 4: Verify GREEN**

Run the command from Step 2. Expected: one passing test.

### Task 4: Documentation, verification, and handoff

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Document durable idempotency**

State that retries use the exact database identity rather than display history,
the first accepted row wins, and retries create no event, outcome, or lesson.

- [ ] **Step 2: Run complete verification**

Run all Python tests, compile checks, `git diff --check`, shell syntax checks,
the deployment preflight suite, and installer suite. Every command must exit
zero.

- [ ] **Step 3: Commit and update the durable handoff**

Record exact test count, unchanged `$0.00` verified revenue, unknown Pi release,
approval boundary, commits, and PR state.

- [ ] **Step 4: Push and verify CI**

Push the existing branch and confirm PR #1 remains open, draft, mergeable, with
successful CI on the same head SHA.

