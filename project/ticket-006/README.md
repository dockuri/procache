# Ticket 006: Align governance repository identity with dockuri/procache

- **ID**: ticket-006
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-19
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — the user explicitly answered “Przejmij ticket-006” on 2026-10-27, transferring this bounded scope from the previous session.

## Goal and scope

Publish the existing isolated repository identity correction from e297a0eb8223ba4f8264e97e486fb317f6123331. Preserve all required check names and the unrelated unpublished performance commit 770343aa952475de636e03107d41cd2848203a04. Preserve the prior expired allocator projection as external handoff evidence; acquire current ownership through the deployed canonical controller implementation and existing external store.

## Acceptance criteria

- [x] AC-01: Explicit user handoff assigns this existing ticket to the current session.
- [x] AC-02: Canonical repository identity and unchanged required checks pass governance and the complete original cache suite.
- [ ] AC-03: Exact-head protected canonical verification and independent publication succeed; activation and canary are recorded separately.

The original cache suite and governance pass on the isolated accepted base. The deployed controller implementation acquired current ownership in the existing external store with fencing token 283 after explicit user handoff. The previous expired allocator projection and original commit remain preserved. The candidate excludes the unrelated 770343 optimization.

The canonical repository identity is published as required-check instance revision 2; the schema and both required check names remain unchanged.
