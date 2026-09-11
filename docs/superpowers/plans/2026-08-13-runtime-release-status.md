# Runtime Release Status Implementation Plan

**Goal:** Make the dashboard distinguish the code installed on the Raspberry Pi from the current pull-request revision without deploying or restarting anything.

**Architecture:** The installer records the exact source revision it copied into a bounded `release.txt` marker. Local installs use the repository commit and append `-dirty` when the worktree is not clean; standalone installs record `MA_RELEASE_REF`. The dashboard validates that marker and compares it with the optional operator-controlled `MA_EXPECTED_RELEASE_REF`, reporting `current`, `outdated`, or `unknown` without making network requests.

**Safety:** Release values are length- and character-bounded before installation or display. No credentials, financial settings, network monitoring, deployment, or service control are added.

---

### Task 1: Specify installer provenance

- Extend `tests/test_installer.sh` to require a preserved, valid `release.txt` marker.
- Make `setup-money-agent.sh` resolve and validate local/standalone revisions and install the marker.
- Verify both initial install and upgrade preservation behavior.

### Task 2: Expose honest dashboard status

- Add failing dashboard tests for clean matches, mismatches, dirty installs, missing markers, invalid markers, and template rendering.
- Implement bounded marker parsing and expected-revision comparison in `money_agent/app.py`.
- Add a compact runtime-release panel to `money_agent/templates/index.html`.

### Task 3: Verify and hand off

- Run shell syntax, installer, Python unit, and diff checks.
- Update `HANDOFF.md` with the exact repository/PR state and an honest deployment status.
- Commit and push the focused changes to PR #1, then confirm GitHub checks.
