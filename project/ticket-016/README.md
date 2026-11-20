# Ticket 016: Cache gh repository reads under an explicit GH_HOST and resolved keyring token

- **ID**: ticket-016
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-20

## Goal and scope

To be completed from human-owned input.

On 2026-11-20 the workstation exhausted the GitHub REST core limit at ~7,700
`gh` calls per hour while the shared cache `~/.cache/subactor/github.sqlite3`
held 17 entries and no cooldowns. Services authenticate through the gh
keyring, which tickets 012/013 rightly refuse to treat as a known identity,
and `gh pr`/`gh issue`/`gh search` reads were only shareable when both public
and enterprise tokens were set. Consumers therefore got no caching even when
they used `CachedReadCommand`.

This ticket keeps those guarantees and adds an explicit path:

- `gh pr`/`gh issue` reads are shareable when `GH_HOST` is set, the repository
  is explicit (`--repo`/`-R` or `GH_REPO`) without host or URL, and the token
  class matches the host; `gh search` only for `GH_HOST=github.com`.
- `github_env(host)` pins `GH_HOST` and copies the token gh would use, read
  locally with `gh auth token --hostname`, into the child environment. On any
  failure no token is added and caching stays bypassed.

The owner asked why procache does not reduce GitHub API load and instructed
"kolejno wykonuj i testuj, scalaj" for the resulting work in this session.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: Explicit-host repository reads are shared; every ambiguous host,
      repository, URL or token-class case still executes each time.
- [x] AC-03: `github_env` resolves the keyring token without persisting it and
      leaves identity unresolved on failure.
- [x] AC-04: The existing suite passes unchanged; a live read with the
      resolved token produces one provider call and one cache hit.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
