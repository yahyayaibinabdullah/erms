"""Private staged preview shares rendering without creating or promoting a record."""
import base64
from dataclasses import replace
import os

import psycopg
from psycopg.rows import dict_row
import pytest
from backend.services.api import main
from backend.services.api.document_conversion import UnsupportedPreview,ConversionUnavailable
from backend.services.api.tests.test_phase7_mutation_authorization import _grant_principal,_login_as_phase7

PDF=b'%PDF-1.4\n% staged fixture\n%%EOF'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1cAAAAASUVORK5CYII=')


def stage(client,aggregation,*,name='draft.pdf',content=PDF,mime='application/pdf'):
    response=client.post('/api/v1/record-drafts',json={'aggregation_id':aggregation['id'],'record_number':'DRAFT-PREVIEW','title':'Unsaved preview'})
    assert response.status_code==201,response.text
    draft=response.json()
    response=client.post(f"/api/v1/record-drafts/{draft['id']}/components",data={'component_order':'1'},files={'file':(name,content,mime)})
    assert response.status_code==201,response.text
    return draft,response.json()


def url(draft,component):return f"/api/v1/record-drafts/{draft['id']}/components/{component['id']}/rendition"


@pytest.mark.parametrize('mime,name,content',[
 ('application/pdf','draft.pdf',PDF),('image/png','draft.png',PNG),
 ('audio/mpeg','draft.mp3',b'ID3-audio'),('video/mp4','draft.mp4',b'video-fixture'),
])
def test_native_staged_preview_range_head_and_no_record_side_effects(client,aggregation,mime,name,content):
    draft,component=stage(client,aggregation,name=name,content=content,mime=mime)
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        before=c.execute('SELECT * FROM record_drafts WHERE id=%s',(draft['id'],)).fetchone()
        before_component=c.execute('SELECT * FROM record_draft_components WHERE id=%s',(component['id'],)).fetchone()
    response=client.get(url(draft,component))
    assert response.status_code==200 and response.content==content
    assert response.headers['content-type'].startswith(mime)
    assert response.headers['cache-control']=='private, no-store'
    assert response.headers['content-disposition'].startswith('inline;')
    assert response.headers['x-content-type-options']=='nosniff'
    assert response.headers['content-security-policy']=='sandbox'
    partial=client.get(url(draft,component),headers={'Range':'bytes=1-3'})
    assert partial.status_code==206 and partial.content==content[1:4]
    assert partial.headers['content-range']==f'bytes 1-3/{len(content)}'
    head=client.head(url(draft,component));assert head.status_code==200 and head.content==b''
    assert head.headers['content-length']==str(len(content))
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        assert c.execute('SELECT * FROM record_drafts WHERE id=%s',(draft['id'],)).fetchone()==before
        assert c.execute('SELECT * FROM record_draft_components WHERE id=%s',(component['id'],)).fetchone()==before_component
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM digital_components').fetchone()['n']==0
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='CONTENT_VIEWED'").fetchone()['n']==0


def test_staged_text_uses_same_conversion_service_and_preserves_original(client,aggregation,monkeypatch):
    draft,component=stage(client,aggregation,name='draft.txt',content=b'preview this',mime='text/plain');calls=[]
    def convert(content,name,mime,**kwargs):
        calls.append((content,name,mime,kwargs));return PDF,'test-conversion'
    monkeypatch.setattr(main,'pdf_rendition',convert)
    response=client.get(url(draft,component))
    assert response.status_code==200 and response.content==PDF and response.headers['content-type'].startswith('application/pdf')
    assert calls[0][:3]==(b'preview this','draft.txt','text/plain') and 'settings' in calls[0][3]
    committed=client.post(f"/api/v1/record-drafts/{draft['id']}/commit")
    assert committed.status_code==201,committed.text
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        saved=c.execute('SELECT id FROM digital_components WHERE record_id=%s',(committed.json()['id'],)).fetchone()
    assert client.get(f"/api/v1/digital-components/{saved['id']}/content").content==b'preview this'
    assert client.get(url(draft,component)).status_code==404


@pytest.mark.parametrize('error,status',[(UnsupportedPreview('Unsupported fixture'),415),(ConversionUnavailable('Unavailable fixture'),503)])
def test_staged_conversion_error_does_not_discard_upload(client,aggregation,monkeypatch,error,status):
    draft,component=stage(client,aggregation,name='draft.txt',content=b'original',mime='text/plain')
    def fail(*a,**kw):raise error
    monkeypatch.setattr(main,'pdf_rendition',fail)
    assert client.get(url(draft,component)).status_code==status
    assert client.get(f"/api/v1/record-drafts/{draft['id']}/components").json()[0]['checksum_value']==component['checksum_value']


def test_staged_unsupported_format_and_conversion_size_limit(client,aggregation,monkeypatch):
    draft,component=stage(client,aggregation,name='draft.zip',content=b'zip',mime='application/zip')
    assert client.get(url(draft,component)).status_code==415
    original=main.settings_cache.for_connection
    monkeypatch.setattr(main.settings_cache,'for_connection',lambda c:replace(original(c),values={**original(c).values,'MAX_RENDITION_SIZE_BYTES':1}))
    assert client.get(url(draft,component)).status_code==413


def test_staged_preview_is_owner_only_and_rechecks_create_privilege(client,aggregation):
    _,role=_grant_principal({'record.create','aggregation.view'});_login_as_phase7(client)
    draft,component=stage(client,aggregation)
    assert client.get(url(draft,component)).status_code==200  # No saved-component view/download/print privilege.
    client.cookies.clear();client.headers.pop('X-CSRF-Token',None)
    login=client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':'Temporary-Test-Password-123!'})
    assert login.status_code==200
    for method in (client.get,client.head):assert method(url(draft,component)).status_code==404
    _login_as_phase7(client)
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT profile_id FROM roles WHERE id=%s) AND privilege_id=(SELECT id FROM privileges WHERE code='record.create')",(role,))
    for method in (client.get,client.head):assert method(url(draft,component)).status_code==403


def test_staged_preview_rejects_cross_draft_deleted_expired_and_incomplete_uploads(client,aggregation):
    draft,component=stage(client,aggregation)
    another=client.post('/api/v1/record-drafts',json={}).json()
    assert client.get(url(another,component)).status_code==404
    with psycopg.connect(os.environ['DATABASE_URL']) as c:c.execute("UPDATE record_draft_components SET content_status='uploading' WHERE id=%s",(component['id'],))
    assert client.get(url(draft,component)).status_code==409
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("UPDATE record_draft_components SET content_status='available' WHERE id=%s",(component['id'],))
        c.execute("UPDATE record_drafts SET expires_at=CURRENT_TIMESTAMP-interval '1 second' WHERE id=%s",(draft['id'],))
    for method in (client.get,client.head):assert method(url(draft,component)).status_code==404
    with psycopg.connect(os.environ['DATABASE_URL']) as c:c.execute("UPDATE record_drafts SET expires_at=CURRENT_TIMESTAMP+interval '1 day' WHERE id=%s",(draft['id'],))
    assert client.delete(f"/api/v1/record-drafts/{draft['id']}/components/{component['id']}").status_code==204
    assert client.get(url(draft,component)).status_code==404


def test_staged_preview_reads_ordered_segments_and_cross_segment_ranges(client,aggregation,monkeypatch):
    original=main.settings_cache.for_connection
    monkeypatch.setattr(main.settings_cache,'for_connection',lambda c:replace(original(c),values={**original(c).values,'CONTENT_SEGMENT_SIZE_BYTES':8}))
    draft,component=stage(client,aggregation)
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        assert c.execute('SELECT count(*) FROM record_draft_component_blobs WHERE record_draft_component_id=%s',(component['id'],)).fetchone()[0]>1
    assert client.get(url(draft,component)).content==PDF
    response=client.get(url(draft,component),headers={'Range':'bytes=6-19'})
    assert response.status_code==206 and response.content==PDF[6:20]
