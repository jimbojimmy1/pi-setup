# Truthful public evidence snapshot design

## Problem

Historical SQLite rows can bypass the strict observation importer. The public
API sanitizes payment amounts and timestamps, but it currently copies an
observation's primary `value` unchanged. A BLOB value is not JSON serializable
and makes `/api/state` return HTTP 500. A text value such as `"1"` can be
coerced by checkout status code and falsely reported as ready.

The API also derives checkout readiness from the newest 100 observations across
the whole ledger. A valid checkout observation can fall outside that display
window after unrelated analytics or monitoring evidence arrives, causing the
owner blocker to reappear even though the project has a newer valid result in
its own experiment.

## Decision

Separate bounded display history from status evidence. The public observation
list remains capped at 100 rows and sanitizes every value to either a native
finite number or `null`. Public availability and checkout metrics additionally
accept only exact numeric `0` and `1`; malformed, textual, binary, non-finite,
or out-of-domain values become `null`.

Add a store query for the latest valid public binary observation. It filters by
metric and optional experiment ID, requires SQLite numeric storage classes,
positive numeric timestamps, and exact 0/1 values, then performs Python
finiteness checks before returning the first valid row. It iterates the ordered
cursor so a malformed newer row cannot hide an older valid row.

## Data flow

`/api/state` continues to expose the newest 100 sanitized observations. It
separately requests:

- the latest valid `public_availability` observation across the ledger; and
- the latest valid `checkout_readiness` observation for each checkout
  experiment in the bounded experiment display set.

Status rendering consumes those validated snapshots, never the raw display
window. Missing valid evidence yields `unknown`/`never` and retains the owner
checkout blocker. Zero yields not ready and retains it. One yields ready and
removes only the missing-link blocker. None of these values can imply a visit,
successful checkout, payment, or revenue.

## Safety and scope

The change performs no network access, deployment, account connection, checkout
navigation, messaging, or payment action. It does not alter verified revenue.
It adds no schema migration and does not expose evidence references. The Pi
remains at an unknown release until an approved preflight and deployment occur.

## Verification

Regression tests will reproduce BLOB/text/non-finite/out-of-domain public
values, prove `/api/state` remains HTTP 200, prove invalid rows fail closed with
fallback to an older valid row, and prove unrelated observations cannot crowd a
project's valid checkout snapshot out of status calculation. Existing bounded
payload, revenue, blocker, installer, and preflight tests must continue to pass.

