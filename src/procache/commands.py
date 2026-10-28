from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .cache import ProviderCooldownError, SQLiteResponseCache, is_rate_limit_error


@dataclass(frozen=True)
class CachedCommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str = ""
    cache_hit: bool = False


class CachedReadCommand:
    """Run allowlisted read commands through a shared SQLite response cache."""

    def __init__(self, cache: SQLiteResponseCache, *, ttl: float = 15.0) -> None:
        self.cache = cache
        self.ttl = ttl
        self.cooldown_seconds = 60.0

    @staticmethod
    def is_read(args: Sequence[str]) -> bool:
        argv = tuple(args)
        if not argv or Path(argv[0]).name != "gh":
            return False
        if "--web" in argv or "--watch" in argv:
            return False
        if len(argv) >= 3 and argv[1] == "search":
            return argv[2] in {"prs", "issues", "repos", "commits", "code"}
        if len(argv) >= 3 and argv[1] in {"pr", "issue", "repo"}:
            return argv[2] in {"list", "view", "status", "checks"}
        if len(argv) >= 2 and argv[1] == "api":
            return _api_is_read(argv[2:])
        return False

    def run(self, args: Sequence[str], *, timeout: int | None = None, env: dict[str, str] | None = None) -> CachedCommandResult:
        argv = tuple(str(item) for item in args)
        if not self.is_read(argv):
            return self._execute(argv, timeout=timeout, env=env)
        effective_env = os.environ if env is None else env
        # gh can keep its effective token in the system credential store,
        # independently of hosts.yml. A username or unchanged config file is
        # therefore not enough to identify that credential across requests.
        if not _cacheable_credential(argv, effective_env):
            return self._execute(argv, timeout=timeout, env=env)
        scope = tuple(
            (name, effective_env.get(name, ""))
            for name in ("GH_HOST", "GH_REPO", "GH_CONFIG_DIR")
        )
        try:
            identity = _credential_scope(effective_env)
        except OSError:
            # If identity cannot be established, execute once without sharing.
            return self._execute(argv, timeout=timeout, env=env)
        key = self.cache.key("command-v2", argv, "scope", scope, os.getcwd(), identity)
        cooldown_key = self.cache.key("provider-v2", effective_env.get("GH_HOST", "github.com"), identity)
        def load() -> bytes:
            result = self._execute(argv, timeout=timeout, env=env)
            if result.returncode and is_rate_limit_error(RuntimeError(result.stderr)):
                self.cache.cooldown(cooldown_key, ttl=self.cooldown_seconds)
            return json.dumps(
                {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
                separators=(",", ":"),
            ).encode()

        try:
            value, hit = self.cache.get_or_set(
                key,
                load,
                ttl=self.ttl,
                should_cache=lambda payload: json.loads(payload)["returncode"] == 0,
                cooldown_key=cooldown_key,
                cooldown_seconds=self.cooldown_seconds,
                is_rate_limit=is_rate_limit_error,
            )
        except ProviderCooldownError as exc:
            return CachedCommandResult(argv, 75, "", str(exc))
        result = json.loads(value)
        return CachedCommandResult(
            argv,
            int(result["returncode"]),
            result["stdout"],
            result["stderr"],
            cache_hit=hit,
        )

    @staticmethod
    def _execute(args: tuple[str, ...], *, timeout: int | None, env: dict[str, str] | None) -> CachedCommandResult:
        proc = subprocess.run(args, check=False, timeout=timeout, env=env, capture_output=True, text=True)
        return CachedCommandResult(args, proc.returncode, proc.stdout, proc.stderr)


_FINGERPRINT_LIMIT = 16
_TOKEN_ENVIRONMENT = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
_API_VALUES = {"-X", "--method", "-f", "--raw-field", "-F", "--field",
               "-H", "--header", "--hostname", "-q", "--jq", "-t", "--template", "-p", "--preview"}
_fingerprints: OrderedDict[Path, tuple[tuple[int, ...], str]] = OrderedDict()
_fingerprint_lock = threading.Lock()


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _github_config_fingerprint(path: Path) -> str:
    """Reuse bounded hashes, never raw credentials, across stable file reads."""
    path = path.absolute()
    try:
        identity = _file_identity(path.stat())
    except FileNotFoundError:
        with _fingerprint_lock:
            _fingerprints.pop(path, None)
        return hashlib.sha256(b"").hexdigest()
    with _fingerprint_lock:
        cached = _fingerprints.get(path)
        if cached is not None and cached[0] == identity:
            _fingerprints.move_to_end(path)
            return cached[1]
    with path.open("rb") as stream:
        if _file_identity(os.fstat(stream.fileno())) != identity:
            raise OSError("Credential configuration changed before read")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
        fingerprint = digest.hexdigest()
        if _file_identity(os.fstat(stream.fileno())) != identity:
            raise OSError("Credential configuration changed during read")
    if _file_identity(path.stat()) != identity:
        raise OSError("Credential configuration replaced during read")
    with _fingerprint_lock:
        _fingerprints[path] = (identity, fingerprint)
        _fingerprints.move_to_end(path)
        while len(_fingerprints) > _FINGERPRINT_LIMIT:
            _fingerprints.popitem(last=False)
    return fingerprint


def _credential_scope(env: dict[str, str]) -> str:
    """Hash identity inputs; credentials never become persisted cache metadata."""
    tokens = tuple(env.get(name, "") for name in _TOKEN_ENVIRONMENT)
    config = Path(env.get("GH_CONFIG_DIR") or
                  str(Path(env.get("XDG_CONFIG_HOME") or
                           str(Path(env.get("HOME") or str(Path.home())) / ".config")) / "gh"))
    fingerprint = _github_config_fingerprint(config / "hosts.yml")
    return SQLiteResponseCache.key("auth-v2", tokens, fingerprint)


def _cacheable_credential(argv: Sequence[str], env: dict[str, str]) -> bool:
    public = bool(env.get("GH_TOKEN") or env.get("GITHUB_TOKEN"))
    enterprise = bool(env.get("GH_ENTERPRISE_TOKEN") or env.get("GITHUB_ENTERPRISE_TOKEN"))
    if public and enterprise:
        return True
    if not (public or enterprise) or len(argv) < 2 or argv[1] != "api":
        return False
    # A host-qualified repository can affect host selection. Avoid guessing how
    # it interacts with gh's repository context when only one token is known.
    if str(env.get("GH_REPO", "")).count("/") >= 2:
        return False
    host = None
    arguments = argv[2:]
    index = 0
    while index < len(arguments):
        token = arguments[index]
        option, separator, value = token.partition("=")
        if not separator and len(token) > 2 and token[:2] in {"-X", "-f", "-F", "-H", "-q", "-t", "-p"}:
            option, value, separator = token[:2], token[2:], "="
        if option in _API_VALUES:
            if not separator:
                index += 1
                if index >= len(arguments):
                    return False
                value = arguments[index]
            if option == "--hostname":
                if host is not None:
                    return False
                host = value
        elif not token.startswith("-") and re.match(r"(?i)^https?://", token):
            # A URL-shaped endpoint may select a host independently of flags.
            return False
        index += 1
    host = (host or env.get("GH_HOST") or "github.com").lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host) or host.endswith(".ghe.com"):
        return False
    return public if host == "github.com" else enterprise


def _api_is_read(arguments: Sequence[str]) -> bool:
    """Recognize gh's effective method; ambiguous request bodies bypass caching."""
    switches = {"--paginate", "--slurp", "-i", "--include", "--silent", "--verbose"}
    endpoint = None
    method = None
    fields = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        option, separator, value = token.partition("=")
        if not separator and len(token) > 2 and token[:2] in {"-X", "-f", "-F", "-H", "-q", "-t", "-p"}:
            option, value, separator = token[:2], token[2:], "="
        if option in _API_VALUES:
            if not separator:
                index += 1
                if index >= len(arguments):
                    return False
                value = arguments[index]
            if option in {"-X", "--method"}:
                if method is not None:
                    return False
                method = value.upper()
            elif option in {"-f", "--raw-field", "-F", "--field"}:
                if "=" not in value or value.split("=", 1)[1].startswith("@"):
                    return False
                fields.append(value)
        elif token in switches:
            pass
        elif token.startswith("-") or endpoint is not None:
            return False
        else:
            endpoint = token
        index += 1
    if not endpoint:
        return False
    effective_method = method or ("POST" if fields else "GET")
    if endpoint != "graphql":
        return effective_method == "GET"
    queries = [value.split("=", 1)[1] for value in fields if value.startswith("query=")]
    if effective_method not in {"GET", "POST"} or len(queries) != 1:
        return False
    # Strip strings before comments so a '#' in a string cannot hide a mutation.
    document = re.sub(r'"(?:\\.|[^"\\])*"', '""', queries[0])
    document = re.sub(r"#[^\r\n]*", "", document).lstrip("\ufeff \t\r\n,")
    return bool(re.match(r"(?:query\b|\{)", document)) and not re.search(r"\b(?:mutation|subscription)\b", document)
