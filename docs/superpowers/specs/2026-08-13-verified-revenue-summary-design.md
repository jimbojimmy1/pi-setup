# Verified Revenue Summary Design

## Context and approval

The Money Agent objective requires evidence-backed result monitoring, the latest
handoff authorizes repository-only evidence improvements, and the owner directly
asked how much money the system has made. This specification adds an explicit,
honest answer without connecting any financial account or claiming a sale from
non-payment signals.

## Approaches considered

1. Summing the observations already returned by `/api/state` is simple but
   silently truncates lifetime revenue at the dashboard's 100-row display limit.
2. Showing only the latest payment avoids addition but does not answer the
   all-time earnings question.
3. A dedicated aggregate query over the complete evidence ledger provides a
   stable all-time total and count. This is the selected approach.

## Revenue contract

`store.verified_revenue_summary()` aggregates observations with a positive
`revenue_usd` only when `source_kind` is `payment_provider_readonly` or
`owner_verified`. The query groups by source and evidence reference across
experiments, so attaching the same accepted payment event to multiple experiments
still counts once. If duplicate rows disagree on amount, the lower positive
amount is used to avoid overstating revenue. The query covers the full ledger
rather than the bounded dashboard observation list.

Historical rows fail closed unless amount and timestamp have numeric SQLite
storage classes, are positive and finite, and the evidence reference is nonblank
bounded text. The public observation list independently zeroes revenue that does
not meet the same evidence requirements, so malformed legacy data cannot create
a payment label or crash the dashboard.

The result contains:

- `total_usd`: sum of accepted observed payment amounts, rounded to cents at the
  API boundary;
- `payments`: number of positive permitted revenue observations;
- `last_observed_at`: newest qualifying evidence timestamp, or null;
- `age`: human-readable age computed by the dashboard, or `never`.

Analytics, public HTTP checks, checkout readiness, experiment forecasts,
positive non-payment metrics, and operating spend never enter this total.

## Dashboard behavior

`/api/state` exposes the summary as `verified_revenue`. The header displays the
amount and payment count, and a dedicated panel states either the latest evidence
age or that no verified payment evidence is recorded. Copy consistently says
“verified revenue recorded,” not bank balance, payout, profit, or cash received.

The raw observation list remains bounded and redacted as before. No evidence
reference, credentials, account identifier, payment-provider details, or customer
information is added to the API.

## Failure handling and testing

SQLite returns a zero total, zero count, and null latest time for an empty ledger.
Tests insert permitted payment observations, an idempotent duplicate, and
disallowed analytics/public revenue rows directly at the storage boundary. The
summary must count the permitted evidence exactly once and ignore the disallowed
rows even if malformed historical data exists.

Dashboard tests cover both zero and positive summaries, timestamp age, template
rendering, and secret non-disclosure. No network, deployment, service restart,
financial account, or payment-setting action is part of this feature.
