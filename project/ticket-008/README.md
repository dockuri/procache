# Ticket 008: Harden HTTP cache identity and private storage

- **ID**: ticket-008
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — continue the requested shared provider API cache rollout and correct identified defects.

## Scope

Reject partially unknown credential/tenant tuples and shared stores in unsafe directories before consumers adopt the HTTP adapter. Preserve private shared storage and server cache policy. Evaluate the independent PR #10 advisory findings against the canonical implementation, including the cookie single-flight claim.

## Acceptance criteria

- [x] AC-01: Unknown identity components bypass caching; unsafe directory chains are rejected before SQLite opens a database.
- [x] AC-02: Concurrent callers receive one upstream response and cached waiters receive no cookie; the full suite and governance pass.
- [ ] AC-03: Exact-head independent publication is read back and unrelated unpublished primary work is preserved.

All 133 library tests pass, including 11 additional identity, directory and concurrent-cookie cases. Pinned Ruff 0.15.11 and managed governance pass. The concurrent-cookie advisory does not reproduce: only the transport owner receives Set-Cookie, and all seven waiters receive the sanitized stored representation. Required explicit governance plugin remains enabled; unrelated globally installed pytest plugins are excluded from local execution.
