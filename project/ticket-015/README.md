# Ticket 015: Revalidate expired HTTP metadata with ETags

- **ID**: ticket-015
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-20

## Goal and scope

OneDev scans GitHub at intervals of at least 30 seconds and caches reads for
15 seconds. Preserve that freshness window and let a metadata consumer send
the retained ETag after expiration. Reuse a body only after the provider
confirms it with HTTP 304. OneDev adoption is a separate source change because
ticket-990 owns its GitHub client.

SESSION_EXECUTION_AUTHORIZATION: the user requested continuation of autonomous
GH publication and asked to use ProCache to reduce GitHub API consumption.

## Acceptance criteria

- [x] AC-01: A 30-second polling fixture gets one full response followed by
  conditional revalidation, with exact isolation by credential scope.
- [x] AC-02: Fresh reads, changed responses, denied access and invalidated
  representations cannot reuse a retained body.
- [x] AC-03: The complete local ProCache suite passes with the new opt-in.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
