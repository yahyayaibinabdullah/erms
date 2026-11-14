"""Pytest safety plugin for DB-free WebUI suites, installed before collection."""
import socket
import importlib.util

import pytest

_patch = pytest.MonkeyPatch()


def pytest_configure(config):
    def blocked(*args, **kwargs):
        raise RuntimeError('Network access is forbidden in the DB-free WebUI suites')

    # ASGITransport and MockTransport remain available. Real HTTP, PostgreSQL,
    # SMTP and other socket connections must use a separate disposable runner.
    _patch.setattr(socket.socket, 'connect', blocked)
    _patch.setattr(socket.socket, 'connect_ex', blocked)
    # libpq opens its own native sockets, bypassing Python's socket methods.
    # CI installs the API dependencies alongside the frontend dependencies.
    if importlib.util.find_spec('psycopg') is not None:
        import psycopg
        _patch.setattr(psycopg, 'connect', blocked)
        _patch.setattr(psycopg.Connection, 'connect', blocked)
        _patch.setattr(psycopg.AsyncConnection, 'connect', blocked)


def pytest_unconfigure(config):
    _patch.undo()
