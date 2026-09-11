# Owner-verified revenue lane design

## Problem

The dashboard can total verified revenue, and the observation importer can
accept `owner_verified` payment evidence, but a fresh installation has no
experiment whose source and metric match that evidence. The importer therefore
has no safe destination for a real payment unless a model happens to propose a
matching trusted experiment. Public availability and checkout readiness must
not be repurposed because neither proves a sale.

## Decision

Bootstrap one local revenue-evidence lane for every valid owned project. The
lane is an experiment-shaped measurement record because observations already
enforce source, metric, deduplication, terminal outcomes, and lesson creation.
It uses:

- action `prepare_verified_revenue_lane`;
- metric `verified_payment`;
- source `owner_verified`;
- zero cost and `AUTO_LOCAL` autonomy;
- `measuring` status immediately after creation so it is never exported as a
  build task.

Creating the lane asserts no revenue and grants no account access. Positive
revenue still requires an explicit observation with a non-empty evidence
reference, and the existing importer and monitoring boundary continue to reject
analytics or public-HTTP revenue claims. A future approved read-only payment
adapter can use a separately configured `payment_provider_readonly` lane rather
than silently changing this source.

## Lifecycle

Each daemon tick creates any missing lane before processing the observation
inbox. Creation is idempotent by project, action, and source. The lane remains
in `measuring`, so ordinary research and work-package export continue. An
owner-verified payment can be imported with `value: 1`, its amount in
`revenue_usd`, and a stable non-secret receipt or transaction reference. The
verified-revenue summary will then count it. Marking the first evidence item
`won` is optional and uses the existing evidence-backed lesson path.

## Safety and display

The implementation does not log in to Stripe or PayPal, follow checkout links,
change payment settings, or fabricate observations. The public API continues
to omit evidence references. Documentation must call the lane a prepared
evidence destination, not an active payment integration, and repository status
must not imply that the Pi is running this release.

