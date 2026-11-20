"""Opt-in, zero-mandatory-dependency bridge projecting Procache HTTP reads into uritime-urtlog.

Activated strictly when ``URTLOG_STATE_DIR`` (or an explicit ``state_dir``) is
provided and ``urtlog`` is importable. Strips URL userinfo, query strings, and
fragments before recording so tokens or sensitive parameters never enter logs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def resolve_state_dir(explicit: Path | str | None = None) -> Path | None:
    """Return configured urtlog state directory, or None when opt-in is inactive."""
    raw = str(explicit).strip() if explicit is not None else os.environ.get("URTLOG_STATE_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def sanitize_url(url: str) -> str:
    """Strip credentials, query parameters, and fragments from a URL."""
    parsed = urlsplit(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "unknown").lower()
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    return f"{scheme}://{host}{port}{path}"


def _slug(value: str, fallback: str = "unknown") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value.strip().lower()).strip("-")
    return cleaned or fallback


def maybe_emit_http_read(
    method: str,
    url: str,
    status_code: int,
    *,
    cache_hit: bool,
    state_dir: Path | str | None = None,
    repository: str = "dockuri/procache",
    sensitivity: str = "internal",
) -> dict[str, Any]:
    """Emit a sanitized Procache HTTP read observation into uritime-urtlog fail-open."""
    try:
        target_dir = resolve_state_dir(state_dir)
        if target_dir is None:
            return {"emitted": False, "reason": "disabled"}

        try:
            urtlog_mod = importlib.import_module("urtlog")
        except (ImportError, OSError, AttributeError, RuntimeError):
            return {"emitted": False, "reason": "urtlog_not_installed"}

        safe_url = sanitize_url(url)
        parsed = urlsplit(safe_url)
        host_slug = _slug(parsed.hostname or "unknown", "unknown")
        method_slug = _slug(method, "get")
        outcome_slug = "hit" if cache_hit else "miss"
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        url_hash = hashlib.sha256(safe_url.encode("utf-8")).hexdigest()[:14]
        eid = "prc-" + hashlib.sha256(
            f"{now_us}|{method_slug}|{safe_url}|{status_code}|{outcome_slug}".encode("utf-8")
        ).hexdigest()[:16]
        status = "succeeded" if 200 <= int(status_code) < 400 else "failed"

        with urtlog_mod.UrtClient(target_dir, source="procache", repository=repository) as client:
            record = urtlog_mod.UrtEventRecord(
                event_id=eid,
                kind="log",
                source="procache",
                urt=urtlog_mod.UrtTime(at_us=now_us),
                uri=urtlog_mod.OperationUri.parse(f"procache://http/{host_slug}/{method_slug}_{outcome_slug}"),
                inputs=(
                    urtlog_mod.DataRef(
                        urn=f"urn:uritime:procache:url:{host_slug}:{url_hash}",
                        role="http_request",
                        sensitivity=sensitivity,
                    ),
                ),
                outputs=(
                    urtlog_mod.DataRef(
                        urn=f"urn:uritime:procache:response:{eid}",
                        role="http_response",
                        sensitivity=sensitivity,
                    ),
                ),
                status=status,
                repository=repository,
                actor="dockuri/procache",
                sensitivity=sensitivity,
                owner_principal="dockuri/procache",
                run_id=eid,
                stage="completed",
                log_type="summary" if status == "succeeded" else "warning",
                summary=f"{method.upper()} {safe_url} -> {status_code} ({outcome_slug})",
                metadata={
                    "method": method.upper(),
                    "sanitized_url": safe_url,
                    "status_code": int(status_code),
                    "cache_hit": bool(cache_hit),
                },
                custody=urtlog_mod.Custody(
                    commissioned_by="dockuri/procache",
                    executed_by="dockuri/procache",
                    recipients=("group:ops", "heyasa"),
                ),
            )
            client.store.append(record)
            client.registry.register_url(
                safe_url,
                owner=repository,
                system="procache",
                description=f"Observed cached HTTP endpoint ({method.upper()})",
                effects=("network", "read"),
                available=status == "succeeded",
                revision="observed",
            )
        return {"emitted": True, "event_id": eid, "sanitized_url": safe_url, "cache_hit": bool(cache_hit)}
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError, KeyError):
        return {"emitted": False, "reason": "emit_failed"}
