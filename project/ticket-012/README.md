# Ticket 012: Protect command cache when GitHub identity is unknown

- **ID**: ticket-012
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28

## Goal and scope

Prevent reuse of GitHub command results when no explicit GitHub token is
available for cache identity. GitHub CLI may keep tokens in an external system
credential store, whose contents are not represented by hosts.yml.

SESSION_EXECUTION_AUTHORIZATION: the user requested continued implementation,
testing and protected publication of the canonical provider cache.

## Acceptance criteria

- [x] AC-01: Commands without an explicit token execute without sharing cached results.
- [x] AC-02: Explicit token identities retain cache hits and separate on rotation.
- [ ] AC-03: Regression tests, managed governance, protected verification and independent publication pass.

Local regression: both synthetic hidden-credential cases fail against the
accepted implementation and pass with this change; 32 command-cache tests pass
under the enrolled Wellman runtime. The protected full suite remains required.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
