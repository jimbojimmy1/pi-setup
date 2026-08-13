# Money Agent Deployment Preflight Design

## Context and approval

The durable handoff explicitly requests a non-mutating deployment preflight and
forbids deployment or service restarts without owner approval. This specification
implements that already-approved scope; it does not add a deploy action.

## Approaches considered

1. Documentation-only commands are easy to write but cannot inspect the Pi's
   installed marker or fail closed on malformed revisions.
2. An installer `--dry-run` mode would share control flow with mutating code,
   increasing the chance that a preflight accidentally performs work.
3. A separate read-only shell script can inspect local state, validate inputs,
   and print exact commands while remaining structurally unable to install or
   restart anything. This is the selected approach.

## Interface and output

`money-agent-deploy-preflight.sh REVIEWED_COMMIT` requires one full 40-character
Git commit SHA. It reads only `${MONEY_AGENT_DIR:-$HOME/money-agent}/release.txt`
and accepts a single bounded ASCII marker. It prints the reviewed commit,
installed marker, comparison status, application directory, and the two systemd
service names.

Status is `current` only when the installed marker exactly matches the reviewed
SHA. A different clean SHA is `outdated`, a `-dirty` marker is `dirty`, and a
missing, invalid, or unversioned marker is `unknown`.

The script then prints, but never evaluates, an exact upgrade command sequence.
That sequence fetches and checks out the reviewed commit, runs the existing
installer, records the expected revision in `config.env`, and restarts the two
services. When the installed marker is a different clean SHA, it also prints an
exact rollback sequence targeting that commit.

## Safety and failure handling

The preflight uses shell built-ins for inspection and formatting. It does not
invoke `git`, `curl`, the installer, `sudo`, or `systemctl`; those strings appear
only in quoted output. Invalid arguments exit nonzero before reading local state.
Paths and revisions are shell-escaped before inclusion in printed commands.

The script never reads `config.env`, the database, artifacts, credentials, or
payment settings. It creates no files and performs no network calls.

## Verification

A shell test runs with fake `git`, `curl`, `sudo`, and `systemctl` executables
that fail if invoked. It covers current, outdated, dirty, missing, malformed,
and invalid-argument cases; verifies exact upgrade and rollback targets; and
confirms the inspected application directory is unchanged. CI runs shell syntax
checks and the new test alongside the existing installer and Python suites.
