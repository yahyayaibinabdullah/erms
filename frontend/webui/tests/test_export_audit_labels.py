"""An export keeps the readable identity of the generated scheme snapshot."""
from frontend.webui.audit_workspace import event_entity_identity


def test_export_identity_prefers_export_snapshot_to_renamed_current_entity():
    event = dict(entity_type='classification_scheme',entity_id=42,operation='EXPORT',metadata={'scheme':{'id':42,'code':'ORIGINAL','title':'Exported title'}},_current_entity={'code':'RENAMED','title':'Current title'})
    assert event_entity_identity(event)[1] == 'ORIGINAL — Exported title'
    event.pop('_current_entity')
    assert event_entity_identity(event)[1] == 'ORIGINAL — Exported title'
