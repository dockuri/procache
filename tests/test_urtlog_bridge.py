"""Unit tests for the opt-in uritime-urtlog bridge in Procache."""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from procache.cache import SQLiteResponseCache
from procache.http import CachedHTTPReads, HTTPResponse
from procache.urtlog_bridge import maybe_emit_http_read, resolve_state_dir, sanitize_url


class TestProcacheUrtlogBridge(unittest.TestCase):
    def test_sanitize_url_strips_credentials_query_and_fragment(self) -> None:
        raw = "https://alice:example@API.GitHub.com:443/repos/dockuri/procache?page=2&sort=asc#frag"
        self.assertEqual(sanitize_url(raw), "https://api.github.com:443/repos/dockuri/procache")

    def test_inactive_when_env_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("URTLOG_STATE_DIR", None)
            self.assertIsNone(resolve_state_dir())
            res = maybe_emit_http_read("GET", "https://api.github.com/rate_limit", 200, cache_hit=False)
            self.assertEqual(res, {"emitted": False, "reason": "disabled"})

    def test_graceful_degradation_when_urtlog_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("procache.urtlog_bridge.importlib.import_module", side_effect=ImportError("no urtlog")):
                res = maybe_emit_http_read(
                    "GET",
                    "https://api.github.com/rate_limit",
                    200,
                    cache_hit=True,
                    state_dir=tmp,
                )
            self.assertEqual(res, {"emitted": False, "reason": "urtlog_not_installed"})

    @unittest.skipUnless(importlib.util.find_spec("urtlog") is not None, "urtlog not installed")
    def test_cached_http_reads_records_miss_and_hit_and_registers_url(self) -> None:
        urtlog_mod = importlib.import_module("urtlog")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "urtlog"
            cache = SQLiteResponseCache(Path(tmp) / "cache.sqlite3", namespace="test")
            http_reads = CachedHTTPReads(cache, ttl=30.0)
            url = "https://api.github.com/repos/dockuri/procache?page=7&filter=should_strip"

            def loader() -> HTTPResponse:
                return HTTPResponse(200, {"Cache-Control": "max-age=30"}, b'{"ok":true}')

            with mock.patch.dict(os.environ, {"URTLOG_STATE_DIR": str(state_dir)}):
                first = http_reads.request("GET", url, loader, scope="user:test", cacheable=True)
                second = http_reads.request("GET", url, loader, scope="user:test", cacheable=True)
            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)

            ctx = urtlog_mod.AccessContext(
                "heyasa",
                roles=frozenset({"assistant"}),
                groups=frozenset({"ops"}),
                max_sensitivity="internal",
            )
            with urtlog_mod.UrtClient(state_dir, source="procache", repository="dockuri/procache") as client:
                rows = client.store.query(ctx, source="procache", op_prefix="op/procache/http/")
                self.assertEqual(len(rows), 2)
                for row in rows:
                    self.assertNotIn("should_strip", row["metadata"]["sanitized_url"])
                urls = client.registry.search(ctx, kind="url", system="procache")
                self.assertEqual(len(urls), 1)
                self.assertEqual(urls[0]["address"], "https://api.github.com/repos/dockuri/procache")


if __name__ == "__main__":
    unittest.main()
