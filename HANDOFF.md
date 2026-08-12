# Money Agent handoff

Updated: 2026-08-11 22:11 (America/New_York)

## Objective

Turn the original research-only Raspberry Pi daemon into a low-intervention,
ethical revenue loop that researches, scores, prepares safe work on owned
projects, exposes blockers, measures results, and iterates without spending or
impersonating the owner.

## Repository state

- Pull request: https://github.com/jimbojimmy1/pi-setup/pull/1
- Branch: `claude/money-making-agent-debate-fp1ag2`
- Latest implementation commit before this handoff update: `ec400eb`
- PR state checked before this update: open, draft, no checks configured
- Remote PR head before this update: `d89c2e6`

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

## Current owned revenue project

- Project: FunnelSleuth
- Live URL: https://funnelsleuth.stinkchimp.chatgpt.site
- Existing offers: $79 audit and $299 Fix Sprint
- Honest status: no observed revenue is recorded by this repository
- Owner-required blocker: connect an existing Stripe or PayPal payment link from
  an authenticated owner session
- Measurement blocker: no read-only Stripe, PayPal, or analytics adapter is
  configured

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
- `python3 -m unittest discover -s tests -v`: 21 tests passed in 0.586 seconds
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

## Next action

Add a local, read-only observation import command with strict JSON validation so
an approved analytics or payment connector can feed the evidence ledger without
database access. Then add deterministic, evidence-backed `won` and `lost`
transitions. Do not connect accounts or request credentials without explicit
owner approval.
