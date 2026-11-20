# Ticket 019: Preserve cached HTTP responses when URTLog configuration fails

- **ID**: ticket-019
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-21

## Goal and scope

An unreadable URTLog path can raise before the bridge enters its error handler. The transport can return a valid response and cache it while the application receives an exception. Keep the existing result of the HTTP read when optional telemetry preparation fails.

SESSION_EXECUTION_AUTHORIZATION covers repairing, testing, publishing, and merging this pilot regression through OneDev and the independent Validator.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: A failed state-directory lookup preserves the live and cached HTTP responses.
- [x] AC-03: An unusable telemetry URL produces an unsuccessful telemetry result without changing the HTTP cache contract.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
