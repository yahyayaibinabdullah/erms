"""Administration Settings: finite API registry, governed saves and bounded pickers.

Form/reference snapshots belong to this page instance, identity and language.
They refresh on entry/Refresh and a successful save refreshes only its category.
Other unsaved categories retain their original values/versions. References are
selected IDs only; no options catalogue or additional authoritative cache exists.
"""
import asyncio
from collections import defaultdict
from typing import Any

from nicegui import ui

from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain
from .remote_select import RemoteSelect

CATEGORY_ORDER = ('general', 'content', 'authentication', 'interface_limits', 'search', 'disposition', 'email')
FIELD_ORDER = {
    'disposition': ('DISPOSITION_DESTRUCTION_REVIEW_ROUTE','DISPOSITION_CLASSIFICATION_SCHEME_ID',
                    'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID','DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID',
                    'DISPOSITION_EXTERNAL_AUTHORITY_NAME','DISPOSITION_EXTERNAL_AUTHORITY_EMAIL','DISPOSITION_DESTRUCTION_REMINDER_MONTHS'),
    'email': ('SMTP_HOST','SMTP_PORT','SMTP_SECURITY','SMTP_AUTH_ENABLED','SMTP_USERNAME','SMTP_PASSWORD',
              'SMTP_SENDER_EMAIL','SMTP_SENDER_NAME','SMTP_REPLY_TO_EMAIL','SMTP_TIMEOUT_SECONDS'),
}
DESTINATION_KEYS = ('DISPOSITION_CLASSIFICATION_SCHEME_ID', 'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID', 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID')
# Literal option keys keep contextual catalogue coverage explicit.
SETTINGS_CHOICE_MESSAGE_KEYS = {
    'standard': 'settings.choice.standard', 'simplified': 'settings.choice.simplified',
    'records_manager_only': 'settings.choice.records_manager_only',
    'starttls': 'settings.choice.starttls', 'implicit_tls': 'settings.choice.implicit_tls',
    'digital': 'settings.choice.digital', 'physical': 'settings.choice.physical', 'mixed': 'settings.choice.mixed',
}
WARNING_LABEL_KEYS = {
    'DISPOSITION_CLASSIFICATION_SCHEME_ID': 'settings.field.disposition_classification_scheme_id.label',
    'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID': 'settings.field.disposition_uploaded_evidence_classification_id.label',
    'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID': 'settings.field.disposition_generated_reports_classification_id.label',
}


def reference_label(row):
    title = (row.get('localized') or {}).get('title') or row.get('title') or str(row['id'])
    return f"{row['code']} · {title}" if row.get('code') else title


def proposed_value(item, value):
    if item['kind'] == 'integer':
        if value is None or value == '':
            return None
        if isinstance(value, bool):
            raise ValueError
        # Preserve full PostgreSQL integer precision through a native text input.
        # Converting via a browser/Python float would silently round large values.
        if isinstance(value, str):
            return int(value.strip())
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        return int(value)
    if item['validation']['nullable'] and isinstance(value, str) and not value.strip():
        return None
    return value


def changed_rows(items, controls, *, password=None, clear_password=False):
    """No plaintext saved value exists in the form; submit only replacements.

    Related groups include every member/version even when its value is retained.
    Explicitly entering the same default counts as configuration when untouched.
    """
    changes = []
    changed_groups = set()
    for item in items:
        key = item['key']
        if item['sensitive']:
            if clear_password:
                changes.append(dict(key=key, expected_version=item['version'], clear_secret=True))
                changed_groups.add(item['validation']['group'])
            elif password:
                changes.append(dict(key=key, expected_version=item['version'], secret_value=password))
                changed_groups.add(item['validation']['group'])
            continue
        value = proposed_value(item, controls[key].value)
        # Changes to an untouched default are explicit only after a field event.
        touched = bool(getattr(controls[key], '_settings_touched', False))
        if value != item['value'] or touched and item['provenance'] == 'default':
            changes.append(dict(key=key, expected_version=item['version'], value=value))
            if item['validation']['group']:
                changed_groups.add(item['validation']['group'])
    submitted = {change['key'] for change in changes}
    for item in items:
        if item['validation']['group'] in changed_groups and item['key'] not in submitted:
            changes.append(dict(key=item['key'], expected_version=item['version']))
    return changes


def disposition_warning_panel(warnings, *, can_manage, open_settings):
    if not warnings:
        return
    with ui.card().classes('governance-status-card governance-status-warning shadow-none w-full gap-3').props('role=status'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('warning', size='20px')
            ui.label(render_message('settings.custody.title')).classes('font-semibold')
        for warning in warnings:
            ui.label(render_message('settings.custody.unset' if warning['code'] == 'destination_unset' else 'settings.custody.no_root', setting=render_message_plain(WARNING_LABEL_KEYS[warning['setting_key']]))).classes('text-sm leading-relaxed')
        if can_manage:
            ui.button(render_message('settings.custody.open'), icon='settings', on_click=open_settings).props('outline no-caps')
        else:
            ui.label(render_message('settings.custody.contact')).classes('text-sm')


async def settings_page(*, api, container, bind_relationship, active, on_error,
                        direction=lambda: 'ltr', initial_category='general', on_category=lambda value: None):
    state = {'revision': 0, 'items': {}, 'references': {}, 'hosts': {}, 'forms': {}, 'loading': False}
    with container:
        with ui.column().classes('application-settings-page w-full p-5 gap-4'):
            with ui.row().classes('w-full items-center gap-3'):
                ui.label(render_message('settings.page.propagation')).classes('grow text-sm text-slate-600 leading-relaxed')
                refresh = ui.button(render_message('settings.action.refresh'), icon='refresh').props('flat no-caps')
            status = ui.label('').classes('text-sm text-slate-500').props('role=status')
            body = ui.column().classes('w-full gap-4')

    def current(revision=None):
        return active() and not container.is_deleted and (revision is None or revision == state['revision'])

    def notify_error(error):
        if current():
            with container:
                ui.notify(on_error(error) if isinstance(error, ApiError) else render_message('settings.error.invalid_value'), color='negative', close_button=True)

    async def resolve_selected(items):
        needed = {(('classification-schemes' if i['kind'] == 'scheme' else 'classifications'), i['value'])
                  for i in items if i['kind'] in {'scheme', 'classification'} and i['value'] is not None}
        if not needed:
            return {}
        keys = sorted(needed)
        rows = await asyncio.gather(*(api.get(resource, entity_id) for resource, entity_id in keys), return_exceptions=True)
        return {key: row for key, row in zip(keys, rows) if not isinstance(row, BaseException)}

    async def browse(control, kind, form):
        scheme_control = form['controls'].get(DESTINATION_KEYS[0])
        scheme_id = scheme_control.value if scheme_control else None
        if kind == 'classification' and scheme_id is None:
            with container:
                ui.notify(render_message('settings.selector.choose_scheme'), color='warning')
            return
        dialog = ui.dialog()
        paging = {'revision': 0, 'offset': 0, 'parent': None, 'path': [], 'open': True, 'loading': False}
        scheme_name = (scheme_control.options or {}).get(scheme_id, '') if scheme_control else ''
        with dialog, ui.card().classes('application-settings-browser w-[760px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-32px)] gap-3'):
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(render_message('settings.selector.browse_schemes' if kind == 'scheme' else 'settings.selector.browse_classifications')).classes('text-lg font-semibold grow')
                ui.button(icon='close', on_click=dialog.close).props('flat round dense').tooltip(render_message('common.action.cancel'))
            if scheme_name:
                ui.label(scheme_name).classes('text-sm text-primary font-semibold')
            breadcrumb = ui.row().classes('w-full gap-1 items-center')
            progress = ui.label('').props('role=status').classes('text-sm text-slate-500')
            retry = ui.button(render_message('settings.action.retry')).props('outline dense no-caps')
            retry.set_visibility(False)
            results = ui.column().classes('w-full gap-2 overflow-y-auto max-h-[60vh]')
            with ui.row().classes('w-full justify-end items-center gap-2'):
                previous = ui.button(render_message('settings.action.previous')).props('flat dense no-caps')
                next_button = ui.button(render_message('settings.action.next')).props('flat dense no-caps')
        dialog.on('hide', lambda: paging.update(open=False))
        dialog.open()

        def live(revision=None):
            return current() and dialog.value and paging['open'] and (kind == 'scheme' or scheme_control.value == scheme_id) and (revision is None or revision == paging['revision'])

        async def choose(row):
            try:
                fresh = await api.get('classification-schemes' if kind == 'scheme' else 'classifications', row['id'])
                if not live():
                    return
                if kind == 'classification' and (fresh['classification_scheme_id'] != scheme_id or not fresh['is_terminal']):
                    raise ValueError
                state['references'][('classification-schemes' if kind == 'scheme' else 'classifications', row['id'])] = fresh
                control.set_options({**dict(control.options), row['id']: reference_label(fresh)}, value=row['id'])
                dialog.close()
            except (ApiError, ValueError) as error:
                notify_error(error)

        async def level(parent=None, path=None, offset=0):
            if paging['loading']:
                return
            paging['revision'] += 1
            revision = paging['revision']
            if not live():
                return
            paging['loading'] = True
            paging['retry_request'] = (parent, path, offset)
            retry.set_visibility(False)
            progress.text = render_message('settings.page.loading')
            previous.disable(); next_button.disable()
            params = {'limit': 26, 'offset': offset}
            if kind == 'classification':
                params.update(classification_scheme_id=scheme_id)
                params.update(roots_only=True) if parent is None else params.update(parent_classification_id=parent['id'])
            else:
                params.update(sort='code', direction='asc')
            try:
                rows = await api.request('GET', '/api/v1/classification-schemes' if kind == 'scheme' else '/api/v1/classifications', params=params)
            except asyncio.CancelledError:
                paging['loading'] = False
                return
            except ApiError as error:
                paging['loading'] = False
                if live(revision):
                    progress.text = on_error(error)
                    retry.set_visibility(True)
                return
            paging['loading'] = False
            if not live(revision):
                return
            paging.update(parent=parent, path=path or [], offset=offset)
            breadcrumb.clear(); results.clear()
            with breadcrumb:
                if parent:
                    ui.button(icon='arrow_forward' if direction() == 'rtl' else 'arrow_back',
                              on_click=lambda: level((path or [])[-1] if path else None, (path or [])[:-1])).props('flat round dense').tooltip(render_message('settings.action.back'))
                    for ancestor in [*(path or []), parent]:
                        ui.label(reference_label(ancestor)).classes('text-xs text-slate-500')
            with results:
                if not rows:
                    ui.label(render_message('settings.selector.empty')).classes('text-sm text-slate-500 py-4')
                for row in rows[:25]:
                    async def activate(_, item=row):
                        if kind == 'scheme' or item['is_terminal']:
                            await choose(item)
                        else:
                            await level(item, [*(path or []), *([parent] if parent else [])])
                    # Established classification browser card/list treatment, no table.
                    with ui.card().classes('w-full shadow-none border border-slate-200 gap-1'):
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            ui.icon('account_tree' if kind == 'scheme' else 'label' if row['is_terminal'] else 'schema', color='primary')
                            ui.button(reference_label(row), on_click=activate).props('flat no-caps align=' + ('right' if direction() == 'rtl' else 'left')).classes('grow whitespace-normal break-words')
                            if kind == 'classification':
                                ui.badge(render_message('settings.selector.terminal' if row['is_terminal'] else 'settings.selector.branch')).props('outline color=primary')
            progress.text = render_message('settings.selector.page', count=min(len(rows),25), offset=offset + 1 if rows else 0)
            previous.set_enabled(offset > 0); next_button.set_enabled(len(rows) > 25)
        previous.on_click(lambda: level(paging['parent'], paging['path'], max(0, paging['offset'] - 25)))
        next_button.on_click(lambda: level(paging['parent'], paging['path'], paging['offset'] + 25))
        retry.on_click(lambda: level(*paging['retry_request']))
        await level()

    def render_category(category):
        host = state['hosts'][category]
        host.clear()
        items = [i for i in state['items'].values() if i['category'] == category]
        form = {'controls': {}, 'loaders': {}, 'busy': False}
        state['forms'][category] = form
        order = {key:index for index,key in enumerate(FIELD_ORDER.get(category,()))}
        with host:
            with ui.grid().classes('w-full grid-cols-1 lg:grid-cols-2 gap-5'):
                for item in sorted(items, key=lambda i: (order.get(i['key'],len(order)), i['key'])):
                    key = item['key']
                    with ui.column().classes('w-full gap-2 min-w-0').props(f'data-setting-key={key}'):
                        ui.label(item['label']).classes('font-semibold text-sm')
                        validation = item['validation']
                        if item['sensitive']:
                            ui.label(render_message('settings.secret.set' if item['secret_is_set'] else 'settings.secret.unset')).classes('text-sm text-slate-500')
                            control = ui.input(render_message('settings.secret.replace'), value='', password=True, password_toggle_button=True).props('outlined dense autocomplete=new-password').classes('w-full')
                            ui.label(render_message('settings.secret.retain')).classes('text-xs text-slate-500')
                            clear = ui.checkbox(render_message('settings.secret.clear'), value=False)
                            def toggle_clear(e, target=control):
                                target.value = ''
                                target.set_enabled(not e.value)
                            clear.on_value_change(toggle_clear)
                            form['password'], form['clear'] = control, clear
                        elif item['kind'] in {'scheme','classification'}:
                            resource = 'classification-schemes' if item['kind'] == 'scheme' else 'classifications'
                            row = state['references'].get((resource,item['value']))
                            options = {item['value']: reference_label(row) if row else render_message_plain('settings.selector.selected_id', id=item['value'])} if item['value'] is not None else {}
                            control = RemoteSelect(options, value=item['value'], label=item['label'], with_input=True).props('outlined dense input-debounce=0').classes('w-full')
                            ui.label(render_message('settings.selector.search_help')).classes('text-xs text-slate-500')
                            ui.button(render_message('settings.action.browse'), icon='account_tree', on_click=lambda _, c=control, k=item['kind'], f=form: browse(c,k,f)).props('outline dense no-caps')
                            async def page_loader(query, kind=item['kind'], f=form):
                                filters = {}
                                if kind == 'classification':
                                    selected = f['controls'][DESTINATION_KEYS[0]].value
                                    if selected is None:
                                        return {'items': []}
                                    filters = {'classification_scheme_id': selected, 'is_terminal': True}
                                return await api.relationship_page('classification-schemes' if kind == 'scheme' else 'classifications', ('code','title','description'), query, limit=25, filters=filters)
                            async def selected_loader(entity_id, r=resource):
                                existing = state['references'].get((r,entity_id))
                                return existing if existing is not None else await api.get(r,entity_id)
                            form['loaders'][key] = bind_relationship(control, resource, ('code','title','description'), ('code','title'),
                                page_loader=page_loader, selected_loader=selected_loader, min_query_length=2,
                                active=lambda h=host,f=form: current() and state['forms'].get(category) is f and not h.is_deleted)
                        elif item['kind'] == 'boolean' and not validation['nullable']:
                            control = ui.checkbox(item['label'], value=item['value'])
                        elif item['kind'] == 'boolean':
                            control = ui.select({True:render_message_plain('settings.choice.yes'), False:render_message_plain('settings.choice.no')}, value=item['value'], label=item['label']).props('outlined dense').classes('w-full')
                        elif item['kind'] == 'enum':
                            options = {choice: render_message_plain(SETTINGS_CHOICE_MESSAGE_KEYS[choice]) for choice in validation['choices']}
                            control = ui.select(options, value=item['value'], label=item['label']).props('outlined dense').classes('w-full')
                        elif item['kind'] == 'integer':
                            control = ui.input(label=item['label'], value=str(item['value']) if item['value'] is not None else '').props('outlined dense inputmode=numeric').classes('w-full')
                            if key == 'SMTP_PORT':
                                form['port_help'] = ui.label(render_message('settings.port.auto')).classes('text-xs text-slate-500')
                        else:
                            control = ui.input(item['label'], value=item['value'] or '').props('outlined dense').classes('w-full')
                            if item['kind'] == 'email':
                                control.props('type=email')
                        if validation['nullable'] and item['kind'] in {'scheme','classification','boolean','enum'}:
                            # Native Select's built-in clear label follows the
                            # process-wide vendor locale. Use NiceGUI's supported
                            # append slot for an identity/language-scoped label.
                            with control.add_slot('append'):
                                clear_selection = ui.button(icon='cancel').props('flat round dense')
                                clear_selection.props(f'aria-label="{render_message_plain("settings.action.clear_selection")}"')
                                clear_selection.tooltip(render_message('settings.action.clear_selection'))
                                clear_selection.on('click.stop', lambda _, c=control: c.set_value(None))
                                clear_selection.set_visibility(control.value is not None)
                                control.on_value_change(lambda e, b=clear_selection: b.set_visibility(e.value is not None))
                        control.on_value_change(lambda _, c=control: setattr(c, '_settings_touched', True))
                        if item['sensitive'] or item['kind'] in {'email','timezone','integer'} or key in {'SMTP_HOST','SMTP_USERNAME'}:
                            control.props('input-style="direction: ltr; unicode-bidi: isolate"')
                        form['controls'][key] = control
                        ui.label(item['description']).classes('text-sm text-slate-600 leading-relaxed w-full whitespace-normal')
            if category == 'disposition':
                async def scheme_changed():
                    for key in DESTINATION_KEYS[1:]:
                        control = form['controls'][key]
                        control.set_options({}, value=None)
                    await asyncio.gather(*(form['loaders'][key]('') for key in DESTINATION_KEYS[1:]))
                form['controls'][DESTINATION_KEYS[0]].on_value_change(scheme_changed)
            if category == 'email':
                def show_effective_port():
                    port = form['controls']['SMTP_PORT'].value
                    security = form['controls']['SMTP_SECURITY'].value
                    port = port or (465 if security == 'implicit_tls' else 587 if security == 'starttls' else None)
                    form['port_help'].text = render_message('settings.port.effective', port=str(port)) if port is not None else render_message('settings.port.auto')
                for key in ('SMTP_PORT', 'SMTP_SECURITY'):
                    form['controls'][key].on_value_change(show_effective_port)
                show_effective_port()
            reason = ui.input(render_message('settings.field.reason')).props('outlined dense').classes('w-full')
            feedback = ui.label('').classes('text-sm').props('role=status')
            with ui.row().classes('w-full justify-end'):
                save = ui.button(render_message('common.action.save'), icon='save').props('no-caps')
            form.update(reason=reason, save=save, feedback=feedback)

        async def submit():
            if form['busy'] or not current():
                return
            if not (reason.value or '').strip():
                feedback.text = render_message('settings.error.reason_required')
                return
            try:
                changes = changed_rows(items, form['controls'], password=form.get('password').value if form.get('password') else None,
                                       clear_password=form.get('clear').value if form.get('clear') else False)
            except (ValueError,TypeError,OverflowError):
                feedback.text = render_message('settings.error.invalid_value')
                return
            if not changes:
                feedback.text = render_message('settings.page.unchanged')
                return
            form['busy'] = True; save.disable(); refresh.disable()
            feedback.text = render_message('settings.page.saving')
            try:
                response = await api.save_application_settings(changes, reason.value.strip())
                references = await resolve_selected([i for i in response['items'] if i['category'] == category])
                if not current() or state['forms'].get(category) is not form:
                    return
                for item in response['items']:
                    if item['category'] == category:
                        state['items'][item['key']] = item
                state['references'].update(references)
                with host:
                    render_category(category)
                with container:
                    status.text = render_message('settings.page.saved')
            except asyncio.CancelledError:
                return
            except ApiError as error:
                if current() and state['forms'].get(category) is form:
                    with host:
                        feedback.text = on_error(error)
            finally:
                form['busy'] = False
                if current():
                    if not any(f['busy'] for f in state['forms'].values()):
                        refresh.enable()
                    if not save.is_deleted:
                        save.enable()
        save.on_click(submit)

    async def load():
        if state['loading'] or any(f['busy'] for f in state['forms'].values()) or not current():
            return
        state['loading'] = True; state['revision'] += 1
        revision = state['revision']; refresh.disable()
        with container:
            status.text = render_message('settings.page.loading')
        try:
            response = await api.application_settings()
            references = await resolve_selected(response['items'])
            if not current(revision):
                return
            state['items'] = {i['key']: i for i in response['items']}
            state['references'] = references
            with body:
                if not state['hosts']:
                    categories = {i['category']: i['category_label'] for i in response['items']}
                    with ui.tabs().props('no-caps outside-arrows mobile-arrows').classes('w-full') as tabs:
                        tab_by_category = {c:ui.tab(c,label=categories[c]) for c in CATEGORY_ORDER if c in categories}
                    tabs.value = initial_category if initial_category in tab_by_category else next(iter(tab_by_category))
                    tabs.on_value_change(lambda e: on_category(e.value))
                    on_category(tabs.value)
                    with ui.tab_panels(tabs,value=tabs.value).classes('w-full'):
                        for category in tab_by_category:
                            with ui.tab_panel(category).classes('w-full p-0'):
                                state['hosts'][category] = ui.column().classes('w-full gap-4 py-3')
                for category in state['hosts']:
                    render_category(category)
            status.text = ''
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if current(revision):
                with container:
                    status.text = on_error(error)
        finally:
            state['loading'] = False
            if current():
                refresh.enable()
    refresh.on_click(load)
    await load()
    return state
