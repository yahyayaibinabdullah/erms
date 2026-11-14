"""Keep production cleanup independent of API replica lifecycle."""
from configparser import ConfigParser
from pathlib import Path


def test_cleanup_is_independently_supervised_outside_uvicorn():
    deploy = Path(__file__).resolve().parents[2] / 'backend/services/api/deploy'
    api, cleanup = ConfigParser(interpolation=None), ConfigParser(interpolation=None)
    api.read(deploy / 'erms-api.service')
    cleanup.read(deploy / 'erms-session-cleanup.service')
    for dependency in ('Wants', 'Requires', 'PartOf', 'BindsTo', 'After'):
        assert 'erms-session-cleanup.service' not in api['Unit'].get(dependency, '').split()
        assert 'erms-api.service' not in cleanup['Unit'].get(dependency, '').split()
    assert cleanup['Service']['EnvironmentFile'] == api['Service']['EnvironmentFile'] == '/etc/erms/api.env'
    assert cleanup['Service']['ExecStart'].endswith('-m backend.services.api.session_cleanup --watch')
    assert cleanup['Service']['Restart'] == 'on-failure'
    assert cleanup['Service']['KillMode'] == 'control-group'
    assert cleanup['Install']['WantedBy'] == 'multi-user.target'
