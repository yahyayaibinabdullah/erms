"""Read-only, page-local metadata overlay; never navigates or mutates a resource."""
import asyncio
from .disposition.messages import text as disposition_text, status_label
from nicegui import ui, context
from .api_client import ApiError
from .entities import ENTITIES, FieldSpec
from .i18n_catalogue import render_message_plain as message


async def resource_inspector(*, api, kind, identity, active, preview, field_label,
                             format_timestamp, medium_label, on_error):
    if kind not in ('record', 'aggregation') or not active():
        return
    client = context.client
    state = {'open': True}
    def current():
        return state['open'] and active()
    with ui.dialog() as dialog, ui.card().classes('w-[760px] max-w-full gap-4'):
        with ui.grid(columns='auto minmax(0, 1fr) auto').classes('w-full items-center gap-3'):
            ui.icon('folder' if kind == 'aggregation' else 'description', color='primary', size='28px')
            title = ui.label(message('messaging.field.' + kind)).classes('text-xl font-semibold break-words')
            ui.button(message('messaging.live.close'), icon='close', on_click=dialog.close).props('flat no-caps')
        content = ui.column().classes('w-full gap-3')
        with content:
            ui.spinner()
    dialog.on('hide', lambda: state.update(open=False))
    dialog.open()
    try:
        resource_name = kind + 's'
        row, capabilities = await asyncio.gather(
            api.get(resource_name, identity), api.resource_capabilities(resource_name, identity))
        if not current():
            dialog.close()
            return dialog
        fields = [field for field in ENTITIES[resource_name].fields if field.name != 'title']
        fields.append(FieldSpec('owning_org_unit_id', 'Organization unit', 'lookup',
                                lookup_resource='org-units', lookup_label_fields=('code', 'name')))
        async def value_for(field):
            with client:
                value = row.get(field.name)
                if field.lookup_resource and value is not None:
                    try:
                        related = await api.get(field.lookup_resource, value)
                        localized = related.get('localized') or {}
                        return ' — '.join(str(localized.get(key) or related.get(key) or '')
                                          for key in field.lookup_label_fields).strip(' —')
                    except ApiError as error:
                        if error.status_code in (403, 404):
                            return message('messaging.reason.message_resource_unavailable')
                        raise
                if field.kind == 'datetime':
                    return format_timestamp(value)
                if field.kind == 'bool':
                    return message('translation_inspector.value.yes' if value else 'translation_inspector.value.no')
                if field.kind == 'medium':
                    return medium_label(value)
                return str(value) if value is not None else '—'
        values = await asyncio.gather(*(value_for(field) for field in fields))
        if not current():
            dialog.close()
            return dialog
        title.text = row['title']
        content.clear()
        with content:
            with ui.column().classes('detail-field w-full gap-1'):
                ui.label(disposition_text('status')).classes('detail-field-label')
                ui.label(status_label(row.get('disposition_status',1))).classes('detail-field-value')
            if kind == 'record' and row.get('medium') != 'physical' and capabilities.get('view_component'):
                async def show_preview():
                    if current():
                        await preview(row)
                ui.button(message('webui.select_record_details.tooltip.preview_digital_components_b4905386'),
                          icon='visibility', on_click=show_preview).props('outline no-caps')
            with ui.grid(columns='repeat(auto-fit, minmax(min(100%, 220px), 1fr))').classes('w-full gap-3'):
                for field, value in zip(fields, values):
                    with ui.column().classes('detail-field w-full gap-1' + (' col-span-full' if field.kind == 'textarea' else '')):
                        ui.label(field_label(field.label)).classes('detail-field-label')
                        ui.label(value or '—').props('dir=auto').classes('detail-field-value whitespace-pre-wrap break-words')
                with ui.column().classes('detail-field w-full gap-1'):
                    ui.label(message('advanced_search.field.date_created')).classes('detail-field-label')
                    ui.label(format_timestamp(row.get('date_created'))).classes('detail-field-value')
    except ApiError as error:
        if current():
            content.clear()
            with content:
                ui.label(message('messaging.error.failed')).props('role=alert')
            on_error(error)
    return dialog
