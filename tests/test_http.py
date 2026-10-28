from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from procache import ProviderCooldownError, SQLiteResponseCache
from procache.http import CachedHTTPReads, HTTPResponse


@pytest.fixture
def cache(tmp_path):
    store = SQLiteResponseCache(tmp_path / "responses.sqlite3", namespace="http-tests")
    try:
        yield CachedHTTPReads(store)
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            close()


@pytest.mark.parametrize("origin", ["https://api.github.test", "https://gitlab.test",
                                   "https://api.openrouter.test", "https://api.anthropic.test",
                                   "https://generativelanguage.test", "http://localhost:11434"])
def test_same_provider_record_is_loaded_once(cache, origin):
    calls = []

    def load():
        calls.append(1)
        return HTTPResponse(200, {"Content-Type": "application/json"}, b'{"id":1}')

    first = cache.request("GET", origin + "/models", load, scope="account-a", cacheable=True)
    second = cache.request("GET", origin + "/models", load, scope="account-a", cacheable=True)
    assert first.body == second.body == b'{"id":1}'
    assert not first.cache_hit and second.cache_hit
    assert len(calls) == 1


@pytest.mark.parametrize('lifetimes', [(15, 15.0), (15.0, 15)])
def test_equivalent_numeric_lifetimes_share_a_record(tmp_path, lifetimes):
    path = tmp_path / 'shared.sqlite3'
    calls = []
    readers = [CachedHTTPReads(SQLiteResponseCache(path), ttl=ttl) for ttl in lifetimes]
    def load():
        calls.append(1)
        return HTTPResponse(200, {}, b'record')
    try:
        first = readers[0].request('GET', 'https://a.test/models', load, scope='one', cacheable=True)
        second = readers[1].request('GET', 'https://a.test/models', load, scope='one', cacheable=True)
        assert first.body == second.body == b'record'
        assert not first.cache_hit and second.cache_hit
        assert len(calls) == 1
    finally:
        for reader in readers:
            reader.cache.close()


def test_distinct_actual_lifetimes_keep_separate_records(tmp_path):
    path = tmp_path / 'shared.sqlite3'
    calls = []
    for lifetime in (15, 30.0):
        with SQLiteResponseCache(path) as backend:
            reader = CachedHTTPReads(backend, ttl=lifetime)
            result = reader.request('GET', 'https://a.test/models',
                lambda: (calls.append(1) or HTTPResponse(200, {}, b'record')),
                scope='one', cacheable=True)
            assert not result.cache_hit
    assert len(calls) == 2


def test_numeric_lifetime_alias_survives_process_restart(tmp_path):
    code = '''
import json,sys
from pathlib import Path
from procache import SQLiteResponseCache
from procache.http import CachedHTTPReads,HTTPResponse
with SQLiteResponseCache(sys.argv[1]) as backend:
    cache=CachedHTTPReads(backend,ttl=json.loads(sys.argv[3]))
    def load():
        with Path(sys.argv[2]).open('a') as output: output.write('load\\n')
        return HTTPResponse(200,{},b'record')
    result=cache.request('GET','https://a.test/models',load,scope='one',cacheable=True)
    print(json.dumps(result.cache_hit))
'''
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                   'PYTHONDONTWRITEBYTECODE': '1'}
    hits = []
    for lifetime in ('15.0', '15'):
        result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'shared.sqlite3'),
                                 str(tmp_path / 'loads'), lifetime], env=environment,
                                capture_output=True, text=True, timeout=10, check=True)
        hits.append(json.loads(result.stdout))
    assert hits == [False, True]
    assert (tmp_path / 'loads').read_text().splitlines() == ['load']


@pytest.mark.parametrize("difference", ["scope", "origin", "parameters", "headers", "method", "url"])
def test_distinct_principals_and_representations_do_not_collide(cache, difference):
    args = {"method": "GET", "url": "https://a.test/records", "scope": "one",
            "parameters": {"page": 1}, "headers": {"Accept": "application/json"}, "cacheable": True}
    first = cache.request(**args, loader=lambda: HTTPResponse(200, {}, b"first"))
    args.update({"scope": "two"} if difference == "scope" else
                {"url": "https://b.test/records"} if difference == "origin" else
                {"url": "https://a.test/records/2"} if difference == "url" else
                {"parameters": {"page": 2}} if difference == "parameters" else
                {"headers": {"accept": "text/plain"}} if difference == "headers" else {"method": "HEAD"})
    second = cache.request(**args, loader=lambda: HTTPResponse(200, {}, b"second"))
    assert first.body == b"first" and second.body == b"second"
    assert not second.cache_hit


@pytest.mark.parametrize("bypass", [{"scope": None}, {"cacheable": False}, {"fresh": True},
                                   {"stream": True}, {"body": b"query"}])
def test_unknown_scope_and_nonrepeatable_reads_bypass(cache, bypass):
    args = {"scope": "account", "cacheable": True, **bypass}
    calls = []
    for _ in range(2):
        response = cache.request("GET", "https://a.test/records",
                                 lambda: (calls.append(1) or HTTPResponse(200, {}, b"ok")), **args)
        assert not response.cache_hit
    assert len(calls) == 2


@pytest.mark.parametrize("headers", [{"Cache-Control": "no-store"}, {"Cache-Control": "no-cache"},
                                     {"Cache-Control": "max-age=0"}, {"Cache-Control": 'max-age="0"'},
                                     {"Cache-Control": "max-age=0, private"}, {"Pragma": "no-cache"},
                                     {"cAcHe-CoNtRoL": "No-Cache"}])
def test_explicit_request_freshness_wins_over_public_response_cache_policy(cache, headers):
    calls = []
    for _ in range(2):
        response = cache.request("GET", "https://a.test/models",
                                 lambda: (calls.append(1) or HTTPResponse(200, {"Cache-Control": "public, max-age=600"}, b"record")),
                                 scope="known", headers=headers, cacheable=True)
        assert not response.cache_hit
    assert len(calls) == 2


@pytest.mark.parametrize("status,headers", [(500, {}), (403, {}), (200, {"Cache-Control": "no-store"}),
                                           (200, {"cache-control": "private, no-cache"}),
                                           (200, {"Cache-Control": "max-age=0"}),
                                           (200, {"Vary": "*"}), (200, {"Set-Cookie": "credential=x"})])
def test_failures_and_response_cache_policy_are_not_stored(cache, status, headers):
    calls = []
    for _ in range(2):
        cache.request("GET", "https://a.test/records",
                      lambda: (calls.append(1) or HTTPResponse(status, headers, b"body")),
                      scope="one", cacheable=True)
    assert len(calls) == 2


def test_provider_max_age_and_age_shorten_ttl(cache):
    clock = [100.0]
    cache.cache._clock = lambda: clock[0]
    calls = []
    def read():
        return cache.request("GET", "https://a.test/models",
                             lambda: (calls.append(1) or HTTPResponse(200, {"Cache-Control": "max-age=5", "Age": "3"}, b"ok")),
                             scope="one", cacheable=True)
    assert not read().cache_hit
    clock[0] += 1
    assert read().cache_hit
    clock[0] += 1
    assert not read().cache_hit and len(calls) == 2


def test_mutation_fences_an_older_inflight_read_and_preserves_other_accounts(cache):
    started, finish = threading.Event(), threading.Event()
    url = "https://a.test/records"
    cache.request("GET", url, lambda: HTTPResponse(200, {}, b"other"), scope="other", cacheable=True)
    def slow():
        started.set()
        assert finish.wait(5)
        return HTTPResponse(200, {}, b"old")
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(cache.request, "GET", url, slow, scope="one", cacheable=True)
        assert started.wait(5)
        cache.request("PUT", url, lambda: HTTPResponse(204, {}, b""), scope="one")
        new = cache.request("GET", url, lambda: HTTPResponse(200, {}, b"new"), scope="one", cacheable=True)
        finish.set()
        assert old.result().body == b"old" and new.body == b"new"
    assert cache.request("GET", url, lambda: pytest.fail("must hit new generation"), scope="one", cacheable=True).body == b"new"
    assert cache.request("GET", url, lambda: pytest.fail("other account invalidated"), scope="other", cacheable=True).body == b"other"


def test_failed_mutation_invalidates_unknown_remote_outcome(cache):
    url = "https://a.test/records"
    cache.request("GET", url, lambda: HTTPResponse(200, {}, b"old"), scope="one", cacheable=True)
    def fail():
        raise TimeoutError("remote outcome unknown")
    with pytest.raises(TimeoutError):
        cache.request("PATCH", url, fail, scope="one")
    assert not cache.request("GET", url, lambda: HTTPResponse(200, {}, b"new"), scope="one", cacheable=True).cache_hit


def test_transport_errors_are_not_cached(cache):
    calls = []
    def fail():
        calls.append(1)
        raise ConnectionError("offline")
    for _ in range(2):
        with pytest.raises(ConnectionError):
            cache.request("GET", "https://a.test/models", fail, scope="one", cacheable=True)
    assert len(calls) == 2


def test_rate_limit_cooldown_is_scoped_to_origin_and_account(cache):
    cache.request("GET", "https://a.test/models", lambda: HTTPResponse(429, {"Retry-After": "30"}, b"limited"), scope="one", cacheable=True)
    with pytest.raises(ProviderCooldownError):
        cache.request("GET", "https://a.test/models", lambda: pytest.fail("cooldown bypassed"), scope="one", cacheable=True)
    assert cache.request("GET", "https://a.test/models", lambda: HTTPResponse(200, {}, b"ok"), scope="two", cacheable=True).body == b"ok"


def test_concurrent_readers_share_one_transport_call(cache):
    calls, lock = [], threading.Lock()
    barrier = threading.Barrier(6)
    def task():
        barrier.wait(timeout=5)
        def load():
            with lock:
                calls.append(1)
            return HTTPResponse(200, {}, b"record")
        return cache.request("GET", "https://a.test/records", load, scope="one", cacheable=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: task(), range(6)))
    assert len(calls) == 1 and sum(r.cache_hit for r in results) == 5


def test_processes_share_one_transport_call(tmp_path):
    code = '''
import sys,time
from pathlib import Path
from procache import SQLiteResponseCache
from procache.http import CachedHTTPReads,HTTPResponse
cache=CachedHTTPReads(SQLiteResponseCache(sys.argv[1]))
def load():
    with Path(sys.argv[2]).open('a') as output: output.write('load\\n')
    time.sleep(.15)
    return HTTPResponse(200,{},b'record')
result=cache.request('GET','https://a.test/models',load,scope='one',cacheable=True)
print('true' if result.cache_hit else 'false')
'''
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    def call(_):
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path / "shared.sqlite3"),
                                 str(tmp_path / "loads")], env=env, capture_output=True, text=True, timeout=10, check=True)
        return json.loads(result.stdout)
    with ThreadPoolExecutor(max_workers=4) as pool:
        hits = list(pool.map(call, range(4)))
    assert sum(hits) == 3 and (tmp_path / "loads").read_text().splitlines() == ["load"]


def test_request_credentials_and_urls_are_not_persisted_as_metadata(cache):
    cache.request("GET", "https://a.test/models?key=secret-query", lambda: HTTPResponse(200, {}, b"ok"),
                  scope="secret-token", headers={"Authorization": "Bearer secret-header"}, cacheable=True)
    with sqlite3.connect(cache.cache.path) as db:
        rows = repr(db.execute("SELECT * FROM responses").fetchall())
    assert "secret-token" not in rows and "secret-header" not in rows and "secret-query" not in rows


def test_public_metadata_is_cached_without_replaying_edge_cookies(cache):
    def load():
        return HTTPResponse(200, {"Cache-Control": "public, max-age=60", "Set-Cookie": "test=edge"}, b"catalog")
    first = cache.request("GET", "https://a.test/models", load, scope="anonymous-public", cacheable=True)
    second = cache.request("GET", "https://a.test/models", lambda: pytest.fail("public metadata fetched twice"),
                           scope="anonymous-public", cacheable=True)
    assert first.headers["Set-Cookie"] == "test=edge"
    assert second.cache_hit and "Set-Cookie" not in second.headers
    with sqlite3.connect(cache.cache.path) as db:
        assert "test=edge" not in repr(db.execute("SELECT * FROM responses").fetchall())


@pytest.mark.parametrize("query", ["query { viewer { id } }", "{ viewer { id } }",
                                  "# metadata\nquery Named { viewer { id } }",
                                  'query { search(query:"mutation") { id } }'])
def test_explicit_graphql_reads_are_cached(cache, query):
    args = {"scope": "one", "cacheable": True, "graphql": True,
            "body": json.dumps({"query": query, "variables": {"number": 1}}).encode()}
    cache.request("POST", "https://a.test/graphql", lambda: HTTPResponse(200, {}, b'{"data":{"id":1}}'), **args)
    assert cache.request("POST", "https://a.test/graphql", lambda: pytest.fail("query fetched twice"), **args).cache_hit


@pytest.mark.parametrize("query", ["mutation { update { id } }", "# query\nmutation { update { id } }",
                                  "query Read { id } mutation Write { update { id } }",
                                  "subscription { events { id } }"])
def test_graphql_writes_and_ambiguous_documents_are_never_cached(cache, query):
    calls = []
    for _ in range(2):
        cache.request("POST", "https://a.test/graphql",
                      lambda: (calls.append(1) or HTTPResponse(200, {}, b'{"data":{}}')),
                      scope="one", cacheable=True, graphql=True, body=json.dumps({"query": query}).encode())
    assert len(calls) == 2


def test_graphql_errors_and_duplicate_query_fields_are_not_cached(cache):
    for body in [b'{"query":"query { id }"}',
                 b'{"query":"mutation { id }","query":"query { id }"}']:
        calls = []
        for _ in range(2):
            cache.request("POST", "https://a.test/graphql",
                          lambda calls=calls: (calls.append(1) or HTTPResponse(200, {}, b'{"errors":[{"message":"failed"}]}')),
                          scope="one", cacheable=True, graphql=True, body=body)
        assert len(calls) == 2


def test_async_sdk_reads_coalesce_without_blocking_the_event_loop(cache):
    calls = []
    async def exercise():
        loop = asyncio.get_running_loop()
        async def load():
            assert asyncio.get_running_loop() is loop
            calls.append(1)
            await asyncio.sleep(.02)
            return HTTPResponse(200, {}, b"record")
        return await asyncio.gather(*[
            cache.arequest("GET", "https://a.test/models", load, scope="one", cacheable=True)
            for _ in range(6)
        ])
    results = asyncio.run(exercise())
    assert len(calls) == 1 and sum(r.cache_hit for r in results) == 5


def test_shared_factory_reuses_records_and_invalidates_across_applications(tmp_path):
    first = CachedHTTPReads.shared(path=tmp_path / "shared.sqlite3")
    second = CachedHTTPReads.shared(path=tmp_path / "shared.sqlite3")
    scope = first.credential_scope("placeholder_a", "tenant")
    assert scope == second.credential_scope("placeholder_a", "tenant")
    assert (tmp_path / "shared.sqlite3").stat().st_mode & 0o077 == 0
    first.request("GET", "https://a.test/models", lambda: HTTPResponse(200, {}, b"old"), scope=scope, cacheable=True)
    assert second.request("GET", "https://a.test/models", lambda: pytest.fail("other application fetched twice"),
                          scope=scope, cacheable=True).cache_hit
    second.request("PUT", "https://a.test/models", lambda: HTTPResponse(204, {}, b""), scope=scope)
    assert first.request("GET", "https://a.test/models", lambda: HTTPResponse(200, {}, b"new"),
                         scope=scope, cacheable=True).body == b"new"


@pytest.mark.parametrize("credentials", [(), (None,), ("",), (b"",), (None, "", b""),
                                         ("known", None), (None, "known"), ("known", ""),
                                         (b"", "tenant"), ("known", "tenant", None)])
def test_missing_credentials_do_not_create_a_shared_known_principal(cache, credentials):
    scope = cache.credential_scope(*credentials)
    assert scope is None
    calls = []
    for _ in range(2):
        response = cache.request("GET", "https://a.test/models",
                                 lambda: (calls.append(1) or HTTPResponse(200, {}, b"record")),
                                 scope=scope, cacheable=True)
        assert not response.cache_hit
    assert len(calls) == 2


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_shared_store_rejects_existing_nonprivate_directory(tmp_path, mode):
    directory = tmp_path / "shared"
    directory.mkdir(mode=mode)
    directory.chmod(mode)
    with pytest.raises(ValueError, match="owned and private"):
        CachedHTTPReads.shared(path=directory / "cache.sqlite3")
    assert directory.stat().st_mode & 0o777 == mode
    assert not (directory / "cache.sqlite3").exists()


def test_shared_store_rejects_replaceable_private_directory(tmp_path):
    writable = tmp_path / "writable"
    writable.mkdir()
    writable.chmod(0o777)
    private = writable / "private"
    private.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="ancestor"):
        CachedHTTPReads.shared(path=private / "cache.sqlite3")
    assert not (private / "cache.sqlite3").exists()


def test_shared_store_rejects_symlink_directory_before_creating_store(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        CachedHTTPReads.shared(path=alias / "new" / "cache.sqlite3")
    assert not (actual / "new").exists()


def test_concurrent_public_reads_only_deliver_cookies_to_transport_owner(tmp_path):
    caches = [CachedHTTPReads.shared(path=tmp_path / "shared.sqlite3") for _ in range(8)]
    start = threading.Barrier(len(caches))
    calls = []

    def load():
        calls.append(1)
        return HTTPResponse(200, {"Cache-Control": "public, max-age=60", "Set-Cookie": "edge=unique"}, b"catalog")

    def read(cache):
        start.wait(timeout=5)
        return cache.request("GET", "https://a.test/models", load, scope="anonymous", cacheable=True)

    with ThreadPoolExecutor(max_workers=len(caches)) as pool:
        results = list(pool.map(read, caches))
    assert len(calls) == 1
    assert sum(response.cache_hit for response in results) == len(caches) - 1
    for response in results:
        assert response.body == b"catalog"
        assert ("Set-Cookie" in response.headers) == (not response.cache_hit)


def test_short_lived_reader_cannot_reuse_a_longer_lived_entry(tmp_path):
    long = CachedHTTPReads.shared(path=tmp_path / "shared.sqlite3", ttl=300)
    short = CachedHTTPReads.shared(path=tmp_path / "shared.sqlite3", ttl=1)
    long.request("GET", "https://a.test/models", lambda: HTTPResponse(200, {}, b"old"), scope="one", cacheable=True)
    assert short.request("GET", "https://a.test/models", lambda: HTTPResponse(200, {}, b"new"),
                         scope="one", cacheable=True).body == b"new"


@pytest.mark.parametrize("ttl", [0, -1, float("nan"), float("inf"), 3601])
def test_ttl_is_bounded(cache, ttl):
    with pytest.raises(ValueError):
        CachedHTTPReads(cache.cache, ttl=ttl)
