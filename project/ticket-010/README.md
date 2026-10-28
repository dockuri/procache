# ticket-010: Canonical numeric TTL identity

- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requests continued cache improvements, tests and protected merges. Existing explicit proxy11435 deployment authorization persists; no credential contents need to be read or transferred.

- [x] AC-01: TTL15 and15.0 share cache records across client instances/processes.
- [x] AC-02: Distinct actual lifetimes remain separate; preserve provider/account/request identity and freshness/invalidation behavior.
- [ ] AC-03: Full tests and governance pass, independent exact-head publication succeeds and the already authorized proxy runtime is qualified.

Observed before implementation: production proxy stores TTL15.0 records, while an independent reader with TTL15 misses the same record and would call upstream. Matching15.0 hits with zero upstream calls. This is an avoidable cross-client cache partition, not a credential or freshness bypass. Normalize the already validated lifetime once.

Validation: three regressions fail on the unchanged accepted base; after normalization all152 tests pass on Python3.10 and3.13. Ruff passes on both material files, governance passes and diff whitespace checks pass. The different-lifetime case still loads separately. Independent native validation, protected publication and runtime qualification remain pending at this source commit.
