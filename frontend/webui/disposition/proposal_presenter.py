"""Compact proposal descriptions from the existing authorized page projection."""
from .messages import text


ACTIONS={'destruction':'destruction','transfer_to_external_archive':'permanent_transfer',
         'selective_preservation':'selective_transfer','retain_as_local_archives':'local_archives'}


def proposed_change(row):
    # Partial envelopes permit the proposal type, never protected values/endpoints.
    if row.get('redacted'):
        return text(row['proposal_type']) if row.get('partial') else '—'
    kind=row['proposal_type'];facts=row.get('current_values') or {};values=row.get('proposed_values') or {}
    if kind=='blocking_security':
        return text('summary_security',level=row.get('proposed_security_name') or (facts.get('proposed_security') or {}).get('name') or '—')
    if kind=='add_to_holds':
        holds=facts.get('holds') or []
        labels=[' · '.join(str(h[k]) for k in ('code','name') if h.get(k)) for h in holds[:3]]
        if len(holds)>3:labels.append(text('summary_more',count=len(holds)-3))
        return text('summary_holds',holds='; '.join(labels) or '—')
    if kind=='local_retention_override':
        return text('summary_retention',current=values.get('current_period_years','—'),intermediate=values.get('intermediate_period_years','—'),action=text(ACTIONS[values['final_disposition']]) if values.get('final_disposition') in ACTIONS else '—')
    if kind in ('create_aggregation_relationship','remove_aggregation_relationship','remove_record_relationship'):
        relation=facts.get('relationship') or {}
        target=row.get('target_record_id') or row['target_aggregation_id']
        related=row.get('relationship_target_label') if relation.get('source_id')==target else row.get('relationship_source_label')
        return text('summary_add_relationship' if kind=='create_aggregation_relationship' else 'summary_remove_relationship',relationship=row.get('relationship_display_name') or row.get('relationship_type_name') or '—',related=related or '—')
    return text(kind)
