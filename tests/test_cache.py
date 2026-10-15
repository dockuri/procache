import threading
import time
from multiprocessing import get_context

import pytest

from procache import ProviderCooldownError, SQLiteResponseCache, is_rate_limit_error


@pytest.mark.parametrize("message", [
    "no required checks reported on the 'ticket/030-distinguish-authority-denial-from-remote-rate-limiting' branch",
    "HTTP 404: repository acme/rate-limit-tools not found",
    "cannot open '/tmp/rate limit exceeded.log'",
    "missing https://example.test/secondary-limit and docs/abuse-detection.md",
    "HTTP 403: permission denied",
    "provider unavailable",
    "Issue 429 is missing",
])
def test_resource_names_and_ordinary_errors_are_not_throttling(message):
    assert not is_rate_limit_error(RuntimeError(message))


@pytest.mark.parametrize("message", [
    "HTTP 429 Too Many Requests",
    "gh: HTTP 403: API rate limit exceeded",
    "You have exceeded a secondary rate limit. Please wait.",
    "secondary limit; try again later",
    "You have triggered an abuse detection mechanism",
    "Requests are temporarily rate-limited",
    '{"message":"API rate limit exceeded"}',
])
def test_explicit_provider_throttling_diagnostics_are_preserved(message):
    assert is_rate_limit_error(RuntimeError(message))


@pytest.mark.parametrize("status,headers,expected", [
    (429, {}, True),
    (403, {"X-RateLimit-Remaining": "0"}, True),
    (403, {"Retry-After": "60"}, True),
    (403, {"X-RateLimit-Remaining": "100"}, False),
    (403, {}, False),
])
def test_structured_throttling_evidence_takes_precedence(status, headers, expected):
    error = RuntimeError("request denied")
    error.status_code = status
    error.headers = headers
    assert is_rate_limit_error(error) is expected


def test_cache_persists_and_expires(tmp_path):
    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3", namespace="github")
    key = cache.key("GET", "/repos/acme/demo")
    assert cache.get(key) is None
    cache.put(key, b"payload", ttl=60)
    assert cache.get(key).value == b"payload"
    assert cache.prune(now=time.time() + 61) == 1
    assert cache.get(key) is None


def test_same_key_load_is_coalesced(tmp_path):
    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3")
    calls = 0
    lock = threading.Lock()

    def loader():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.02)
        return b"ok"

    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.get_or_set("k", loader, ttl=60))) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == 1
    assert all(value == b"ok" for value, _ in results)


def test_rate_limit_cooldown_is_shared_and_blocks_loader(tmp_path):
    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3", namespace="github")
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        error = RuntimeError("HTTP 429 rate limit exceeded")
        error.status_code = 429
        raise error

    with pytest.raises(RuntimeError):
        cache.get_or_set(
            "read",
            loader,
            ttl=60,
            cooldown_key="provider",
            cooldown_seconds=60,
            is_rate_limit=lambda exc: getattr(exc, "status_code", None) == 429,
        )
    with pytest.raises(ProviderCooldownError):
        cache.get_or_set(
            "other-read",
            loader,
            ttl=60,
            cooldown_key="provider",
            is_rate_limit=lambda exc: getattr(exc, "status_code", None) == 429,
        )
    assert calls == 1


def _process_loader(path, ready, calls, result):
    cache = SQLiteResponseCache(path, namespace="processes")
    ready.wait()

    def loader():
        with calls.get_lock():
            calls.value += 1
        time.sleep(0.2)
        return b"shared"

    result.put(cache.get_or_set("same", loader, ttl=60))


def test_same_key_load_is_coalesced_across_processes(tmp_path):
    context = get_context("fork")
    ready = context.Barrier(2)
    calls = context.Value("i", 0)
    results = context.Queue()
    processes = [
        context.Process(target=_process_loader, args=(tmp_path / "cache.sqlite3", ready, calls, results))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
    assert all(process.exitcode == 0 for process in processes)
    assert calls.value == 1
    assert sorted(results.get() for _ in processes) == [(b"shared", False), (b"shared", True)]


def test_injected_clock_controls_expiry_and_cooldown(tmp_path):
    moments = [1_000.0]
    cache = SQLiteResponseCache(
        tmp_path / "cache.sqlite3", namespace="github", clock=lambda: moments[0]
    )
    key = cache.key("GET", "/user")
    cache.put(key, b"payload", ttl=15)
    assert cache.get(key).value == b"payload"
    cache.cooldown("provider", ttl=60)
    assert cache.cooldown_remaining("provider") == pytest.approx(60.0)
    moments[0] += 16
    assert cache.get(key) is None
    assert cache.cooldown_remaining("provider") == pytest.approx(44.0)
    moments[0] += 45
    assert cache.cooldown_remaining("provider") == 0.0


def test_injected_clock_applies_to_get_or_set(tmp_path):
    moments = [2_000.0]
    calls = []

    def loader():
        calls.append(1)
        return b"value"

    first = SQLiteResponseCache(tmp_path / "cache.sqlite3", clock=lambda: moments[0])
    second = SQLiteResponseCache(tmp_path / "cache.sqlite3", clock=lambda: moments[0])
    assert first.get_or_set("k", loader, ttl=15) == (b"value", False)
    assert second.get_or_set("k", loader, ttl=15) == (b"value", True)
    moments[0] += 16
    assert second.get_or_set("k", loader, ttl=15) == (b"value", False)
    assert len(calls) == 2


def test_writes_retire_expired_reads_in_bounded_batches(tmp_path):
    moments = [3_000.0]
    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3", namespace="github", clock=lambda: moments[0])
    other = SQLiteResponseCache(tmp_path / "cache.sqlite3", namespace="other", clock=lambda: moments[0])
    for i in range(cache.PRUNE_BATCH + 10):
        cache.put(f"old{i}", b"x", ttl=5)
    other.put("theirs", b"y", ttl=5)
    cache.put("live", b"z", ttl=600)
    moments[0] += 10

    def rows(namespace):
        with cache._connect() as db:
            return db.execute("SELECT count(*) FROM responses WHERE namespace=?", (namespace,)).fetchone()[0]

    def writer():
        return SQLiteResponseCache(cache.path, namespace="github", clock=lambda: moments[0])

    first = writer()
    first.put("new", b"n", ttl=60)
    assert rows("github") == 10 + 2
    for i in range(first.PRUNE_EVERY - 1):
        first.put(f"between{i}", b"n", ttl=60)
    assert rows("github") == 10 + 2 + first.PRUNE_EVERY - 1
    first.put("pruning", b"n", ttl=60)
    assert rows("github") == 2 + first.PRUNE_EVERY
    assert cache.get("live").value == b"z"
    assert rows("other") == 1


def test_waiter_does_not_take_the_write_lock_while_a_flight_is_active(tmp_path, monkeypatch):
    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3")
    assert cache._claim_flight("k", "other-process")
    claims = []
    original = cache._claim_flight
    monkeypatch.setattr(cache, "_claim_flight", lambda key, owner: claims.append(key) or original(key, owner))
    threading.Timer(0.4, lambda: (cache.put("k", b"loaded", ttl=60), cache._release_flight("k", "other-process"))).start()
    assert cache.get_or_set("k", lambda: b"own", ttl=60) == (b"loaded", True)
    assert claims == []


def test_stale_flight_is_reclaimed_by_the_next_waiter(tmp_path):
    moments = [4_000.0]
    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3", clock=lambda: moments[0])
    assert cache._claim_flight("k", "crashed-process")
    moments[0] += 121
    assert cache.get_or_set("k", lambda: b"fresh", ttl=60) == (b"fresh", False)
