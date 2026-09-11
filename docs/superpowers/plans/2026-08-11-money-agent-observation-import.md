# Money Agent Observation Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict local JSON importer that feeds the existing evidence ledger and makes conservative, evidence-backed experiment outcome transitions.

**Architecture:** A focused `import_observation.py` command parses one bounded JSON object from stdin or a file, rejects unknown or sensitive fields, and delegates to `monitoring.ingest_observation`. The monitoring policy remains authoritative for source matching, revenue semantics, idempotency, and terminal transitions.

**Tech Stack:** Python 3 standard library, SQLite, `unittest`

---

### Task 1: Add strict observation parsing and CLI

**Files:**
- Create: `money_agent/import_observation.py`
- Create: `tests/test_import_observation.py`
- Modify: `setup-money-agent.sh`
- Modify: `tests/test_installer.sh`

- [ ] Write tests for required fields, exact allowed keys, type checks, size limits, secret-like key rejection, stdin/file input, and non-zero exit on invalid evidence.
- [ ] Run `python3 -m unittest tests.test_import_observation -v` and verify failure because the module is absent.
- [ ] Implement the parser and command without logging payload contents on failure.
- [ ] Add the command to canonical installer validation and run the focused tests.
- [ ] Commit as `feat: import strict local observation evidence`.

### Task 2: Add deterministic terminal outcomes

**Files:**
- Modify: `money_agent/monitoring.py`
- Modify: `tests/test_monitoring.py`

- [ ] Write tests proving ordinary evidence remains `measuring`, `won` requires positive evidence, `lost` requires a completed window, public HTTP cannot create a terminal outcome, and terminal outcomes cannot conflict.
- [ ] Run `python3 -m unittest tests.test_monitoring -v` and verify the new tests fail.
- [ ] Extend `ingest_observation` with optional `outcome` and `window_complete`; record outcome events and a transferable lesson only after an accepted unique observation.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: apply evidence-backed experiment outcomes`.

### Task 3: Document, verify, and publish

**Files:**
- Modify: `MONEY_AGENT.md`
- Modify: `HANDOFF.md`

- [ ] Document the JSON contract, examples, exit behavior, and the distinction between metric success and observed revenue.
- [ ] Run `bash -n setup-money-agent.sh`, `bash tests/test_installer.sh`, `python3 -m unittest discover -s tests -v`, and `git diff --check`.
- [ ] Update exact verification results and the next safe action.
- [ ] Commit, push, update PR #1, and keep it draft.
