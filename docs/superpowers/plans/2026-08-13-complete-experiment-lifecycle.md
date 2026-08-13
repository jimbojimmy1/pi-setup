# Complete Experiment Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure daemon lifecycle work includes every persisted experiment while the public dashboard remains capped at 50 experiments.

**Architecture:** Extend the existing store query with an explicit `None` mode that omits SQL `LIMIT`; retain the current bounded default. Internal daemon lifecycle callers opt into the complete scan, while the dashboard makes no code change.

**Tech Stack:** Python 3.11, SQLite, `unittest`.

---

### Task 1: Store query contract

**Files:**
- Modify: `money_agent/store.py`
- Test: `tests/test_experiment_store.py`

- [ ] **Step 1: Write the failing bounded/unbounded query test**

Add a test that inserts 55 experiments and asserts:

```python
self.assertEqual(len(self.store.list_experiments()), 50)
self.assertEqual(len(self.store.list_experiments(limit=None)), 55)
```

Also assert that `limit=0`, `limit=-1`, and `limit=True` raise `ValueError`, so accidental invalid bounds fail closed.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m unittest tests.test_experiment_store.ExperimentStoreTest.test_list_experiments_keeps_display_bound_and_supports_complete_scan -v
```

Expected: error because `int(None)` is invalid.

- [ ] **Step 3: Implement the store mode**

Change `list_experiments` to:

```python
def list_experiments(limit=50):
    if limit is None:
        rows = conn().execute(
            "SELECT * FROM experiments ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    else:
        if isinstance(limit, bool) or int(limit) < 1:
            raise ValueError("experiment limit must be a positive integer or None")
        rows = conn().execute(
            "SELECT * FROM experiments ORDER BY updated_at DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run the focused store test and verify GREEN**

Run the command from Step 2. Expected: one passing test.

### Task 2: Complete daemon lifecycle callers

**Files:**
- Modify: `money_agent/agent.py`
- Test: `tests/test_agent_experiments.py`

- [ ] **Step 1: Write failing lifecycle regressions**

Create 51 experiments so the oldest experiment falls outside the default
window. Assert `monitor_experiments()` still invokes `monitor_experiment` for
the oldest ID. Separately create an old `prepare_verified_revenue_lane`, add 50
newer filler experiments, and assert `bootstrap_owned_revenue_lanes()` returns
zero and does not create a duplicate lane.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_agent_experiments.AgentExperimentTest.test_monitoring_scans_beyond_dashboard_window tests.test_agent_experiments.AgentExperimentTest.test_revenue_bootstrap_finds_lane_beyond_dashboard_window -v
```

Expected: the oldest ID is absent from monitoring and the bootstrap returns
one instead of zero.

- [ ] **Step 3: Opt lifecycle callers into complete scans**

In `monitor_experiments`, `bootstrap_owned_health_checks`,
`bootstrap_owned_checkout_checks`, and `bootstrap_owned_revenue_lanes`, replace:

```python
store.list_experiments()
```

with:

```python
store.list_experiments(limit=None)
```

- [ ] **Step 4: Run the focused agent tests and verify GREEN**

Run the command from Step 2. Expected: two passing tests.

### Task 3: Documentation and full verification

**Files:**
- Modify: `HANDOFF.md`

- [ ] **Step 1: Run fresh verification**

Run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q money_agent tests
git diff --check
```

Then use Git Bash for:

```bash
bash -n setup-money-agent.sh money-agent-deploy-preflight.sh tests/test_installer.sh tests/test_deploy_preflight.sh
bash tests/test_deploy_preflight.sh
bash tests/test_installer.sh
```

Expected: every command exits zero.

- [ ] **Step 2: Update the durable handoff**

Record the lifecycle fix, exact test count, local/remote commit state, unchanged
`$0.00` verified revenue, unknown Pi deployment state, and the same explicit
owner-approval boundary.

- [ ] **Step 3: Commit, push, and verify PR CI**

Commit implementation and handoff separately, push the existing branch, then
run:

```bash
gh pr view 1 --json state,isDraft,mergeable,headRefOid,statusCheckRollup,url
```

Expected: PR #1 remains open, draft, and mergeable; remote head matches local;
CI completes successfully.

