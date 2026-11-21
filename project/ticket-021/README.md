# Ticket 021: Revalidate expired PyGithub reads with ETag

- **ID**: ticket-021
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-21

## Goal and scope

To be completed from human-owned input.

Proposed by the agent (pending owner approval): semcod/planfile wraps PyGithub
with `CachedPyGithubRequester` at `SUBACTOR_GITHUB_READ_TTL=15` s. Every read
older than 15 s is a full REST call, while GitHub does not count a 304 answer
to a conditional request against the primary rate limit (measured 2026-11-21:
REST core exhausted 10:36-10:57 UTC).

- `src/procache/pygithub.py`: keep the last ETag-bearing GET response for
  24 h; after the short TTL, send `If-None-Match`. PyGithub returns a 304 as
  headers with no payload; only then, and when the tag matches, reuse the
  former payload with the fresh response headers. Any other answer replaces
  it. Caller-supplied conditional headers are never overridden.
- `tests/test_pygithub.py`: 304 reuse, changed resource, mismatched tag,
  caller conditionals. Two test credential literals now use the `test-`
  prefix required by the secret gate.

## Acceptance criteria

- [ ] AC-01: Scope is approved by a human owner.
- [ ] AC-02: An expired read with a stored ETag is revalidated; a matching 304
      returns the former payload with the new headers.
- [ ] AC-03: A changed or mismatched answer returns and stores the new payload.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
