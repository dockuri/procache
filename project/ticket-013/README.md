# Ticket 013: Bind command cache credentials to the selected GitHub host

- **ID**: ticket-013
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28

## Goal and scope

Bind command cache eligibility to a credential appropriate for the selected
GitHub host. A token for github.com alone does not identify a credential in
the Enterprise keyring, and vice versa. When host selection is ambiguous,
bypass caching unless both credential classes are explicit.

SESSION_EXECUTION_AUTHORIZATION: the user requested continued implementation,
testing and protected publication of canonical provider caching.

## Acceptance criteria

- [x] AC-01: Mixed-host requests never reuse cache with the wrong token class.
- [x] AC-02: Unambiguous API requests and requests with both token classes retain safe cache hits.
- [ ] AC-03: Regression tests, managed governance, protected verification and independent publication pass.

Local regression: mixed-host, configured-default-host and hostname-normalization
cases fail against earlier candidates. All 51 command-cache tests pass through
the enrolled Wellman runtime on Python 3.10 and 3.13; protected full-suite
verification remains required.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
