"""Readable generator history from immutable snapshots, without live lookups."""
from .code_generator_messages import t
from .i18n_catalogue import render_message_plain

PRIMARY = {
    'record_number':'entity_metadata.field.record_number',
    'aggregation_number':'entity_metadata.field.aggregation_number',
    'title':'entity_metadata.field.title','description':'entity_metadata.field.description',
    'assigned_location':'entity_metadata.field.assigned_location',
    'current_location':'entity_metadata.field.current_location',
}
APPLIES_TO = {'all':'all_items','untyped':'untyped_only','type':'selected_type'}
SCOPES = {'generator':'scope_generator','parent_aggregation':'scope_parent',
          'classification':'scope_classification','org_unit':'scope_org'}
LABELS = {'id':'audit_entity','applies_to':'applies_to','name':'name_header','kind':'resource','primary_field':'field',
          'type_id':'type','field_id':'field','pattern':'pattern_header','start':'start','increment':'increment',
          'scope':'scope','reset_frequency':'reset','padding_width':'padding','max_code_length':'maximum',
          'enabled':'enabled','target_snapshot':'target','next_number':'next_number'}


def field_label(key):
    if key in LABELS:
        return t(LABELS[key]).removesuffix(' *')
    message = {'updated_by_user_id':'webui.show_event_detail.label.actor_43121a3e',
               'version':'classification_transfer.version',
               'date_created':'classification_transfer.date_created',
               'date_updated':'classification_transfer.date_updated'}.get(key)
    return render_message_plain(message) if message else key


def target(snapshot):
    if not snapshot:
        return '—'
    field = render_message_plain(PRIMARY[snapshot['primary_field']]) if snapshot.get('primary_field') else snapshot.get('field_name')
    mode=snapshot.get('applies_to') or ('type' if snapshot.get('type_id') else 'all')
    owner=snapshot.get('type_name') if mode=='type' else t(APPLIES_TO[mode]) if field else None
    return ' · '.join(str(v) for v in (field or t('unbound'),owner) if v)


def change_rows(event, format_timestamp):
    metadata = event.get('metadata') or {}
    before = event.get('before_state') or metadata.get('before') or {}
    after = event.get('after_state') or metadata.get('after') or {}
    changed = event.get('changed_fields') or sorted(set(before)|set(after))
    rows = []
    if event['operation']=='NEXT_NUMBER_CHANGED':
        scope = t(SCOPES[metadata['scope_kind']])
        if metadata['scope_kind']!='generator':
            scope += ' · ' + str(metadata['scope_id'])
        for title,value in (
            (t('target'),target(metadata.get('target_snapshot'))),(t('scope'),scope),
            (t('reset'),t(metadata['reset_frequency'])),(t('period'),metadata['period_bucket'])):
            rows.append(dict(field=title,before=value,after=value))

    def value(key, state):
        v = state.get(key)
        if key=='applies_to' and state:
            return t(APPLIES_TO[v or ('type' if state.get('type_id') else 'all')])
        if v is None:return '—'
        if key=='kind':return render_message_plain(
            'dashboard.resource.record' if v=='record' else 'dashboard.resource.aggregation')
        if key=='primary_field':return render_message_plain(PRIMARY[v])
        if key=='scope':return t(SCOPES[v])
        if key=='reset_frequency':return t(v)
        if key=='enabled':return t('enabled' if v else 'disabled')
        if key=='target_snapshot':return target(v)
        if key in ('type_id','field_id'):
            name = (state.get('target_snapshot') or {}).get('type_name' if key=='type_id' else 'field_name')
            return ' · '.join(str(part) for part in (name,v) if part is not None)
        if key in ('date_created','date_updated'):return format_timestamp(v)
        return str(v)
    for key in changed:
        rows.append(dict(field=field_label(key),before=value(key,before),after=value(key,after)))
    return rows
