"""Phase 12 contracts; all DB access uses the disposable test-runner database."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib
import json

from fastapi import HTTPException
from lxml import etree
from pypdf import PdfReader
import psycopg
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.application_settings import load_snapshot
from backend.services.api.disposition import documents as d,template_engine as e,document_snapshots as snapshots
from backend.services.api.disposition.template_contract import CONTRACTS,row_fields,group_fields
from backend.services.api.tests.test_disposition_artifacts import fixture,officer
from backend.services.api.tests.test_disposition_membership import db,setup,actor,ready,admit,job_version

MAXIMUM=104857600


def sample(kind,job_id=1,rows=1):
    c=CONTRACTS[kind]
    fields={k:'قيمة فعلية / Actual value' for k in c.fields}
    fields.update({'job.id':job_id,'job.number':'DEST-2026-001','generated_at':'2026-10-15T10:00:00Z',
      'job.created_at':'2026-10-01T09:00:00Z','job.type':'Destruction / إتلاف','job.owner':'وحدة الوثائق / Records Unit',
      'job.officer':'مسؤول الوثائق / Records Officer'})
    if kind=='digital_destruction_certificate':
        fields={key:value for key,value in fields.items() if key in c.fields}
        fields['certificate.statement.en']='Pursuant to approval for DEST-2026-001, digital destruction completed.'
    for k in fields:
        if k.startswith(('counts.','totals.')):fields[k]=1
    if 'integrity.value' in fields:fields['integrity.value']='sha256:'+('ab'*32)
    if 'membership.checksum' in fields:fields['membership.checksum']='sha256:'+('cd'*32)
    result={'fields':fields}
    for group,labels in group_fields(c).items():
        row={k:'قيمة فعلية / Actual value' for k in labels}
        for k in row:
            if k.split('.')[-1] in ('roots','descendant_aggregations','records','physical','digital','mixed','current_years','intermediate_years','physical_aggregations','mixed_aggregations','physical_records','mixed_records'):row[k]=1
        result[group]=[dict(row) for _ in range(rows)]
    return result


def revised(kind='destruction_request',old='Request for destruction',new='Revised request for destruction'):
    value=d.default(kind)['content'];out=BytesIO()
    with ZipFile(BytesIO(value)) as archive,ZipFile(out,'w',ZIP_DEFLATED) as target:
        for name in archive.namelist():
            content=archive.read(name)
            if name=='word/document.xml':content=content.replace(old.encode(),new.encode())
            target.writestr(name,content)
    return out.getvalue()


def revise(c,job,kind='destruction_request',content=None,**kwargs):
    return d.revise(c,job_id=job['id'],kind=kind,expected_reference=d.current(c,kind)['reference'],command_id=kwargs.pop('command_id',uuid4()),
      acting_role_id=kwargs.pop('acting_role_id',officer(c)),reason='Revise controlled template for acceptance',
      content=content or revised(kind,CONTRACTS[kind].english,'Revised '+CONTRACTS[kind].english),filename='قالب معدل.docx',settings=load_snapshot(c),**kwargs)


@pytest.mark.parametrize('kind',CONTRACTS)
def test_all_defaults_validate_fill_all_fields_and_repeating_rows(kind):
    default=d.default(kind);source=sample(kind,rows=3)
    e.validate(default['content'],kind,MAXIMUM)
    filled=e.fill(default['content'],kind,source,MAXIMUM)
    with ZipFile(BytesIO(filled)) as archive:
        xml=archive.read('word/document.xml').decode()
        assert '{{' not in xml and '}}' not in xml
        assert 'DEST-2026-001' in xml
        assert not any(s in xml.lower() for s in ('signature','seal','توقيع','ختم'))
    assert default['reference'].endswith(hashlib.sha256(default['content']).hexdigest())


@pytest.mark.parametrize('old,new,code',[
 ('{{organization.name}}','','disposition_template_fields_missing'),
 ('{{aggregation.records}}','','disposition_template_repeat_invalid'),
 ('{{/aggregations}}','','disposition_template_repeat_invalid'),
 ('{{#aggregations}}','{{#proposals}}','disposition_template_invalid'),
 ('{{organization.name}}','{{unknown.value}}','disposition_template_invalid'),
 ('{{job.number}}','{{not closed','disposition_template_invalid'),
])
def test_missing_unknown_malformed_and_broken_repeats_rejected(old,new,code):
    with pytest.raises(HTTPException) as error:e.validate(revised(old=old,new=new),'destruction_request',MAXIMUM)
    assert error.value.detail['code']==code


def test_split_word_runs_preserve_replacement_and_surrounding_formatting():
    content=revised(old='{{job.number}}',new='{{job.</w:t></w:r><w:r><w:t>number}}')
    result=e.fill(content,'destruction_request',sample('destruction_request',42),MAXIMUM)
    with ZipFile(BytesIO(result)) as archive:assert '<w:t xml:space="preserve">DEST-2026-001' in archive.read('word/document.xml').decode()


@pytest.mark.parametrize('kind',['destruction_request','physical_preparation_report'])
def test_missing_snapshot_values_or_noninteger_counts_rejected(kind):
    value=sample(kind);value['fields'].pop('job.number')
    with pytest.raises(HTTPException):e.fill(d.default(kind)['content'],kind,value,MAXIMUM)
    value=sample(kind);key=next(k for k in value['fields'] if k.startswith(('counts.','totals.')));value['fields'][key]=1.5
    with pytest.raises(HTTPException):e.snapshot_values(kind,value)


def test_unsafe_and_oversize_word_packages_rejected():
    with pytest.raises(HTTPException):e.validate(b'not a Word file','destruction_request',MAXIMUM)
    original=d.default('destruction_request')['content']
    with pytest.raises(HTTPException) as error:e.validate(original,'destruction_request',100)
    assert error.value.status_code==413
    for name,value in [('word/vbaProject.bin',b'macro'),('word/_rels/evil.rels',b'<Relationships><Relationship TargetMode="External" Target="file:///etc/passwd"/></Relationships>'),('word/evil.xml',b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><x>&a;</x>')]:
        out=BytesIO()
        with ZipFile(BytesIO(original)) as source,ZipFile(out,'w',ZIP_DEFLATED) as target:
            for entry in source.namelist():target.writestr(entry,source.read(entry))
            target.writestr(name,value)
        with pytest.raises(HTTPException):e.validate(out.getvalue(),'destruction_request',MAXIMUM)


def test_bilingual_direction_and_changa_required():
    for content,code in [(revised(old='اسم الجهة الطالبة',new='English only heading'),'disposition_template_bilingual_required'),
                         (revised(old='w:bidi w:val="1"',new='w:bidi w:val="0"'),'disposition_template_direction_invalid'),
                         (revised(old='Changa',new='Arial'),'disposition_template_changa_required')]:
        with pytest.raises(HTTPException) as error:e.validate(content,'destruction_request',MAXIMUM)
        assert error.value.detail['code']==code


@pytest.mark.parametrize('kind',CONTRACTS)
def test_real_word_renderer_embeds_changa_and_outputs_actual_snapshot_pdf(kind):
    pdf,metadata=e.render(d.default(kind)['content'],kind,sample(kind),{'MAX_RENDITION_SIZE_BYTES':MAXIMUM,'DOCUMENT_CONVERSION_TIMEOUT_SECONDS':60})
    reader=PdfReader(BytesIO(pdf));text='\n'.join(p.extract_text() for p in reader.pages)
    assert 'DEST-2026-001' in text and '{{' not in text
    assert metadata['pages']==e.verify_pdf(pdf) and 'filled_docx_sha256' in metadata


@pytest.mark.parametrize('kind',CONTRACTS)
def test_organization_wide_revisions_history_old_download_and_exact_retry(kind):
    with db() as c:
        job=setup(c);original=d.current(c,kind);settings=load_snapshot(c);key=uuid4();content=revised(kind,CONTRACTS[kind].english,'Updated '+CONTRACTS[kind].english)
        args=dict(job_id=job['id'],kind=kind,expected_reference=original['reference'],command_id=key,acting_role_id=officer(c),reason='Organization-wide template revision',content=content,filename='Updated.docx',settings=settings)
        first=d.revise(c,**args);assert d.revise(c,**args)==first
        other=setup(c);assert d.current(c,kind)['reference']==first['reference']
        assert d.download(c,other['id'],kind,original['reference'])['content']==original['content']
        assert d.download(c,other['id'],kind,first['reference'])['content']==content
        second=revise(c,other,kind);page=d.history(c,job['id'],kind,limit=2,offset=0)
        assert page['total']==3 and [r['revision_number'] for r in page['items']]==[2,1]
        assert d.history(c,job['id'],kind,limit=2,offset=2)['items'][0]['reference']==original['reference']
        assert d.history(c,job['id'],kind,limit=1,offset=0,descending=False)['items'][0]['revision_number']==0
        assert all('content' not in row for row in page['items'])
        audit=c.execute("SELECT actor_type,metadata FROM event_history WHERE operation='TEMPLATE_REVISED' ORDER BY id DESC LIMIT 1").fetchone()
        assert audit['actor_type']=='user' and audit['metadata']['acting_role_id']==officer(c) and 'content' not in audit['metadata']
        with pytest.raises(HTTPException) as error:d.revise(c,**{**args,'command_id':uuid4()})
        assert error.value.detail['code']=='disposition_template_stale'
        with pytest.raises(psycopg.Error),c.transaction():d.revise(c,**{**args,'content':revised(kind,CONTRACTS[kind].english,'Different '+CONTRACTS[kind].english)})
        for sql in ['UPDATE disposition_template_revisions SET original_filename=\'other.docx\'','DELETE FROM disposition_template_revisions']:
            with pytest.raises(psycopg.Error,match='disposition_template_immutable'),c.transaction():c.execute(sql)


def test_profile_authority_current_assignments_and_sql_guard():
    with db() as c:
        job=setup(c)
        with pytest.raises(HTTPException) as error:revise(c,job,acting_role_id=1)
        assert error.value.status_code==403 # ALL_PRIVS is not an Officer/Manager.
        role=officer(c);c.execute('UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP-interval \'2 days\',valid_until=CURRENT_TIMESTAMP-interval \'1 second\' WHERE role_id=%s',(role,))
        with pytest.raises(HTTPException):d.catalogue(c,job['id'])
        c.execute('UPDATE user_role_assignments SET valid_until=NULL WHERE role_id=%s',(role,))
        row=revise(c,job)
        c.execute('SELECT disposition_private.require_actor(%s)',(role,))
        with pytest.raises(psycopg.Error,match='disposition_protected_operation_required'),c.transaction():
            c.execute('''INSERT INTO disposition_template_revisions(document_type,revision_number,original_filename,content,checksum,uploaded_by_user_id,acting_role_id,uploaded_from_job_id)
              VALUES('destruction_request',2,'x.docx',%s,%s,1,%s,%s)''',(b'x',hashlib.sha256(b'x').hexdigest(),role,job['id']))


def test_generated_artifact_retains_exact_revision_snapshot_retry_and_original_bytes(monkeypatch):
    with db() as c:
        job,_=fixture(c);settings=load_snapshot(c);kind='destruction_request';key=uuid4();snapshot=sample(kind,job['id'])
        original=d.current(c,kind);preview=d.artifacts.destination(c,job['id'],kind)
        args=dict(job_id=job['id'],expected_version=job['version'],kind=kind,snapshot=snapshot,command_id=key,acting_role_id=officer(c),reason='Generate approved snapshot',preview=preview,settings=settings,connection_factory=db)
        first=d.generate(c,**args);before=c.execute('SELECT * FROM disposition_job_documents WHERE id=%s',(first['id'],)).fetchone()
        c.commit();actor(c)
        new_revision=revise(c,job);c.commit();actor(c)
        second=d.generate(c,**{**args,'command_id':uuid4()})
        newer=c.execute('SELECT * FROM disposition_job_documents WHERE id=%s',(second['id'],)).fetchone()
        assert newer['template_version']==new_revision['reference'] and second['id']!=first['id']
        page=d.artifacts.page(c,job['id'],limit=25,offset=0)
        generated=next(row for row in page['items'] if row['id']==second['id'])
        assert generated['template_revision_number']==new_revision['revision_number']
        assert generated['can_download_template'] and generated['template_version']==new_revision['reference']
        content=b''.join(bytes(row['content']) for row in c.execute('''SELECT b.content FROM digital_component_blobs b
          JOIN digital_components dc ON dc.active_content_set_id=b.content_set_id WHERE dc.id=%s ORDER BY b.segment_no''',(second['digital_component_id'],)))
        assert 'Revised' in '\n'.join(p.extract_text() for p in PdfReader(BytesIO(content)).pages)
        c.commit();actor(c)
        monkeypatch.setattr(e,'render',lambda *a,**k:pytest.fail('Committed retry must not render again'))
        assert d.generate(c,**args)==first
        after=c.execute('SELECT * FROM disposition_job_documents WHERE id=%s',(first['id'],)).fetchone();assert after==before
        assert after['template_version']==original['reference'] and after['provenance']['snapshot']==snapshot
        assert after['provenance']['snapshot_checksum']==d.checksum(snapshot)
        assert c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']==2
        changed=deepcopy(snapshot);changed['fields']['job.number']='different'
        with pytest.raises(psycopg.Error),c.transaction():d.generate(c,**{**args,'snapshot':changed})


def test_generation_failure_and_outer_rollback_leave_no_artifacts_or_staging(monkeypatch):
    with db() as c:
        job,_=fixture(c);settings=load_snapshot(c);c.commit();actor(c)
        args=dict(job_id=job['id'],expected_version=job['version'],kind='destruction_request',snapshot=sample('destruction_request',job['id']),
          command_id=uuid4(),acting_role_id=officer(c),reason='Generation failure acceptance',preview=d.artifacts.destination(c,job['id'],'destruction_request'),settings=settings,connection_factory=db)
        with pytest.raises(RuntimeError),c.transaction():
            d.generate(c,**args);raise RuntimeError('Later action failure rolls back the artifact too')
        assert c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM record_drafts WHERE owner_user_id IS NULL').fetchone()['n']==0
        monkeypatch.setattr(e,'render',lambda *a: e.invalid('disposition_document_render_failed',409))
        with pytest.raises(HTTPException):d.generate(c,**args)
        assert c.execute('SELECT count(*) n FROM disposition_private.command_receipts WHERE command_id=%s',(args['command_id'],)).fetchone()['n']==0


def test_request_grouping_local_values_and_physical_nested_totals_are_not_double_counted():
    aggs=[dict(id=i,parent_aggregation_id=p,root_id=r,classification_id=1,classification_code='A',classification_title='تصنيف',aggregation_number=str(i),title='ملف',medium=m,owner='Unit',assigned_location=None,current_location=None) for i,p,r,m in [(1,None,1,'digital'),(2,1,1,'physical'),(3,2,1,'mixed'),(4,None,4,'physical'),(5,None,5,'mixed')]]
    records=[dict(id=1,aggregation_id=3,medium='physical'),dict(id=2,aggregation_id=2,medium='mixed')]
    rule=dict(rule_source='classification',current_period_years=5,intermediate_period_years=0,final_disposition='destruction')
    source=dict(aggregations=aggs,records=records,roots=[dict(id=1,rule_snapshot=rule),dict(id=4,rule_snapshot=dict(rule,rule_source='aggregation')),dict(id=5,rule_snapshot=dict(rule,rule_source='aggregation',current_period_years=2))])
    groups=snapshots.request_groups(source);assert len(groups)==3 and sum(g['group.roots'] for g in groups)==3
    assert any('Local retention override' in g['group.rule_source'] for g in groups)
    rows,totals,classes=snapshots.physical_rows(source)
    assert len(rows)==4 # digital parent must not hide physical descendants
    assert rows[0]['aggregation.descendants.mixed_aggregations']==1
    assert rows[0]['aggregation.descendants.physical_aggregations']==0
    assert totals==dict(physical_aggregations=2,mixed_aggregations=2,physical_records=1,mixed_records=1)
    assert rows[0]['aggregation.assigned_location']==snapshots.NOT_SPECIFIED and 'Physical records: 1' in classes


def test_actual_database_membership_snapshot_uses_inherited_locations_and_stable_counts():
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root]);
        source=snapshots.capture(c,job['id']);assert len(source['roots'])==1 and len(source['aggregations'])==3
        snapshot=snapshots.request_snapshot(c,job['id'],authority_name='Authority / الجهة المختصة',review_summaries=dict(file_administrator='Reviewed',unit_manager='Reviewed',records_manager='Approved'),review_round=1,form_version=1,generated_at='2026-10-15T10:00:00Z')
        e.snapshot_values('destruction_request',snapshot)
        assert snapshot['fields']['counts.roots']==1 and snapshot['fields']['counts.descendant_aggregations']==2
        assert snapshot['source']==source


@pytest.mark.parametrize('shared',[False,True])
def test_template_http_upload_validation_reason_retry_download_and_page_bounds(client,shared):
    with db() as c:
        job=setup(c);role=officer(c);original=d.default('destruction_request')
    base="/api/v1/disposition/templates" if shared else f"/api/v1/disposition/jobs/{job['id']}/templates"
    catalogue=client.get(base).json();assert len(catalogue['items'])==4 and 'content' not in catalogue['items'][0]
    url=base+'/destruction_request/revisions';data={'command_id':str(uuid4()),'acting_role_id':str(role),'expected_reference':original['reference']}
    content=revised();files={'file':('Updated.docx',content,e.MIME)}
    assert client.post(url,data=data,files=files).status_code==422
    headers={'X-Change-Reason':'Correct the bilingual template layout'}
    bad=client.post(url,data=data,files={'file':('bad.docx',b'bad',e.MIME)},headers=headers)
    assert bad.status_code==422 and bad.json()['detail']['code']=='disposition_template_invalid'
    created=client.post(url,data=data,files=files,headers=headers);assert created.status_code==201,created.text
    assert client.post(url,data=data,files=files,headers=headers).json()==created.json()
    result=client.get(base+'/destruction_request/content',params={'reference':created.json()['reference']})
    assert result.status_code==200 and result.content==content and result.headers['content-type']==e.MIME
    assert result.headers['cache-control']=='private, no-store'
    assert client.get(base+'/destruction_request/content',params={'reference':original['reference']}).content==original['content']
    assert client.get(url,params={'limit':51}).status_code==422
    assert client.get(url,params={'limit':1,'offset':1}).json()['items'][0]['revision_number']==0
    assert client.post(url,data={**data,'command_id':str(uuid4()),'acting_role_id':'1'},files=files,headers=headers).status_code==403
    assert client.post(f"/api/v1/disposition/jobs/{job['id']}/generate",json={}).status_code in (404,405)


@pytest.mark.parametrize('name',['File Administrator','Unit Manager'])
def test_review_roles_cannot_upload_even_if_person_also_has_an_officer_role(name):
    with db() as c:
        job=setup(c)
        existing=c.execute('SELECT id FROM profiles WHERE name=%s',(name,)).fetchone()
        profile=existing['id'] if existing else c.execute('INSERT INTO profiles(code,name) VALUES(%s,%s) RETURNING id',(uuid4().hex,name)).fetchone()['id']
        role=c.execute('INSERT INTO roles(org_unit_id,code,name,profile_id) VALUES(1,%s,%s,%s) RETURNING id',(uuid4().hex,name,profile)).fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(1,%s)',(role,))
        with pytest.raises(HTTPException) as error:revise(c,job,acting_role_id=role)
        assert error.value.status_code==403
        assert d.current(c,'destruction_request')['revision_number']==0


def test_different_current_manager_can_revise_with_their_own_attribution():
    with db() as c:
        job=setup(c)
        person=c.execute("INSERT INTO users(name,email) VALUES('Another Manager','manager-phase12@example.invalid') RETURNING id").fetchone()['id']
        role=c.execute("INSERT INTO roles(org_unit_id,code,name,is_information_governance,profile_id) SELECT 1,'phase12-manager','Records Manager',true,id FROM profiles WHERE code='INFO_GOV_MGR' RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(person,role));actor(c,person)
        result=revise(c,job,acting_role_id=role)
        saved=c.execute('SELECT * FROM disposition_template_revisions WHERE id=%s',(result['id'],)).fetchone()
        assert (saved['uploaded_by_user_id'],saved['acting_role_id'],saved['actor_type'])==(person,role,'user')


def test_direction_uses_standard_word_style_inheritance_and_rejects_ltr_arabic_tables():
    content=d.default('destruction_request')['content'];out=BytesIO()
    with ZipFile(BytesIO(content)) as archive,ZipFile(out,'w',ZIP_DEFLATED) as target:
        for name in archive.namelist():
            value=archive.read(name)
            if name=='word/document.xml':
                tree=etree.fromstring(value)
                for p in tree.findall('.//w:p',e.NS):
                    bidi=p.find('w:pPr/w:bidi',e.NS)
                    if bidi is not None and bidi.get(e.W+'val')=='1':
                        pr=p.find('w:pPr',e.NS);pr.remove(bidi);style=etree.Element(e.W+'pStyle');style.set(e.W+'val','ArabicTest');pr.insert(0,style)
                value=etree.tostring(tree)
            if name=='word/styles.xml':
                tree=etree.fromstring(value);style=etree.SubElement(tree,e.W+'style',{e.W+'type':'paragraph',e.W+'styleId':'ArabicTest'})
                etree.SubElement(style,e.W+'name',{e.W+'val':'Arabic test'});etree.SubElement(style,e.W+'basedOn',{e.W+'val':'Normal'})
                prop=etree.SubElement(style,e.W+'pPr');etree.SubElement(prop,e.W+'bidi',{e.W+'val':'1'});value=etree.tostring(tree)
            target.writestr(name,value)
    e.validate(out.getvalue(),'destruction_request',MAXIMUM)
    with pytest.raises(HTTPException) as error:e.validate(revised(old='w:bidiVisual w:val="1"',new='w:bidiVisual w:val="0"'),'destruction_request',MAXIMUM)
    assert error.value.detail['code']=='disposition_template_direction_invalid'
    filled=e.fill(out.getvalue(),'destruction_request',sample('destruction_request'),MAXIMUM)
    assert filled==e.fill(out.getvalue(),'destruction_request',sample('destruction_request'),MAXIMUM)
    with ZipFile(BytesIO(filled)) as archive:assert all(i.date_time==(1980,1,1,0,0,0) for i in archive.infolist())


def test_generated_pdf_rejects_missing_embedding_and_font_substitution():
    from tools.preview_disposition import preview_pdf
    with pytest.raises(HTTPException) as error:e.verify_pdf(preview_pdf())
    assert error.value.detail['code']=='disposition_template_changa_required'


def test_concurrent_uploads_have_one_current_winner_and_no_lost_revision():
    with db() as c:
        job=setup(c);role=officer(c);settings=load_snapshot(c);reference=d.current(c,'destruction_request')['reference']
    def attempt(index):
        try:
            with db() as c:
                actor(c)
                return d.revise(c,job_id=job['id'],kind='destruction_request',expected_reference=reference,command_id=uuid4(),acting_role_id=role,
                  reason='Concurrent template revision',content=revised(new='Concurrent revision '+str(index)),filename='concurrent.docx',settings=settings)
        except HTTPException as error:return error.detail['code']
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,[1,2]))
    assert sum(isinstance(r,dict) for r in results)==1 and 'disposition_template_stale' in results
    with db() as c:
        actor(c);assert d.current(c,'destruction_request')['revision_number']==1
        assert c.execute('SELECT count(*) n FROM disposition_template_revisions').fetchone()['n']==1


def test_concurrent_same_generation_key_creates_one_pdf_record():
    with db() as c:
        job,_=fixture(c);settings=load_snapshot(c);role=officer(c);key=uuid4();preview=d.artifacts.destination(c,job['id'],'destruction_request')
    def attempt(_):
        with db() as c:
            actor(c)
            return d.generate(c,job_id=job['id'],expected_version=job['version'],kind='destruction_request',snapshot=sample('destruction_request',job['id']),
              command_id=key,acting_role_id=role,reason='Concurrent deterministic generation',preview=preview,settings=settings,connection_factory=db)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,[1,2]))
    assert results[0]==results[1]
    with db() as c:
        assert c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM record_drafts WHERE owner_user_id IS NULL').fetchone()['n']==0


def test_global_management_upload_retry_history_and_legacy_revision_preserved():
    with db() as c:
        job=setup(c);legacy_content=revised();legacy=revise(c,job,content=legacy_content);original=d.default('destruction_request')
        args=dict(job_id=None,kind='destruction_request',expected_reference=legacy['reference'],command_id=uuid4(),
          acting_role_id=officer(c),reason='Update shared template',content=revised(new='Shared request'),filename='Shared.docx',settings=load_snapshot(c))
        result=d.revise(c,**args)
        assert d.revise(c,**args)==result
        assert c.execute('SELECT uploaded_from_job_id FROM disposition_template_revisions WHERE id=%s',(result['id'],)).fetchone()['uploaded_from_job_id'] is None
        assert d.current(c,'destruction_request')['reference']==result['reference']
        assert d.history(c,None,'destruction_request',limit=25,offset=0)['total']==3
        assert d.download(c,None,'destruction_request',legacy['reference'])['content']==legacy_content
        assert d.download(c,None,'destruction_request',original['reference'])['content']==original['content']
        assert c.execute('SELECT uploaded_from_job_id FROM disposition_template_revisions WHERE id=%s',(legacy['id'],)).fetchone()['uploaded_from_job_id']==job['id']
        event=c.execute("SELECT * FROM event_history WHERE operation='TEMPLATE_REVISED' ORDER BY id DESC LIMIT 1").fetchone()
        assert event['entity_type']=='disposition_template_revision' and event['entity_id']==result['id']
        assert len(d.catalogue(c,None)['items'])==4
        with pytest.raises(HTTPException):d.revise(c,**{**args,'command_id':uuid4(),'acting_role_id':1})


def test_shared_templates_available_before_any_job_exists():
    from backend.services.api.tests.test_disposition_foundation import ensure_officer
    with db() as c:
        actor(c);ensure_officer(c)
        assert not c.execute('SELECT 1 FROM disposition_jobs').fetchone()
        assert len(d.catalogue(c,None)['items'])==4


def test_shared_template_role_and_history_names_use_arabic():
    with db() as c:
        job=setup(c);role=officer(c)
        c.execute('UPDATE users SET translations=%s WHERE id=1',(Jsonb({'ar':{'name':'المراجع'}}),))
        c.execute('UPDATE roles SET translations=%s WHERE id=%s',(Jsonb({'ar':{'name':'مسؤول الوثائق'}}),role))
        revise(c,job)
        assert next(row for row in d.catalogue(c,None,language_tag='ar')['roles'] if row['id']==role)['name']=='مسؤول الوثائق'
        row=d.history(c,None,'destruction_request',limit=25,offset=0,language_tag='ar')['items'][0]
        assert row['uploader']=='المراجع' and row['acting_role']=='مسؤول الوثائق'


def test_request_v2_layout_omits_internal_fields_and_starts_aggregation_section_on_new_page():
    content=d.default('destruction_request')['content']
    values=e.parts(content,MAXIMUM);tree=etree.fromstring(values['word/document.xml'])
    text=e.paragraph_text(tree)
    for key in ('job.id','job.type','job.created_at','counts.descendant_aggregations','review.round','membership.checksum'):
        assert '{{'+key+'}}' not in text
    for key in ('organization.name','organization.email','organization.phone','records.from_year','records.to_year','aggregation.serial_number','aggregation.number','aggregation.assigned_location'):
        assert '{{'+key+'}}' in text
    assert 'Governing root aggregations' not in text
    assert 'الملفات المطلوب إتلافها' in text
    assert 'Aggregations requested for destruction' in text
    table=tree.xpath('//w:tbl',namespaces=e.NS)[-1]
    assert '{{aggregation.serial_number}}' in e.paragraph_text(table.xpath('./w:tr',namespaces=e.NS)[1][0])
    assert len(tree.xpath('//w:sectPr',namespaces=e.NS))==2
    assert d.default('destruction_request')['reference'].startswith('default.v2:')
    assert (d.DEFAULTS/'request-for-destruction.default.v1.docx').exists()


def test_execution_report_has_separate_required_root_and_proposal_groups():
    content=d.default('proposal_execution_report')['content']
    snapshot=sample('proposal_execution_report',rows=1)
    snapshot['aggregations']*=2
    snapshot['aggregations'][0]=dict(snapshot['aggregations'][0],**{'aggregation.number':'ROOT-FIRST'})
    snapshot['aggregations'][1]=dict(snapshot['aggregations'][1],**{'aggregation.number':'ROOT-LAST'})
    snapshot['proposals'][0]['proposal.change']='RELATIONSHIP-REMOVED'
    xml=e.parts(e.fill(content,'proposal_execution_report',snapshot,MAXIMUM),MAXIMUM)['word/document.xml'].decode()
    assert xml.count('ROOT-FIRST')==1 and xml.count('ROOT-LAST')==1
    assert xml.count('RELATIONSHIP-REMOVED')==1
    assert 'organization.name' not in xml and '{{' not in xml
    with pytest.raises(HTTPException):
        e.fill(content,'proposal_execution_report',{k:v for k,v in snapshot.items() if k!='aggregations'},MAXIMUM)
    with pytest.raises(HTTPException):
        e.validate(revised('proposal_execution_report','{{#aggregations}}',''),'proposal_execution_report',MAXIMUM)


def test_execution_report_v1_package_remains_available():
    assert d.default('proposal_execution_report','v1')['reference'].startswith('default.v1:')


def test_execution_report_both_groups_paginate_and_keep_their_last_rows(client):
    snapshot=sample('proposal_execution_report',rows=0)
    base=sample('proposal_execution_report',rows=1)
    for group,key,prefix in [('aggregations','aggregation.number','REPORT-ROOT'),('proposals','proposal.change','REPORT-CHANGE')]:
        snapshot[group]=[dict(base[group][0],**{key:f'{prefix}-{i:03}'}) for i in range(1,41)]
    snapshot['fields']['execution.count']=40
    with db() as c:settings=load_snapshot(c)
    pdf,_=e.render(d.default('proposal_execution_report')['content'],'proposal_execution_report',snapshot,settings)
    reader=PdfReader(BytesIO(pdf));text='\n'.join(page.extract_text() for page in reader.pages)
    assert len(reader.pages)>3
    assert 'REPORT-ROOT-040' in text and 'REPORT-CHANGE-040' in text
    assert '{{' not in text


def test_all_generated_record_title_types_use_generating_user_preference():
    from backend.services.api.disposition import artifacts
    with db() as c:
        actor(c)
        for language in ('en','ar'):
            c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,%s,'Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag=EXCLUDED.language_tag",(language,))
            for kind,contract in CONTRACTS.items():
                result=artifacts.generated_record_title(c,{'job_number':'DT-2026-1'},kind)
                expected='إستمارة إتلاف DT-2026-1' if kind=='destruction_request' and language=='ar' else (contract.arabic if language=='ar' else contract.english)+' — DT-2026-1'
                assert result=={'record_title':expected,'record_title_language':language}


@pytest.mark.parametrize('language',['en','ar'])
def test_generated_record_title_is_readable_and_saved_retries_keep_original_title(language,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(e,'render',lambda *a,**kw:(preview_pdf(),{}))
    with db() as c:
        job,_=fixture(c);kind='destruction_request'
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,%s,'Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag=EXCLUDED.language_tag",(language,))
        args=dict(job_id=job['id'],expected_version=job['version'],kind=kind,snapshot=sample(kind,job['id']),command_id=uuid4(),acting_role_id=officer(c),reason='Generate readable record title',preview=d.artifacts.destination(c,job['id'],kind),settings=load_snapshot(c),connection_factory=db)
        first=d.generate(c,**args)
        record=c.execute('SELECT title FROM records WHERE id=%s',(first['record_id'],)).fetchone()
        expected=('إستمارة إتلاف '+job['job_number']) if language=='ar' else CONTRACTS[kind].english+' — '+job['job_number']
        assert record['title']==expected
        provenance=c.execute('SELECT provenance FROM disposition_job_documents WHERE id=%s',(first['id'],)).fetchone()['provenance']
        assert provenance['record_title']==expected and provenance['record_title_language']==language
        component=c.execute('SELECT file_name FROM digital_components WHERE id=%s',(first['digital_component_id'],)).fetchone()
        assert component['file_name']==f'{kind}-{job["id"]}.pdf'
        c.commit();actor(c)
        c.execute("UPDATE user_preferences SET language_tag=%s WHERE user_id=1",('en' if language=='ar' else 'ar',))
        monkeypatch.setattr(e,'render',lambda *a,**kw:pytest.fail('Saved retry must reuse original bytes/title'))
        assert d.generate(c,**args)==first
        assert c.execute('SELECT title FROM records WHERE id=%s',(first['record_id'],)).fetchone()==record


@pytest.mark.parametrize('kind',['destruction_request','proposal_execution_report'])
def test_repeated_serial_cells_start_with_number_without_control_paragraph_gap(kind):
    snapshot=sample(kind)
    for group in group_fields(CONTRACTS[kind]):
        for row in snapshot[group]:
            for key in row:
                if key.endswith('.serial_number'):row[key]=1
    xml=e.parts(e.fill(d.default(kind)['content'],kind,snapshot,MAXIMUM),MAXIMUM)['word/document.xml']
    tree=etree.fromstring(xml)
    serial_cells=[]
    for table in tree.xpath('//w:tbl',namespaces=e.NS):
        rows=table.findall('w:tr',e.NS)
        if rows and 'No.' in e.paragraph_text(rows[0].findall('w:tc',e.NS)[0]):serial_cells.append(rows[1].findall('w:tc',e.NS)[0])
    assert len(serial_cells)==len(group_fields(CONTRACTS[kind]))
    for cell in serial_cells:
        paragraphs=cell.findall('w:p',e.NS)
        assert e.paragraph_text(paragraphs[0])=='1'
        assert cell.find('w:tcPr/w:vAlign',e.NS).get(e.W+'val')=='top'
