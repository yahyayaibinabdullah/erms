"""Offline command safety without making a database connection."""
import pytest
psycopg = pytest.importorskip("psycopg")
from tools import migrate_application_settings as command


def test_readiness_connection_failure_is_nonzero_and_does_not_print_credentials(monkeypatch,tmp_path,capsys):
    source=tmp_path/'legacy.env';source.write_text('DEFAULT_WORKING_TIMEZONE=UTC\n')
    def fail(*args,**kwargs):raise psycopg.OperationalError('private-password-and-connection-string')
    monkeypatch.setattr(command.psycopg,'connect',fail)
    assert command.main(['--check','--database-url','never-connect-private-password','--source-env',str(source)])==1
    output=capsys.readouterr()
    assert 'OperationalError' in output.err and 'private-password' not in output.err+output.out


def test_preview_output_cannot_replace_source_file(monkeypatch,tmp_path,capsys):
    source=tmp_path/'legacy.env';source.write_text('DEFAULT_WORKING_TIMEZONE=UTC\n')
    original=source.read_bytes()
    def unexpected(*args,**kwargs):raise AssertionError('Connection should not be opened')
    monkeypatch.setattr(command.psycopg,'connect',unexpected)
    assert command.main(['--preview','--database-url','unused','--source-env',str(source),'--plan',str(source)])==1
    assert source.read_bytes()==original
    assert 'plan_cannot_replace_source' in capsys.readouterr().err
