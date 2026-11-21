# Ticket 020: Hold the gh provider cooldown until the rate-limit reset per API family

- **ID**: ticket-020
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-21

## Goal and scope

To be completed from human-owned input.

Proposed by the agent (pending owner approval): on 2026-11-21 the GitHub REST
core limit was exhausted from 10:36 to 10:57 UTC. Host gh calls continued at
about 6300/h meanwhile, and right after the reset core dropped at about
5950/h before settling near 1800/h. `CachedReadCommand` cools a provider down
for a fixed 60 s, so callers retry every minute and resume together at reset;
one cooldown also covers every API family.

- `src/procache/commands.py`: on a rate-limit error, read `gh api rate_limit`
  (not counted against the primary limit) and cool down until the exhausted
  resource resets, plus 1-15 s jitter, bounded to 60-3600 s. Without reset
  evidence, or when quota remains (secondary limit), keep 60 s. The cooldown
  key now includes the API family (core, graphql, search), so an exhausted
  GraphQL budget no longer blocks REST reads.
- `tests/test_commands.py`: family mapping, reset-bound cooldown, family
  isolation, default and bounds.

## Acceptance criteria

- [ ] AC-01: Scope is approved by a human owner.
- [ ] AC-02: A read limited on an exhausted resource is refused with 75
      until that resource's reset (jittered, bounded); other families run.
- [ ] AC-03: Without reset evidence or with remaining quota the cooldown
      stays 60 s.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
