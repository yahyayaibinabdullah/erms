"""Content policy cutover and extension of the reviewed migration."""
from datetime import datetime,timezone
from pathlib import Path
import subprocess
import pytest
from backend.services.api import application_settings_migration as migration
from backend.services.api import content_cleanup,document_conversion
from backend.services.api.application_settings import SettingsInvalid
from backend.services.api.tests.test_application_settings_phase4 import db,save,items,plan_for,apply_plan


def upload(client,record,payload,order=1):
    return client.post(f"/api/v1/records/{record['id']}/digital-components/upload",data={'component_order':str(order)},files={'file':('policy.bin',payload,'application/octet-stream')})


def test_content_snapshot_boundaries_checksums_ttl_and_runtime_change(client,record,monkeypatch):
    for key in migration.CONTENT_KEYS:monkeypatch.setenv(key,'invalid-obsolete-value')
    assert save(client,{'MAX_UPLOAD_SIZE_BYTES':8,'CONTENT_SEGMENT_SIZE_BYTES':3,
                        'CONTENT_SEGMENT_CHECKSUMS_ENABLED':False,'CONTENT_UPLOAD_SESSION_TTL_SECONDS':45}).status_code==200
    before=datetime.now(timezone.utc)
    response=upload(client,record,b'12345678');assert response.status_code==201,response.text
    component=response.json()
    with db() as c:
        blobs=c.execute('SELECT segment_size,segment_checksum_algo,segment_checksum_value FROM digital_component_blobs WHERE content_set_id=%s ORDER BY segment_no',(component['active_content_set_id'],)).fetchall()
        assert [r['segment_size'] for r in blobs]==[3,3,2] and all(r['segment_checksum_value'] is None for r in blobs)
        session=c.execute('SELECT expires_at FROM content_upload_sessions WHERE content_set_id=%s',(component['active_content_set_id'],)).fetchone()
        assert 44 <= (session['expires_at']-before).total_seconds() < 48
    failed=upload(client,record,b'123456789',2);assert failed.status_code==413
    with db() as c:assert c.execute('SELECT count(*) AS n FROM digital_components').fetchone()['n']==1
    assert save(client,{'CONTENT_SEGMENT_SIZE_BYTES':2,'CONTENT_SEGMENT_CHECKSUMS_ENABLED':True,'MAX_UPLOAD_SIZE_BYTES':9}).status_code==200
    second=upload(client,record,b'123456789',2);assert second.status_code==201
    with db() as c:
        blobs=c.execute('SELECT segment_size,segment_checksum_value FROM digital_component_blobs WHERE content_set_id=%s ORDER BY segment_no',(second.json()['active_content_set_id'],)).fetchall()
        assert [r['segment_size'] for r in blobs]==[2,2,2,2,1] and all(r['segment_checksum_value'] for r in blobs)
    assert client.get(f"/api/v1/digital-components/{component['id']}/content",headers={'Range':'bytes=2-6'}).content==b'34567'


def test_content_worker_runtime_interval_override_and_failure_before_cleanup(client,monkeypatch):
    assert save(client,{'CONTENT_CLEANUP_INTERVAL_SECONDS':7}).status_code==200
    assert content_cleanup._run_pass(batch_size=1,dry_run=True)[1]==7
    assert save(client,{'CONTENT_CLEANUP_INTERVAL_SECONDS':9}).status_code==200
    assert content_cleanup._run_pass(batch_size=1,dry_run=True,watch=True)[1]==9
    assert content_cleanup._run_pass(batch_size=1,dry_run=True,interval_seconds=2)[1]==2
    called=[]
    monkeypatch.setattr(content_cleanup,'cleanup_content',lambda *a,**k:called.append(True))
    def fail(*args):raise SettingsInvalid('fixture_unavailable')
    monkeypatch.setattr(content_cleanup,'load_snapshot',fail)
    with pytest.raises(SettingsInvalid):content_cleanup.run_once(batch_size=1,dry_run=False)
    assert called==[]


def test_conversion_captures_runtime_timeout_and_size_for_entire_operation(client,monkeypatch):
    calls=[];pdf=b'%PDF-large-fixture'
    monkeypatch.setattr(document_conversion,'_libreoffice_binary',lambda:'/fixture/soffice')
    def convert(command,**kwargs):
        calls.append(kwargs['timeout']);(Path(command[command.index('--outdir')+1])/'source.pdf').write_bytes(pdf)
        return subprocess.CompletedProcess(command,0,stdout=b'',stderr=b'')
    monkeypatch.setattr(document_conversion.subprocess,'run',convert)
    for key in ('DOCUMENT_CONVERSION_TIMEOUT_SECONDS','MAX_RENDITION_SIZE_BYTES'):monkeypatch.setenv(key,'invalid-obsolete')
    assert save(client,{'DOCUMENT_CONVERSION_TIMEOUT_SECONDS':3,'MAX_RENDITION_SIZE_BYTES':len(pdf)}).status_code==200
    with db() as c:
        from backend.services.api.application_settings import load_snapshot
        configuration=load_snapshot(c)
    assert document_conversion.pdf_rendition(b'input','file.txt','text/plain',settings=configuration)[0]==pdf
    assert calls==[3]
    assert save(client,{'DOCUMENT_CONVERSION_TIMEOUT_SECONDS':5,'MAX_RENDITION_SIZE_BYTES':len(pdf)-1}).status_code==200
    with db() as c:configuration=load_snapshot(c)
    with pytest.raises(document_conversion.ConversionUnavailable,match='size limit'):
        document_conversion.pdf_rendition(b'input','file.txt','text/plain',settings=configuration)
    assert calls==[3,5]
    monkeypatch.setattr(document_conversion.subprocess,'run',lambda command,**kwargs:(_ for _ in ()).throw(subprocess.TimeoutExpired(command,kwargs['timeout'])))
    with pytest.raises(document_conversion.ConversionUnavailable,match='timed out'):
        document_conversion.pdf_rendition(b'input','file.txt','text/plain',settings=configuration)


def test_extended_migration_preserves_completed_general_keys_and_boolean_legacy(client,tmp_path,monkeypatch):
    original=migration.MIGRATED_KEYS
    path=tmp_path/'legacy.env';path.write_text('DEFAULT_WORKING_TIMEZONE=UTC\nCONTENT_SEGMENT_CHECKSUMS_ENABLED=no\nMAX_UPLOAD_SIZE_BYTES=12345\n')
    monkeypatch.setattr(migration,'MIGRATED_KEYS',migration.GENERAL_INTERFACE_KEYS)
    apply_plan(plan_for(path),path)
    before=items(client)['DEFAULT_WORKING_TIMEZONE']
    monkeypatch.setattr(migration,'MIGRATED_KEYS',original)
    path.write_text('DEFAULT_WORKING_TIMEZONE=invalid-later-edit\nCONTENT_SEGMENT_CHECKSUMS_ENABLED=no\nMAX_UPLOAD_SIZE_BYTES=12345\n')
    untouched=path.read_bytes();plan=plan_for(path)
    assert all(r['action']=='completed' for r in plan['items'] if r['key'] in migration.GENERAL_INTERFACE_KEYS)
    assert not plan['issues']
    apply_plan(plan,path)
    assert path.read_bytes()==untouched and items(client)['DEFAULT_WORKING_TIMEZONE']==before
    assert items(client)['CONTENT_SEGMENT_CHECKSUMS_ENABLED']['value'] is False
    assert items(client)['MAX_UPLOAD_SIZE_BYTES']['value']==12345
    assert save(client,{'MAX_UPLOAD_SIZE_BYTES':6789}).status_code==200
    apply_plan(plan,path)
    assert items(client)['MAX_UPLOAD_SIZE_BYTES']['value']==6789


def test_valid_large_upload_lifetime_is_representable(client,record):
    assert save(client,{'CONTENT_UPLOAD_SESSION_TTL_SECONDS':9223372036854775807}).status_code==200
    response=upload(client,record,b'content');assert response.status_code==201,response.text
    with db() as c:
        expires=c.execute('SELECT expires_at FROM content_upload_sessions WHERE content_set_id=%s',(response.json()['active_content_set_id'],)).fetchone()['expires_at']
    assert expires.year==9999
