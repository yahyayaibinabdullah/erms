"""Lifecycle safety checks; no database, SMTP service or external network."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'local_maildev', Path(__file__).resolve().parents[2] / 'run-maildev.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'RUNTIME', tmp_path)
    monkeypatch.setattr(module, 'CERT', tmp_path / 'localhost.pem')
    monkeypatch.setattr(module, 'KEY', tmp_path / 'localhost.key')
    return module


def test_reused_pid_is_never_signalled(launcher, monkeypatch):
    monkeypatch.setattr(launcher, 'identity', lambda pid: 'another process')
    kill = Mock()
    monkeypatch.setattr(launcher.os, 'kill', kill)
    launcher.stop({'pid': 123, 'identity': 'original process'})
    kill.assert_not_called()


def test_owned_process_stops_without_killing_replacement(launcher, monkeypatch):
    identities = iter(['original process', 'replacement process'])
    monkeypatch.setattr(launcher, 'identity', lambda pid: next(identities))
    kill = Mock()
    monkeypatch.setattr(launcher.os, 'kill', kill)
    launcher.stop({'pid': 123, 'identity': 'original process'})
    kill.assert_called_once_with(123, launcher.signal.SIGTERM)


def test_stack_cannot_stop_maildev_owned_by_someone_else(launcher, monkeypatch):
    kill = Mock()
    monkeypatch.setattr(launcher.os, 'kill', kill)
    launcher.stop({'pid': 123, 'identity': 'process', 'owner': 'manual'}, owner='stack')
    kill.assert_not_called()


def test_stack_reuse_does_not_take_ownership(launcher, monkeypatch):
    previous = {'pid': 123, 'owner': None}
    monkeypatch.setattr(launcher, 'running', lambda state: True)
    monkeypatch.setattr(launcher, 'health', lambda state: None)
    monkeypatch.setattr(launcher, 'report', lambda state: None)
    launcher.start(SimpleNamespace(owner='stack'), previous)
    assert previous['owner'] is None


def test_stack_stops_its_own_maildev(launcher, monkeypatch):
    identities = iter(['process', None])
    monkeypatch.setattr(launcher, 'identity', lambda pid: next(identities))
    kill = Mock()
    monkeypatch.setattr(launcher.os, 'kill', kill)
    launcher.stop({'pid': 123, 'identity': 'process', 'owner': 'stack'}, owner='stack')
    kill.assert_called_once_with(123, launcher.signal.SIGTERM)


@pytest.mark.parametrize('existing', ['CERT', 'KEY'])
def test_partial_key_pair_is_preserved_and_rejected(launcher, existing):
    path = getattr(launcher, existing)
    path.write_text('do not replace')
    with pytest.raises(RuntimeError, match='Incomplete certificate/key pair'):
        launcher.certificates()
    assert path.read_text() == 'do not replace'


@pytest.mark.parametrize('value', ['0', '1023', '65536'])
def test_privileged_and_invalid_ports_rejected(launcher, value):
    with pytest.raises(launcher.argparse.ArgumentTypeError):
        launcher.port(value)
