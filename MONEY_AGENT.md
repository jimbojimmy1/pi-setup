# Money Agent operator guide

Money Agent runs a BULL/BEAR/JUDGE research loop on a Raspberry Pi. Promoted
ideas become bounded experiments for projects you already own. The service can
write a redacted work package for Codex; it cannot spend money, contact people,
open accounts, or alter payment settings.

It does not guarantee revenue. Record earnings only after a payment provider or
bank confirms them.

## Install on a Raspberry Pi

Clone the repository and run the installer:

```bash
git clone https://github.com/jimbojimmy1/pi-setup.git
cd pi-setup
sudo true
bash setup-money-agent.sh
```

The default application directory is `~/money-agent`. The installer validates
all Python, JSON, and template files before replacing runtime code. It preserves
an existing `config.env`, `profile.json`, `money.db`, and `artifacts/` directory.

Open `http://PI_ADDRESS:8086` after installation. Check service state with:

```bash
systemctl status money-agent money-agent-web
journalctl -u money-agent -f
```

API spending starts disabled (`MA_DAILY_USD=0.00`). A configured API key cannot
incur agent usage while that cap remains zero. The Claude CLI and dry-run
backends remain available without an API key.

## Test without installing services

Use a temporary or explicit application directory:

```bash
MONEY_AGENT_DIR=/tmp/money-agent-test \
MA_SKIP_APT=1 \
MA_SKIP_SYSTEMD=1 \
bash setup-money-agent.sh
```

This mode writes no systemd units and starts no daemons.

## Upgrade

For a cloned installation:

```bash
cd pi-setup
git pull --ff-only
bash setup-money-agent.sh
```

For a standalone copy of the installer, pin the source files to a commit:

```bash
MA_RELEASE_REF=COMMIT_SHA bash setup-money-agent.sh
```

The standalone path downloads every required file from that exact ref into a
temporary staging directory. A missing or invalid file stops the upgrade before
runtime files are replaced.

Every install writes the copied source revision to `~/money-agent/release.txt`.
A cloned install records the full Git commit and adds `-dirty` when local
changes or untracked files were present. A standalone install requires and
records the full 40-character commit SHA in `MA_RELEASE_REF`; branch and tag
names are rejected because they can move. The marker contains no credentials.
It is removed before runtime replacement and published again only after every
runtime file is installed successfully.

To make the dashboard compare the installed runtime with a reviewed release,
set the expected commit in `~/money-agent/config.env` before restarting the web
service:

```bash
MA_EXPECTED_RELEASE_REF=FULL_REVIEWED_COMMIT_SHA
```

The release panel reports `current` only for an exact or unambiguous Git-SHA
prefix match. It reports `outdated` for a mismatch, `dirty` for an uncommitted
local install, and `unknown` when either side is not recorded. The dashboard
does not query GitHub or claim that repository-only changes are deployed.

### Deployment preflight

On the Pi, inspect an exact reviewed release before approving an upgrade:

```bash
bash money-agent-deploy-preflight.sh REVIEWED_COMMIT
```

`REVIEWED_COMMIT` must be a full 40-character Git SHA. The preflight reads only
the local `release.txt` marker and prints the reviewed commit, installed marker,
comparison status, application directory, and the `money-agent` and
`money-agent-web` service names. A different clean installed commit also
produces a rollback sequence.

Printed Git commands target the repository directory containing the preflight
script, independent of the shell's current directory. Set `MA_REPO_DIR` only if
the reviewed checkout intentionally lives elsewhere.

The upgrade and rollback commands are output for review; the preflight never
executes them. Confirm `NO_ACTIONS_EXECUTED: true` in its output. Running the
printed commands still requires explicit owner approval because they fetch and
check out code, install files, update the expected-release setting, and restart
services. The preflight itself makes no network call, writes no file, and does
not invoke Git, the installer, `sudo`, or `systemctl`.

## Roll back

Find the last known-good commit, then reinstall its runtime:

```bash
MA_RELEASE_REF=LAST_GOOD_COMMIT bash setup-money-agent.sh
sudo systemctl restart money-agent money-agent-web
```

The SQLite migrations are additive. The installer does not delete or replace
`money.db`. Copy the application directory before a manual database change:

```bash
cp -a ~/money-agent ~/money-agent.backup
```

## Configuration

The installer creates `~/money-agent/config.env` once. Later runs leave it
unchanged.

| Setting | Default | Purpose |
| --- | ---: | --- |
| `ANTHROPIC_API_KEY` | empty | Enables the Anthropic API backend. Treat it as a secret. |
| `MA_DAILY_USD` | `0.00` | Stops API-backed work at the UTC daily cap. |
| `MA_TRUSTED_MEASUREMENT_SOURCES` | empty | Comma-separated read-only sources configured outside the model. |
| `MA_TICK_SECONDS` | `900` | Seconds between daemon cycles. |
| `MA_HORIZON` | `fast` | Favors speed to a first verified payment. |
| `MA_MAX_ROUNDS` | `4` | Iterations allowed per idea. |
| `MA_MAX_DEPTH` | `2` | Maximum child-question depth. |
| `MA_CHILD_FANOUT` | `2` | Child questions created by a promoted idea. |
| `MA_MAX_OPEN` | `12` | Open-idea limit before seeding stops. |
| `MA_PROMOTE_AT` | `72` | Score required for promotion. |
| `MA_KILL_AT` | `35` | Scores below this value kill an idea. |
| `MA_ARTIFACT_ROOT` | `~/money-agent/artifacts` | Destination for automation handoffs. |
| `MA_EXPECTED_RELEASE_REF` | empty | Reviewed commit expected to be installed; used only for local dashboard comparison. |

Edit `profile.json` to change the operator constraints or owned projects. The
installer never overwrites a customized profile.

## Experiment permissions

- `AUTO_LOCAL`: local files, deterministic transforms, tests, public health
  checks, and read-only public analysis.
- `CODEX_REVIEWED`: repository edits, draft pull requests, and changes to sites
  the operator owns. Codex verifies the diff and keeps rollback available.
- `OWNER_REQUIRED`: spending, outreach, account creation, identity or legal
  acceptance, secrets, and payment or payout settings.
- `REJECTED`: spam, deception, credential theft, prohibited scraping, or other
  unsafe work.

Unknown action types are `OWNER_REQUIRED`. The policy code calculates the class;
it ignores any permission class proposed by a model.

## Handoff files

The daemon claims one ready experiment before researching a new idea and writes:

- `~/money-agent/artifacts/next-work.json`
- `~/money-agent/artifacts/HANDOFF.md`

Both files are written through sibling temporary files and renamed into place.
Keys that look like credentials are removed before serialization.

The recurring Codex task reads the repository handoff, works only inside the
authorized repository or owned site, verifies changes, updates the handoff, and
keeps the draft pull request recoverable. A heartbeat is not permission to
spend, send messages, create accounts, or make payment changes.

## Measurement evidence

Experiments now store a measurement source and append-only observations. The
model may propose a source, but the daemon accepts it only if it appears in
`MA_TRUSTED_MEASUREMENT_SOURCES`. `public_http:https://...` is the exception:
it may be accepted after public-address validation, but it proves availability,
not a sale.

Allowed source kinds are:

- `analytics_readonly`
- `payment_provider_readonly`
- `owner_verified`
- `public_http`

Unknown sources fail closed. Missing sources move an experiment to `blocked`
and create one blocker event. Matching evidence moves non-terminal experiments
to `measuring`. Duplicate evidence references do not create duplicate rows.
Analytics and public-health evidence cannot report revenue. A positive payment
amount requires `payment_provider_readonly` or `owner_verified` evidence.

The database boundary is ready for a read-only adapter, but this release does
not log in to Stripe, PayPal, or an analytics account and does not poll them.
Do not add a source name to the trusted list until its read-only adapter is
configured and tested.

### Import one observation

The local importer accepts one JSON object from a file or stdin. It rejects
unknown fields, credential-like fields, invalid types, and input larger than 64
KiB. Rejected input produces a generic error and is not echoed to logs.

```json
{
  "experiment_id": 7,
  "source_kind": "analytics_readonly",
  "metric": "qualified runs",
  "value": 3,
  "evidence_ref": "analytics:event-123",
  "observed_at": 1786500000,
  "revenue_usd": 0,
  "outcome": "measuring",
  "window_complete": false
}
```

Import a named file:

```bash
python3 ~/money-agent/import_observation.py observation.json
```

Or pipe the object through stdin:

```bash
python3 ~/money-agent/import_observation.py - < observation.json
```

Exit code `0` means the observation was accepted or already existed. Exit code
`2` means it was rejected. Successful output contains only experiment ID,
observation ID, and current status; it omits the evidence reference and payload.

`outcome` may be omitted or set to `measuring`, `won`, or `lost`:

- `won` requires a positive verified metric or permitted payment amount.
- `lost` requires `window_complete: true` and no observed payment.
- `public_http` observations cannot set `won` or `lost`.
- a terminal `won`/`lost` result cannot be changed to the opposite outcome.

A positive analytics metric can verify that experiment's declared metric. It
does not prove a sale and is never labeled as revenue. Positive revenue still
requires `payment_provider_readonly` or `owner_verified` evidence.

### Owner-verified revenue lane

On its first tick, the daemon prepares one zero-cost local evidence lane for
each named project in `profile.json`. The lane uses action
`prepare_verified_revenue_lane`, metric `verified_payment`, and source
`owner_verified`. It starts in `measuring`, contains no observation, asserts no
revenue, and is not exported as a work package. It does not connect to Stripe,
PayPal, a bank, or any other account.

After independently confirming a real payment, find that project's lane ID in
`/api/state` and import an observation with the exact contract below. Use a
stable non-secret receipt or transaction reference; never put credentials,
customer personal data, access tokens, or checkout URLs in the payload.

```json
{
  "experiment_id": 12,
  "source_kind": "owner_verified",
  "metric": "verified_payment",
  "value": 1,
  "evidence_ref": "owner:receipt-79",
  "observed_at": 1800000000,
  "revenue_usd": 79,
  "outcome": "won",
  "window_complete": false
}
```

`outcome` can remain `measuring` for ordinary payment entries. Setting the
first confirmed payment to `won` also records the existing evidence-backed
lesson for the project. The same source and evidence reference is idempotent.
The owner must verify the payment before importing it; preparing this lane does
not make a typed claim true. A future provider adapter must use a separately
configured `payment_provider_readonly` lane and still needs explicit approval
before any account connection.

Observation idempotency uses the database identity
`(experiment_id, source_kind, evidence_ref)`, not the dashboard's bounded
history window. The first accepted row for that identity wins permanently.
Retrying it returns the original row without adding an event, changing an
outcome or result, or creating another lesson, even after more than 100 newer
observations exist. Public health and checkout collectors use the same exact
lookup, so retrying an old collection bucket does not repeat its network probe.

### Observation inbox

An approved read-only adapter can deposit the same JSON contract at:

```text
~/money-agent/artifacts/observation-inbox/incoming/
```

The producer should write to a sibling temporary file and rename it to a
`.json` filename only after the write is complete. Each daemon tick claims at
most 25 files before monitoring or research. Claimed files move through:

```text
observation-inbox/processing/
observation-inbox/accepted/
observation-inbox/rejected/
```

All four directories stay under `MA_ARTIFACT_ROOT`. Symlinks are rejected and
never read. Accepted and rejected archives use restrictive permissions. A
rejected archive can contain the original invalid input, so inspect it only on
the Pi and remove it after diagnosing the producer. Logs and result summaries
contain counts, not payload contents.

### Public availability

On its first tick, the daemon creates one zero-cost `AUTO_LOCAL` availability
experiment for every valid URL in `profile.json` under `owned_projects`. It
therefore begins checking FunnelSleuth after the updated service is installed
and restarted; it does not wait for a model to propose the check.

The check resolves the host, rejects any non-public address, connects directly
to one validated IP with TLS hostname verification, sends one `HEAD` request,
follows no redirects, and caps its timeout and response bytes. It records at
most one `public_availability` observation per hour: `1` for HTTP 2xx/3xx and
`0` for failure. That value cannot set `won` or `lost` and cannot report a sale,
traffic, conversion, or revenue.

### Dashboard evidence status

The dashboard shows `.json` file counts for the incoming, processing, accepted,
and rejected inbox directories. It does not expose filenames, evidence
references, file contents, or rejected payloads. Missing or unreadable
directories report zero instead of breaking the dashboard.

The public availability panel shows only the latest `public_availability`
observation as available or unavailable, plus its age. It is an uptime signal.
It does not prove traffic, checkout readiness, conversion, a sale, or revenue.

The public observation list is bounded to its newest 100 rows for display. It
is not the source of availability or checkout status. Those panels query the
newest valid numeric 0/1 evidence independently for each matching monitor, so
unrelated analytics cannot crowd a valid status out of view. Historical text,
binary, non-finite, invalid-time, or non-binary public values fail closed; the
status query falls back to an older valid row or reports no evidence. Invalid
values are returned as `null` in display history and cannot break the API or be
coerced into readiness.

The checkout-readiness panel groups evidence by the matching owned-project
experiment. Missing or zero evidence keeps the owner payment-link blocker.
Positive matching evidence removes only the warning that no link is present;
it does not clear other owner-required or measurement blockers. An unrelated
analytics or availability observation cannot clear it.

The verified-revenue header and panel answer how much payment evidence is
recorded across the complete ledger. They sum only positive
`payment_provider_readonly` and `owner_verified` amounts. The same source and
evidence reference counts once even when attached to multiple experiments; if
duplicate rows disagree, the lower positive amount is used. Analytics, public
availability, checkout readiness, forecasts, and operating spend are excluded.

This total is recorded evidence, not a live provider balance, payout status,
profit calculation, or bank confirmation. Until an approved read-only payment
adapter or owner-verified observation is imported, it correctly remains `$0.00`
with zero payment evidence items. Malformed historical revenue on a disallowed
source is zeroed at the public API boundary and cannot create a payment label.

### Checkout readiness

Each valid owned-project URL also gets one zero-cost `AUTO_LOCAL` experiment
with metric `checkout_readiness`. Once per hour, the daemon makes one bounded
direct-IP HTTPS `GET` with TLS hostname verification, a ten-second timeout, a
64 KiB response cap, identity encoding, and no redirect handling. It parses
only HTML anchor `href` and form `action` attributes. It never opens a checkout
destination, submits a form, stores cookies, or creates a checkout session.

The allowlist recognizes HTTPS destinations on `buy.stripe.com`,
`book.stripe.com`, `donate.stripe.com`, and `paypal.me`, plus the PayPal-hosted
`/ncp/payment/` path on `paypal.com`. Provider words, scripts, HTTP links,
lookalike domains, relative links, and unrelated provider pages do not count.

A value of `1` means a recognized destination was present in the bounded public
HTML response. It does not prove the link is active, the provider account is
connected, checkout succeeds, a customer visited, a payment occurred, or any
revenue was earned. The probe cannot close an experiment or report revenue.

## FunnelSleuth blocker

FunnelSleuth is the first owned project. Its current offers are a $79 audit and
a $299 Fix Sprint. Checkout still needs one owner-authenticated action: create
or select an existing Stripe or PayPal payment link and connect it to the site.
The agent may display this blocker but cannot complete it or request credentials.

Automatic provider collection is not yet implemented. The importer is a safe
input boundary for a future adapter, not proof that any account is connected.
Until a trusted analytics or payment adapter supplies evidence, treat experiment
outcomes and revenue as unverified.
