# Ticket 005: Classify provider diagnostics without resource name false positives

- **ID**: ticket-005
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-15

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue repairs and protected merging (PLF-144).
A read-only fd2 trace of the independent Validator reproduced a false cooldown:
`gh pr checks --required` returns no required checks reported on a branch whose
identifier contains rate-limiting. An arbitrary substring is not provider
throttle evidence. Correct this at Procache HOME without weakening publication
checks, deleting cooldown state or changing the protected Validator actor.

## Acceptance criteria

- [x] AC-01: Resource names and ordinary permission/availability errors never become rate-limit evidence solely from identifier substrings.
- [x] AC-02: Actual429,403 with relevant headers and established provider throttling diagnostics still enforce shared cooldowns.
- [x] AC-03: The exact gh failure remains visible and a subsequent unrelated read executes; focused/full checks and governance pass.
- [ ] AC-04: Independent protected publication and exact merge readback; consumer runtime adoption has separate evidence.

## Validation

60 full-suite tests pass, including20 added cases. Four new regression cases
failed on the previous classifier. Ruff and managed governance pass.
Existing fixture credential literals were replaced with canonical test-prefixed
placeholders; cache secrecy assertions still verify their absence.
No runtime or protected publication policy has been changed.
