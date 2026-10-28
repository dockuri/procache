import os
import subprocess

import pytest

from procache import CachedReadCommand, SQLiteResponseCache


@pytest.mark.parametrize(('args', 'env'), [
    (['gh', 'api', 'user'], {'GH_HOST': 'enterprise.example', 'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user', '--hostname', 'enterprise.example'], {'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user', '--hostname=github.com'], {'GH_ENTERPRISE_TOKEN': 'test-credential-a'}),
    (['gh', 'pr', 'view', '1'], {'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'repos/{owner}/{repo}'], {'GH_TOKEN': 'test-credential-a',
                                              'GH_REPO': 'enterprise.example/owner/repo'}),
    (['gh', 'api', 'https://enterprise.example/user'], {'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user', '--hostname', 'github.com', '--hostname', 'enterprise.example'],
     {'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user'], {'GH_HOST': 'company.ghe.com', 'GH_ENTERPRISE_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user'], {'GH_HOST': 'github.localhost', 'GH_ENTERPRISE_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user', '--hostname', 'api.github.com'], {'GH_ENTERPRISE_TOKEN': 'test-credential-a'}),
])
def test_unrelated_token_or_unknown_host_never_reuses_cached_result(tmp_path, monkeypatch, args, env):
    env = {**env, 'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    replies = iter(['old-permissions', 'new-permissions'])
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, next(replies), '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    assert runner.run(args, env=env).stdout == 'old-permissions'
    second = runner.run(args, env=env)
    assert second.stdout == 'new-permissions' and not second.cache_hit
    assert len(calls) == 2


@pytest.mark.parametrize(('args', 'env'), [
    (['gh', 'api', 'user'], {'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user'], {'GH_HOST': 'enterprise.example', 'GH_ENTERPRISE_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user', '--hostname', 'enterprise.example'], {'GH_ENTERPRISE_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user'], {'GH_HOST': 'company.ghe.com', 'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user'], {'GH_HOST': 'github.localhost', 'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user', '--hostname', 'github.com'],
     {'GH_HOST': 'enterprise.example', 'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'api', 'user', '-H', '--hostname=enterprise.example'],
     {'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'pr', 'view', '1'], {'GH_TOKEN': 'test-credential-a', 'GH_ENTERPRISE_TOKEN': 'test-credential-b'}),
])
def test_known_host_with_matching_token_or_both_tokens_still_caches(tmp_path, monkeypatch, args, env):
    env = {**env, 'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'response', '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    assert not runner.run(args, env=env).cache_hit
    assert runner.run(args, env=env).cache_hit
    assert len(calls) == 1


def test_configured_default_host_without_explicit_host_does_not_reuse(tmp_path, monkeypatch):
    config = tmp_path / 'gh'
    config.mkdir()
    (config / 'hosts.yml').write_text('enterprise.example:\n  user: same-user\n')
    env = {'GH_CONFIG_DIR': str(config), 'GH_TOKEN': 'test-credential-a'}
    replies = iter(['old-permissions', 'new-permissions'])
    def execute(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, next(replies), '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    assert runner.run(['gh', 'api', 'user'], env=env).stdout == 'old-permissions'
    second = runner.run(['gh', 'api', 'user'], env=env)
    assert second.stdout == 'new-permissions' and not second.cache_hit


@pytest.mark.parametrize('hosts_present', [False, True])
def test_hidden_credential_changes_do_not_reuse_cached_result(tmp_path, monkeypatch, hosts_present):
    config = tmp_path / 'gh'
    config.mkdir()
    if hosts_present:
        # A username in hosts.yml does not identify a token held in a keyring.
        (config / 'hosts.yml').write_text('github.com:\n  user: same-user\n')
    env = {'GH_CONFIG_DIR': str(config)}
    replies = iter(['old-permissions', 'new-permissions'])
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, next(replies), '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    first = runner.run(['gh', 'api', 'user'], env=env)
    second = runner.run(['gh', 'api', 'user'], env=env)
    assert first.stdout == 'old-permissions'
    assert second.stdout == 'new-permissions'
    assert not second.cache_hit
    assert len(calls) == 2


@pytest.mark.parametrize('atomic', [False, True])
def test_same_size_account_rotation_with_preserved_mtime_is_not_a_cache_hit(tmp_path, monkeypatch, atomic):
    config = tmp_path / 'gh'
    config.mkdir()
    hosts = config / 'hosts.yml'
    hosts.write_bytes(b'user: synthetic-a\n')
    env = {'GH_CONFIG_DIR': str(config), 'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, hosts.read_text(), '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    args = ['gh', 'api', 'user']
    first = runner.run(args, env=env)
    assert runner.run(args, env=env).cache_hit
    info = hosts.stat()
    replacement = config / 'next-hosts.yml' if atomic else hosts
    replacement.write_bytes(b'user: synthetic-b\n')
    os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
    if atomic:
        os.replace(replacement, hosts)
    second = runner.run(args, env=env)
    assert not second.cache_hit and second.stdout != first.stdout
    assert runner.run(args, env=env).cache_hit
    assert len(calls) == 2


def test_unchanged_credential_config_is_read_once(tmp_path, monkeypatch):
    from pathlib import Path

    from procache.commands import _credential_scope
    config = tmp_path / 'hosts.yml'
    config.write_bytes(b'user: synthetic\n')
    original = Path.open
    reads = []
    def open_file(path, *args, **kwargs):
        if path == config:
            reads.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', open_file)
    env = {'GH_CONFIG_DIR': str(tmp_path)}
    first = _credential_scope(env)
    assert all(_credential_scope(env) == first for _ in range(10))
    assert len(reads) == 1


def test_fingerprint_cache_is_bounded_and_contains_no_raw_credentials(tmp_path):
    from procache.commands import _FINGERPRINT_LIMIT, _credential_scope, _fingerprints
    for number in range(_FINGERPRINT_LIMIT + 8):
        directory = tmp_path / str(number)
        directory.mkdir()
        (directory / 'hosts.yml').write_bytes(b'synthetic-secret-value')
        _credential_scope({'GH_CONFIG_DIR': str(directory)})
    assert len(_fingerprints) <= _FINGERPRINT_LIMIT
    assert all(len(value[1]) == 64 and 'synthetic-secret' not in value[1]
               for value in _fingerprints.values())


def test_replacement_during_identity_read_bypasses_cache(tmp_path, monkeypatch):
    from pathlib import Path
    hosts = tmp_path / 'hosts.yml'
    hosts.write_bytes(b'user: synthetic-a\n')
    original = Path.open
    swapped = False
    def open_file(path, *args, **kwargs):
        nonlocal swapped
        stream = original(path, *args, **kwargs)
        if path == hosts and not swapped:
            swapped = True
            replacement = tmp_path / 'replacement.yml'
            replacement.write_bytes(b'user: synthetic-b\n')
            replacement.replace(hosts)
        return stream
    monkeypatch.setattr(Path, 'open', open_file)
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'response', '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    env = {'GH_CONFIG_DIR': str(tmp_path), 'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}
    args = ['gh', 'api', 'user']
    assert not runner.run(args, env=env).cache_hit
    assert not runner.run(args, env=env).cache_hit
    assert runner.run(args, env=env).cache_hit
    assert len(calls) == 2


def test_unreadable_identity_never_shares_cached_reads(tmp_path, monkeypatch):
    from pathlib import Path
    hosts = tmp_path / 'hosts.yml'
    hosts.write_bytes(b'user: synthetic\n')
    original = Path.open
    def open_file(path, *args, **kwargs):
        if path == hosts:
            raise PermissionError('synthetic permission denial')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', open_file)
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'response', '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    for _ in range(2):
        assert not runner.run(['gh', 'api', 'user'], env={'GH_CONFIG_DIR': str(tmp_path), 'GH_HOST': 'github.com',
                                                          'GH_TOKEN': 'test-credential-a'}).cache_hit
    assert len(calls) == 2


def test_only_read_gh_commands_are_cacheable(tmp_path):
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / "cache.sqlite3"))
    assert runner.is_read(["gh", "pr", "view", "1"])
    assert runner.is_read(["gh", "api", "repos/acme/demo"])
    assert runner.is_read(["gh", "search", "prs", "--json", "number"])
    assert runner.is_read(["gh", "api", "graphql", "-f", "query=query { viewer { login } }"])
    assert runner.is_read(["gh", "api", "graphql", "-f", "query=query { viewer { login } }", "--method", "POST"])
    assert not runner.is_read(["gh", "pr", "merge", "1"])
    assert not runner.is_read(["gh", "api", "graphql", "-f", "query=mutation { deleteThing }"])


def test_command_cache_preserves_result_and_does_not_cache_failures(tmp_path, monkeypatch):
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / "cache.sqlite3"))
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        class Result:
            returncode = 1
            stdout = "partial"
            stderr = "provider unavailable"
        return Result()

    monkeypatch.setattr("procache.commands.subprocess.run", fake_run)
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh'), 'GH_TOKEN': 'test-credential-a'}
    first = runner.run(["gh", "pr", "view", "1"], env=env)
    second = runner.run(["gh", "pr", "view", "1"], env=env)
    assert (first.returncode, first.stdout, first.stderr) == (1, "partial", "provider unavailable")
    assert second.cache_hit is False
    assert calls == 2


@pytest.mark.parametrize('arguments', [
    ['repos/acme/demo/issues', '-X', 'POST'],
    ['repos/acme/demo/issues', '-XPOST'],
    ['repos/acme/demo/issues', '--method=PATCH'],
    ['repos/acme/demo/issues', '-f', 'title=new'],
    ['repos/acme/demo/issues', '--raw-field=title=new'],
    ['repos/acme/demo/issues', '-F', 'title=new'],
    ['repos/acme/demo/issues', '--input', 'body.json'],
    ['graphql', '-f', 'query=# comment\nmutation { changeThing }'],
    ['graphql', '-f', 'query=query { viewer { login } } mutation { changeThing }'],
    ['graphql', '-f', 'query=subscription { changed }'],
    ['graphql', '-F', 'query=@query.graphql'],
    ['graphql', '--input', '-'],
    ['repos/acme/demo', '--method'],
    ['repos/acme/demo', '--unknown-flag'],
])
def test_mutations_and_ambiguous_requests_execute_each_time(tmp_path, monkeypatch, arguments):
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{}', '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    for _ in range(2):
        assert not runner.run(['gh', 'api', *arguments]).cache_hit
    assert len(calls) == 2


@pytest.mark.parametrize('arguments', [
    ['repos/acme/demo/issues', '--method', 'GET', '-f', 'state=open'],
    ['repos/acme/demo/issues', '-XGET', '--field=page=1'],
    ['graphql', '-f', 'query=# comment\nquery { viewer { login } }'],
    ['graphql', '-f', 'query={ viewer { login } }'],
])
def test_explicit_reads_still_hit_cache(tmp_path, monkeypatch, arguments):
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{}', '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    runner = CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3'))
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh'), 'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}
    assert not runner.run(['gh', 'api', *arguments], env=env).cache_hit
    assert runner.run(['gh', 'api', *arguments], env=env).cache_hit
    assert len(calls) == 1


def test_credentials_config_and_repository_context_partition_cache(tmp_path, monkeypatch):
    cache = SQLiteResponseCache(tmp_path / 'cache.sqlite3')
    runner = CachedReadCommand(cache)
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, str(len(calls)), '')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh'), 'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}
    args = ['gh', 'api', 'user']
    first = runner.run(args, env=env)
    assert runner.run(args, env=env).stdout == first.stdout
    env['GH_TOKEN'] = 'test-credential-b'
    assert runner.run(args, env=env).stdout != first.stdout
    config = tmp_path / 'gh'
    config.mkdir()
    (config / 'hosts.yml').write_text('new-account')
    assert not runner.run(args, env=env).cache_hit
    other = tmp_path / 'repository'
    other.mkdir()
    monkeypatch.chdir(other)
    assert not runner.run(args, env=env).cache_hit
    assert len(calls) == 4
    assert b'test-credential' not in (tmp_path / 'cache.sqlite3').read_bytes()


def test_textual_403_stops_further_commands_for_same_identity(tmp_path, monkeypatch):
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, '', 'HTTP 403: API rate limit exceeded')
    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    cache = SQLiteResponseCache(tmp_path / 'cache.sqlite3')
    first = CachedReadCommand(cache)
    second = CachedReadCommand(cache)
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh'), 'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}
    assert first.run(['gh', 'api', 'user'], env=env).returncode == 1
    assert second.run(['gh', 'api', 'repos/acme/demo'], env=env).returncode == 75
    assert len(calls) == 1


def test_unrelated_issue_number_is_not_a_rate_limit():
    from procache import is_rate_limit_error
    assert not is_rate_limit_error(RuntimeError('Issue 429 is missing'))
    assert not is_rate_limit_error(RuntimeError('HTTP 403: permission denied'))


def test_branch_name_in_cli_diagnostic_does_not_block_the_next_read(tmp_path, monkeypatch):
    calls = []
    message = "no required checks reported on the 'ticket/030-distinguish-authority-denial-from-remote-rate-limiting' branch"

    def execute(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return subprocess.CompletedProcess(args, 1, '', message)
        return subprocess.CompletedProcess(args, 0, '{}', '')

    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    cache = SQLiteResponseCache(tmp_path / 'cache.sqlite3')
    first = CachedReadCommand(cache)
    second = CachedReadCommand(cache)
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh'), 'GH_TOKEN': 'test-credential-a'}
    failure = first.run(['gh', 'pr', 'checks', '34', '--required'], env=env)
    assert (failure.returncode, failure.stderr) == (1, message)
    following = second.run(['gh', 'api', 'repos/acme/demo/commits/head/status'], env=env)
    assert following.returncode == 0
    assert len(calls) == 2
