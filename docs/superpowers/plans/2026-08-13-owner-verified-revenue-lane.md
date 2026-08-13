# Owner-verified revenue lane implementation plan

1. Add failing agent tests for idempotent per-project lane creation, zero
   revenue at bootstrap, non-exportable measuring state, and tick ordering
   before inbox processing.
2. Add the narrow policy action and bootstrap method, then call it from the
   daemon tick.
3. Add an importer regression proving that owner-verified payment evidence can
   enter the lane and update the deduplicated verified-revenue summary.
4. Document the exact import contract and its trust boundary.
5. Run focused tests, the full test suite, syntax checks, installer checks, and
   `git diff --check`; update `HANDOFF.md`; commit and push the recoverable PR.

