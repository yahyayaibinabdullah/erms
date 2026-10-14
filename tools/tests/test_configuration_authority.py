"""Production authority coverage and safe local bootstrap reconciliation."""
import json,re,subprocess,sys
from pathlib import Path
from tools.check_configuration_authority import ROOT,inventory


def test_inventory_is_current_closed_and_every_setting_has_one_owner():
    actual=inventory();assert actual==json.loads((ROOT/'docs/configuration-authority-inventory.json').read_text())
    settings=actual['settings'];assert len(settings)==len({s['setting'] for s in settings})==117
    database=[s for s in settings if s['authority']=='database']
    from backend.services.api.application_settings_registry import REGISTRY
    assert {s['setting'] for s in database}==set(REGISTRY)
    assert len(database)==51 and all(s['category'] for s in database)
    assert not any(s['setting']=='WEBUI_FULL_TEXT_SEARCH_ENABLED' for s in settings)
    assert all(not s['templates'] for s in database)


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
