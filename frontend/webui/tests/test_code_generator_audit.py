"""Readable immutable configuration/counter evidence, including historic names."""
from contextvars import Context

from frontend.webui.audit_workspace import event_entity_identity
from frontend.webui.code_generator_audit import change_rows
from frontend.webui.i18n_catalogue import set_active_messages


def test_counter_history_uses_name_at_event_time_and_keeps_exact_old_new_values():
    def exercise():
        set_active_messages({})
        event=dict(entity_type='code_generator',entity_id=7,operation='NEXT_NUMBER_CHANGED',
            _current_entity={'name':'Current renamed series'},metadata={
                'generator_name':'Historical series','scope_kind':'org_unit','scope_id':19,
                'reset_frequency':'monthly','period_bucket':'2026-11-01',
                'target_snapshot':{'kind':'record','primary_field':'record_number'},
                'before':{'next_number':'10','version':0},
                'after':{'next_number':'9'*300,'version':1}})
        assert event_entity_identity(event)[1]=='Historical series'
        rows=change_rows(event,str)
        assert next(v for v in rows if v['field']=='Next serial number')=={
            'field':'Next serial number','before':'10','after':'9'*300}
        assert any(v['before']==v['after']=='Each owning organization unit · 19' for v in rows)
        assert any(v['before']==v['after']=='2026-11-01' for v in rows)
        assert next(v for v in rows if v['field']=='Version')['before']=='0'
    Context().run(exercise)


def test_rename_history_preserves_both_names_and_captured_target_labels():
    def exercise():
        set_active_messages({})
        event=dict(entity_type='code_generator',entity_id=2,operation='UPDATE',
            before_state={'name':'Original series','type_id':8,'target_snapshot':{'type_name':'Old type name'}},
            after_state={'name':'New series','type_id':9,'target_snapshot':{'type_name':'New type name'}},
            changed_fields=['name','type_id'])
        rows=change_rows(event,str)
        assert rows==[
            {'field':'Name','before':'Original series','after':'New series'},
            {'field':'Type','before':'Old type name · 8','after':'New type name · 9'}]
        assert event_entity_identity(event)[1]=='New series'
    Context().run(exercise)


def test_applicability_audit_labels_and_legacy_target_snapshots():
    def exercise():
        from frontend.webui.code_generator_audit import target
        set_active_messages({})
        rows=change_rows(dict(operation='UPDATE',changed_fields=['applies_to'],
            before_state={'applies_to':'all'},after_state={'applies_to':'untyped'}),str)
        assert rows==[{'field':'Applies to','before':'All items','after':'Untyped items only'}]
        assert target({'primary_field':'record_number'})=='Record number · All items'
        assert target({'primary_field':'record_number','type_id':7,'type_name':'Historical type'})=='Record number · Historical type'
        assert target({'primary_field':'record_number','applies_to':'untyped'})=='Record number · Untyped items only'
    Context().run(exercise)
