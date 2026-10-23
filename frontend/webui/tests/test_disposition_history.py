import json
from pathlib import Path
import pytest
from nicegui import ui
from frontend.webui.disposition import messages,history_presenter
from frontend.webui.disposition.history import event_details
from frontend.webui import event_labels

@pytest.fixture(params=['en','ar'])
def language(request,monkeypatch):
    base=Path(__file__).parents[1]/'i18n'
    rows=json.loads((base/('messages.en.json' if request.param=='en' else 'messages.ar.generated.json')).read_text())
    if isinstance(rows,dict):rows=rows['items']
    values={r['message_key']:r['default_text' if request.param=='en' else 'translated_text'] for r in rows}
    monkeypatch.setattr(messages,'render_message_plain',lambda key,**kw:values[key].format(**kw))
    monkeypatch.setattr(event_labels,'render_message',lambda key,**kw:values[key].format(**kw))
    return request.param


def test_membership_names_not_ids_and_no_empty_comparison(language):
    row={'metadata':{'before':None,'after':{'id':2,'job_id':1,'root_aggregation_id':426,'added_by_user_id':9,'membership_state':'active','removed_at':None}},'display_references':{'job:1':'DT-2026-1','aggregation:426':'1141/DEMO/011/2026 · Meetings','user:9':'Shyma'}}
    result=history_presenter.sections(row,str)
    assert len(result)==1 and result[0][0]=='history_details'
    values=[v for _,v in result[0][1]]
    assert {'DT-2026-1','1141/DEMO/011/2026 · Meetings','Shyma'}<=set(values)
    assert not {'null','426','9','1'}&set(values)


def test_blocker_metadata_and_cleared_values(language):
    sections=history_presenter.sections({'metadata':{'root_id':426,'vital':True,'security':False,'held':True,'relationships':False,'signature':'privatehash'}},str)
    assert len(sections[0][1])==5
    assert 'privatehash' not in str(sections)
    sections=history_presenter.sections({'before_state':{'assigned_user_id':9,'version':1},'after_state':{'assigned_user_id':None,'version':2},'display_references':{'user:9':'Shyma'}},str)
    assert sections==[('before_values',[(messages.text('assignee'),'Shyma')]),('after_values',[(messages.text('assignee'),messages.text('history_not_set'))])]


@pytest.mark.parametrize('admin',[False,True])
def test_technical_details_only_for_auditors_collapsed(language,admin):
    with ui.column() as host:
        event_details({'operation':'DISPOSITION_BLOCKERS_DETECTED','occurred_at':'2026-10-22','actor_name':'Shyma','metadata':{'held':True},'can_view_technical_details':admin},str)
        codes=[e for e in host.descendants() if isinstance(e,ui.code)]
        assert bool(codes)==admin
        expansions=[e for e in host.descendants() if isinstance(e,ui.expansion)]
        assert all(not e.value for e in expansions)
        assert not any(isinstance(e,ui.label) and e.text in (messages.text('before_values'),messages.text('after_values')) for e in host.descendants())
    host.delete()


def test_redacted_and_unknown_references_do_not_leak(language):
    assert history_presenter.sections({'metadata':{'redacted':True,'root_id':426}},str)==[]
    assert history_presenter.facts({'root_id':426},{},str)==[(messages.text('aggregation'),messages.text('history_unavailable'))]


def test_all_field_labels_exist(language):
    for key in set(history_presenter.FIELDS.values())|set(history_presenter.GROUPS.values()):assert messages.text(key)


@pytest.mark.parametrize('data',[
    {'workflow_stage':'unit_manager_review','destination_user_id':9,'task_state':'claimed'},
    {'proposal_type':'blocking_security','proposed_values':{'security_level_id':2},'reason':'Review'},
    {'review_notes':'Review note','author_user_id':9,'review_round':1},
    {'evidence_type':'destruction_request','record_id':44,'evidence_version':2},
    {'state':'sent','recipient':'records@example.test'},
    {'completed_units':3,'total_units':4,'state':'running'},
    {'lifecycle_state':'terminated','termination_reason':'Correction required'},
])
def test_event_families_have_readable_facts(language,data):
    result=history_presenter.sections({'metadata':data},str)
    assert result and result[0][1]
    assert not any(v in ('null','running','sent','blocking_security','unit_manager_review') for _,items in result for _,v in items)


def test_global_audit_keeps_shell_and_uses_shared_fields(language):
    import ast
    from frontend.webui.capabilities import can_navigate
    tree=ast.parse((Path(__file__).parents[1]/'app.py').read_text())
    function=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='show_event_detail')
    env={'__package__':'frontend.webui','Any':object,'ui':ui,'json':json,'event_entity_identity':lambda e:('Disposition Job','DT-2026-1'),
         'event_actor_identity':lambda e:('Shyma',None),'event_label':event_labels.event_label,'format_timestamp':str,
         'can_open_event_entity':lambda e:False,'render_message':messages.render_message_plain,
         'disposition_text':messages.text,'can_navigate':can_navigate,'auth_state':{'principal':{'global_privileges':['audit.view']}},'event_value':str}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'audit-dialog','exec'),env)
    with ui.column() as host:
        env['show_event_detail']({'id':1,'operation':'MEMBERSHIP_ADD','display_presentation':'disposition','occurred_at':'2026-10-22','source':'web_ui','metadata':{'after':{'root_aggregation_id':426}},'display_references':{'aggregation:426':'1141/DEMO/011/2026 · Meetings'}})
        assert any(isinstance(e,ui.label) and e.text=='1141/DEMO/011/2026 · Meetings' for e in host.descendants())
        assert any(isinstance(e,ui.label) and e.text=='DT-2026-1' for e in host.descendants())
        assert not any(isinstance(e,ui.table) for e in host.descendants())
        assert all(not e.value for e in host.descendants() if isinstance(e,ui.expansion))
    host.delete()
