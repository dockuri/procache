from procache import CachedPyGithubRequester, SQLiteResponseCache
from types import SimpleNamespace

import pytest


class Delegate:
    def __init__(self, token="test-synthetic-a", base_url="https://api.github.test"):
        self.calls = 0
        self.auth = SimpleNamespace(token=token, token_type="token")
        self.base_url = base_url

    def requestJsonAndCheck(self, *args):
        self.calls += 1
        return {"X-RateLimit-Remaining": "10"}, {"value": self.calls}


def test_pygithub_get_is_cached_but_mutation_is_delegated(tmp_path):
    delegate = Delegate()
    requester = CachedPyGithubRequester(
        delegate,
        SQLiteResponseCache(tmp_path / "cache.sqlite3", namespace="github"),
    )
    assert requester.requestJsonAndCheck("GET", "https://api.github.test/repos/a/b")[1] == {"value": 1}
    assert requester.requestJsonAndCheck("GET", "https://api.github.test/repos/a/b")[1] == {"value": 1}
    requester.requestJsonAndCheck("POST", "https://api.github.test/repos/a/b/issues", input={"x": 1})
    assert delegate.calls == 2



def test_accounts_and_token_rotation_do_not_share_payloads(tmp_path):
    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3", namespace="same-repo")
    first, second = Delegate("synthetic-a"), Delegate("synthetic-b")
    a, b = CachedPyGithubRequester(first, cache), CachedPyGithubRequester(second, cache)
    a.requestJsonAndCheck("GET", "/user")
    b.requestJsonAndCheck("GET", "/user")
    assert (first.calls, second.calls) == (1, 1)
    a.requestJsonAndCheck("GET", "/user")
    assert first.calls == 1
    first.auth.token = "test-rotated"
    a.requestJsonAndCheck("GET", "/user")
    assert first.calls == 2
    assert b"synthetic-" not in (tmp_path / "cache.sqlite3").read_bytes()


@pytest.mark.parametrize("change", [
    {"headers": {"Accept": "application/vnd.github.raw"}},
    {"headers": {"Authorization": "synthetic-override"}},
    {"follow_302_redirect": True},
])
def test_request_representation_partitions_cache(tmp_path, change):
    delegate = Delegate()
    requester = CachedPyGithubRequester(delegate, SQLiteResponseCache(tmp_path / "cache.db"))
    original = requester.requestJsonAndCheck("GET", "/resource")
    assert original[0] == {"X-RateLimit-Remaining": "10"}
    assert requester.requestJsonAndCheck("GET", "/resource") == original
    assert delegate.calls == 1
    requester.requestJsonAndCheck("GET", "/resource", **change)
    assert delegate.calls == 2


def test_unknown_auth_delegate_bypasses_cache(tmp_path):
    delegate = Delegate()
    del delegate.auth
    requester = CachedPyGithubRequester(delegate, SQLiteResponseCache(tmp_path / "cache.db"))
    requester.requestJsonAndCheck("GET", "/resource")
    requester.requestJsonAndCheck("GET", "/resource")
    assert delegate.calls == 2


def test_host_isolation_with_relative_urls(tmp_path):
    cache = SQLiteResponseCache(tmp_path / "cache.db")
    first, second = Delegate(), Delegate(base_url="https://enterprise.github.test/api/v3")
    CachedPyGithubRequester(first, cache).requestJsonAndCheck("GET", "/user")
    CachedPyGithubRequester(second, cache).requestJsonAndCheck("GET", "/user")
    assert (first.calls, second.calls) == (1, 1)


def test_known_anonymous_context_can_share_reads(tmp_path):
    delegate = Delegate()
    delegate.auth = None
    requester = CachedPyGithubRequester(delegate, SQLiteResponseCache(tmp_path / "cache.db"))
    requester.requestJsonAndCheck("GET", "/public")
    requester.requestJsonAndCheck("GET", "/public")
    assert delegate.calls == 1


class EtagDelegate(Delegate):
    """First reply carries an ETag; conditional requests answer 304 (no payload) until changed."""

    def __init__(self):
        super().__init__()
        self.tag = '"v1"'
        self.seen = []

    def requestJsonAndCheck(self, verb, url, parameters=None, headers=None, *rest):
        self.calls += 1
        self.seen.append(dict(headers or {}))
        if (headers or {}).get("If-None-Match") == self.tag:
            return {"etag": self.tag, "x-ratelimit-remaining": str(100 - self.calls)}, None
        return {"etag": self.tag, "x-ratelimit-remaining": str(100 - self.calls)}, {"value": self.calls}


def _clocked(tmp_path, delegate):
    now = [1000.0]
    cache = SQLiteResponseCache(tmp_path / "cache.db", clock=lambda: now[0])
    return CachedPyGithubRequester(delegate, cache, ttl=15.0), now


def test_expired_read_revalidates_with_etag_and_reuses_payload_on_304(tmp_path):
    delegate = EtagDelegate()
    requester, now = _clocked(tmp_path, delegate)
    assert requester.requestJsonAndCheck("GET", "/repos/a/b")[1] == {"value": 1}
    now[0] += 20
    headers, payload = requester.requestJsonAndCheck("GET", "/repos/a/b")
    assert payload == {"value": 1} and headers["x-ratelimit-remaining"] == "98"
    assert delegate.seen[-1]["If-None-Match"] == '"v1"'
    assert requester.requestJsonAndCheck("GET", "/repos/a/b")[1] == {"value": 1}
    assert delegate.calls == 2


def test_changed_resource_returns_the_new_payload_and_tag(tmp_path):
    delegate = EtagDelegate()
    requester, now = _clocked(tmp_path, delegate)
    requester.requestJsonAndCheck("GET", "/repos/a/b")
    delegate.tag = '"v2"'
    now[0] += 20
    assert requester.requestJsonAndCheck("GET", "/repos/a/b")[1] == {"value": 2}
    now[0] += 20
    assert requester.requestJsonAndCheck("GET", "/repos/a/b")[1] == {"value": 2}
    assert delegate.seen[-1]["If-None-Match"] == '"v2"'


def test_mismatched_304_tag_refetches_without_condition(tmp_path):
    delegate = EtagDelegate()
    requester, now = _clocked(tmp_path, delegate)
    requester.requestJsonAndCheck("GET", "/repos/a/b")
    replies = iter([({"etag": '"other"'}, None), ({"etag": '"v3"'}, {"value": "fresh"})])
    delegate.requestJsonAndCheck = lambda *a: next(replies)
    now[0] += 20
    assert requester.requestJsonAndCheck("GET", "/repos/a/b")[1] == {"value": "fresh"}


def test_caller_conditional_headers_are_never_overridden(tmp_path):
    delegate = EtagDelegate()
    requester, now = _clocked(tmp_path, delegate)
    requester.requestJsonAndCheck("GET", "/r", headers={"If-None-Match": '"mine"'})
    now[0] += 20
    requester.requestJsonAndCheck("GET", "/r", headers={"If-None-Match": '"mine"'})
    assert [seen.get("If-None-Match") for seen in delegate.seen] == ['"mine"', '"mine"']
