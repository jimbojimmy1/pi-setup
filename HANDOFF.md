# Money Agent handoff

Updated: 2026-08-12 19:11 (America/New_York)

## Objective

Turn the original research-only Raspberry Pi daemon into a low-intervention,
ethical revenue loop that researches, scores, prepares safe work on owned
projects, exposes blockers, measures results, and iterates without spending or
impersonating the owner.

## Repository state

- Pull request: https://github.com/jimbojimmy1/pi-setup/pull/1
- Branch: `claude/money-making-agent-debate-fp1ag2`
- Latest implementation commit before this handoff update: `6af160c`
- PR state checked before this update: open, draft, mergeable
- Remote PR head before this update: `6400ec9`

## Implemented architecture

- Versioned runtime source now lives under `money_agent/`.
- SQLite persists bounded experiments and append-only experiment events.
- Unknown and paid actions fail closed to `OWNER_REQUIRED`; deceptive or spammy
  actions are rejected.
- Promoted judge results create one deduplicated, deterministically classified
  experiment. Model-supplied autonomy claims are ignored.
- Ready experiments are exported atomically to redacted JSON and Markdown before
  the daemon researches another idea.
- The dashboard exposes experiments, next work, and owner-required blockers
  without exposing environment credentials.
- The default profile prioritizes the existing FunnelSleuth project and assumes
  zero startup spend.
- The installer stages and validates canonical versioned source, preserves
  operator files and data, and defaults API spending to zero.
- Experiments now name a measurement source and store structured, deduplicated
  observations in an append-only evidence ledger.
- Monitoring rejects non-public URLs, blocks missing or unknown sources, and
  prevents analytics or health evidence from reporting revenue.
- A model cannot trust its own proposed connector; the installer defaults
  `MA_TRUSTED_MEASUREMENT_SOURCES` to empty.
- A strict local importer accepts one bounded JSON observation from a file or
  stdin, rejects unknown and sensitive-looking fields, and never echoes rejected
  payload contents.
- Evidence-backed outcomes are deterministic: wins need positive evidence,
  losses need a completed window with no payment, public health cannot close an
  experiment, and terminal conflicts are rejected.
- Accepted terminal results add an event and a reusable lesson for future idea
  scoring.
- The daemon atomically consumes up to 25 local observation files per tick,
  archives accepted/rejected inputs under the artifact root, rejects symlinks,
  and exposes only counts in logs.
- Public checks use a validated direct IP, TLS hostname verification, a bounded
  `HEAD` request, no redirects, and one availability observation per hour.
- Each valid owned-project URL gets one deterministic zero-cost `AUTO_LOCAL`
  availability experiment, so FunnelSleuth monitoring starts after the updated
  daemon is installed and restarted.
- GitHub Actions now runs the installer syntax check, installer preservation
  test, and complete Python suite on pull requests and pushes to `main`, with
  read-only repository permissions and a ten-minute job limit.
- The dashboard reports only inbox file counts and the latest public
  availability state/time. It does not expose filenames, payloads, evidence
  references, or infer revenue from uptime.

## Current owned revenue project

- Project: FunnelSleuth
- Live URL: https://funnelsleuth.stinkchimp.chatgpt.site
- Existing offers: $79 audit and $299 Fix Sprint
- Honest status: no observed revenue is recorded by this repository
- Owner-required blocker: connect an existing Stripe or PayPal payment link from
  an authenticated owner session
- Measurement blocker: no read-only Stripe, PayPal, or analytics adapter is
  configured
- Public availability evidence: the bounded direct-IP probe returned HTTP 200
  on 2026-08-12; this does not verify checkout, conversion, or revenue

The daemon may prepare and implement bounded owned-site experiments. It must not
spend money, contact people, create accounts, change payment or payout settings,
accept legal terms, handle owner secrets, or claim unobserved earnings.

## Verification

Run from the repository root in Git Bash:

```bash
python3 -m unittest discover -s tests -v
```

Latest combined verification before this documentation update:

- Git Bash `bash -n setup-money-agent.sh`: exit 0
- Git Bash `bash tests/test_installer.sh`: exit 0; canonical source and operator-file
  preservation checks passed twice
- Python 3.11 `python -m unittest discover -s tests -v`: 45 tests passed in
  0.804 seconds
- `git diff --check`: exit 0
- GitHub Actions run `31645803074`: all steps passed; the workflow was then
  moved to the Node 24 action releases to remove its runtime deprecation warning

## Commits added in this workstream

- `d2d8f88` design bounded execution loop
- `6ed7f67` implementation plan
- `43f7e67` version runtime source
- `93abba6` ignore generated Python artifacts
- `b133c42` persist measurable experiments
- `52355e6` policy-check and atomically export handoffs
- `0d4021d` convert promoted owned-project ideas into experiments
- `ae8eb2f` show experiments and blockers on the dashboard
- `2404038` add the durable interim handoff
- `96d8214` replace the embedded installer with the canonical source installer
- `d89c2e6` document operations and the durable handoff
- `0113b5c` plan evidence-backed monitoring
- `5bb5514` persist trusted observations
- `36c5a02` enforce the fail-closed monitoring policy
- `ced8cdc` integrate monitoring with the daemon, dashboard, and installer
- `ec400eb` default configured measurement sources to untrusted
- `652d387` hand off evidence-backed monitoring
- `75ba199` plan strict local observation import
- `f97fa69` add the strict JSON importer
- `d74daf4` apply evidence-backed terminal outcomes
- `038feda` hand off strict observation import
- `6c6dd69` plan the observation inbox and health checks
- `686011f` add the atomic observation inbox
- `362a10d` add bounded public-health evidence
- `be3e857` run inbox and health monitoring each tick
- `e4bbff7` bootstrap owned-project health monitoring
- `d157225` hand off automated evidence collection and final verification
- `c844c55` plan dashboard evidence visibility
- `6af160c` show evidence health on the dashboard

## Next action

Add a bounded, read-only checkout-readiness probe for owned public pages. It may
detect whether an HTTPS Stripe or PayPal checkout destination is present but
must not follow the checkout link, submit forms, create sessions, or infer a
sale. Do not connect financial or analytics accounts, send alerts/messages, or
request credentials without explicit owner approval.
