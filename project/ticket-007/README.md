# Ticket 007: Add account-scoped multi-provider HTTP read caching

- **ID**: ticket-007
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-27
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — the user requested reusable caching for repeated API records across providers and investigation of remaining gaps.

## Goal and scope

Cache repeated successful provider reads with TTL, response policy, process coalescing, fresh bypass and fenced invalidation; preserve account separation.

## Acceptance criteria

- [x] AC-01: Repeated eligible reads share results while different accounts and representations remain isolated.
- [x] AC-02: Existing behavior and new concurrency, invalidation and failure regressions pass.
- [ ] AC-03: Protected publication is observed separately; unknown existing work and all required gates are preserved.

The canonical identity correction is independently merged in PR #9. Resume on that accepted base and exclude the unrelated unpublished development/performance commits. Approved canonical OneDev and Validator profiles are active; the first real canonical canary passed. Consumer pins remain separate owned integrations.

On the independently accepted identity base, all 122 complete cache tests pass. Missing credential inputs remain unknown and bypass caching; public metadata requires an explicit anonymous scope. Scoped lint and governance pass. The candidate contains only this adapter, its regressions and this ticket, with no inherited unpublished development commits.

Explicit request no-store/no-cache, max-age=0 and legacy Pragma freshness bypass cached reads and storage even when the provider returns publicly cacheable data.
