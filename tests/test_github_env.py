import subprocess

import pytest

from procache import CachedReadCommand, SQLiteResponseCache, github_env


def _runner(tmp_path, monkeypatch):
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, f'reply-{len(calls)}', '')

    monkeypatch.setattr('procache.commands.subprocess.run', execute)
    return CachedReadCommand(SQLiteResponseCache(tmp_path / 'cache.sqlite3')), calls


PUBLIC = {'GH_HOST': 'github.com', 'GH_TOKEN': 'test-credential-a'}
ENTERPRISE = {'GH_HOST': 'enterprise.example', 'GH_ENTERPRISE_TOKEN': 'test-credential-a'}


@pytest.mark.parametrize(('args', 'env'), [
    (['gh', 'pr', 'list', '--repo', 'acme/demo', '--state', 'open', '--json', 'number'], PUBLIC),
    (['gh', 'pr', 'view', '7', '-R', 'acme/demo', '--json', 'headRefName'], PUBLIC),
    (['gh', 'pr', 'checks', '7', '--repo=acme/demo'], PUBLIC),
    (['gh', 'issue', 'list', '-Racme/demo', '--json', 'number'], PUBLIC),
    (['gh', 'pr', 'list', '--json', 'number'], {**PUBLIC, 'GH_REPO': 'acme/demo'}),
    (['gh', 'pr', 'view', 'feature/a/b', '--repo', 'acme/demo'], PUBLIC),
    (['gh', 'search', 'prs', '--owner', 'acme', '--state', 'open', '--json', 'number'], PUBLIC),
    (['gh', 'pr', 'list', '--repo', 'acme/demo'], ENTERPRISE),
])
def test_explicit_host_and_repository_reads_are_shared(tmp_path, monkeypatch, args, env):
    runner, calls = _runner(tmp_path, monkeypatch)
    env = {**env, 'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    first = runner.run(args, env=env)
    second = runner.run(args, env=env)
    assert not first.cache_hit and second.cache_hit
    assert second.stdout == first.stdout
    assert len(calls) == 1


@pytest.mark.parametrize(('args', 'env'), [
    # No explicit host: gh may pick its sole configured host.
    (['gh', 'pr', 'list', '--repo', 'acme/demo'], {'GH_TOKEN': 'test-credential-a'}),
    # No explicit repository: gh derives the host from git remotes.
    (['gh', 'pr', 'list', '--json', 'number'], PUBLIC),
    # Host-qualified or URL repository selects another host.
    (['gh', 'pr', 'list', '--repo', 'enterprise.example/acme/demo'], PUBLIC),
    (['gh', 'pr', 'view', 'https://enterprise.example/acme/demo/pull/7'], PUBLIC),
    (['gh', 'pr', 'view', '7', '--repo', 'https://github.com/acme/demo'], PUBLIC),
    (['gh', 'pr', 'list'], {**PUBLIC, 'GH_REPO': 'enterprise.example/acme/demo'}),
    (['gh', 'pr', 'list', '--repo', 'acme/demo'], {**PUBLIC, 'GH_REPO': 'enterprise.example/acme/demo'}),
    # Conflicting or incomplete repository options.
    (['gh', 'pr', 'list', '--repo', 'acme/demo', '-R', 'acme/other'], PUBLIC),
    (['gh', 'pr', 'list', '--repo'], PUBLIC),
    # Token class does not match the explicit host.
    (['gh', 'pr', 'list', '--repo', 'acme/demo'], {'GH_HOST': 'enterprise.example', 'GH_TOKEN': 'test-credential-a'}),
    (['gh', 'pr', 'list', '--repo', 'acme/demo'], {'GH_HOST': 'github.com', 'GH_ENTERPRISE_TOKEN': 'test-credential-a'}),
    # Search has no repository context; only github.com is admitted.
    (['gh', 'search', 'prs', '--owner', 'acme'], ENTERPRISE),
    (['gh', 'search', 'prs', '--owner', 'acme'], {'GH_HOST': 'company.ghe.com', 'GH_TOKEN': 'test-credential-a'}),
    # Repository commands keep their previous behaviour.
    (['gh', 'repo', 'view', 'acme/demo'], PUBLIC),
    (['gh', 'pr', 'list', '--repo', 'acme/demo'], {'GH_HOST': 'bad host', 'GH_TOKEN': 'test-credential-a'}),
])
def test_ambiguous_host_reads_execute_each_time(tmp_path, monkeypatch, args, env):
    runner, calls = _runner(tmp_path, monkeypatch)
    env = {**env, 'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    runner.run(args, env=env)
    assert not runner.run(args, env=env).cache_hit
    assert len(calls) == 2


def test_mutating_repository_commands_are_never_cached(tmp_path, monkeypatch):
    runner, calls = _runner(tmp_path, monkeypatch)
    env = {**PUBLIC, 'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    for _ in range(2):
        assert not runner.run(['gh', 'pr', 'merge', '7', '--repo', 'acme/demo'], env=env).cache_hit
    assert len(calls) == 2


def test_tokens_partition_shared_reads_and_are_not_persisted(tmp_path, monkeypatch):
    runner, calls = _runner(tmp_path, monkeypatch)
    args = ['gh', 'pr', 'list', '--repo', 'acme/demo']
    env = {**PUBLIC, 'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    runner.run(args, env=env)
    assert not runner.run(args, env={**env, 'GH_TOKEN': 'test-credential-b'}).cache_hit
    assert len(calls) == 2
    assert b'test-credential' not in (tmp_path / 'cache.sqlite3').read_bytes()


def _token_runner(stdout='test-keyring-token\n', returncode=0, raises=None):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(args, returncode, stdout, '')

    return run, calls


def test_github_env_resolves_keyring_token_for_public_host():
    run, calls = _token_runner()
    env = github_env(env={'PATH': '/usr/bin'}, runner=run)
    assert env['GH_HOST'] == 'github.com'
    assert env['GH_TOKEN'] == 'test-keyring-token'
    assert calls[0][0] == ['gh', 'auth', 'token', '--hostname', 'github.com']
    assert calls[0][1]['env']['GH_HOST'] == 'github.com'


def test_github_env_uses_enterprise_variable_for_enterprise_host():
    run, _ = _token_runner()
    env = github_env('Enterprise.Example', env={}, runner=run)
    assert env['GH_HOST'] == 'enterprise.example'
    assert env['GH_ENTERPRISE_TOKEN'] == 'test-keyring-token'
    assert 'GH_TOKEN' not in env


def test_github_env_keeps_existing_token_without_running_gh():
    run, calls = _token_runner()
    env = github_env(env={'GITHUB_TOKEN': 'test-credential-a'}, runner=run)
    assert calls == [] and 'GH_TOKEN' not in env and env['GH_HOST'] == 'github.com'


@pytest.mark.parametrize('runner_args', [
    {'returncode': 1, 'stdout': ''},
    {'stdout': ''},
    {'stdout': 'two words\n'},
    {'raises': OSError('gh missing')},
    {'raises': subprocess.TimeoutExpired(['gh'], 10)},
])
def test_github_env_failure_leaves_identity_unresolved(runner_args):
    run, _ = _token_runner(**runner_args)
    env = github_env(env={}, runner=run)
    assert 'GH_TOKEN' not in env and env['GH_HOST'] == 'github.com'


def test_github_env_rejects_invalid_host():
    with pytest.raises(ValueError):
        github_env('bad host', env={})


def test_github_env_does_not_mutate_input():
    run, _ = _token_runner()
    source = {'PATH': '/usr/bin'}
    github_env(env=source, runner=run)
    assert source == {'PATH': '/usr/bin'}
