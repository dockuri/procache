# Ticket 003: Bound shared cache growth and stop write-lock polling while waiting for a flight

- **ID**: ticket-003
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

The shared `~/.cache/subactor/github.sqlite3` used by the Validator and its
reconcile timers had grown to 1.04 GB: 51,517 of 51,520 `github-user` rows
were expired, because nothing calls `prune()`, plus 579 abandoned flights.
Sampling `BEGIN IMMEDIATE` on it for 60 s gave a p50 wait of 34 ms, p95 2.7 s
and max 3.7 s, and manual Validator runs failed with "database is locked"
unless pointed at a private `XDG_CACHE_HOME`.

Two changes in `SQLiteResponseCache`:

- The first `put()` of each instance and every `PRUNE_EVERY`-th (16) after it
  retires at most `PRUNE_BATCH` (64) expired rows and the expired flights of
  its namespace inside the write transaction it already holds, so the file
  stops growing and an existing backlog drains without a long lock.
- A waiter checks the other process's flight with a read and backs off to
  `MAX_WAIT_INTERVAL` (0.5 s); it attempts a claim, which takes the write lock,
  only when no live flight exists. Before, every waiter took the write lock
  every 50 ms.

Keys, TTLs, namespaces, read semantics and the schema are unchanged. Existing
cache files shrink only through SQLite free-page reuse; compaction is out of
scope.

## Benchmark

800 writes of 16 KB, one per simulated second with the Validator's 15 s TTL,
real disk, three interleaved runs per side (thread CPU, host load about 60):

| | before | after |
|---|---|---|
| `put` CPU p50 | 729–747 µs | 686–714 µs |
| `put` CPU p95 | 1068–1218 µs | 1219–1338 µs |
| rows left | 800 | 30 |
| file size | 15.9 MB | 4.7 MB |

Pruning on every write cost +30–50% p50 CPU, so it is amortized over 16
writes; the p95 increase is the pruning write itself.

## Acceptance criteria

- [x] AC-01: Expired rows are retired in bounded batches; live rows and other
  namespaces are kept.
- [x] AC-02: A waiter makes no claim while another flight is active; a stale
  flight is still reclaimed.
- [x] AC-03: Full suite and governance gate pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
