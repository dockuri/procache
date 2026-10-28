# ticket-009: Bound cache resources and safely reuse SQLite connections

- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requests continued implementation, tests and protected merges; explicitly handed off commit 770343aa952475de636e03107d41cd2848203a04 on 2026-10-28 ("Tak, przejmij zmianę 770343a"). Original history is preserved in local annotated recovery/procache-770343a-20261028 and verified external bundle. This bounded ticket replaces the old unrelated ticket-001 attribution for the material performance work.

- [x] AC-01: Reuse SQLite connections per thread/PID, preserve durability defaults and support explicit close/reopen.
- [x] AC-02: Keep same-key single-flight correct without retaining locks for completed unique keys.
- [x] AC-03: Bound credential fingerprints; detect account rotation even with preserved mtime and byte length, and bypass cache on unstable identity.
- [ ] AC-04: Run complete regressions, governance and exact-head native CI; publish through independent Validator.

Qualification before implementation: accepted cache coalesced 1920 logical reads across 16 processes to 30 loads, with correct account/page isolation and live fresh/health paths. Original handed-off connection reuse measured ~19.5x faster bare warm reads and ~4.6x for profiled 1 KiB HTTP cache hits, not end-to-end API speed. Original credential mtime/size-only optimization fails synthetic atomic replacement; accepted strong lock registry retains 1200 entries after 1200 one-use keys. Preserve these observations; repair before publication. Runtime deployment remains separate.

Validation: 148 tests pass on Python 3.13 and 3.10; four new resource/performance regressions fail on the unchanged accepted base. A reproduced SQLITE_BUSY in concurrent cold WAL initialization is repaired with bounded retry; 40 independent fresh databases with eight processes each pass with exactly one shared HTTP load per database. Ruff passes on the five material files; governance passes. Canonical process qualification preserves account, provider and page identity, explicit freshness, mutation invalidation and live health. 1200 unique completed reads retain zero synchronization locks. Independent publication remains pending at this commit.
