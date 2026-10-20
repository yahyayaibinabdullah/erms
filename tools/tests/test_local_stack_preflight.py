"""Port ownership checks without any database access."""
import socket
from io import BytesIO
from types import SimpleNamespace

import pytest

from tools import local_stack_preflight as probe


@pytest.mark.parametrize('kind,body,expected', [
    ('api', b'{"status":"ok"}', False),
    ('api', b'{"status":"ok","notifications":{},"messaging_realtime":{}}', True),
    ('api', b'[]', False),
    ('webui', b'<title>Another application</title>', False),
    ('webui', b'<title>wathiq</title><script src="/_nicegui/app.js"></script>', True),
])
def test_unrelated_http_200_is_not_reused(monkeypatch, kind, body, expected):
    def open_response(*args, **kwargs):
        response = BytesIO(body)
        response.status = 200
        return response
    monkeypatch.setattr(probe.urllib.request, 'build_opener',
                        lambda *args: SimpleNamespace(open=open_response))
    assert probe.expected_service('http://localhost:8000', kind) is expected


def test_loopback_listener_is_rejected_before_wildcard_bind(monkeypatch):
    monkeypatch.setattr(probe, 'expected_service', lambda *args: False)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = probe.check(f'http://127.0.0.1:{port}', 'api', '0.0.0.0', port)
        assert 'occupied' in result and 'API_PORT and WEBUI_API_URL' in result
        assert listener.fileno() != -1


def test_wrong_ui_service_is_rejected(monkeypatch):
    monkeypatch.setattr(probe, 'expected_service', lambda *args: False)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = probe.check(f'http://127.0.0.1:{port}', 'webui', '0.0.0.0', port)
        assert 'occupied' in result and 'WEBUI_PORT and ERMS_LOCAL_UI_URL' in result


def test_matching_service_is_reused(monkeypatch):
    monkeypatch.setattr(probe, 'expected_service', lambda *args: True)
    assert probe.check('http://127.0.0.1:8000', 'api', '0.0.0.0', 8000) is None


def test_url_and_bind_port_must_agree(monkeypatch):
    monkeypatch.setattr(probe, 'expected_service', lambda *args: False)
    assert 'consistently' in probe.check('http://127.0.0.1:8000', 'api', '0.0.0.0', 18000)
