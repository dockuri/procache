"""Opt-in HTTP read caching independent of a provider or HTTP SDK.

The caller supplies the actual transport and a credential/principal scope.
Only explicitly eligible GET/HEAD and validated GraphQL queries are stored. Authorization,
publication and health observations should use ``fresh=True``. Secrets in
request identity are hashed; response bodies still belong in a private cache.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import stat
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .cache import SQLiteResponseCache
from .commands import CachedReadCommand


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    cache_hit: bool = False


class CachedHTTPReads:
    """Coalesce successful metadata reads across processes using Procache.

    ``scope`` must identify the transport's current credentials and tenant,
    including authentication hidden inside an SDK session. Unknown scopes
    bypass caching. Headers and parameters distinguish representations.
    Mutations invalidate that origin/scope even when transport failure leaves
    the remote outcome unknown. Generation keys fence older in-flight reads.
    """

    MAX_BODY_BYTES = 4 * 1024 * 1024
    EPOCH_TTL = 86400

    def __init__(self, cache: SQLiteResponseCache, *, ttl: float = 15.0) -> None:
        if not math.isfinite(ttl) or not 0 < ttl <= 3600:
            raise ValueError("HTTP cache TTL must be finite and between 0 and 3600 seconds")
        self.cache = cache
        # The validated lifetime is part of the shared identity. Equivalent
        # int/float arguments must not partition records across API clients.
        self.ttl = float(ttl)

    @classmethod
    def shared(cls, *, path: str | Path | None = None, ttl: float = 15.0) -> CachedHTTPReads:
        """Use the common cross-application HTTP namespace and private store."""
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        location = Path(path or os.environ.get("SUBACTOR_PROCACHE_PATH") or root / "subactor" / "provider-http.sqlite3").absolute()
        if ".." in location.parts:
            raise ValueError("HTTP cache path must not contain parent traversal")
        cls._private_directory(location.parent, require_exists=False)
        location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        cls._private_directory(location.parent, require_exists=True)
        if location.is_symlink():
            raise ValueError("HTTP cache must be a regular private file")
        descriptor = os.open(location, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or (hasattr(os, "geteuid") and info.st_uid != os.geteuid()):
                raise ValueError("HTTP cache must be an owned regular file")
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            else:
                location.chmod(0o600)
        finally:
            os.close(descriptor)
        return cls(SQLiteResponseCache(location, namespace="provider-http-v1"), ttl=ttl)

    @staticmethod
    def _private_directory(directory: Path, *, require_exists: bool) -> None:
        # SQLite reopens the filename for each connection. Its parent must
        # therefore remain private, rather than just validating the first fd.
        # A sticky ancestor such as /tmp protects an owned child from other
        # users; ordinary writable ancestors and symlinks do not.
        uid = os.geteuid() if hasattr(os, "geteuid") else None
        for parent in (*reversed(directory.parents), directory):
            try:
                info = parent.lstat()
            except FileNotFoundError:
                if require_exists:
                    raise ValueError("HTTP cache directory must exist") from None
                continue
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("HTTP cache directory chain must not contain symlinks")
            if uid is not None and info.st_uid not in {0, uid}:
                raise ValueError("HTTP cache directory chain must be trusted")
            if parent == directory:
                if (uid is not None and info.st_uid != uid) or info.st_mode & 0o077:
                    raise ValueError("HTTP cache directory must be owned and private")
            elif info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                raise ValueError("HTTP cache directory ancestor must not be writable by other users")

    @staticmethod
    def credential_scope(*credentials: object) -> str | None:
        """Hash a known identity; missing inputs retain the uncached path.

        Public callers can explicitly use an ``"anonymous"`` identity.
        """
        if not credentials or any(value is None or value == "" or value == b"" for value in credentials):
            return None
        return SQLiteResponseCache.key("http-principal-v1", credentials)

    def _authority(self, url: str, scope: str) -> str:
        parsed = urlsplit(url)
        return self.cache.key("http-authority-v1", parsed.scheme.lower(), parsed.netloc.lower(), scope)

    def invalidate(self, url: str, *, scope: str) -> None:
        """Invalidate every representation for one origin and principal."""
        self.cache.put(self._authority(url, scope), uuid.uuid4().hex.encode(), ttl=self.EPOCH_TTL)

    @staticmethod
    def _headers(headers: Mapping[str, str]) -> dict[str, str]:
        return {str(k).lower(): str(v) for k, v in headers.items()}

    def _ttl(self, response: HTTPResponse) -> float:
        if not 200 <= response.status < 300 or len(response.body) > self.MAX_BODY_BYTES:
            return 0
        headers = self._headers(response.headers)
        policy = headers.get("cache-control", "").lower()
        directives = {part.strip().split("=", 1)[0] for part in policy.split(",")}
        if directives & {"no-store", "no-cache"} or ("set-cookie" in headers and "public" not in directives):
            return 0
        if "*" in {value.strip() for value in headers.get("vary", "").split(",")}:
            return 0
        ttl = self.ttl
        match = re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)"?\s*(?:,|$)', policy)
        if match:
            try:
                age = max(0, int(headers.get("age", "0")))
            except ValueError:
                return 0
            ttl = min(ttl, max(0, int(match[1]) - age))
        return ttl

    @staticmethod
    def _graphql_read(body: bytes | None) -> bool:
        if body is None or len(body) > CachedHTTPReads.MAX_BODY_BYTES:
            return False
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("ambiguous GraphQL envelope")
                result[key] = value
            return result
        try:
            document = json.loads(body, object_pairs_hook=unique)
        except (UnicodeError, ValueError):
            return False
        if not isinstance(document, dict) or not isinstance(document.get("query"), str):
            return False
        return CachedReadCommand.is_read(["gh", "api", "graphql", "-f", "query=" + document["query"]])

    @staticmethod
    def _encode(response: HTTPResponse) -> bytes:
        return json.dumps([response.status, dict(response.headers),
                           base64.b64encode(response.body).decode("ascii")],
                          separators=(",", ":")).encode()

    @staticmethod
    def _decode(payload: bytes, hit: bool) -> HTTPResponse:
        status, headers, body = json.loads(payload)
        return HTTPResponse(status, headers, base64.b64decode(body), cache_hit=hit)

    def request(
        self,
        method: str,
        url: str,
        loader: Callable[[], HTTPResponse],
        *,
        scope: str | None = None,
        headers: Mapping[str, str] | None = None,
        parameters: object = None,
        body: bytes | None = None,
        cacheable: bool = False,
        fresh: bool = False,
        stream: bool = False,
        graphql: bool = False,
    ) -> HTTPResponse:
        method = method.upper()
        graphql_read = graphql and method == "POST" and self._graphql_read(body)
        if method not in {"GET", "HEAD"} and not graphql_read:
            try:
                return replace(loader(), cache_hit=False)
            finally:
                if scope:
                    self.invalidate(url, scope=scope)
        request_headers = self._headers(headers or {})
        policy = request_headers.get("cache-control", "").lower()
        directives = {part.strip().split("=", 1)[0] for part in policy.split(",")}
        request_fresh = bool(directives & {"no-store", "no-cache"}) or bool(
            re.search(r'(?:^|,)\s*max-age\s*=\s*"?0"?\s*(?:,|$)', policy)
        ) or "no-cache" in {value.strip().lower() for value in request_headers.get("pragma", "").split(",")}
        if not scope or not cacheable or fresh or request_fresh or stream or (body is not None and not graphql_read):
            return replace(loader(), cache_hit=False)

        authority = self._authority(url, scope)
        epoch = self.cache.get(authority)
        key = self.cache.key("http-read-v1", authority, epoch.value.hex() if epoch else "initial",
                             method, url, request_headers, parameters, body, self.ttl)
        cached = self.cache.get(key)
        if cached is not None:
            return self._decode(cached.value, True)

        def load() -> bytes:
            response = loader()
            value = self._encode(response)
            ttl = self._ttl(response)
            if graphql_read:
                try:
                    payload = json.loads(response.body)
                    if not isinstance(payload, dict) or payload.get("errors") or "data" not in payload:
                        ttl = 0
                except (UnicodeError, ValueError):
                    ttl = 0
            if response.status == 429:
                try:
                    retry_after = float(self._headers(response.headers).get("retry-after", "60"))
                except ValueError:
                    retry_after = 60
                if not math.isfinite(retry_after):
                    retry_after = 60
                self.cache.cooldown(authority, ttl=min(3600, max(1, retry_after)))
            if ttl > 0:
                # This loader owns the backend's single flight. Store with the
                # response's effective lifetime; get_or_set must not reinsert
                # it with the caller's longer default TTL.
                # Explicitly public metadata may accompany edge cookies.
                # Preserve them on the live response, never persist or replay
                # them when serving the cached representation.
                stored = replace(response, headers={k: v for k, v in response.headers.items()
                                                    if k.lower() != "set-cookie"})
                self.cache.put(key, self._encode(stored), ttl=ttl)
            return value

        value, hit = self.cache.get_or_set(
            key, load, ttl=self.ttl, should_cache=lambda _: False, cooldown_key=authority,
        )
        return self._decode(value, hit)

    async def arequest(
        self, method: str, url: str, loader: Callable[[], Awaitable[HTTPResponse]], **kwargs: Any,
    ) -> HTTPResponse:
        """Run async SDK transport on its own loop without blocking that loop.

        SQLite and cross-process waiting run in the executor. A cancelled
        waiter leaves a shared fetch available to the other readers; the
        transport retains responsibility for its network timeout.
        """
        loop = asyncio.get_running_loop()
        async def call_loader() -> HTTPResponse:
            return await loader()
        def load() -> HTTPResponse:
            return asyncio.run_coroutine_threadsafe(call_loader(), loop).result()
        return await asyncio.to_thread(self.request, method, url, load, **kwargs)
