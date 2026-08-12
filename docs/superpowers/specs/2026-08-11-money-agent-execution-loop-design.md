# Money Agent Execution Loop Design

## Status

Approved by the user-owned `continue-money-agent` heartbeat on 2026-08-11. This document converts PR #1 from an idea-ranking daemon into a bounded, recoverable execution loop.

## Problem

PR #1 continuously debates business ideas, but its output stops at a human action list. That creates more planning rather than revenue. The implementation is also embedded in a single 1,749-line installer, so ordinary unit testing and incremental changes are unnecessarily difficult.

The system must reduce intervention without pretending that software can lawfully open financial accounts, accept terms, perform identity checks, send unsolicited messages, or make consequential purchases for the owner.

## Approaches considered

1. **Keep the debate dashboard.** Lowest risk and smallest change, but it cannot execute anything and therefore does not materially improve the path to revenue.
2. **Bounded execution loop (chosen).** Researches and scores opportunities, converts winners into measurable experiments, automatically produces local work packages, and hands safe implementation work to a recurring Codex task. External actions remain explicitly classified.
3. **Autonomous outreach and sales bot.** Potentially faster feedback, but it creates unacceptable spam, impersonation, account, consent, and platform-policy risks. It is out of scope.

## First revenue project

The agent will optimize an owned project before seeding unrelated ideas:

- **Project:** FunnelSleuth
- **Public URL:** `https://funnelsleuth.stinkchimp.chatgpt.site`
- **Offers:** $79 Profit-Leak Audit and $299 Fix Sprint
- **Current constraint:** checkout links require the owner's authenticated Stripe or PayPal session
- **Near-term objective:** improve qualified organic discovery and conversion while keeping fulfillment capacity honest

The default profile will include this project. New root ideas are allowed only after the owned-project queue has no viable experiment.

## Architecture

### Versioned application source

The Python application becomes normal source under `money_agent/`:

- `store.py`: SQLite persistence and atomic claims
- `llm.py`: model backends and structured output parsing
- `agent.py`: BULL/BEAR/JUDGE research loop
- `experiments.py`: experiment validation, autonomy classification, and handoff export
- `app.py`: dashboard API
- `templates/index.html`: dashboard UI

`setup-money-agent.sh` remains the one-command Raspberry Pi installer. It installs the versioned files rather than being the only copy of the application.

### Experiment lifecycle

Promoted ideas create experiments with:

- one specific hypothesis;
- one owned project;
- one success metric and measurement window;
- estimated hours and cash cost;
- an autonomy class;
- a concrete deliverable;
- a stop condition.

States are `proposed`, `ready`, `exported`, `running`, `measuring`, `won`, `lost`, and `blocked`.

The scheduler prioritizes existing `ready`, `running`, and `measuring` experiments before asking the model for new root ideas.

### Autonomy classes

Every action is classified before it can leave the database:

- **AUTO_LOCAL:** may run automatically. Limited to local files inside the configured artifact directory, deterministic transforms, tests, public HTTP health checks, and read-only analysis.
- **CODEX_REVIEWED:** exported to the recurring Codex task. Includes repository edits, draft pull requests, owned-site builds, and owned-site deployments. Codex must verify the diff and preserve rollback.
- **OWNER_REQUIRED:** never executed automatically. Includes spending, financial or payout settings, account creation, identity verification, legal acceptance, direct outreach, posting as the owner, and collecting or handling secrets.
- **REJECTED:** deceptive, illegal, spammy, unsafe, unlicensed, or unrelated actions.

Unknown action types default to `OWNER_REQUIRED`.

### Work-package handoff

`experiments.py` writes two recoverable artifacts atomically:

- `artifacts/next-work.json`: structured current work package for automation;
- `HANDOFF.md`: concise human/model-readable state, evidence, changed files, verification commands, blockers, and next action.

The hourly Codex heartbeat reads these files, implements only `CODEX_REVIEWED` work within authorized repositories/sites, verifies it, and updates the handoff. A lock and run identifier prevent duplicate execution.

### Monitoring and learning

The Pi daemon may perform bounded public HTTP checks and store observations. It may not fabricate conversion evidence. Experiments without a configured measurement source remain `blocked` with the missing source recorded.

Results feed back into the lesson store:

- `won`: preserve the successful mechanism and propose one incremental follow-up;
- `lost`: record the failed assumption and avoid equivalent proposals;
- `blocked`: surface the smallest owner action needed, without repeatedly creating duplicates.

## Data model changes

Add an `experiments` table containing project, hypothesis, deliverable, metric, window, autonomy class, status, cost, hours, artifact path, timestamps, and result. Add an `experiment_events` append-only table for status changes and observations.

Existing databases migrate through `CREATE TABLE IF NOT EXISTS`; existing ideas, rounds, actions, lessons, usage, and metadata remain intact.

## Safety boundaries

- No arbitrary shell command generated by an LLM is executed.
- All filesystem targets are resolved and must remain inside the configured artifact directory.
- Public checks reject localhost, private, link-local, and reserved network targets.
- Secrets never appear in exported handoff files or dashboard responses.
- Cash cost greater than zero is always `OWNER_REQUIRED` unless the owner later configures a specific, separate allowance.
- Direct messages, emails, comments, ads, purchases, payment settings, and account changes are never automatic.

## Error handling

- Invalid model output is rejected and logged; it does not partially create an experiment.
- Atomic temp-file replacement prevents truncated handoffs.
- Claimed work has a lease; stale claims return to `ready` after restart.
- Repeated blocked actions are deduplicated by project, action kind, and normalized deliverable.
- The existing daily model-spend cap remains authoritative.

## Testing

Tests use Python's standard `unittest` and temporary directories so they run on Raspberry Pi OS without new test dependencies.

Required coverage:

- existing installer syntax and generated Python compilation;
- experiment schema migration on a fresh and existing database;
- autonomy classification, including unknown-action fail-closed behavior;
- artifact-directory path containment;
- atomic handoff export and secret redaction;
- experiment prioritization and stale-lease recovery;
- private-network URL rejection;
- dashboard experiment payload;
- idempotent installer behavior.

## Launch boundary

This phase is complete when PR #1 contains versioned source, green tests, the experiment/handoff bridge, the FunnelSleuth owned-project profile, an updated installer, and a current `HANDOFF.md`. It does not claim revenue until a real successful payment is observed. Connecting checkout remains a one-time owner-authenticated action.
