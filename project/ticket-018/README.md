# Ticket 018: Add optional uritime-urtlog extra dependency in pyproject.toml

- **ID**: ticket-018
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-20
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (autonomous pilot rollout of optional uritime-urtlog integration and publication)

## Goal and scope

Add `[project.optional-dependencies] urtlog = ["uritime-urtlog>=0.3.0"]` to `pyproject.toml` to pair with the opt-in `procache.urtlog_bridge` merged in `ticket-017` (`#19`) while preserving zero mandatory dependencies.

## Acceptance criteria

- [x] AC-01: `[project.optional-dependencies]` defines `urtlog = ["uritime-urtlog>=0.3.0"]`.
- [x] AC-02: Zero mandatory runtime dependencies remain in `pyproject.toml`.
- [x] AC-03: `pytest` and `./project/governance-check.sh` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
