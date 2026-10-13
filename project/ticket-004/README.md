# Ticket 004: Upgrade new-project governance adoption to 0.20.97

- **ID**: ticket-004
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

procache adopted new-project 0.20.35 (`cfaa0bf`). Its `project/new-ticket.sh`
scaffolds a ticket directory on `main` in the primary checkout instead of
allocating a linked worktree on a ticket branch; tickets 003 and 004 had to be
moved by hand. This ticket upgrades the managed adoption to 0.20.97
(`c6587635`, the revision used by wellmanifest/data-plane and semcod/willset)
with the pinned updater, and regenerates the `[tool.wellmanifest]` declaration
in `pyproject.toml` from the new lock. No procache code, tests or docs change.

## Acceptance criteria

- [x] AC-01: `create_adoption_lock.py --upgrade` from new-project at
  `c6587635` applied; managed files and hashes are not hand-edited.
- [x] AC-02: `create_adoption_lock.py --check` reports the adoption current.
- [ ] AC-03: Governance gate passes locally and in hosted CI.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
