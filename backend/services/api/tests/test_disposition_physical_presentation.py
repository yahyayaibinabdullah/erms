"""Approved collection-location layout; database tests use the disposable runner."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
from pypdf import PdfReader

import pytest
from lxml import etree

from backend.services.api.disposition import document_snapshots as s,documents,template_engine as e,artifacts
from backend.services.api.disposition.template_contract import PHYSICAL_PRESENTATION_FIELDS,PHYSICAL_PRESENTATION_ROWS
from backend.services.api.application_settings import load_snapshot
from backend.services.api.tests.test_disposition_membership import db,actor
from backend.services.api.tests.test_disposition_physical import approved,report
from backend.services.api.tests.test_disposition_templates import sample,MAXIMUM
from backend.services.api.tests.test_disposition_communications import settings
from tools.preview_disposition import preview_pdf


def collection_source():
    aggs=[]
    for i,parent,medium,current,assigned,owner in [
        (1,None,'digital','Store A','Store A','Records Unit'),
        (2,1,'physical','Store A','Store A','Records Unit'),
        (3,2,'mixed','Store A','Store B','Records Unit'),
        (4,None,'physical','Store B',None,'Records Unit'),
        (5,None,'physical',None,'Store C','Other Unit'),
        (6,None,'physical',None,None,'Records Unit'),
    ]:
        aggs.append(dict(id=i,parent_aggregation_id=parent,medium=medium,current_location=current,
          assigned_location=assigned,owner=owner,aggregation_number=f'A/{i:03}',title=f'Collection {i}',
          classification_id=1,classification_code='1141',classification_title='Meetings'))
    return {'roots':[],'aggregations':aggs,'records':[
      dict(id=1,aggregation_id=3,medium='physical'),dict(id=2,aggregation_id=2,medium='mixed'),
      dict(id=3,aggregation_id=3,medium='digital'),dict(id=4,aggregation_id=4,medium='physical',physical_remaining=False)]}


def test_collection_order_locations_owner_and_unique_totals():
    source=collection_source();before=deepcopy(source)
    rows,totals,_,owner=s.collection_rows(source,'en')
    assert source==before and owner is None
    assert [r['aggregation.identifier'] for r in rows]==['A/002','A/003','A/004','A/005','A/006']
    assert [r['aggregation.serial_number'] for r in rows]==[1,2,3,4,5]
    assert rows[0]['aggregation.assigned_note']=='—'
    assert rows[1]['aggregation.assigned_note']=='Assigned location: Store B'
    assert rows[3]['aggregation.collection_group']=='Locations to verify'
    assert rows[3]['aggregation.current_location']=='Current location not recorded'
    assert rows[3]['aggregation.assigned_note']=='Assigned location: Store C'
    assert rows[4]['aggregation.assigned_note']=='—'
    assert rows[3]['aggregation.owner_note']=='Owning organizational unit: Other Unit'
    # Nested descendants remain listed; totals count actual items, not overlapping subtrees.
    assert totals==dict(physical_aggregations=4,mixed_aggregations=1,physical_records=1,mixed_records=1)


def test_common_owner_localization_and_completed_physical_items():
    source=collection_source();source['aggregations'][4]['physical_remaining']=False
    localized={a['id']:{'owner':'وحدة الوثائق'} for a in source['aggregations']}
    rows,totals,_,owner=s.collection_rows(source,'ar',localized)
    assert owner=='وحدة الوثائق' and all(r['aggregation.owner_note']=='—' for r in rows)
    assert rows[0]['aggregation.title']=='Collection 2' and rows[0]['aggregation.medium']=='مادي'
    assert rows[1]['aggregation.medium']=='هجين'
    assert rows[-1]['aggregation.collection_group']=='مواقع تحتاج إلى التحقق'
    assert totals['physical_aggregations']==3


def test_different_owning_units_with_identical_names_are_not_collapsed():
    source=collection_source()
    metadata={a['id']:{'owner_id':1 if a['id']<5 else 2,'owner':'Records Unit'} for a in source['aggregations']}
    rows,_,_,owner=s.collection_rows(source,'en',metadata)
    assert owner is None and all(r['aggregation.owner_note']=='Owning organizational unit: Records Unit' for r in rows)


def test_v2_group_headers_repeat_columns_and_top_align_data_preserving_v1():
    snapshot=sample('physical_preparation_report')
    rows,_,_,_=s.collection_rows(collection_source(),'en')
    snapshot['aggregations']=rows
    filled=e.fill(documents.default('physical_preparation_report')['content'],'physical_preparation_report',snapshot,MAXIMUM)
    with ZipFile(BytesIO(filled)) as archive:tree=etree.fromstring(archive.read('word/document.xml'))
    # Location headings span all three columns, appear once, and stay with their first row.
    heads=tree.xpath('//w:tc[w:tcPr/w:gridSpan]',namespaces=e.NS)
    assert [e.paragraph_text(h) for h in heads]==['Store A','Store B','Locations to verify']
    assert all(h.find('w:p/w:pPr/w:keepNext',e.NS) is not None for h in heads)
    assert len(tree.xpath('//w:tr[w:trPr/w:tblHeader]',namespaces=e.NS))==1
    assert len(tree.xpath('//w:tc[w:tcPr/w:vAlign[@w:val="top"]]',namespaces=e.NS))==15
    text=e.paragraph_text(tree)
    assert 'Membership checksum' not in text and 'Descendant' not in text and '{{' not in text
    assert 'Assigned location: Store B' in text and '—' not in text
    legacy=sample('physical_preparation_report')
    for key in PHYSICAL_PRESENTATION_FIELDS:legacy['fields'].pop(key)
    for row in legacy['aggregations']:
        for key in PHYSICAL_PRESENTATION_ROWS:row.pop(key)
    retained=documents.default('physical_preparation_report','v1')
    assert retained['reference'].startswith('default.v1:')
    e.fill(retained['content'],'physical_preparation_report',legacy,MAXIMUM)
    assert documents.default('physical_preparation_report')['reference'].startswith('default.v2:')


@pytest.mark.parametrize('language,direction',[('en','0'),('ar','1'),('bilingual','1')])
def test_table_order_follows_report_language(language,direction):
    snapshot=sample('physical_preparation_report');snapshot['fields']['report.language']=language
    content=e.fill(documents.default('physical_preparation_report')['content'],'physical_preparation_report',snapshot,MAXIMUM)
    with ZipFile(BytesIO(content)) as archive:tree=etree.fromstring(archive.read('word/document.xml'))
    assert all(n.get(e.W+'val')==direction for n in tree.findall('.//w:tbl/w:tblPr/w:bidiVisual',e.NS))


def test_real_multipage_pdf_repeats_headers_and_preserves_every_aggregation_once():
    snapshot=sample('physical_preparation_report')
    rows,_,_,_=s.collection_rows(collection_source())
    rows=[dict(row) for row in rows*4]
    rows.sort(key=lambda row:row['aggregation.collection_group'])
    for i,row in enumerate(rows,1):
        row.update({'aggregation.serial_number':i,'aggregation.identifier':f'FILE-{i:03}',
          'aggregation.title':'ملفات اجتماعات متابعة المشاريع والبرامج والخدمات / Follow-up meetings for projects programmes and services'})
    snapshot['aggregations']=rows;snapshot['fields']['report.language']='bilingual'
    pdf,metadata=e.render(documents.default('physical_preparation_report')['content'],
      'physical_preparation_report',snapshot,{'MAX_RENDITION_SIZE_BYTES':MAXIMUM,'DOCUMENT_CONVERSION_TIMEOUT_SECONDS':60})
    reader=PdfReader(BytesIO(pdf));assert metadata['pages']==len(reader.pages)>1
    texts=[p.extract_text() for p in reader.pages];text='\n'.join(texts)
    assert all('Current location' in t and 'Aggregation' in t and 'DEST-2026-001' in t for t in texts)
    assert all(text.count(f'FILE-{i:03}')==1 for i in range(1,21))
    assert e.verify_pdf(pdf)==len(reader.pages)


@pytest.mark.parametrize('mode,language,expected',[
    ('arabic_first_bilingual','en','الجهة / Organization'),
    ('manager_preference','ar','الجهة'),('manager_preference','en','Organization')])
def test_actual_report_settings_inherited_locations_and_frozen_retry(monkeypatch,mode,language,expected):
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{'renderer':'test'}))
    with db() as c:
        job,root,mgr,_=approved(c)
        c.execute("UPDATE org_units SET name='Organization',translations='{\"ar\":{\"name\":\"الجهة\"}}' WHERE id=1")
        c.execute("SELECT set_config('app.location_change_authorized','authorized',true),set_config('app.change_reason','Disposable collection-location fixture',true)")
        c.execute("UPDATE aggregations SET current_location='Store A',assigned_location='Store B' WHERE id=%s",(root,))
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,%s,'Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag=EXCLUDED.language_tag",(language,))
        settings(c,{'DISPOSITION_REQUEST_LANGUAGE':mode,'DISPOSITION_ORGANIZATION_NAME':None,'DEFAULT_WORKING_TIMEZONE':'Asia/Dubai'})
        snap=s.preparation_snapshot(c,job['id'],report_version=1,generated_at='2026-11-02T05:00:00+00:00',settings=load_snapshot(c))
        assert snap['fields']['organization.name']==expected
        assert snap['fields']['report.generated_at']=='2026-11-02 09:00 +04'
        assert snap['aggregations'] and all(r['aggregation.current_location']=='Store A' for r in snap['aggregations'])
        assert all('Store B' in r['aggregation.assigned_note'] for r in snap['aggregations'])
        from uuid import uuid4
        key=uuid4();saved=report(c,job,mgr,key)
        before=artifacts.document(c,job['id'],saved['id'])
        assert before['template_version'].startswith('default.v2:')
        settings(c,{'DISPOSITION_ORGANIZATION_NAME':'Future organization'})
        c.execute("SELECT set_config('app.location_change_authorized','authorized',true),set_config('app.change_reason','Disposable location revision',true)")
        c.execute("UPDATE aggregations SET current_location='Changed later' WHERE id=%s",(root,))
        c.commit();actor(c)
        assert report(c,job,mgr,key)==saved
        assert artifacts.document(c,job['id'],saved['id'])==before
        assert s.preparation_snapshot(c,job['id'],report_version=2,generated_at='2026-11-02T05:00:00+00:00')['fields']['organization.name']=='Future organization'
