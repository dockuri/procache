from __future__ import annotations

import json
from typing import Any

from .cache import SQLiteResponseCache, is_rate_limit_error

REVALIDATION_TTL = 86400.0
_CONDITIONAL_HEADERS = frozenset({
    "if-none-match", "if-modified-since", "if-match", "if-unmodified-since", "if-range", "range",
})


def _etag(headers: Any) -> str | None:
    if not isinstance(headers, dict):
        return None
    tag = next((str(value) for name, value in headers.items() if str(name).lower() == "etag"), "")
    return tag or None


def _same_tag(left: str, right: str) -> bool:
    return left.removeprefix("W/") == right.removeprefix("W/")


class CachedPyGithubRequester:
    """Read-through adapter for PyGithub's JSON requester.

    Only GET responses with a known authentication context are cached.
    Response headers and request representation are preserved. All writes go
    directly through the delegated requester; rate-limit exceptions open the
    shared provider cooldown in ``SQLiteResponseCache``.

    After the short TTL an expired read is revalidated with the stored ETag.
    PyGithub returns a 304 as headers with no payload; the former payload is
    reused only then and when the provider confirms the same tag. GitHub does
    not count such a 304 against the primary rate limit.
    """

    def __init__(self, delegate: Any, cache: SQLiteResponseCache, *, ttl: float = 15.0) -> None:
        self._delegate = delegate
        self._cache = cache
        self._ttl = ttl

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def requestJsonAndCheck(
        self,
        verb: str,
        url: str,
        parameters: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        input: Any | None = None,
        follow_302_redirect: bool = False,
    ) -> tuple[dict[str, Any], Any]:
        identity = self._identity() if verb.upper() == "GET" else None
        if identity is None:
            return self._delegate.requestJsonAndCheck(
                verb, url, parameters, headers, input, follow_302_redirect
            )

        key = self._cache.key(
            "pygithub-v2", identity, verb.upper(), url, parameters, headers,
            input, follow_302_redirect,
        )

        explicit = {str(name).lower() for name in (headers or {})} & _CONDITIONAL_HEADERS
        revalidation_key = None if explicit else self._cache.key("pygithub-etag-v1", key)

        def encode(response_headers: Any, payload: Any) -> bytes:
            return json.dumps(
                [dict(response_headers), payload], separators=(",", ":"), default=str
            ).encode("utf-8")

        def load() -> bytes:
            previous = self._cache.get(revalidation_key) if revalidation_key else None
            if previous is not None and previous.etag:
                conditional = {**(headers or {}), "If-None-Match": previous.etag}
                response_headers, payload = self._delegate.requestJsonAndCheck(
                    verb, url, parameters, conditional, input, follow_302_redirect
                )
                returned = _etag(response_headers)
                if payload is None and (returned is None or _same_tag(returned, previous.etag)):
                    old_headers, old_payload = json.loads(previous.value)
                    value = encode({**old_headers, **dict(response_headers)}, old_payload)
                    self._cache.put(revalidation_key, value, ttl=REVALIDATION_TTL, etag=previous.etag)
                    return value
                if payload is None:
                    response_headers, payload = self._delegate.requestJsonAndCheck(
                        verb, url, parameters, headers, input, follow_302_redirect
                    )
            else:
                response_headers, payload = self._delegate.requestJsonAndCheck(
                    verb, url, parameters, headers, input, follow_302_redirect
                )
            value = encode(response_headers, payload)
            tag = _etag(response_headers)
            if revalidation_key and tag and payload is not None:
                self._cache.put(revalidation_key, value, ttl=REVALIDATION_TTL, etag=tag)
            return value

        value, _ = self._cache.get_or_set(
            key,
            load,
            ttl=self._ttl,
            cooldown_key=self._cache.key("pygithub-provider-v2", identity),
            cooldown_seconds=60,
            is_rate_limit=is_rate_limit_error,
        )
        response_headers, payload = json.loads(value)
        return response_headers, payload

    def _identity(self) -> str | None:
        """Hash PyGithub's public auth context; unknown delegates bypass sharing."""
        try:
            auth = self._delegate.auth
            base_url = self._delegate.base_url
            token = auth.token if auth is not None else None
            token_type = auth.token_type if auth is not None else "anonymous"
        except AttributeError:
            return None
        if not isinstance(base_url, str) or not base_url:
            return None
        if auth is not None and (not isinstance(token, str) or not token):
            return None
        return self._cache.key("pygithub-auth-v1", base_url, token_type, token)
