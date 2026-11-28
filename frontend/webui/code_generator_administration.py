"""Custom code generator settings; page/dialog state only, no configuration cache."""
from datetime import date
from html import escape
import asyncio
import re

from nicegui import ui

from .api_client import ApiError
from .code_generator_messages import t
from .entity_selectors import relationship_options
from .i18n_catalogue import render_message_plain
from .relationship_select import relationship_select
from .resource_relationships import PageTable
from .type_controls import pick

BASE = '/api/v1/code-generators'
PRIMARY_LABELS = {
    'record_number': 'entity_metadata.field.record_number',
    'aggregation_number': 'entity_metadata.field.aggregation_number',
    'title': 'entity_metadata.field.title',
    'description': 'entity_metadata.field.description',
    'assigned_location': 'entity_metadata.field.assigned_location',
    'current_location': 'entity_metadata.field.current_location',
}
KINDS = {'record': 'dashboard.resource.record', 'aggregation': 'dashboard.resource.aggregation'}
APPLIES_TO = {'all': 'all_items', 'untyped': 'untyped_only', 'type': 'selected_type'}
SCOPES = {'generator': 'scope_generator', 'parent_aggregation': 'scope_parent',
          'classification': 'scope_classification', 'org_unit': 'scope_org'}
RESETS = {'never': 'never', 'yearly': 'yearly', 'monthly': 'monthly'}
TOKENS = {
    'YYYY': 'year4', 'YY': 'year2', 'MM': 'month', 'DD': 'day', 'DATE': 'date_token',
    'PARENT_AGGREGATION_NUMBER': 'parent_token', 'CLASSIFICATION_CODE': 'classification_token',
    'CLASSIFICATION_SCHEME_CODE': 'scheme_token', 'ORG_UNIT_CODE': 'org_token',
    'ROLE_CODE': 'role_token', 'SERIAL': 'serial_token',
}
SAMPLES = {
    'parent_aggregation_number': ('parent_token', 'PARENT'),
    'classification_code': ('classification_token', 'CLASS'),
    'classification_scheme_code': ('scheme_token', 'SCHEME'),
    'org_unit_code': ('org_token', 'ORG'), 'role_code': ('role_token', 'ROLE'),
}
FIELD_LABELS = {'name': 'name', 'kind': 'resource', 'pattern': 'pattern', 'start': 'start',
                'increment': 'increment', 'scope': 'scope', 'reset_frequency': 'reset',
                'padding_width': 'padding', 'max_code_length': 'maximum',
                'applies_to': 'applies_to', 'primary_field': 'field', 'type_id': 'type', 'field_id': 'field',
                'reason': 'reason_edit', 'sample_date': 'sample_date',
                'scope_id': 'scope_id', 'period_bucket': 'period', 'next_number': 'next_number'}


class InvalidForm(ValueError):
    def __init__(self, field):
        self.field = field
        super().__init__(field)


def whole_text(value, field, *, positive=False, maximum=None):
    """Keep arbitrary serials as strings, never browser/Python floating point."""
    value = str(value or '').strip()
    if not re.fullmatch('[0-9]+', value) or positive and not value.strip('0'):
        raise InvalidForm(field)
    if maximum is not None:
        significant = value.lstrip('0') or '0'
        if len(significant) > len(str(maximum)) or int(significant) > maximum:
            raise InvalidForm(field)
        return int(significant)
    return value


def configuration(controls, target, *, allow_unbound=False):
    name = controls['name'].value or ''
    if not name.strip():
        raise InvalidForm('name')
    pattern = controls['pattern'].value or ''
    if not pattern:
        raise InvalidForm('pattern')
    primary = target.get('primary') if target['mode'] == 'primary' else None
    owner = target.get('type') if target['mode'] == 'specific' or target['applies_to']=='type' else None
    field = target.get('field') if target['mode'] == 'specific' else None
    unbound = allow_unbound and not primary and not field and owner is None and not controls['enabled'].value
    if not unbound and (target['mode'] == 'specific' or target['applies_to']=='type') and not owner:
        raise InvalidForm('type_id')
    if not unbound and (not target.get('ready') or not primary and not field):
        raise InvalidForm('field_id')
    padding = str(controls['padding_width'].value or '').strip()
    return dict(name=name, kind=target['kind'], primary_field=primary,
        applies_to='type' if target['mode']=='specific' else target['applies_to'],
        type_id=owner['id'] if owner else None, field_id=field['id'] if field else None,
        pattern=pattern, start=whole_text(controls['start'].value, 'start'),
        increment=whole_text(controls['increment'].value, 'increment', positive=True),
        scope=controls['scope'].value, reset_frequency=controls['reset_frequency'].value,
        padding_width=whole_text(padding, 'padding_width', maximum=2_147_483_647) if padding else None,
        max_code_length=whole_text(controls['max_code_length'].value, 'max_code_length',
                                  positive=True, maximum=2_147_483_647),
        enabled=bool(controls['enabled'].value))


def column(name, title, direction, sortable=False):
    return dict(name=name, field=name, label=t(title),
                align='right' if direction() == 'rtl' else 'left', sortable=sortable)


def target_label(row):
    snapshot = row.get('target_snapshot') or {}
    field = (render_message_plain(PRIMARY_LABELS[row['primary_field']]) if row.get('primary_field')
             else snapshot.get('field_name') or t('unbound'))
    applies_to = row.get('applies_to') or ('type' if row.get('type_id') else 'all')
    owner = snapshot.get('type_name') if applies_to=='type' else t(APPLIES_TO[applies_to]) if row.get('primary_field') else ''
    return ' · '.join(part for part in (render_message_plain(KINDS[row['kind']]), field, owner) if part)


def form_error(error, on_error):
    if isinstance(error, InvalidForm):
        return t('invalid_field', field=t(FIELD_LABELS.get(error.field, 'field'))) + ' ' + t('required')
    message = on_error(error)
    detail = getattr(error, 'detail', None)
    if isinstance(detail, dict) and detail.get('field') in FIELD_LABELS:
        message += ' ' + t('invalid_field', field=t(FIELD_LABELS[detail['field']]))
    return message


async def edit_generator(*, api, row, active, on_error, bind_relationship,
                         direction, on_saved, render_history=None, can_audit=lambda: False):
    """Three mockup tabs, using authoritative unsaved server simulations."""
    creating = row is None
    initial = row or {}
    snapshot = initial.get('target_snapshot') or {}
    target = dict(kind=initial.get('kind', 'record'), mode='specific' if initial.get('field_id') else 'primary',
        applies_to=initial.get('applies_to') or ('type' if initial.get('type_id') else 'all'),
        primary=initial.get('primary_field', 'record_number' if creating else None),
        type=({'id': initial['type_id'], 'name': snapshot.get('type_name') or str(initial['type_id'])}
              if initial.get('type_id') else None),
        field=({'id': initial['field_id'], 'name': snapshot.get('field_name') or str(initial['field_id'])}
               if initial.get('field_id') else None), ready=False, revision=0)
    state = dict(busy=False, stale=False, preview_revision=0, preview_requested=False, timer=None)
    controls, sample_controls = {}, {}
    # Immutable primary-key catalogue snapshot: this dialog/kind only, no
    # language or identity data; failed loads are not retained. Reopening or
    # explicitly reloading the form reads it again. Generator settings are fresh.
    primary_catalogue = {}
    # NiceGUI Dialog has no dimensions API. Its minimized QDialog card cap
    # overrides width classes, so size only this card through supported style().
    # Desktop: half the former full width; the reduced height plus 150px. The
    # viewport-bounded floors keep fields and scrolling usable on small screens.
    dialog = ui.dialog()
    with dialog, ui.card().classes('application-settings-page w-full overflow-hidden gap-3').style(
        'width: max(min(40rem, calc(100vw - 32px)), calc((100vw - 48px) / 2)); '
        'max-width: calc(100vw - 32px); '
        'height: calc(max(min(26rem, calc(100vh - 32px)), calc((100vh - 48px) * 2 / 3)) + 150px); '
        'max-height: calc(100vh - 32px)') as card:
        with ui.row().classes('w-full items-center gap-2'):
            ui.label(t('new' if creating else 'edit')).classes('text-xl font-semibold grow')
            if row:
                ui.label(t('generator_identity', identity=row['id'])).classes('text-sm text-slate-500')
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').tooltip(t('cancel'))
        controls['name'] = ui.input(t('name'), value=initial.get('name', '')).props('outlined dense').classes('w-full')
        pattern_warning = ui.label('').props('role=status').classes('text-sm text-amber-800')
        with ui.tabs().props('no-caps outside-arrows mobile-arrows').classes('w-full') as tabs:
            ui.tab('settings', label=t('settings'))
            ui.tab('preview', label=t('preview_tab'))
            ui.tab('history', label=t('history'))
        with ui.scroll_area().classes('w-full flex-1 min-h-0'):
            with ui.tab_panels(tabs, value='settings').classes('w-full p-0'):
                with ui.tab_panel('settings').classes('p-0 gap-3'):
                    ui.label(t('future_help')).classes('text-sm text-slate-600')
                    with ui.row().classes('w-full gap-3 items-center'):
                        kind = ui.select({k: render_message_plain(v) for k, v in KINDS.items()},
                                         value=target['kind'], label=t('resource')).props('outlined dense').classes('grow')
                        mode = ui.select({'primary': t('primary'), 'specific': t('specific')},
                                         value=target['mode'], label=t('metadata')).props('outlined dense').classes('grow')
                    target_host = ui.column().classes('w-full gap-2')
                    controls['enabled'] = ui.checkbox(t('enabled'), value=initial.get('enabled', True))
                    controls['pattern'] = ui.input(t('pattern'), value=initial.get('pattern', '{SERIAL}')).props(
                        'outlined dense input-style="direction:ltr; unicode-bidi:isolate"').classes('w-full')
                    with ui.row().classes('w-full gap-2 items-center'):
                        token = ui.select({key: t(value) for key, value in TOKENS.items()}, value='SERIAL',
                                          label=t('placeholder')).props('outlined dense').classes('grow')
                        ui.button(t('insert'), icon='add', on_click=lambda: controls['pattern'].set_value(
                            (controls['pattern'].value or '') + '{' + token.value + '}')).props('outline no-caps')
                    ui.label(t('pattern_help')).classes('text-xs text-slate-500')
                    with ui.grid(columns='repeat(auto-fit,minmax(min(100%,260px),1fr))').classes('w-full gap-3'):
                        controls['scope'] = ui.select({k: t(v) for k, v in SCOPES.items()}, value=initial.get('scope', 'generator'),
                                                      label=t('scope')).props('outlined dense').classes('w-full')
                        controls['reset_frequency'] = ui.select({k: t(v) for k, v in RESETS.items()},
                            value=initial.get('reset_frequency', 'never'), label=t('reset')).props('outlined dense').classes('w-full')
                        controls['start'] = ui.input(t('start'), value=str(initial.get('start', '1'))).props(
                            'outlined dense inputmode=numeric').classes('w-full')
                        controls['increment'] = ui.input(t('increment'), value=str(initial.get('increment', '1'))).props(
                            'outlined dense inputmode=numeric').classes('w-full')
                        controls['padding_width'] = ui.input(t('padding'),
                            value='' if initial.get('padding_width') is None else str(initial['padding_width'])).props(
                            'outlined dense inputmode=numeric').classes('w-full')
                        controls['max_code_length'] = ui.input(t('maximum'), value=str(initial.get('max_code_length', ''))).props(
                            'outlined dense inputmode=numeric').classes('w-full')
                    for key in ('start_help', 'padding_help', 'maximum_help', 'scope_help', 'reset_help'):
                        ui.label(t(key)).classes('text-xs text-slate-500')
                    capacity = ui.label('').classes('text-xs text-slate-500')
                    target_retry = ui.button(render_message_plain('settings.action.retry'), icon='refresh',
                        on_click=lambda:build_targets()).props('outline dense no-caps')
                    target_retry.set_visibility(False)
                with ui.tab_panel('preview').classes('p-0 gap-3'):
                    ui.label(t('simulation_help')).classes('text-sm text-slate-600')
                    with ui.row().classes('w-full gap-3 items-center'):
                        scenario = ui.select({}, value=None, label=t('scenario')).props('outlined dense').classes('grow')
                        sample_date = ui.input(t('sample_date'), value=date.today().isoformat()).props('outlined dense type=date')
                        preview_button = ui.button(t('preview'), icon='preview').props('outline no-caps')
                    with ui.grid(columns='repeat(auto-fit,minmax(min(100%,260px),1fr))').classes('w-full gap-4'):
                        for identity, title in (('A', 'context_a'), ('B', 'context_b')):
                            with ui.column().classes('w-full gap-2'):
                                ui.label(t(title)).classes('font-semibold')
                                sample_controls[identity] = {
                                    key: ui.input(t(text), value=f'{prefix}-{identity}').props('outlined dense').classes('w-full')
                                    for key, (text, prefix) in SAMPLES.items()}
                    preview_status = ui.label(t('preview_prompt')).props('role=status').classes('text-sm text-slate-500')
                    warning = ui.label('').props('role=status').classes('text-sm text-amber-800')
                    timezone = ui.label('').classes('text-xs text-slate-500')
                    preview_table = ui.table(columns=[
                        column('date', 'sample_date', direction), column('scope_label', 'scope', direction),
                        column('value', 'sample_code', direction), column('characters', 'characters', direction),
                        column('reset_label', 'reset_marker', direction)],
                        rows=[], row_key='position').props('flat bordered separator=horizontal hide-bottom wrap-cells').classes('erms-page-table w-full')
                    with ui.expansion(t('occupied_title'), icon='info').classes('w-full') as occupied:
                        occupied_text = ui.label('').classes('text-sm')
                    occupied.set_visibility(False)
                with ui.tab_panel('history').classes('p-0 gap-3'):
                    history_host = ui.column().classes('w-full gap-3')
        controls['reason'] = ui.textarea(t('reason_create' if creating else 'reason_edit')).props('outlined dense rows=2').classes('w-full')
        feedback = ui.label('').props('role=alert').classes('text-negative text-sm')
        with ui.row().classes('w-full justify-end items-center gap-2'):
            reload_button = ui.button(t('reload')).props('outline no-caps').tooltip(t('reload_help'))
            reload_button.set_visibility(False)
            cancel = ui.button(t('cancel'), on_click=dialog.close).props('flat no-caps')
            save_button = ui.button(t('save'), icon='save').props('unelevated no-caps')
    dialog.open()

    def live():
        return active() and dialog.value and not target_host.is_deleted

    def scenario_options():
        choices = {key: t(key) for key in ('same_scope', 'year_transition', 'month_transition', 'different_scopes')}
        if controls['scope'].value != 'generator' and controls['reset_frequency'].value != 'never':
            choices['combined'] = t('combined')
        return choices

    def update_capacity():
        maximum = ((target.get('field') or {}).get('max_length') if target['mode'] == 'specific' else
                   200 if target.get('primary') in {'assigned_location', 'current_location'} else None)
        capacity.text = t('capacity', maximum=maximum) if maximum is not None else ''

    def changed(*_):
        if not live():
            return
        state['preview_revision'] += 1
        if state['timer']:
            state['timer'].active = False
        options = scenario_options()
        selected = scenario.value if scenario.value in options else 'same_scope'
        if scenario.options != options or scenario.value != selected:
            scenario.set_options(options, value=selected)
        preview_table.rows = []
        preview_table.update()
        preview_button.props(remove='loading')
        occupied.set_visibility(False)
        warning.text = timezone.text = ''
        pattern_warning.text = ''
        if not state['stale']:
            feedback.text = ''
        preview_status.text = t('preview_stale' if state['preview_requested'] else 'preview_prompt')
        if state['preview_requested'] and not state['busy']:
            state['timer'] = ui.timer(.35, lambda: preview_now(automatic=True), once=True)

    def target_error(error):
        if live():
            feedback.text = on_error(error)
            target_retry.set_visibility(True)

    async def build_targets():
        target['revision'] += 1
        revision = target['revision']
        target['ready'] = False
        target_host.clear()
        with target_host:
            ui.spinner(size='sm')
        try:
            captured_kind = target['kind']
            pending = []
            if captured_kind not in primary_catalogue:
                pending.append(('primary', api.request('GET', BASE + '/targets/primary', params={'kind': captured_kind})))
            if (target.get('type') or {}).get('_unresolved'):
                pending.append(('type', api.request('GET', BASE + '/targets/types', params={
                    'kind': captured_kind, 'selected': target['type']['id'], 'limit': 1})))
            if target.get('field') and 'max_length' not in target['field']:
                pending.append(('field', api.request('GET', BASE + '/targets/fields', params={
                    'kind': captured_kind, 'type_id': target['type']['id'],
                    'selected': target['field']['id'], 'limit': 1})))
            results = await asyncio.gather(*(call for _, call in pending))
        except ApiError as error:
            if live() and revision==target['revision']:
                target_host.clear()
                target_error(error)
            return
        if not live() or revision != target['revision']:
            return
        for (name,_), result in zip(pending,results):
            if name == 'primary':
                primary_catalogue[captured_kind] = result
            elif name == 'type':
                target['type'] = next((item for item in result['items'] if item['id']==target['type']['id']),None)
            else:
                target['field'] = next((item for item in result['items'] if item['id']==target['field']['id']),None)
        primary = primary_catalogue[captured_kind]
        target_host.clear()
        with target_host:
            if target['mode'] == 'primary':
                selector = ui.select({item['key']: render_message_plain(PRIMARY_LABELS[item['key']])
                    for item in primary['items']}, value=target.get('primary'), label=t('field')).props('outlined dense clearable').classes('w-full')
                def primary_changed(event):
                    target['primary'] = event.value
                    update_capacity(); changed()
                selector.on_value_change(primary_changed)
                applicability = ui.select({key:t(label) for key,label in APPLIES_TO.items()},
                    value=target['applies_to'],label=t('applies_to')).props('outlined dense').classes('w-full')
                async def applicability_changed(event):
                    target['applies_to'] = event.value
                    if target['applies_to']!='type':
                        target['type'] = None
                    await build_targets()
                    changed()
                applicability.on_value_change(applicability_changed)
            if target['mode'] == 'specific' or target['applies_to']=='type':
                def current():
                    return live() and revision == target['revision']
                owner = target.get('type')
                selections = dict(type=0,field=0)
                type_rows = {owner['id']:owner} if owner and not owner.get('_unresolved') else {}
                type_control = relationship_select(t('type'), {owner['id']: owner['name']} if owner else {},
                                                   value=owner['id'] if owner else None, remote=True)
                async def type_page(query):
                    result = await api.request('GET', BASE + '/targets/types', params={
                        'kind': target['kind'], 'q': query, 'limit': 25, 'offset': 0})
                    if current():
                        retained = target.get('type')
                        type_rows.clear()
                        type_rows.update({v['id']:v for v in result['items']})
                        if retained:type_rows[retained['id']]=retained
                    return result
                async def selected_type(identity):
                    if identity in type_rows:
                        return type_rows[identity]
                    page = await api.request('GET', BASE + '/targets/types', params={
                        'kind': target['kind'], 'selected': identity, 'limit': 1})
                    selected = next((v for v in page['items'] if v['id'] == identity), None)
                    if selected is None:
                        raise ApiError(404,t('unbound'))
                    return selected
                bind_relationship(type_control, 'resource-types', ('name',), ('name',),
                    page_loader=type_page, selected_loader=selected_type, active=current)
                async def choose_type(event):
                    if not current() or event.value == (target.get('type') or {}).get('id'):
                        return
                    selections['type'] += 1
                    request = selections['type']
                    target['ready'], target['field'] = False, None
                    target['type'] = ({'id':event.value,'name':type_control.options.get(event.value,str(event.value)),'_unresolved':True}
                                      if event.value else None)
                    changed()
                    try:
                        selected = await selected_type(event.value) if event.value else None
                    except ApiError as error:
                        if current() and request==selections['type']:target_error(error)
                        return
                    if not current() or request!=selections['type']:
                        return
                    target['type'], target['field'] = selected, None
                    await build_targets()
                    changed()
                type_control.on_value_change(choose_type)
                async def browse_type():
                    try:
                        selected = await pick(api, BASE + '/targets/types', t('type'), params={'kind': target['kind']})
                    except ApiError as error:
                        target_error(error)
                        return
                    if selected and current():
                        target['type'], target['field'] = selected, None
                        await build_targets()
                        changed()
                ui.button(render_message_plain('settings.action.browse'), icon='search', on_click=browse_type).props('outline dense no-caps')
                if target['mode'] == 'specific' and owner:
                    selected = target.get('field')
                    field_rows = {selected['id']:selected} if selected else {}
                    field_control = relationship_select(t('field'), {selected['id']: selected['name']} if selected else {},
                        value=selected['id'] if selected else None, remote=True)
                    params = {'kind': target['kind'], 'type_id': owner['id']}
                    async def field_page(query):
                        result = await api.request('GET', BASE + '/targets/fields', params={**params, 'q': query, 'limit': 25})
                        if current():
                            retained = target.get('field')
                            field_rows.clear()
                            field_rows.update({v['id']:v for v in result['items']})
                            if retained:field_rows[retained['id']]=retained
                        return result
                    async def selected_field(identity):
                        if identity in field_rows:
                            return field_rows[identity]
                        page = await api.request('GET', BASE + '/targets/fields', params={**params, 'selected': identity, 'limit': 1})
                        selected = next((v for v in page['items'] if v['id'] == identity), None)
                        if selected is None:
                            raise ApiError(404,t('unbound'))
                        return selected
                    bind_relationship(field_control, 'resource-type-fields', ('name',), ('name',),
                        page_loader=field_page, selected_loader=selected_field, active=current)
                    async def choose_field(event):
                        if not current():
                            return
                        selections['field'] += 1
                        request = selections['field']
                        target['ready'] = False
                        target['field'] = ({'id':event.value,'name':field_control.options.get(event.value,str(event.value))}
                                           if event.value else None)
                        changed()
                        try:
                            selected = await selected_field(event.value) if event.value else None
                        except ApiError as error:
                            if current() and request==selections['field']:target_error(error)
                            return
                        if current() and request==selections['field']:
                            target['field'] = selected
                            target['ready'] = True
                            update_capacity(); changed()
                    field_control.on_value_change(choose_field)
                    async def browse_field():
                        try:
                            selected = await pick(api, BASE + '/targets/fields', t('field'), params=params)
                        except ApiError as error:
                            target_error(error)
                            return
                        if selected and current():
                            target['field'] = selected
                            field_rows.clear()
                            field_rows[selected['id']]=selected
                            field_control.set_options({selected['id']: selected['name']}, value=selected['id'])
                            update_capacity(); changed()
                    ui.button(render_message_plain('settings.action.browse'), icon='search', on_click=browse_field).props('outline dense no-caps')
        target['ready'] = True
        target_retry.set_visibility(False)
        update_capacity()

    async def context_changed(*_):
        target.update(kind=kind.value, mode=mode.value, type=None, field=None,
                      applies_to='type' if mode.value=='specific' else target['applies_to'], primary=
                      ('record_number' if kind.value == 'record' else 'aggregation_number') if mode.value == 'primary' else None)
        changed()
        await build_targets()
    kind.on_value_change(context_changed)
    mode.on_value_change(context_changed)
    for control in [*(control for name,control in controls.items() if name!='reason'), sample_date, scenario,
                    *(c for group in sample_controls.values() for c in group.values())]:
        control.on_value_change(changed)
    changed()

    async def preview_now(*_, automatic=False):
        if not live() or state['busy']:
            return
        state['preview_requested'] = True
        state['preview_revision'] += 1
        revision = state['preview_revision']
        preview_table.rows = []; preview_table.update(); occupied.set_visibility(False)
        preview_button.props('loading')
        try:
            body = dict(configuration=configuration(controls, target), scenario=scenario.value,
                        sample_date=sample_date.value,
                        context_a={k: c.value or None for k, c in sample_controls['A'].items()},
                        context_b={k: c.value or None for k, c in sample_controls['B'].items()})
            if row:
                body['generator_id'] = row['id']
            preview_status.text = t('preview_loading')
            result = await api.request('POST', BASE + '/preview', json=body, _cancellable_read=True)
            if not live() or revision != state['preview_revision']:
                return
            preview_table.rows = [{**item, 'position': index,
                'scope_label': t('scope_generator') if item['scope_kind'] == 'generator' else t('scope_a' if item['scope_id'] == 1 else 'scope_b'),
                'characters': len(item['value']), 'reset_label': t('reset_marker') if item['reset'] else ''}
                for index, item in enumerate(result['items'], 1)]
            preview_table.update()
            preview_status.text = ''
            timezone.text = t('timezone', timezone=result['working_timezone'])
            warning.text = t('yy_warning') if 'two_digit_year_repeats' in result.get('warnings', []) else ''
            pattern_warning.text = t('independent_pattern') if 'independent_number_pattern' in result.get('warnings', []) else ''
            unique = body['configuration']['primary_field'] in {'record_number', 'aggregation_number'}
            occupied.set_visibility(unique)
            if unique:
                occupied_text.text = t('occupied_help', occupied=result['items'][0]['value'], next=result['items'][1]['value'])
        except (InvalidForm, ApiError) as error:
            if live() and revision == state['preview_revision']:
                preview_status.text = form_error(error, on_error)
        finally:
            if live() and revision == state['preview_revision']:
                preview_button.props(remove='loading')
    preview_button.on_click(preview_now)

    def freeze(value):
        state['busy'] = value
        state['preview_revision'] += 1
        preview_button.props(remove='loading')
        if value:
            dialog.props('persistent')
            state['frozen'] = [(element,element.enabled) for element in card.descendants()
                               if hasattr(element,'set_enabled')]
            for element,_ in state['frozen']:element.disable()
            save_button.props('loading')
        else:
            dialog.props(remove='persistent')
            for element,enabled in state.get('frozen',[]):
                if not element.is_deleted:element.set_enabled(enabled)
            save_button.props(remove='loading')

    async def save():
        if not live() or state['busy'] or state['stale']:
            return
        try:
            payload = configuration(controls, target, allow_unbound=not creating)
            reason = controls['reason'].value or ''
            if not creating and not reason.strip():
                raise InvalidForm('reason')
        except InvalidForm as error:
            feedback.text = form_error(error, on_error)
            tabs.value = 'settings'
            return
        freeze(True)
        try:
            headers = {'X-Change-Reason': reason} if reason.strip() else {}
            if row:
                headers['If-Match'] = str(row['version'])
            result = await api.request('POST' if creating else 'PUT', BASE + ('' if creating else f"/{row['id']}"),
                                       json=payload, headers=headers)
            if not live():
                return
            dialog.close()
            if active():
                ui.notify(t('saved'), color='positive')
                if 'independent_number_pattern' in result.get('warnings', []):
                    ui.notify(t('independent_pattern'), color='warning', timeout=10000)
                await on_saved()
        except ApiError as error:
            if live():
                if error.status_code == 412:
                    state['stale'] = True
                    feedback.text = t('conflict')
                    reload_button.set_visibility(True)
                else:
                    feedback.text = form_error(error, on_error)
        finally:
            if live():
                freeze(False)
                save_button.set_enabled(not state['stale'])
    save_button.on_click(save)

    async def reload_saved():
        if not live() or not row or state['busy']:
            return
        try:
            fresh = await api.request('GET', f"{BASE}/{row['id']}")
        except ApiError as error:
            feedback.text = on_error(error)
            return
        if live():
            dialog.close()
            await edit_generator(api=api, row=fresh, active=active, on_error=on_error,
                bind_relationship=bind_relationship, direction=direction, on_saved=on_saved,
                render_history=render_history, can_audit=can_audit)
    reload_button.on_click(reload_saved)
    if row:
        load_history = await generator_history(api=api, row=row, host=history_host, active=live, on_error=on_error,
                                               render_history=render_history, allowed=can_audit)
        async def history_selected(event):
            if event.value=='history' and load_history is not None and live():
                await load_history()
        tabs.on_value_change(history_selected)
    else:
        with history_host:
            ui.label(t('history_new')).classes('text-sm text-slate-500')
    await build_targets()
    if 'independent_number_pattern' in initial.get('warnings', []):
        pattern_warning.text = t('independent_pattern')
    # Test callers and view owners receive only this dialog's ephemeral state.
    return dict(dialog=dialog, controls=controls, target=target, state=state,
                preview=preview_now, table=preview_table, save=save, tabs=tabs,
                save_button=save_button, feedback=feedback, scenario=scenario,
                sample_date=sample_date, sample_controls=sample_controls)


async def generator_history(*, api, row, host, active, on_error, render_history, allowed):
    """Reuse the shared immutable timeline; no audit privilege is inferred."""
    with host:
        if not allowed() or render_history is None:
            ui.label(t('history_denied')).classes('text-sm text-slate-500')
            return None
        state = dict(offset=0, revision=0, loaded=False, more=False)
        with ui.row().classes('w-full gap-2 items-center justify-end'):
            refresh = ui.button(t('refresh'), icon='refresh').props('outline dense no-caps')
            previous = ui.button(render_message_plain('relationships.ui.previous')).props('flat dense no-caps')
            following = ui.button(render_message_plain('relationships.ui.next')).props('flat dense no-caps')
        feedback = ui.label('').props('role=status').classes('text-sm text-slate-500')
        timeline = ui.column().classes('w-full gap-2')
    previous.disable(); following.disable()

    async def load(delta=0):
        if not active() or not allowed():
            return
        state['offset'] = max(0, state['offset'] + delta * 25)
        state['revision'] += 1
        revision = state['revision']
        refresh.disable(); previous.disable(); following.disable()
        try:
            events = await api.history('code-generators', row['id'], limit=26, offset=state['offset'])
            if not active() or revision != state['revision'] or not allowed():
                return
            state['loaded'], state['more'] = True, len(events) > 25
            render_history([{**event, '_current_entity': row} for event in events[:25]], timeline)
            feedback.text = ''
        except ApiError as error:
            if active() and revision == state['revision']:
                feedback.text = on_error(error)
        finally:
            if active() and revision == state['revision']:
                refresh.enable()
                previous.set_enabled(state['offset'] > 0)
                following.set_enabled(state['more'])
    refresh.on_click(lambda: load())
    previous.on_click(lambda: load(-1))
    following.on_click(lambda: load(1))
    return load


async def counter_dialog(*, api, row, active, on_error, direction):
    """One scope/period, exact serial strings and optimistic counter versions."""
    state = dict(loaded=None, revision=0, busy=False)
    dialog = ui.dialog().props('full-width')
    with dialog, ui.card().classes('messaging-workspace w-full max-h-[calc(100vh-32px)] overflow-y-auto gap-3'):
        with ui.row().classes('w-full items-center'):
            ui.label(t('counters') + ' · ' + row['name']).classes('text-xl font-semibold grow')
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').tooltip(t('cancel'))
        ui.label(t('counter_help')).classes('text-sm text-slate-600')
        with ui.grid(columns='repeat(auto-fit,minmax(min(100%,260px),1fr))').classes('w-full gap-3'):
            scope = ui.select({k: t(v) for k, v in SCOPES.items()}, value=row['scope'], label=t('scope')).props('outlined dense')
            scope_id = ui.input(t('scope_id'), value='0' if row['scope'] == 'generator' else '').props('outlined dense inputmode=numeric')
            reset = ui.select({k: t(v) for k, v in RESETS.items()}, value=row['reset_frequency'], label=t('reset')).props('outlined dense')
            period = ui.input(t('period'), value='0001-01-01' if row['reset_frequency'] == 'never' else '').props('outlined dense type=date')
        scope_name = ui.label('').classes('text-sm text-primary')
        ui.label(t('scope_id_help')).classes('text-xs text-slate-500')
        ui.label(t('bucket_help')).classes('text-xs text-slate-500')
        with ui.row().classes('w-full gap-2'):
            browse = ui.button(render_message_plain('settings.action.browse'), icon='search').props('outline no-caps')
            inspect = ui.button(t('inspect'), icon='refresh').props('outline no-caps')
        current_next = ui.label('').props('role=status').classes('text-sm text-slate-600 break-all')
        desired = ui.input(t('next_number')).props('outlined dense inputmode=numeric').classes('w-full')
        reason = ui.textarea(t('reason_edit')).props('outlined dense rows=2').classes('w-full')
        feedback = ui.label('').props('role=alert').classes('text-negative text-sm')
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button(t('cancel'), on_click=dialog.close).props('flat no-caps')
            advance = ui.button(t('advance'), icon='trending_up').props('unelevated no-caps')
        table_host = ui.column().classes('w-full gap-2')
    dialog.open()

    def live():
        return active() and dialog.value and not table_host.is_deleted

    def key():
        identity = whole_text(scope_id.value, 'scope_id', maximum=2**63-1)
        if scope.value == 'generator' and identity != 0 or scope.value != 'generator' and identity == 0:
            raise InvalidForm('scope_id')
        try:
            day = date.fromisoformat(period.value or '')
        except ValueError:
            raise InvalidForm('period_bucket') from None
        if (reset.value == 'never' and day != date(1,1,1) or
            reset.value == 'yearly' and (day.month,day.day) != (1,1) or
            reset.value == 'monthly' and day.day != 1):
            raise InvalidForm('period_bucket')
        return dict(scope_kind=scope.value, scope_id=identity,
                    reset_frequency=reset.value, period_bucket=day.isoformat())

    def invalidate(*_):
        state['revision'] += 1
        state['loaded'] = None
        current_next.text = ''
        scope_name.text = ''
        advance.disable()
        browse.set_enabled(scope.value != 'generator' and not state['busy'])
        scope_id.set_enabled(scope.value != 'generator' and not state['busy'])
        period.set_enabled(reset.value != 'never' and not state['busy'])

    def change_scope(*_):
        scope_id.value = '0' if scope.value == 'generator' else ''
        desired.value = ''
        invalidate()
    def change_reset(*_):
        period.value = '0001-01-01' if reset.value == 'never' else ''
        desired.value = ''
        invalidate()
    scope.on_value_change(change_scope); reset.on_value_change(change_reset)
    scope_id.on_value_change(invalidate); period.on_value_change(invalidate)

    async def load():
        if not live() or state['busy']:
            return
        invalidate()
        revision = state['revision']
        try:
            params = key()
            result = await api.request('GET', f"{BASE}/{row['id']}/counter", params=params)
            if not live() or revision != state['revision']:
                return
            state['loaded'] = dict(key=params, version=result['version'])
            current_next.text = t('next_number') + ' · ' + result['next_number']
            if not desired.value:
                desired.value = result['next_number']
            feedback.text = ''
            advance.enable()
        except (InvalidForm, ApiError) as error:
            if live() and revision == state['revision']:
                feedback.text = form_error(error, on_error)
    inspect.on_click(load)

    async def browse_scope():
        resource, fields = {'parent_aggregation': ('aggregations', ('aggregation_number','title')),
            'classification': ('classifications', ('code','title')), 'org_unit': ('org-units', ('code','name'))}[scope.value]
        captured = scope.value
        submitted = ''
        with ui.dialog() as picker, ui.card().classes('messaging-workspace w-full max-w-3xl'):
            ui.label(t(SCOPES[captured])).classes('text-lg font-semibold')
            with ui.row().classes('w-full items-center'):
                query = ui.input(t('apply')).props('outlined dense clearable').classes('grow')
                async def search():
                    nonlocal submitted
                    submitted = (query.value or '').strip()
                    await choices.load(reset=True)
                ui.button(t('apply'), icon='search', on_click=search).props('outline no-caps')
                query.on('keydown.enter', search)
            async def fetch(p):
                page = await api.relationship_page(resource, fields, submitted, limit=p.size, offset=(p.page-1)*p.size)
                labels = relationship_options(page['items'], fields)
                for item in page['items']:
                    item['display_name'] = labels[item['id']]
                return page
            choices = PageTable(columns=[column('display_name', 'scope_id', direction)], fetch=fetch,
                active=lambda: live() and picker.value and scope.value == captured,
                on_error=on_error, empty='', empty_text=lambda:t('scope_empty'), selection='single', wrap_cells=True)
            async def choose():
                if choices.table.selected and live() and scope.value == captured:
                    selected = choices.table.selected[0]
                    scope_id.value = str(selected['id'])
                    picker.close()
                    await load()
                    if live():
                        scope_name.text = selected['display_name']
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('cancel'), on_click=picker.close).props('flat no-caps')
                ui.button(t('use_counter'), on_click=choose).props('unelevated no-caps')
        picker.open()
        await choices.load()
    browse.on_click(browse_scope)

    async def fetch(p):
        page = await api.request('GET', f"{BASE}/{row['id']}/counters", params={'limit':p.size,'offset':(p.page-1)*p.size})
        for item in page['items']:
            item['id'] = '|'.join(str(item[name]) for name in ('scope_kind','scope_id','reset_frequency','period_bucket'))
            item['scope_id'] = str(item['scope_id'])
            item['scope_label'], item['reset_label'] = t(SCOPES[item['scope_kind']]), t(RESETS[item['reset_frequency']])
        return page
    with table_host:
        page = PageTable(columns=[column('scope_label','scope',direction), column('scope_id','scope_id',direction),
            column('reset_label','reset',direction), column('period_bucket','period',direction),
            column('next_number','next_number',direction), column('actions','actions',direction)],
            fetch=fetch, active=live, on_error=on_error, empty='', empty_text=lambda:t('counter_empty'), wrap_cells=True)
        page.table.add_slot('body-cell-actions', '<q-td :props="props"><q-btn flat dense icon="edit" aria-label="'+escape(t('use_counter'))+
            '" @click="$parent.$emit(\'choose-counter\', props.row.id)"><q-tooltip>'+escape(t('use_counter'))+'</q-tooltip></q-btn></q-td>')
    async def choose_counter(event):
        selected = next((v for v in page.table.rows if v['id']==event.args),None)
        if selected and live() and not state['busy']:
            scope.value, reset.value = selected['scope_kind'], selected['reset_frequency']
            scope_id.value, period.value = str(selected['scope_id']), selected['period_bucket']
            desired.value = ''
            await load()
    page.table.on('choose-counter', choose_counter)

    async def apply():
        if not live() or state['busy'] or state['loaded'] is None:
            return
        try:
            selection = key()
            if selection != state['loaded']['key']:
                raise InvalidForm('scope_id')
            value = whole_text(desired.value, 'next_number')
            if not (reason.value or '').strip():
                raise InvalidForm('reason')
        except InvalidForm as error:
            feedback.text = form_error(error, on_error)
            return
        state['busy'] = True
        for control in (scope,scope_id,reset,period,desired,reason,advance,inspect,browse):
            control.disable()
        try:
            await api.request('POST', f"{BASE}/{row['id']}/counter/advance",
                json={**selection,'next_number':value},
                headers={'If-Match':str(state['loaded']['version']),'X-Change-Reason':reason.value})
            if live():
                ui.notify(t('adjusted'),color='positive')
                reason.value = ''
                await page.load()
        except ApiError as error:
            if live():
                feedback.text = t('counter_stale') if error.status_code==412 else on_error(error)
        finally:
            state['busy'] = False
            if live():
                for control in (scope,reset,desired,reason,inspect):
                    control.enable()
                invalidate()  # A success or unknown response must be reread.
    advance.on_click(apply)
    invalidate()
    await page.load()
    return dict(dialog=dialog, state=state, page=page, scope=scope, scope_id=scope_id,
                reset=reset, period=period, desired=desired, reason=reason, load=load, apply=apply)


async def code_generation_page(*, api, container, bind_relationship, active, on_error,
                               direction=lambda:'ltr', render_history=None, can_audit=lambda:False):
    """Server-paged named generators with submitted filters and local dialogs."""
    submitted = dict(q='',kind=None,enabled=None)
    with container:
        host = ui.column().classes('application-settings-page w-full gap-3')
    def live():
        return active() and not host.is_deleted
    async def search():
        submitted.update(q=(query.value or '').strip(),kind=None if kind.value=='all' else kind.value,
                         enabled=None if enabled.value=='all' else enabled.value=='enabled')
        await page.load(reset=True)
    async def edit(row=None):
        if not live():
            return
        try:
            fresh = await api.request('GET',f"{BASE}/{row['id']}") if row else None
            if live():
                return await edit_generator(api=api,row=fresh,active=live,on_error=on_error,
                    bind_relationship=bind_relationship,direction=direction,on_saved=page.load,
                    render_history=render_history,can_audit=can_audit)
        except ApiError as error:
            if live():
                ui.notify(on_error(error),color='negative')
    with host:
        ui.label(t('future_help')).classes('text-sm text-slate-600')
        with ui.row().classes('w-full gap-2 items-center'):
            query = ui.input(t('search')).props('outlined dense clearable').classes('grow')
            kind = ui.select({'all':t('all'),**{k:render_message_plain(v) for k,v in KINDS.items()}},
                             value='all',label=t('resource')).props('outlined dense')
            enabled = ui.select({'all':t('all'),'enabled':t('enabled'),'disabled':t('disabled')},
                                value='all',label=t('status')).props('outlined dense')
            ui.button(t('apply'),icon='search',on_click=search).props('outline no-caps')
            ui.button(t('new'),icon='add',on_click=lambda:edit()).props('unelevated no-caps')
        query.on('keydown.enter',search)
        async def fetch(p):
            result = await api.request('GET',BASE,params={k:v for k,v in {
                **submitted,'limit':p.size,'offset':(p.page-1)*p.size,'descending':p.descending}.items() if v is not None})
            for row in result['items']:
                row['reference'] = str(row['id'])
                row['target_label'] = target_label(row)
                row['status_label'] = t('enabled' if row['enabled'] else 'disabled')
                row['bound'] = bool(row.get('primary_field') or row.get('field_id'))
            return result
        page = PageTable(columns=[column('name','name_header',direction,True),column('target_label','target',direction),
            column('pattern','pattern_header',direction),column('status_label','status',direction),
            column('actions','actions',direction)],fetch=fetch,active=live,on_error=on_error,empty='',
            empty_text=lambda:t('empty'),loading_text=lambda:t('loading'),wrap_cells=True,initial={'sort':'name'})
        page.table.props('row-key=reference')
        actions = [('edit','edit','edit'),('counters','tag','counters'),('unbind','link_off','unbind'),('delete','delete','delete')]
        page.table.add_slot('body-cell-actions','<q-td :props="props"><div class="row no-wrap items-center gap-1">'+''.join(
            '<q-btn flat dense icon="'+icon+'" aria-label="'+escape(t(title))+'" '+
            ('v-if="props.row.bound" ' if action=='unbind' else '')+
            '@click="$parent.$emit(\''+action+'\', props.row.reference)"><q-tooltip>'+escape(t(title))+'</q-tooltip></q-btn>'
            for action,icon,title in actions)+'</div></q-td>')
        ui.button(t('refresh'),icon='refresh',on_click=page.load).props('outline no-caps')

    def selected(identity):
        return next((row for row in page.table.rows if str(row['id'])==str(identity)),None)
    page.table.on('edit',lambda event:edit(selected(event.args)) if selected(event.args) else None)
    async def counters(event):
        row = selected(event.args)
        if row and live():
            try:
                fresh = await api.request('GET',f"{BASE}/{row['id']}")
                if live():
                    await counter_dialog(api=api,row=fresh,active=live,on_error=on_error,direction=direction)
            except ApiError as error:
                if live():
                    ui.notify(on_error(error),color='negative')
    page.table.on('counters',counters)

    async def remove(event, *, unbind):
        row = selected(event.args)
        if not row or not live():
            return
        # Read current settings before presenting the reasoned operation.
        try:
            fresh = await api.request('GET',f"{BASE}/{row['id']}")
        except ApiError as error:
            if live():ui.notify(on_error(error),color='negative')
            return
        if not live():return
        with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-full max-w-xl gap-3'):
            ui.label(t('unbind' if unbind else 'delete')+' · '+fresh['name']).classes('text-lg font-semibold')
            ui.label(t('unbind_help' if unbind else 'delete_help')).classes('text-sm')
            reason = ui.textarea(t('reason_edit')).props('outlined dense rows=2').classes('w-full')
            feedback = ui.label('').props('role=alert').classes('text-negative text-sm')
            busy = False
            async def apply():
                nonlocal busy
                if busy or not dialog.value or not live():return
                if not (reason.value or '').strip():
                    feedback.text=t('required')
                    return
                busy=True;button.disable()
                try:
                    await api.request('DELETE',f"{BASE}/{fresh['id']}"+('/binding' if unbind else ''),
                        headers={'If-Match':str(fresh['version']),'X-Change-Reason':reason.value})
                    dialog.close()
                    if live():
                        if unbind:ui.notify(t('removed'),color='positive')
                        await page.load()
                except ApiError as error:
                    if dialog.value and live():feedback.text=on_error(error)
                finally:
                    busy=False
                    if dialog.value and live():button.enable()
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('cancel'),on_click=dialog.close).props('flat no-caps')
                button=ui.button(t('unbind' if unbind else 'delete'),on_click=apply).props('unelevated no-caps')
        dialog.open()
    page.table.on('unbind',lambda event:remove(event,unbind=True))
    page.table.on('delete',lambda event:remove(event,unbind=False))
    await page.load()
    return dict(page=page,host=host,submitted=submitted,query=query,kind=kind,enabled=enabled,
                search=search,edit=edit,refresh=page.load)
