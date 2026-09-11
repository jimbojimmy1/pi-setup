# Complete experiment lifecycle scan design

## Problem

`store.list_experiments()` returns at most 50 rows by default. That limit is
appropriate for the public dashboard, but the daemon also uses the same query
to bootstrap owned-project monitoring and to monitor active experiments. After
the ledger exceeds 50 rows, an older active experiment can stop being checked,
and an older bootstrap record can fall outside the window and be recreated.

## Decision

Keep the existing 50-row default for display callers and add an explicit
unbounded mode to `list_experiments`. Internal lifecycle code will request the
complete ledger when it:

- validates and collects experiment evidence;
- checks whether an owned-project availability experiment exists;
- checks whether an owned-project checkout experiment exists; or
- checks whether an owner-verified revenue lane exists.

This is preferable to raising the global default, which could make `/api/state`
grow without bound, or adding multiple nearly identical store queries.

## Interface and data flow

`list_experiments(limit=None)` runs the same deterministic ordering without a
SQL `LIMIT`. A positive integer retains the bounded query. Invalid or
non-positive explicit limits fail closed with `ValueError`; current callers use
the default or `None`.

The dashboard continues calling `list_experiments()` and therefore exposes no
more than 50 experiments. The daemon calls `list_experiments(limit=None)` for
lifecycle work. No schema migration, network call, deployment, payment action,
or evidence claim is involved.

## Verification

Store tests will prove the default remains bounded and the explicit mode returns
the full ledger. Agent tests will create more than 50 newer experiments and
prove that the oldest active experiment is still monitored and that old
bootstrap records are not duplicated. The complete Python and shell suites must
remain green before the change is pushed.

