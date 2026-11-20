# Ticket 017: Optional uritime-urtlog bridge for Procache HTTP read observations

- **ID**: ticket-017
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-20
- **Authorization**: `SESSION_EXECUTION_AUTHORIZATION` (user autonomous pilot rollout mandate for `uritime/urtlog` across HTTP/URL cache and service clients, including publication through the repository's protected delivery process)

## Goal and scope

Add a zero-mandatory-dependency, opt-in `uritime-urtlog` bridge (`src/procache/urtlog_bridge.py`) wired fail-open into `CachedHTTPReads.request()` when `URTLOG_STATE_DIR` is configured. Sanitize observed URLs (stripping userinfo, query parameters, and fragments so secrets never leak), record cache hit/miss telemetry in `UrtLogStore`, and register observed service URLs in `UnifiedRegistry`.

## Acceptance criteria

- [x] AC-01: `src/procache/urtlog_bridge.py` sanitizes URLs (removing credentials, queries, and fragments) and lazily imports `urtlog` strictly when `URTLOG_STATE_DIR` (or explicit `state_dir`) is set.
- [x] AC-02: `CachedHTTPReads.request()` invokes the opt-in bridge fail-open with zero mandatory dependencies and unchanged default behavior when `URTLOG_STATE_DIR` is unset.
- [x] AC-03: Unit tests in `tests/test_urtlog_bridge.py` cover URL sanitization, opt-out no-op, missing-package degradation, and live `CachedHTTPReads` + `urtlog` recording, with `pytest` and `./project/governance-check.sh` passing.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
