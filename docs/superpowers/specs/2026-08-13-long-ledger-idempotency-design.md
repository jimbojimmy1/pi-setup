# Long-ledger idempotency design

## Problem

Observation uniqueness is defined by `(experiment_id, source_kind,
evidence_ref)`, but ingestion checks for an existing row by scanning only the
newest 100 observations for an experiment. After 100 newer rows, retrying old
evidence reaches `INSERT OR IGNORE`, appends another observation event, and then
raises `StopIteration` because the ignored row is still outside the bounded
return scan. A retried payload can therefore look like a failed import even
though its evidence exists, while mutating event history.

Hourly public collectors use the same bounded scan pattern. Their current
bucket is normally recent, but exact lookup is the correct durable contract and
avoids coupling idempotency to history-display limits.

## Decision

Add `store.find_observation(experiment_id, source_kind, evidence_ref)`, backed by
the existing SQLite unique index. It validates a positive non-Boolean integer
experiment ID and non-empty bounded text source/reference, then returns the
matching row or `None`.

`ingest_observation` calls the exact lookup before any status, event, or lesson
mutation and returns an existing row unchanged. After insertion it retrieves
the row through the same exact lookup instead of scanning history. Public health
and checkout collectors use the helper for their bucket reference as well.

## Alternatives

An unbounded observation scan would restore correctness but make memory and
latency grow with the ledger. Returning insertion state from a redesigned
upsert could work, but changes the store contract more broadly and still needs
an exact retrieval path. The focused indexed query is simpler and matches the
database's declared identity rule.

## Safety and outcomes

A duplicate is idempotent even if a retry changes value, timestamp, revenue, or
requested outcome: the first accepted evidence row wins, and the retry creates
no status update, event, or lesson. This protects payment evidence from replay
without changing verified-revenue deduplication. New evidence follows the
existing validation and outcome rules.

The change performs no network access, deployment, messaging, account action,
checkout navigation, or payment setting change. Verified revenue remains based
only on accepted owner/provider evidence.

## Verification

Tests will create more than 100 newer observations, retry the oldest evidence,
and prove the original row is returned with unchanged event/lesson/status
counts. Store tests will cover exact lookup and invalid arguments. Collector
tests will prove an existing bucket uses the direct helper behavior. The full
Python, installer, preflight, syntax, and PR CI suites must pass before handoff.

