# Money Agent handoff

Updated: 2026-08-11 (America/New_York)

## Objective

Turn the original research-only Raspberry Pi daemon into a low-intervention,
ethical revenue loop that researches, scores, prepares safe work on owned
projects, exposes blockers, measures results, and iterates without spending or
impersonating the owner.

## Repository state

- Pull request: https://github.com/jimbojimmy1/pi-setup/pull/1
- Branch: `claude/money-making-agent-debate-fp1ag2`
- Local HEAD before this handoff commit: `ae8eb2f`
- PR state checked before push: open, draft, mergeable, no checks configured
- Remote PR head before push: `6411420`

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

## Current owned revenue project

- Project: FunnelSleuth
- Live URL: https://funnelsleuth.stinkchimp.chatgpt.site
- Existing offers: $79 audit and $299 Fix Sprint
- Honest status: no observed revenue is recorded by this repository
- Owner-required blocker: connect an existing Stripe or PayPal payment link from
  an authenticated owner session

The daemon may prepare and implement bounded owned-site experiments. It must not
spend money, contact people, create accounts, change payment or payout settings,
accept legal terms, handle owner secrets, or claim unobserved earnings.

## Verification

Run from the repository root in Git Bash:

```bash
python3 -m unittest discover -s tests -v
```

Latest result: 11 tests passed in 0.398 seconds. `git diff --check` passed before
each feature commit.

## Commits added in this workstream

- `d2d8f88` design bounded execution loop
- `6ed7f67` implementation plan
- `43f7e67` version runtime source
- `93abba6` ignore generated Python artifacts
- `b133c42` persist measurable experiments
- `52355e6` policy-check and atomically export handoffs
- `0d4021d` convert promoted owned-project ideas into experiments
- `ae8eb2f` show experiments and blockers on the dashboard

## Next action

Rewrite `setup-money-agent.sh` to install the canonical versioned runtime,
including `experiments.py` and `profile.json`, while preserving an existing
`config.env`, database, and customized profile. Add an installer smoke test
before changing the script. Then run the full suite, inspect the generated Pi
installation, and update this handoff and the draft PR description.
