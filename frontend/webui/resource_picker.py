"""Reusable bounded record/aggregation picker over the existing search API.

State belongs to one open dialog; no cross-user/language cache. Searches always
fetch fresh data. Revision guards discard responses after a new search or close.
Selections retain only identity/title until the caller revalidates confirmation.
"""
from nicegui import ui
from .creator_labels import render_creator_name
from .api_client import ApiError
from .i18n_catalogue import render_message_plain as message

RESOURCE_PICKER_MESSAGE_KEYS = {
    key: value for key, value in (
        ('title', 'resource_picker.title'), ('search', 'resource_picker.search'),
        ('query', 'resource_picker.query'), ('prompt', 'resource_picker.prompt'),
        ('selected', 'resource_picker.selected'), ('add_selected', 'resource_picker.add_selected'),
        ('empty', 'resource_picker.empty'), ('limit', 'resource_picker.limit'),
    )
}
KEYS = RESOURCE_PICKER_MESSAGE_KEYS


def search_payload(kind, query, cursor=None):
    term = query.strip()
    if not term:
        raise ValueError('A resource search requires a nonblank query')
    payload = {'result_types': [], 'limit': 25}
    if kind in ('all', 'record'):
        payload['result_types'].append('records')
        payload['record_where'] = {'full_text': {'query': term, 'sources': ['metadata', 'components']}}
    if kind in ('all', 'aggregation'):
        payload['result_types'].append('aggregations')
        payload['aggregation_where'] = {'full_text': {'query': term, 'sources': ['metadata']}}
    if cursor:
        payload['cursor'] = cursor
    return payload


async def resource_picker(*, search, eligible, on_confirm, remaining, active, on_error, on_inspect=None):
    """Confirm receives unique (kind, id) dictionaries and returns success."""
    selected = {}
    state = {'open': True, 'revision': 0, 'page': 0, 'cursors': [None], 'busy': False, 'next_cursor': None}
    def current():
        return state['open'] and active()
    # QDialog's full-width setting forced 1232px at a 1280px viewport in
    # inspection; its default cap is 560px. Neither setting expresses half the
    # viewport. Scope the fractional width to this card, retaining mobile room.
    with ui.dialog() as dialog, ui.card().classes('gap-4').style(
        'width: max(calc(50vw - 24px), min(560px, calc(100vw - 32px))); '
        'max-width: calc(100vw - 32px)'
    ):
        ui.label(message(KEYS['title'])).classes('text-xl font-semibold')
        with ui.column().classes('w-full gap-3'):
            kind = ui.select({'all': message('messaging.field.all'),
                              'aggregation': message('navigation.item.aggregations'),
                              'record': message('navigation.item.records')},
                             value='all', label=message('messaging.field.resource_kind')).props('outlined').classes('w-full')
            query = ui.input(message(KEYS['query'])).props('outlined clearable').classes('w-full')
            search_button = ui.button(message(KEYS['search']), icon='search', on_click=lambda: load(True)).props('no-caps')
        status = ui.label().props('role=status').classes('text-sm')
        with ui.scroll_area().classes('w-full h-64'):
            results = ui.column().classes('w-full gap-2')
        with ui.grid(columns=2).classes('self-start gap-2'):
            previous = ui.button(message('messaging.action.previous'), on_click=lambda: move(-1)).props('outline no-caps')
            following = ui.button(message('messaging.action.next'), on_click=lambda: move(1)).props('outline no-caps')
        selection_count = ui.label().classes('font-medium')
        with ui.scroll_area().props('visible').classes('w-full shrink-0').mark('selected-resources') as selection_scroll:
            selection = ui.column().classes('w-full gap-1')

        def render_selection():
            selection_count.text = message(KEYS['selected']) + ': ' + str(len(selected))
            selection_scroll.set_visibility(bool(selected))
            selection_scroll.style(f'height: {min(len(selected) * 56, 168)}px')
            selection.clear()
            with selection:
                for key, row in selected.items():
                    with ui.grid(columns='minmax(0, 1fr) auto').classes('w-full items-center gap-2'):
                        ui.label(message('messaging.field.' + row['resource_kind']) + ' · ' + row['title']).classes('min-w-0 break-words')
                        def remove(key=key):
                            if state['busy']:
                                return
                            selected.pop(key, None)
                            render_selection()
                            for identity, control in checks.items():
                                control.value = identity in selected
                        ui.button(message('messaging.action.remove'), icon='close', on_click=remove).props('flat no-caps')
            confirm.set_enabled(bool(selected) and len(selected) <= remaining() and not state['busy'])
            if len(selected) > remaining():
                status.props(remove='dir')
                status.text = message(KEYS['limit'])

        checks = {}
        allowed = {}
        def invalidate():
            search_button.set_enabled(bool((query.value or '').strip()) and not state['busy'])
            state['revision'] += 1
            state.update(page=0, cursors=[None], next_cursor=None, criteria=None)
            results.clear()
            checks.clear()
            allowed.clear()
            previous.disable()
            following.disable()
            status.props(remove='dir')
            status.text = message(KEYS['prompt'])

        async def load(reset=False):
            if not current() or state['busy']:
                return
            if reset:
                if not (query.value or '').strip():
                    invalidate()
                    return
                state.update(page=0, cursors=[None], next_cursor=None)
                state['criteria'] = (kind.value, query.value.strip())
            if not state.get('criteria'):
                return
            state['revision'] += 1
            revision = state['revision']
            requested_kind, requested_query = state['criteria']
            status.props(remove='dir')
            status.text = message('webui.execute_search.text.searching_ec84eae6')
            previous.disable()
            following.disable()
            try:
                page = await search(search_payload(requested_kind, requested_query, state['cursors'][state['page']]))
            except ApiError as error:
                if current() and revision == state['revision']:
                    status.text = message('messaging.error.failed')
                    on_error(error)
                return
            if not current() or revision != state['revision']:
                return
            state['next_cursor'] = page.get('next_cursor')
            results.clear()
            checks.clear()
            allowed.clear()
            with results:
                if not page['items']:
                    ui.label(message(KEYS['empty'])).classes('text-slate-500')
                for item in page['items']:
                    row_kind = item['type']
                    row = item[row_kind]
                    key = (row_kind, row['id'])
                    reason = eligible(row)
                    with ui.card().classes('w-full border border-blue-100 shadow-none p-3 gap-1'):
                        def toggle(event, key=key, row=row, requested_kind=row_kind):
                            if state['busy']:
                                return
                            if event.value:
                                selected[key] = {'resource_kind': requested_kind, 'target_id': row['id'], 'title': row['title']}
                            else:
                                selected.pop(key, None)
                            render_selection()
                        with ui.grid(columns='auto minmax(0, 1fr)').classes('w-full items-start gap-3'):
                            check = ui.checkbox(value=key in selected, on_change=toggle).props('dense')
                            check.props['aria-label'] = row['title']
                            with ui.column().classes('flex-1 min-w-0 gap-2'):
                                async def inspect(requested_kind=row_kind, identity=row['id']):
                                    if current() and not state['busy'] and on_inspect:
                                        await on_inspect(requested_kind, identity, current)
                                ui.button(row['title'], icon='folder' if row_kind == 'aggregation' else 'description',
                                          on_click=inspect).props('flat dense no-caps').classes('font-semibold self-start text-start')
                                with ui.grid(columns='auto auto').classes('self-start items-center gap-2'):
                                    ui.badge(message('messaging.field.' + row_kind)).props('outline')
                                    ui.label(row.get(row_kind + '_number') or '').props('dir=ltr').classes('text-sm text-slate-500')
                                render_creator_name(row)
                                if row.get('description'):
                                    ui.label(row['description']).classes('text-sm text-slate-600 whitespace-pre-line')
                                if reason:
                                    ui.label(reason).classes('text-sm text-slate-500')
                        check.set_enabled(not reason and not state['busy'])
                        checks[key] = check
                        allowed[key] = not reason
            status.props('dir=ltr')
            status.text = str(state['page'] * 25 + 1 if page['items'] else 0) + '–' + str(state['page'] * 25 + len(page['items']))
            previous.set_enabled(state['page'] > 0)
            following.set_enabled(bool(state['next_cursor']))
            render_selection()

        async def move(delta):
            if delta > 0:
                if not state['next_cursor']:
                    return
                state['cursors'] = state['cursors'][:state['page'] + 1] + [state['next_cursor']]
            state['page'] = max(0, state['page'] + delta)
            await load()

        async def confirm_selection():
            if not current() or state['busy'] or not selected:
                return
            if len(selected) > remaining():
                status.props(remove='dir')
                status.text = message(KEYS['limit'])
                return
            state['busy'] = True
            confirm.disable()
            for control in (kind, query, search_button, previous, following, *checks.values()):
                control.disable()
            try:
                if await on_confirm(list(selected.values()), current):
                    if current():
                        dialog.close()
            except ApiError as error:
                if current():
                    on_error(error)
            finally:
                state['busy'] = False
                if current():
                    for control in (kind, query, search_button):
                        control.enable()
                    search_button.set_enabled(bool((query.value or '').strip()))
                    for key, control in checks.items():
                        control.set_enabled(allowed[key])
                    previous.set_enabled(state['page'] > 0)
                    following.set_enabled(bool(state['next_cursor']))
                    render_selection()

        with ui.grid(columns=2).classes('self-start gap-2'):
            confirm = ui.button(message(KEYS['add_selected']), icon='add_link', on_click=confirm_selection).props('no-caps')
            ui.button(message('messaging.action.cancel'), on_click=dialog.close).props('flat no-caps')
        query.on('keydown.enter', lambda: load(True))
        query.on_value_change(invalidate)
        kind.on_value_change(invalidate)
        def close():
            state['open'] = False
            state['revision'] += 1
        dialog.on('hide', close)
        render_selection()
        invalidate()
    dialog.open()
    return dialog
