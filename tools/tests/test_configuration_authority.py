"""Production authority coverage and safe local bootstrap reconciliation."""
import json,re,subprocess,sys
from pathlib import Path
import pytest
from tools import check_configuration_authority as authority
from tools.check_configuration_authority import ROOT,inventory


def test_inventory_is_current_closed_and_every_setting_has_one_owner():
    actual=inventory();assert actual==json.loads((ROOT/'docs/configuration-authority-inventory.json').read_text())
    settings=actual['settings'];assert len(settings)==len({s['setting'] for s in settings})
    database=[s for s in settings if s['authority']=='database']
    from backend.services.api.application_settings_registry import REGISTRY
    assert {s['setting'] for s in database}==set(REGISTRY)
    assert all(s['category'] for s in database)
    assert not any(s['setting']=='WEBUI_FULL_TEXT_SEARCH_ENABLED' for s in settings)
    assert all(not s['templates'] for s in database)


def test_all_service_templates_and_later_presentation_settings_are_reconciled():
    settings={s['setting']:s for s in inventory()['settings']}
    assert set(authority.TEMPLATES)=={
        '.env.example','.env.example.api','.env.example.text_indexer',
        'backend/services/api/deploy/api.env.example',
        'frontend/webui/deploy/webui.env.example',
        'backend/services/text_indexer/deploy/text-indexer.env.example',
    }
    for key in authority.REQUEST_PRESENTATION_SETTINGS:
        assert settings[key]['authority']=='database' and not settings[key]['templates']
        assert settings[key]['contract'].startswith('specs/administration-settings.md#')
    trust=settings['SSL_CERT_FILE']
    assert trust['authority']=='deployment' and trust['service']=='API'
    assert set(trust['templates'])=={'.env.example','.env.example.api','backend/services/api/deploy/api.env.example'}
    assert 'platform trust' in trust['default_or_requirement']


@pytest.mark.parametrize('template',authority.TEMPLATES)
@pytest.mark.parametrize('key',['SMTP_HOST','DISPOSITION_REQUEST_LANGUAGE'])
def test_database_keys_are_rejected_in_every_template(tmp_path,monkeypatch,template,key):
    probe=tmp_path/'example.env'
    probe.write_text((ROOT/template).read_text()+'\n'+key+'=obsolete\n')
    monkeypatch.setattr(authority,'TEMPLATES',[str(probe)])
    with pytest.raises(ValueError,match='Database key in environment template: '+key):
        inventory()


def test_cross_service_keys_are_rejected(tmp_path,monkeypatch):
    probe=tmp_path/'webui.env.example';probe.write_text('DATABASE_URL=example\n')
    monkeypatch.setattr(authority,'TEMPLATES',[str(probe)])
    monkeypatch.setattr(authority,'TEMPLATE_SERVICES',{str(probe):'WebUI'})
    with pytest.raises(ValueError,match='Wrong service environment template: DATABASE_URL'):
        inventory()


def test_missing_service_template_documentation_is_rejected(monkeypatch):
    monkeypatch.setattr(authority,'TEMPLATES',[t for t in authority.TEMPLATES if t!='frontend/webui/deploy/webui.env.example'])
    with pytest.raises(ValueError,match='Production reader absent from service template: WEBUI_'):
        inventory()


def test_local_bootstrap_preserves_private_bytes_empty_assignments_and_permissions(tmp_path):
    source=(ROOT/'tools/bootstrap-local-dev.sh').read_text()
    script=re.search(r"python3 - .*? <<'PY'\n(.*?)\nPY",source,re.S).group(1)
    path=tmp_path/'local.env';before=b'# Private operator choices\nDATABASE_URL=preserve-private-value\nTEXT_INDEXER_ENABLED=false\nLIBREOFFICE_BINARY=\nFULL_TEXT_SEARCH_ENABLED=true\n'
    path.write_bytes(before);path.chmod(0o600)
    result=subprocess.run([sys.executable,'-',str(path),str(ROOT)],input=script,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert path.read_bytes().startswith(before) and path.stat().st_mode & 0o777==0o600
    assert path.read_text().count('TEXT_INDEXER_ENABLED=')==1
    assert 'WEBUI_FULL_TEXT_SEARCH_ENABLED' not in path.read_text()
    after=path.read_bytes()
    assert subprocess.run([sys.executable,'-',str(path),str(ROOT)],input=script,text=True,capture_output=True).returncode==0
    assert path.read_bytes()==after
