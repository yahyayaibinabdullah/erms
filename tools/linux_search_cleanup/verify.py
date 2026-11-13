"""Destructive lifecycle probes, exclusively inside a marked disposable Linux host."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

import psutil
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from dotenv import dotenv_values

API = 'erms-api.service'
CLEANUP = 'erms-session-cleanup.service'
STANDBY = 'erms-session-cleanup-standby.service'
OUTPUT = Path('/tmp/lifecycle-result.json')
REPORT = {'checks': [], 'snapshots': [], 'leader_samples': []}
LEADER_KEY = 2026091803


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def show(unit):
    return dict(line.split('=', 1) for line in run(
        'systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID',
        '-p', 'InvocationID', '-p', 'NRestarts',
    ).splitlines())


def owners(url=None):
    with psycopg.connect(url or os.environ['DATABASE_URL']) as c:
        rows = c.execute("""SELECT l.pid,a.state FROM pg_locks l JOIN pg_stat_activity a USING(pid)
            WHERE l.locktype='advisory' AND l.classid=0 AND l.objid=%s AND l.objsubid=1
              AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database())
              AND l.granted""", (LEADER_KEY,)).fetchall()
    assert len(rows) <= 1, rows
    REPORT['leader_samples'].append([row[0] for row in rows])
    return rows


def wait_for(check, description, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if check():
                return
        except (OSError, ValueError, psycopg.OperationalError,
                psutil.NoSuchProcess, psutil.ZombieProcess):
            pass
        time.sleep(0.1)
    raise AssertionError('Timed out: ' + description)


def healthy():
    with urlopen('http://127.0.0.1:8000/health', timeout=1) as response:
        return response.status == 200


def journal(unit, invocation=None):
    args = ['journalctl', '-b', '-u', unit, '--no-pager', '-o', 'cat']
    if invocation:
        args.append('_SYSTEMD_INVOCATION_ID=' + invocation)
    return run(*args)


def snapshot(label):
    REPORT['snapshots'].append({'label': label, 'api': show(API),
        'cleanup': show(CLEANUP), 'standby': show(STANDBY), 'owners': owners()})


def check(label):
    REPORT['checks'].append(label)
    print('PASS: ' + label, flush=True)


def cache_count():
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        return c.execute('SELECT count(*) FROM global_search_results').fetchone()[0]


def seed_expired():
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("""INSERT INTO global_search_results(session_id,tab_id,user_id,requires_tab_id,
            search_id,fingerprint,hits,truncated,started_at,expires_at)
            SELECT id,gen_random_uuid(),user_id,true,gen_random_uuid(),'linux-fixture','[]',false,
                now(),now()-interval '1 minute' FROM login_sessions WHERE session_token_hash='linux-test-token'
        """)


def main():
    url = os.environ['DATABASE_URL']
    database = conninfo_to_dict(url)['dbname']
    assert database.startswith('erms_linux_cleanup_')
    # Reject BEFORE any service action or signal. The process environment alone
    # must never authorize stopping services pointing at a persistent database.
    assert Path('/etc/erms/disposable-lifecycle-test').read_text().strip() == database
    service_environment = dotenv_values('/etc/erms/api.env')
    assert conninfo_to_dict(service_environment['DATABASE_URL']) == conninfo_to_dict(url)
    assert service_environment['API_WORKERS'] == '2'
    assert run('cat', '/proc/1/comm') == 'systemd'
    REPORT.update(database=database, systemd=run('systemctl', '--version').splitlines()[0],
                  linux=run('uname', '-srmo'), os_release=Path('/etc/os-release').read_text(), api_workers=2)
    wait_for(lambda: len(owners()) == 1, 'PostgreSQL and cleanup ready after boot')
    with psycopg.connect(url) as c:
        REPORT['postgresql'] = c.execute('SHOW server_version').fetchone()[0]
    run('systemd-analyze', 'verify', '/etc/systemd/system/' + API, '/etc/systemd/system/' + CLEANUP)
    check('packaged systemd units validate')
    assert run('systemctl', 'is-enabled', CLEANUP) == 'enabled'
    wait_for(lambda: show(CLEANUP)['ActiveState'] == 'active' and len(owners()) == 1, 'boot leader')
    assert show(API)['ActiveState'] == 'inactive'
    check('enabled cleanup starts at Linux boot without API')

    run('systemctl', 'stop', CLEANUP)
    with psycopg.connect(url) as c:
        c.execute("SELECT set_config('app.actor_type','automated_process',true), set_config('app.event_source','seeding',true), set_config('app.change_reason','Disposable lifecycle fixture',true)")
        # Fixture-only timing reduction on this freshly initialized database.
        # Runtime settings permissions are covered by API regression tests;
        # this process test does not bootstrap a signed-in administrator.
        # Transactional DDL restores the guard even if fixture setup fails.
        c.execute('ALTER TABLE application_settings DISABLE TRIGGER application_settings_guard')
        c.execute("UPDATE application_settings SET value='2' WHERE key IN ('GLOBAL_SEARCH_CACHE_CLEANUP_INTERVAL_SECONDS','GLOBAL_SEARCH_CACHE_CLEANUP_BATCH_SIZE')")
        c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        c.execute('ALTER TABLE application_settings ENABLE TRIGGER application_settings_guard')
        user = c.execute("INSERT INTO users(name,email,account_type) VALUES('Linux cleanup fixture','linux-cleanup@example.invalid','person') RETURNING id").fetchone()[0]
        session = c.execute("""INSERT INTO login_sessions(user_id,session_token_hash,csrf_token_hash,expires_at,absolute_expires_at)
            VALUES(%s,'linux-test-token','linux-test-csrf',now()+interval '1 hour',now()+interval '2 hours') RETURNING id""", (user,)).fetchone()[0]
        c.execute("""INSERT INTO global_search_results(session_id,tab_id,user_id,requires_tab_id,search_id,fingerprint,hits,truncated,started_at,expires_at)
            SELECT %s,md5(n::text)::uuid,%s,true,md5(n::text)::uuid,'linux-fixture','[]',false,now(),
                now()+CASE WHEN n<=3 THEN -interval '1 minute' ELSE interval '1 hour' END FROM generate_series(1,4) n
        """, (session, user))
    run('systemctl', 'start', CLEANUP)
    wait_for(lambda: cache_count() == 1, 'only expired lists deleted in bounded batches')
    assert show(API)['ActiveState'] == 'inactive'
    assert 'job=search_cache selected=2 removed=2' in journal(CLEANUP, show(CLEANUP)['InvocationID'])
    check('cleanup works with API stopped, preserves active list, obeys batch size')

    original = show(CLEANUP)
    run('systemctl', 'start', API)
    wait_for(healthy, 'API start')
    children = psutil.Process(int(show(API)['MainPID'])).children(recursive=True)
    assert len([p for p in children if any('spawn_main' in a for a in p.cmdline())]) == 2
    assert show(CLEANUP)['InvocationID'] == original['InvocationID']
    run('systemctl', 'restart', API)
    wait_for(healthy, 'API restart')
    assert show(CLEANUP)['InvocationID'] == original['InvocationID']
    run('systemctl', 'stop', API)
    assert show(CLEANUP)['InvocationID'] == original['InvocationID']
    assert len(owners()) == 1
    check('two-worker API start/restart/stop leave cleanup unchanged')

    run('systemctl', 'start', API)
    wait_for(healthy, 'API before cleanup restart')
    api = show(API)
    run('systemctl', 'restart', CLEANUP)
    wait_for(lambda: len(owners()) == 1 and show(CLEANUP)['InvocationID'] != original['InvocationID'], 'cleanup restart')
    assert show(API)['InvocationID'] == api['InvocationID'] and healthy()
    check('cleanup restart leaves API unchanged')

    # A separate systemd service models another deployed process; coordination
    # uses PostgreSQL only, with no shared PID file or local singleton check.
    Path('/run/systemd/system/' + STANDBY).write_text(Path('/etc/systemd/system/' + CLEANUP).read_text())
    run('systemctl', 'daemon-reload')
    run('systemctl', 'start', STANDBY)
    wait_for(lambda: 'role=standby' in journal(STANDBY), 'second worker standby')
    standby_invocation = show(STANDBY)['InvocationID']
    leader_pid = owners()[0][0]
    for _ in range(30):
        assert owners()[0][0] == leader_pid
        time.sleep(0.1)
    assert 'job=' not in journal(STANDBY, standby_invocation)
    wait_for(lambda: owners()[0][1] == 'idle', 'leader sleeps without open transaction')
    check('concurrent workers keep one leader across job commits; standby performs no jobs')
    snapshot('two_workers')

    for extra in ([], ['--dry-run']):
        output = run('/opt/erms/backend/services/api/.venv/bin/python', '-m', 'backend.services.api.session_cleanup', *extra)
        assert 'role=standby' in output and 'job=' not in output
    check('one-shot and dry-run commands respect existing leader')

    started = time.monotonic()
    run('systemctl', 'stop', CLEANUP)
    REPORT['graceful_stop_seconds'] = round(time.monotonic() - started, 3)
    assert REPORT['graceful_stop_seconds'] < 3
    wait_for(lambda: len(owners()) == 1 and owners()[0][0] != leader_pid, 'standby promotion')
    REPORT['graceful_takeover_seconds'] = round(time.monotonic() - started, 3)
    assert 'role=leader' in journal(STANDBY, standby_invocation)
    seed_expired()
    wait_for(lambda: cache_count() == 1, 'promoted worker performs cleanup')
    check('graceful leader stop releases lock and standby takes over and cleans')

    run('systemctl', 'start', CLEANUP)
    wait_for(lambda: 'role=standby' in journal(CLEANUP, show(CLEANUP)['InvocationID']), 'old owner rejoins as standby')
    old = show(STANDBY)
    old_owner = owners()[0][0]
    os.kill(int(old['MainPID']), signal.SIGKILL)
    wait_for(lambda: len(owners()) == 1 and owners()[0][0] != old_owner, 'crash takeover')
    wait_for(lambda: show(STANDBY)['ActiveState'] == 'active' and show(STANDBY)['InvocationID'] != old['InvocationID'], 'supervisor restarts crashed worker')
    seed_expired()
    wait_for(lambda: cache_count() == 1, 'cleanup after crash')
    check('SIGKILL releases leadership, supervision restarts process, cleanup continues')
    snapshot('after_crash')

    old_owner = owners()[0][0]
    before = {unit: show(unit)['InvocationID'] for unit in (CLEANUP, STANDBY)}
    with psycopg.connect(url) as c:
        c.execute('SELECT pg_terminate_backend(%s)', (old_owner,))
    wait_for(lambda: len(owners()) == 1 and owners()[0][0] != old_owner, 'database connection loss takeover')
    wait_for(lambda: any(show(unit)['InvocationID'] != before[unit] for unit in before), 'failed connection owner restarts')
    seed_expired()
    wait_for(lambda: cache_count() == 1, 'cleanup after lost database session')
    assert show(API)['InvocationID'] == api['InvocationID'] and healthy()
    check('lost PostgreSQL leader connection forces restart and safe takeover without API restart')
    snapshot('connection_loss')

    # Independence is per database, not per PostgreSQL server. Initialize a
    # second fresh database from the canonical initializer, never a live clone.
    from tools.initialize_database import initialize
    other_name = database + '_other'
    other_url = make_conninfo(url, dbname=other_name)
    process = None
    created = False
    with psycopg.connect(make_conninfo(url, dbname='postgres'), autocommit=True) as admin:
        try:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(other_name)))
            created = True
            with psycopg.connect(other_url) as c:
                initialize(c)
            with Path('/tmp/other-database-cleanup.log').open('w') as log:
                process = subprocess.Popen(
                    [sys.executable, '-m', 'backend.services.api.session_cleanup', '--watch'],
                    env={**os.environ, 'DATABASE_URL': other_url}, stdout=log, stderr=subprocess.STDOUT,
                )
                wait_for(lambda: len(owners(other_url)) == 1 and len(owners()) == 1,
                         'independent leaders on two databases')
                assert process.poll() is None
                check('two databases on one PostgreSQL server elect independent active workers')
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if created:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(other_name)))
                REPORT['secondary_database_dropped'] = other_name

    run('systemctl', 'stop', CLEANUP, STANDBY)
    assert owners() == []
    assert healthy()
    run('systemctl', 'stop', API)
    snapshot('final_stop')
    check('stopping both cleanup services releases leadership and leaves API operational until explicitly stopped')
    REPORT['passed'] = True


if __name__ == '__main__':
    try:
        main()
    finally:
        REPORT['journal'] = {unit: journal(unit) for unit in (API, CLEANUP, STANDBY)}
        OUTPUT.write_text(json.dumps(REPORT, indent=2) + '\n')
