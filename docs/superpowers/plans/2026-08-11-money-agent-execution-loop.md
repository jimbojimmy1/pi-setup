# Money Agent Execution Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert PR #1 into a testable Raspberry Pi service that turns promoted opportunities for owned projects into policy-classified, recoverable work packages for the recurring Codex task.

**Architecture:** Preserve the existing BULL/BEAR/JUDGE logic as normal Python source under `money_agent/`. Add SQLite-backed experiments and a fail-closed policy/export module. Keep `setup-money-agent.sh` as an idempotent installer that copies sibling source when cloned and can fetch the same files when run standalone.

**Tech Stack:** Bash, Python 3 standard library, SQLite, Flask, systemd, `unittest`.

---

### Task 1: Materialize versioned application source

**Files:**
- Create: `money_agent/__init__.py`
- Create: `money_agent/store.py`
- Create: `money_agent/llm.py`
- Create: `money_agent/agent.py`
- Create: `money_agent/app.py`
- Create: `money_agent/templates/index.html`
- Create: `tests/test_source_layout.py`

- [ ] **Step 1: Write the failing source-layout test**

```python
from pathlib import Path
import py_compile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourceLayoutTest(unittest.TestCase):
    def test_runtime_modules_are_versioned_and_compile(self):
        for name in ("store.py", "llm.py", "agent.py", "app.py"):
            path = ROOT / "money_agent" / name
            self.assertTrue(path.is_file(), name)
            py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python3 -m unittest tests.test_source_layout -v`

Expected: FAIL because `money_agent/store.py` does not exist.

- [ ] **Step 3: Copy the known-good generated payload into `money_agent/`**

Run the current installer with `MA_SKIP_APT=1`, `MA_SKIP_SYSTEMD=1`, and a temporary `MONEY_AGENT_DIR`; copy the generated runtime modules and template into `money_agent/`; add an empty `money_agent/__init__.py`. Do not edit behavior during this step.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `python3 -m unittest tests.test_source_layout -v`

Expected: PASS with four compiled modules.

- [ ] **Step 5: Commit**

```bash
git add money_agent tests/test_source_layout.py
git commit -m "refactor: version money agent runtime source"
```

### Task 2: Persist measurable experiments

**Files:**
- Modify: `money_agent/store.py`
- Create: `tests/test_experiment_store.py`

- [ ] **Step 1: Write failing persistence tests**

```python
import importlib
import os
from pathlib import Path
import tempfile
import unittest


class ExperimentStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MA_DB"] = str(Path(self.tmp.name) / "money.db")
        import money_agent.store as store
        self.store = importlib.reload(store)
        self.store.init()

    def tearDown(self):
        self.store.close_connection()
        self.tmp.cleanup()

    def test_add_and_claim_ready_experiment(self):
        idea_id = self.store.add_idea("FunnelSleuth organic landing page")
        experiment_id = self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="build_owned_asset",
            hypothesis="A niche audit page attracts qualified visitors.",
            deliverable="Create one audit page for local roofers.",
            metric="qualified_snapshot_runs",
            window_days=30,
            autonomy_class="CODEX_REVIEWED",
            hours=2,
            cost_usd=0,
        )
        claimed = self.store.claim_experiment(lease_seconds=300)
        self.assertEqual(claimed["id"], experiment_id)
        self.assertEqual(claimed["status"], "exported")

    def test_stale_export_is_recovered(self):
        idea_id = self.store.add_idea("Recover me")
        experiment_id = self.store.add_experiment(
            idea_id, "FunnelSleuth", "write_brief", "h", "d", "m", 7,
            "AUTO_LOCAL", 1, 0,
        )
        self.store.claim_experiment(lease_seconds=-1)
        self.assertEqual(self.store.recover_stale_experiments(), 1)
        self.assertEqual(self.store.get_experiment(experiment_id)["status"], "ready")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_experiment_store -v`

Expected: FAIL because `add_experiment` and `close_connection` are missing.

- [ ] **Step 3: Add schema and store API**

Add `experiments` and `experiment_events` tables described in the design. Implement:

```python
def close_connection():
    c = getattr(_local, "c", None)
    if c is not None:
        c.close()
        _local.c = None


def add_experiment(idea_id, project, action_kind, hypothesis, deliverable,
                   metric, window_days, autonomy_class, hours, cost_usd):
    now = time.time()
    c = conn()
    cur = c.execute(
        "INSERT INTO experiments(idea_id,project,action_kind,hypothesis,deliverable,"
        "metric,window_days,autonomy_class,status,hours,cost_usd,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?, 'ready',?,?,?,?)",
        (idea_id, project, action_kind, hypothesis, deliverable, metric,
         int(window_days), autonomy_class, float(hours), float(cost_usd), now, now),
    )
    c.commit()
    return cur.lastrowid
```

Implement `get_experiment`, `list_experiments`, `claim_experiment`, `recover_stale_experiments`, and append-only `add_experiment_event`. Claims use `BEGIN IMMEDIATE` and set `lease_until`.

- [ ] **Step 4: Run all tests and verify GREEN**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add money_agent/store.py tests/test_experiment_store.py
git commit -m "feat: persist measurable revenue experiments"
```

### Task 3: Add fail-closed autonomy policy and atomic handoff export

**Files:**
- Create: `money_agent/experiments.py`
- Create: `tests/test_experiments.py`

- [ ] **Step 1: Write failing policy and export tests**

```python
import json
from pathlib import Path
import tempfile
import unittest

from money_agent.experiments import classify_action, export_work_package


class ExperimentPolicyTest(unittest.TestCase):
    def test_unknown_and_paid_actions_require_owner(self):
        self.assertEqual(classify_action("unknown", 0), "OWNER_REQUIRED")
        self.assertEqual(classify_action("write_brief", 1), "OWNER_REQUIRED")

    def test_safe_classes_are_explicit(self):
        self.assertEqual(classify_action("write_brief", 0), "AUTO_LOCAL")
        self.assertEqual(classify_action("build_owned_asset", 0), "CODEX_REVIEWED")
        self.assertEqual(classify_action("send_outreach", 0), "OWNER_REQUIRED")
        self.assertEqual(classify_action("fake_review", 0), "REJECTED")

    def test_export_stays_inside_root_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "id": 7,
                "project": "FunnelSleuth",
                "deliverable": "Build page",
                "autonomy_class": "CODEX_REVIEWED",
                "api_key": "must-not-leak",
            }
            paths = export_work_package(payload, Path(td))
            data = json.loads(paths.json_path.read_text())
            self.assertNotIn("api_key", data)
            self.assertTrue(paths.json_path.resolve().is_relative_to(Path(td).resolve()))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_experiments -v`

Expected: FAIL because `money_agent.experiments` is missing.

- [ ] **Step 3: Implement explicit action maps and exporter**

```python
AUTO_LOCAL = {"write_brief", "public_health_check", "analyze_public_data"}
CODEX_REVIEWED = {"build_owned_asset", "edit_owned_site", "draft_pull_request"}
OWNER_REQUIRED = {"send_outreach", "spend_money", "change_payment", "create_account"}
REJECTED = {"fake_review", "spam", "credential_harvest", "evade_terms"}


def classify_action(action_kind, cost_usd):
    if float(cost_usd or 0) > 0:
        return "OWNER_REQUIRED"
    if action_kind in REJECTED:
        return "REJECTED"
    if action_kind in AUTO_LOCAL:
        return "AUTO_LOCAL"
    if action_kind in CODEX_REVIEWED:
        return "CODEX_REVIEWED"
    return "OWNER_REQUIRED"
```

`export_work_package` resolves the root, writes sanitized JSON and Markdown to sibling temporary files, calls `os.replace`, and never serializes keys matching `key`, `token`, `secret`, `password`, `cookie`, or `authorization` case-insensitively.

- [ ] **Step 4: Run all tests and verify GREEN**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add money_agent/experiments.py tests/test_experiments.py
git commit -m "feat: export policy-checked automation handoffs"
```

### Task 4: Focus the debate loop on the owned revenue project

**Files:**
- Create: `money_agent/profile.json`
- Modify: `money_agent/agent.py`
- Modify: `money_agent/store.py`
- Create: `tests/test_agent_experiments.py`

- [ ] **Step 1: Write a failing experiment-conversion test**

Create a test that passes a promoted judge result containing:

```python
judge = {
    "verdict": "PROMOTE",
    "score": 82,
    "experiment": {
        "project": "FunnelSleuth",
        "action_kind": "build_owned_asset",
        "hypothesis": "A roofer-specific page produces qualified snapshot runs.",
        "deliverable": "Create one evidence-led roofer audit page.",
        "metric": "qualified_snapshot_runs",
        "window_days": 30,
        "hours": 2,
        "cost_usd": 0,
        "stop_condition": "Stop after 30 days with zero qualified runs."
    }
}
```

Assert `Agent.persist_experiment(idea_id, judge)` creates exactly one deduplicated `CODEX_REVIEWED` experiment and exports it on the next work cycle.

- [ ] **Step 2: Run test and verify RED**

Run: `python3 -m unittest tests.test_agent_experiments -v`

Expected: FAIL because `persist_experiment` is missing.

- [ ] **Step 3: Extend the judge schema and prompt**

Require one `experiment` object for `PROMOTE` and allow an empty object otherwise. Add a prompt rule that owned projects come first and every metric must name an observable source. Validate the object before insertion; classification is deterministic and ignores any model-supplied autonomy class.

- [ ] **Step 4: Add FunnelSleuth to the default profile**

```json
{
  "owned_projects": [
    {
      "name": "FunnelSleuth",
      "url": "https://funnelsleuth.stinkchimp.chatgpt.site",
      "offers_usd": [79, 299],
      "constraint": "Checkout requires one owner-authenticated payment-link setup.",
      "objective": "Earn qualified organic traffic and improve conversion without spam."
    }
  ]
}
```

Merge this object into the existing profile rather than removing skills, assets, constraints, goal, or notes.

- [ ] **Step 5: Run all tests and verify GREEN**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add money_agent/agent.py money_agent/store.py money_agent/profile.json tests/test_agent_experiments.py
git commit -m "feat: turn promoted ideas into owned-project experiments"
```

### Task 5: Show experiments and blockers on the dashboard

**Files:**
- Modify: `money_agent/app.py`
- Modify: `money_agent/templates/index.html`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing API test**

Use Flask's test client with a temporary database. Assert `/api/state` returns `experiments`, `next_work`, and `owner_blockers`, and does not return any environment secret.

- [ ] **Step 2: Run test and verify RED**

Run: `python3 -m unittest tests.test_dashboard -v`

Expected: FAIL because the keys are absent.

- [ ] **Step 3: Add experiment payload and three dashboard sections**

Add `EXPERIMENTS`, `NEXT AUTOMATED WORK`, and `OWNER BLOCKERS` sections. Render autonomy and status as text, never as trusted HTML. Keep the existing leaderboard, debate, lessons, and kill log.

- [ ] **Step 4: Run all tests and verify GREEN**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add money_agent/app.py money_agent/templates/index.html tests/test_dashboard.py
git commit -m "feat: surface experiments and automation blockers"
```

### Task 6: Replace the monolithic installer with a source installer

**Files:**
- Modify: `setup-money-agent.sh`
- Create: `tests/test_installer.sh`

- [ ] **Step 1: Write failing installer test**

```bash
#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
MONEY_AGENT_DIR="$tmp/app" MA_SKIP_APT=1 MA_SKIP_SYSTEMD=1 \
  bash "$root/setup-money-agent.sh"
for file in store.py llm.py agent.py experiments.py app.py profile.json templates/index.html; do
  cmp "$root/money_agent/$file" "$tmp/app/$file"
done
python3 -m py_compile "$tmp/app/"*.py
```

- [ ] **Step 2: Run test and verify RED**

Run: `bash tests/test_installer.sh`

Expected: FAIL because the current installer does not install `experiments.py` or the versioned profile.

- [ ] **Step 3: Rewrite installer to copy canonical source**

The installer must:

1. preserve existing `config.env` and `profile.json`;
2. copy sibling `money_agent/` source when present;
3. when no sibling source exists, download the exact `MA_RELEASE_REF` files from `raw.githubusercontent.com/jimbojimmy1/pi-setup` into a temporary staging directory;
4. validate every required file before replacing the installed runtime;
5. install the existing two systemd services only when `MA_SKIP_SYSTEMD != 1`;
6. retain the daily spend cap and port 8086.

- [ ] **Step 4: Run installer and Python tests**

Run:

```bash
bash -n setup-money-agent.sh
bash tests/test_installer.sh
python3 -m unittest discover -s tests -v
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add setup-money-agent.sh tests/test_installer.sh
git commit -m "refactor: install canonical money agent source"
```

### Task 7: Create the durable handoff and update PR #1

**Files:**
- Create: `HANDOFF.md`
- Modify: `README.md` if the repository has one; otherwise create `MONEY_AGENT.md`

- [ ] **Step 1: Run complete verification**

```bash
bash -n setup-money-agent.sh
bash tests/test_installer.sh
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all commands exit 0 with zero failed tests.

- [ ] **Step 2: Write `HANDOFF.md`**

Record the objective, PR URL, branch and HEAD SHA, architecture, files changed, exact verification output, current experiment, owner-required blockers, and one next action. Do not include secrets or unverified revenue claims.

- [ ] **Step 3: Write operator documentation**

Document install, upgrade, rollback, dashboard URL, environment settings, autonomy classes, artifact paths, heartbeat behavior, and the one-time payment-link blocker.

- [ ] **Step 4: Commit and push**

```bash
git add HANDOFF.md MONEY_AGENT.md
git commit -m "docs: hand off the money agent execution loop"
git push origin claude/money-making-agent-debate-fp1ag2
```

- [ ] **Step 5: Update the pull request description**

Add the bounded execution loop, test evidence, migration/rollback notes, remaining owner blocker, and truthful scope: the system prepares and implements safe experiments but does not claim earnings until a payment is observed.
