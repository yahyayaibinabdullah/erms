"""Request v2 presentation, ancestry, date coverage and immutable inputs."""
from pathlib import Path
import pytest
from backend.services.api.disposition import document_snapshots as snapshots,documents
from backend.services.api.application_settings import load_snapshot,apply_changes
from backend.services.api.application_settings_routes import SettingChange
from backend.services.api.tests.test_disposition_membership import db,actor,setup,ready,admit
from backend.services.api.tests.test_disposition_communications import settings
from backend.services.api.tests.test_disposition_external import prepared,generate
from tools.preview_disposition import preview_pdf


def test_only_root_rows_include_descendant_record_years_and_counts(client):
    with db() as c:
        from uuid import uuid4
        from backend.services.api.disposition.eligibility import worker_actor,evaluate_root
        job=setup(c);root,child,leaf,record=ready(c,closed=None)
        c.execute("UPDATE aggregations SET assigned_location='Main store',medium='mixed' WHERE id=%s",(root,))
        c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title) VALUES(%s,%s,'Empty')",(root,str(uuid4())))
        c.execute("UPDATE records SET date_originated='1999-12-31T22:30:00Z' WHERE id=%s",(record,))
        c.execute("INSERT INTO records(aggregation_id,record_number,title,date_originated) VALUES(%s,%s,'Later','2008-01-01')",(root,str(uuid4())))
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
        digital=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened,medium) VALUES(%s,'Empty digital',1,1,'1900-01-01','digital') RETURNING id",(str(uuid4()),)).fetchone()['id']
        c.execute("INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,justification) VALUES(%s,5,0,'destruction','Specific test policy')",(digital,))
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(digital,))
        worker_actor(c);evaluate_root(c,root);evaluate_root(c,digital);actor(c);admit(c,job['id'],[root,digital])
        years=snapshots.request_years(c,job['id'],'Asia/Dubai')
        assert years=={'records.from_year':2000,'records.to_year':2008}
        assert snapshots.request_years(c,job['id'],'UTC')['records.from_year']==1999
        rows=snapshots.request_aggregation_rows(c,job['id'],'Asia/Dubai')
        assert len(rows)==2
        assert [r['aggregation.serial_number'] for r in rows]==[1,2]
        root_number=c.execute('SELECT aggregation_number FROM aggregations WHERE id=%s',(root,)).fetchone()['aggregation_number']
        root_row=next(r for r in rows if r['aggregation.number']==root_number)
        assert root_row['aggregation.records']==2 and root_row['aggregation.from_year']==2000
        assert root_row['aggregation.assigned_location']=='Main store'
        assert any(r['aggregation.assigned_location']=='لا ينطبق / Not applicable' for r in rows)
        empty=next(r for r in rows if r['aggregation.records']==0)
        assert empty['aggregation.from_year']==snapshots.NOT_SPECIFIED
        # All rows use the inherited root classification number, never raw IDs.
        assert all(r['aggregation.classification_code'] for r in rows)


@pytest.mark.parametrize('mode,language,expected',[('arabic_first_bilingual','en','الجهة / Organization'),('manager_preference','ar','الجهة'),('manager_preference','en','Organization')])
def test_request_settings_language_and_organization_override(client,monkeypatch,mode,language,expected):
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,round_id=prepared(c)
        c.execute("UPDATE org_units SET name='Organization',translations='{\"ar\":{\"name\":\"الجهة\"}}' WHERE id=1")
        # These are presentation fields: approval identity is untouched.
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,%s,'Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag=EXCLUDED.language_tag",(language,))
        settings(c,{'DISPOSITION_REQUEST_LANGUAGE':mode,'DISPOSITION_RECORDS_UNIT_EMAIL':'records@example.test','DISPOSITION_RECORDS_UNIT_PHONE':'+971 6 000 0000'})
        snap=load_snapshot(c)
        assert snapshots.request_organization(c,job['id'],snap,snapshots.request_language(c,snap,round_id))['organization.name']==expected
        settings(c,{'DISPOSITION_ORGANIZATION_NAME':'اسم مخصص / Custom organization'})
        data=snapshots.request_organization(c,job['id'],load_snapshot(c),snapshots.request_language(c,load_snapshot(c),round_id))
        assert data=={'organization.name':'اسم مخصص / Custom organization','organization.email':'records@example.test','organization.phone':'+971 6 000 0000'}


def test_request_v1_default_remains_downloadable_after_v2(client):
    with db() as c:
        actor(c);job=setup(c)
        old=documents.default('destruction_request','v1')
        assert documents.download(c,job['id'],'destruction_request',old['reference'])['content']==old['content']
        assert documents.current(c,'destruction_request')['reference'].startswith('default.v2:')


def test_request_uses_generating_user_language_and_preserves_saved_presentation(client,monkeypatch):
    from backend.services.api.disposition import artifacts
    from backend.services.api.tests.test_disposition_workflow import person
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,round_id=prepared(c)
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'")
        settings(c,{'DISPOSITION_REQUEST_LANGUAGE':'manager_preference','DISPOSITION_ORGANIZATION_NAME':'جهة الاختبار','DISPOSITION_RECORDS_UNIT_EMAIL':'records@example.test'})
        other=person(c)
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(%s,'en','Asia/Dubai')",(other,))
        actor(c,user=other)
        assert snapshots.request_language(c,load_snapshot(c),round_id)=='en'
        actor(c)
        result=generate(c,job,mgr,round_id)
        before=artifacts.document(c,job['id'],result['request_document_id'])
        value=before['provenance']['snapshot']
        assert value['source']['presentation']['language']=='ar'
        assert value['fields']['organization.name']=='جهة الاختبار'
        assert value['fields']['organization.email']=='records@example.test'
        assert value['fields']['authority.name']=='دار الوثائق في إمارة الشارقة'
        assert len(value['aggregations'])==1
        settings(c,{'DISPOSITION_REQUEST_LANGUAGE':'arabic_first_bilingual','DISPOSITION_ORGANIZATION_NAME':'Changed future organization'})
        c.execute("UPDATE user_preferences SET language_tag='en' WHERE user_id=1")
        c.commit();actor(c)
        assert generate(c,job,mgr,round_id)['request_document_id']==before['id']
        assert artifacts.document(c,job['id'],before['id'])==before


def test_organization_fallback_uses_tenancy_root_and_selected_document_language(client):
    with db() as c:
        actor(c)
        c.execute("UPDATE org_units SET name='Root organization',translations='{\"ar\":{\"name\":\"الجهة الجذرية\"}}' WHERE id=1")
        child=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('HEADER-CHILD','Department',1) RETURNING id").fetchone()['id']
        job=setup(c,owner=child)
        snap=load_snapshot(c)
        for language,expected in [('ar','الجهة الجذرية'),('en','Root organization'),('bilingual','الجهة الجذرية / Root organization')]:
            assert snapshots.request_organization(c,job['id'],snap,language)['organization.name']==expected
        c.execute("UPDATE org_units SET translations='{}' WHERE id=1")
        assert snapshots.request_organization(c,job['id'],snap,'ar')['organization.name']=='Root organization'
