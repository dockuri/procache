# ticket-011: Independent cache load concurrency

- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: the user requested continued implementation/testing/protected publication and maximum throughput across simultaneous projects. Scope: remove unrelated cache-database and namespace/key lock contention in canonical dockuri/procache.

- [x] AC-01: Independent database loaders and distinct namespace/key pairs proceed while an unrelated loader is deliberately held.
- [x] AC-02: Same-record loads still coalesce; storage identity, database records and behavior remain compatible.
- [ ] AC-03: Supported-version regressions, governance and exact-head independent publication pass.

No provider request, paid inference or credential access is required for qualification. Only thread-lock identity changes; SQLite remains the cross-process singleflight authority.

Validation: all 40 cache-backend tests pass on Python3.10.20 and3.13.12 through the approved Wellman runtime. The final event-based regression harness reproduces two failures on accepted c70037d and passes for the fix; equivalent database paths still coalesce. The local full suite records 148 passes and seven privacy-fixture failures because checkout-local scratch has a group-writable ancestor. The HTTP privacy module is byte-identical to accepted base; preserve this failed result and require all155 tests in private protected CI scratch. No privacy check or review policy is weakened.
