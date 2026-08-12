# Money Agent handoff

Updated: 2026-08-12 17:12 (America/New_York)

## Objective

Turn the original research-only Raspberry Pi daemon into a low-intervention,
ethical revenue loop that researches, scores, prepares safe work on owned
projects, exposes blockers, measures results, and iterates without spending or
impersonating the owner.

## Repository state

- Pull request: https://github.com/jimbojimmy1/pi-setup/pull/1
- Branch: `claude/money-making-agent-debate-fp1ag2`
- Latest implementation commit before this handoff update: `e4bbff7`
- PR state checked before this update: open, draft, no checks configured
- Remote PR head before this update: `038feda`

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

- `bash -n setup-money-agent.sh`: exit 0
- `bash tests/test_installer.sh`: exit 0; canonical source and operator-file
  preservation checks passed twice
- `python3 -m unittest discover -s tests -v`: 42 tests passed in 0.947 seconds
- `git diff --check`: exit 0 before each monitoring commit

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

## Next action

Add repository CI for the installer and Python suite, then expose inbox counts
and recent availability on the dashboard. Do not connect financial or analytics
accounts, send alerts/messages, or request credentials without explicit owner
approval.
