"""Named-link panels and catalogue administration; no cross-page data cache."""
import asyncio
from html import escape
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message_plain
from .locale_services import current_locale_context
from .remote_select import RemoteSelect

# Literal keys let catalogue validation prove coverage for every control.
RELATIONSHIP_MESSAGE_KEYS = {
    'target_search_hint': 'relationships.ui.target_search_hint', 'title': 'relationships.ui.title', 'catalogue': 'relationships.ui.catalogue',
    'aggregation': 'relationships.ui.aggregation', 'record': 'relationships.ui.record',
    'add': 'relationships.ui.add', 'remove': 'relationships.ui.remove',
    'refresh': 'relationships.ui.refresh', 'type': 'relationships.ui.type',
    'target': 'relationships.ui.target', 'direction': 'relationships.ui.direction',
    'empty': 'relationships.ui.empty', 'loading': 'relationships.ui.loading',
    'redacted': 'relationships.ui.redacted', 'deactivated': 'relationships.ui.deactivated',
    'active': 'relationships.ui.active', 'status': 'relationships.ui.status',
    'actions': 'relationships.ui.actions', 'open': 'relationships.ui.open',
    'cancel': 'relationships.ui.cancel', 'save': 'relationships.ui.save',
    'confirm_remove': 'relationships.ui.confirm_remove',
    'code': 'relationships.ui.code', 'forward': 'relationships.ui.forward', 'english_forward': 'relationships.ui.english_forward',
    'reverse': 'relationships.ui.reverse', 'english_reverse': 'relationships.ui.english_reverse', 'arabic_forward': 'relationships.ui.arabic_forward',
    'arabic_reverse': 'relationships.ui.arabic_reverse', 'symmetric': 'relationships.ui.symmetric',
    'edit': 'relationships.ui.edit', 'new_type': 'relationships.ui.new_type',
    'delete_type': 'relationships.ui.delete_type', 'confirm_delete': 'relationships.ui.confirm_delete',
    'search': 'relationships.ui.search', 'no_types': 'relationships.ui.no_types',
    'catalogue_help': 'relationships.ui.catalogue_help', 'link_help': 'relationships.ui.link_help',
    'required': 'relationships.ui.required', 'page_size': 'relationships.ui.page_size',
    'page_count': 'relationships.ui.page_count', 'previous': 'relationships.ui.previous', 'next': 'relationships.ui.next', 'preview': 'relationships.ui.preview',
}


def text(name, **parameters):
    return render_message_plain(RELATIONSHIP_MESSAGE_KEYS[name], **parameters)


def language():
    return current_locale_context()[0]


def link_row(item, can_link):
    target = item['related']
    return {**item, 'target_label': text('redacted') if target['redacted'] else
            ' · '.join(str(part) for part in (target['number'], target['title']) if part),
            'status': text('active' if item['is_active'] else 'deactivated'),
            'can_open': not target['redacted'], 'can_remove': can_link and not target['redacted']}


class PageTable:
    """Server pagination with revision and active-page guards, no cached results."""
    def __init__(self, *, columns, fetch, active, on_error, empty):
        self.fetch, self.active, self.on_error = fetch, active, on_error
        self.revision = 0
        self.page, self.size, self.sort, self.descending = 1, 25, '', False
        self.status = ui.label('').classes('text-sm text-slate-500').props('role=status')
        self.table = ui.table(columns=columns, rows=[], row_key='id', pagination={
            'page': 1, 'rowsPerPage': 25, 'rowsNumber': 0,
        }).props('flat bordered separator=horizontal :rows-per-page-options="[10,25,50]"').classes('erms-page-table w-full')
        self.empty = empty
        self.total = 0
        self.table.props('hide-bottom')
        self.no_data = ui.label('').classes('text-sm text-slate-500').props('role=status')
        with ui.row().classes('w-full items-center justify-end gap-3'):
            self.page_size = ui.select([10,25,50],value=25,label=text('page_size')).props('outlined dense').classes('w-40')
            self.count = ui.label('').classes('text-sm text-slate-500')
            self.previous = ui.button(text('previous'),icon='chevron_right' if language() == 'ar' else 'chevron_left',on_click=lambda:self.move(-1)).props('flat dense no-caps')
            self.next = ui.button(text('next'),icon='chevron_left' if language() == 'ar' else 'chevron_right',on_click=lambda:self.move(1)).props('flat dense no-caps')
        self.previous.disable()
        self.next.disable()
        self.page_size.on_value_change(self.resize)
        self.table.on('request', self.request)

    async def move(self, delta):
        self.page = max(1, self.page + delta)
        await self.load()

    async def resize(self, event):
        self.size = int(event.value)
        await self.load(reset=True)


    async def request(self, event):
        pagination = event.args['pagination']
        self.page = max(1, int(pagination['page']))
        self.size = int(pagination['rowsPerPage'])
        self.sort = pagination.get('sortBy') or ''
        self.descending = bool(pagination.get('descending'))
        await self.load()

    async def load(self, reset=False):
        if not self.active() or self.table._deleted:
            return
        if reset:
            self.page = 1
        self.revision += 1
        revision = self.revision
        self.table.props('loading')
        self.status.text = text('loading')
        self.no_data.text = ''
        try:
            result = await self.fetch(self)
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if revision == self.revision and self.active() and not self.table._deleted:
                self.table.rows = []
                self.table.props(remove='loading')
                self.status.text = self.on_error(error)
                self.no_data.text = ''
                self.previous.disable()
                self.next.disable()
                self.count.text = ''
                self.table.update()
            return
        if revision != self.revision or not self.active() or self.table._deleted:
            return
        # A final row may have been removed on the last page.
        last_page = max(1, (result['total'] + self.size - 1) // self.size)
        if self.page > last_page:
            self.page = last_page
            await self.load()
            return
        self.total = result['total']
        self.table.rows = result['items']
        self.table.pagination = {'page': self.page, 'rowsPerPage': self.size,
                                 'rowsNumber': result['total'], 'sortBy': self.sort,
                                 'descending': self.descending}
        self.status.text = ''
        self.no_data.text = text(self.empty) if not self.total else ''
        self.count.text = text('page_count', first=(self.page-1)*self.size+1 if self.total else 0, last=min(self.page*self.size,self.total),total=self.total)
        self.previous.set_enabled(self.page > 1)
        self.next.set_enabled(self.page*self.size < self.total)
        self.table.props(remove='loading')
        self.table.update()


def column(name, label, sortable=False):
    return {'name': name, 'label': text(label), 'field': name, 'align': 'right' if language() == 'ar' else 'left', 'sortable': sortable}


async def relationship_panel(*, api, kind, identity, source_label, can_link, active,
                             open_target, bind_remote, on_error, browse_resource=None):
    lang = language()
    base = f'/api/v1/relationships/{kind}/{identity}'
    with ui.card().classes('detail-surface messaging-workspace w-full p-5 gap-3') as host:
        def alive():
            return active() and not host._deleted
        with ui.row().classes('w-full items-center justify-between'):
            ui.label(text('title')).classes('text-xl font-semibold')
            with ui.row():
                ui.button(text('refresh'), icon='refresh', on_click=lambda: page.load()).props('flat no-caps')
                if can_link:
                    ui.button(text('add'), icon='add_link', on_click=lambda: add_link()).props('outline no-caps')
        async def fetch(p):
            result = await api.request('GET', base, params={'limit': p.size, 'offset': (p.page-1)*p.size,
                'sort': 'type' if p.sort == 'label' else 'id', 'descending': p.descending, 'language_tag': lang})
            result['items'] = [link_row(row, can_link) for row in result['items']]
            return result
        page = PageTable(columns=[column('label', 'type', True), column('target_label', 'target'),
                                  column('status', 'status'), column('actions', 'actions')],
                         fetch=fetch, active=alive, on_error=on_error, empty='empty')
        page.table.add_slot('body-cell-target_label', '''
            <q-td :props="props"><span dir="auto">{{ props.row.target_label }}</span></q-td>''')
        page.table.add_slot('body-cell-actions', '''
            <q-td :props="props"><div class="row items-center no-wrap gap-1">
            <q-btn v-if="props.row.can_open" flat dense icon="open_in_new" aria-label="''' + escape(text('open')) + '''"
                @click="$parent.$emit('open-target', props.row.id)"><q-tooltip>''' + escape(text('open')) + '''</q-tooltip></q-btn>
            <q-btn v-if="props.row.can_remove" flat dense color="negative" icon="link_off" aria-label="''' + escape(text('remove')) + '''"
                @click="$parent.$emit('remove-link', props.row.id)"><q-tooltip>''' + escape(text('remove')) + '''</q-tooltip></q-btn>
            </div></q-td>''')
        async def navigate(event):
            row = next((row for row in page.table.rows if row['id'] == event.args), None)
            if alive() and row and row['can_open']:
                try:
                    await open_target(kind, row['related']['id'])
                except ApiError as error:
                    if alive():
                        ui.notify(on_error(error), color='negative')
        page.table.on('open-target', navigate)

        async def remove(event):
            row = next((row for row in page.table.rows if row['id'] == event.args), None)
            if not alive() or not row or not row['can_remove']:
                return
            with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-full gap-3'):
                ui.label(text('confirm_remove')).classes('text-lg font-semibold')
                ui.label(source_label).props('dir=auto')
                ui.label(row['label'])
                ui.label(row['target_label']).props('dir=auto')
                feedback = ui.label('').classes('text-negative').props('role=alert')
                async def commit():
                    if not alive() or not dialog.value:
                        return
                    button.disable()
                    try:
                        await api.request('DELETE', f"{base}/{row['id']}")
                    except ApiError as error:
                        if alive() and dialog.value:
                            feedback.text = on_error(error)
                            button.enable()
                        return
                    dialog.close()
                    await page.load()
                with ui.row().classes('w-full justify-end'):
                    ui.button(text('cancel'), on_click=dialog.close).props('flat')
                    button = ui.button(text('remove'), on_click=commit, color='negative')
            dialog.open()
        page.table.on('remove-link', remove)

        async def add_link():
            if not alive():
                return
            with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-full gap-3').style('max-width: 600px'):
                ui.label(text('add')).classes('text-xl font-semibold')
                ui.label(text('link_help')).classes('text-sm text-slate-500')
                ui.label(source_label).props('dir=auto')
                type_select = RemoteSelect({}, label=text('type'), with_input=True).props('outlined clearable maxlength=200').classes('w-full')
                target_select = RemoteSelect({}, label=text('target'), with_input=True).props('outlined clearable maxlength=200').classes('w-full')
                ui.label(text('target_search_hint')).classes('text-xs text-slate-500')
                async def browse_target():
                    async def choose(item, browser_active):
                        row = await hydrate_target(api, base, item['id'])
                        if not dialog_active() or not browser_active():
                            return
                        target_select.options = {row['id']: ' · '.join(str(row[field]) for field in ('number','title') if row.get(field))}
                        target_select.value = row['id']
                        target_select.update()
                        update_preview()
                    await browse_resource(target_select, resource_kind=kind, exclude_id=identity,
                                          on_select=choose, active=dialog_active)
                ui.button(render_message_plain('webui.render_condition.button.browse_3bc4c331'), icon='account_tree', on_click=browse_target).props('outline dense no-caps').classes('self-start')
                direction = ui.select({}, label=text('direction'), value=None).props('outlined').classes('w-full')
                preview = ui.label('').classes('text-sm').props('dir=auto')
                feedback = ui.label('').classes('text-negative').props('role=alert')
                types = {}
                async def type_page(query):
                    result = await api.request('GET', f'/api/v1/relationships/types/{kind}', params={'q':query,'limit':25,'language_tag':lang})
                    selected = types.get(type_select.value)
                    types.clear()
                    if selected:
                        types[selected['id']] = selected
                    types.update({row['id']: row for row in result['items']})
                    return result
                async def selected_type(value):
                    row = await api.request('GET', f'/api/v1/relationships/types/{kind}/{value}', params={'language_tag':lang})
                    types[value] = row
                    return row
                def dialog_active():
                    return alive() and dialog.value
                load_types = bind_remote(type_select, 'relationship-types', ('forward_label',), ('forward_label','reverse_label'),
                            page_loader=type_page, selected_loader=selected_type, active=dialog_active)
                load_targets = bind_remote(target_select, kind, ('number','title'), ('number','title'),
                            page_loader=lambda query: api.request('GET', base+'/targets', params={'q':query,'limit':25}),
                            selected_loader=lambda value: hydrate_target(api, base, value), active=dialog_active, min_query_length=2)
                def update_preview(refresh_type=False):
                    row = types.get(type_select.value)
                    if refresh_type and row:
                        direction.options = {'forward': row['forward_label']}
                        if not row['is_symmetric']:
                            direction.options['reverse'] = row['reverse_label']
                        if direction.value not in direction.options:
                            direction.value = 'forward'
                    elif refresh_type:
                        direction.options = {}
                        direction.value = None
                    if refresh_type:
                        direction.update()
                    preview.text = text('preview', source=source_label,
                        relationship=direction.options.get(direction.value, '—'),
                        target=target_select.options.get(target_select.value, '—'))
                type_select.on_value_change(lambda _: update_preview(refresh_type=True))
                target_select.on_value_change(lambda _: update_preview())
                direction.on_value_change(lambda _: update_preview())
                async def commit():
                    if not dialog_active():
                        return
                    if not type_select.value or not target_select.value or not direction.value:
                        feedback.text = text('required')
                        return
                    button.disable()
                    try:
                        await api.request('POST', base, json={'relationship_type_id':type_select.value,
                            'target_id':target_select.value,'direction':direction.value})
                    except ApiError as error:
                        if dialog_active():
                            feedback.text = on_error(error)
                            button.enable()
                        return
                    dialog.close()
                    await page.load(reset=True)
                with ui.row().classes('w-full justify-end'):
                    ui.button(text('cancel'), on_click=dialog.close).props('flat')
                    button = ui.button(text('save'), on_click=commit)
            dialog.open()
            await load_types()
        await page.load()
    return page


async def hydrate_target(api, base, value):
    result = await api.request('GET', base+'/targets', params={'selected_id': value, 'limit':1})
    if not result['items']:
        raise ApiError(404, 'relationship target unavailable')
    return result['items'][0]


async def relationship_administration(*, api, container, active, on_error, supported_languages=()):
    lang = language()
    with container, ui.column().classes('messaging-workspace w-full p-5 gap-3') as host:
        def alive():
            return active() and not host._deleted
        ui.label(text('catalogue_help')).classes('text-sm text-slate-500')
        with ui.tabs(value='aggregation').classes('w-full') as kind:
            ui.tab('aggregation', label=text('aggregation'))
            ui.tab('record', label=text('record'))
        with ui.row().classes('w-full items-center'):
            search = ui.input(text('search')).props('outlined clearable debounce=250 maxlength=200').classes('grow')
            ui.button(text('refresh'), icon='refresh', on_click=lambda: page.load()).props('outline no-caps')
            ui.button(text('new_type'), icon='add', on_click=lambda: edit()).props('outline no-caps')
        async def fetch(p):
            result = await api.request('GET', f'/api/v1/relationships/types/{kind.value}', params={
                'q': search.value or '', 'limit':p.size,'offset':(p.page-1)*p.size,
                'active_only':False,'language_tag':lang,'descending':p.descending})
            result['items'] = [{**row,'status':text('active' if row['is_active'] else 'deactivated')} for row in result['items']]
            return result
        page = PageTable(columns=[column('code','code',True),column('forward_label','forward'),
            column('reverse_label','reverse'),column('status','status'),column('actions','actions')],
            fetch=fetch,active=alive,on_error=on_error,empty='no_types')
        page.table.add_slot('body-cell-actions', '''<q-td :props="props"><div class="row no-wrap gap-1">
            <q-btn flat dense icon="edit" aria-label="''' + escape(text('edit')) + '''" @click="$parent.$emit('edit-type', props.row.id)"><q-tooltip>''' + escape(text('edit')) + '''</q-tooltip></q-btn>
            <q-btn flat dense icon="delete" color="negative" aria-label="''' + escape(text('delete_type')) + '''" @click="$parent.$emit('delete-type', props.row.id)"><q-tooltip>''' + escape(text('delete_type')) + '''</q-tooltip></q-btn>
            </div></q-td>''')
        async def edit(identity=None):
            selected_kind = kind.value
            row = None
            if identity is not None:
                try:
                    row = await api.request('GET', f'/api/v1/relationships/types/{selected_kind}/{identity}')
                except ApiError as error:
                    if alive():
                        ui.notify(on_error(error), color='negative')
                    return
                if not alive() or kind.value != selected_kind:
                    return
            with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-full gap-3').style('max-width: 650px'):
                ui.label(text('edit' if row else 'new_type')).classes('text-xl font-semibold')
                ui.label(text(selected_kind)).classes('text-sm text-slate-500')
                fields = {}
                for name, key, value in [('code','code',(row or {}).get('code','')),
                    ('forward_name','english_forward',(row or {}).get('forward_name','')),
                    ('reverse_name','english_reverse',(row or {}).get('reverse_name',''))]:
                    fields[name] = ui.input(text(key),value=value).props('outlined').classes('w-full')
                    if name == 'code':
                        fields[name].props('input-style="direction: ltr; unicode-bidi: isolate" maxlength=100')
                        if row:
                            fields[name].disable()
                    else:
                        field_direction = 'ltr'
                        fields[name].props(f'maxlength=250 input-style="direction: {field_direction}; unicode-bidi: isolate"')
                translations = {tag: dict(names) for tag, names in (row or {}).get('translations', {}).items()}
                translation_changes = {}
                languages = {item['language_tag']: item for item in supported_languages if item.get('is_enabled', True)}
                def translated_message(key):
                    return render_message_plain(key)
                with ui.expansion(translated_message('entity_translation_editor.expansion.title'), icon='translate').props("dense header-class='text-sm font-medium'").classes('w-full rounded-lg border border-slate-200 bg-slate-50'):
                    language_control = ui.select({tag: f"{item['native_name']} · {item['english_name']}" for tag,item in languages.items()}, label=translated_message('webui.open_editor.select.language_a1337600')).props('outlined dense options-dense').classes('w-full')
                    translated_fields = {name: ui.input(text(key)).props('outlined dense maxlength=250').classes('w-full') for name,key in [('forward_name','forward'),('reverse_name','reverse')]}
                    selected_language = [None]
                    def stage_translation():
                        tag = selected_language[0]
                        if tag:
                            values = {name: (control.value or '').strip() for name,control in translated_fields.items()}
                            if any(values.values()):
                                translations[tag] = values
                                translation_changes[tag] = values
                            elif tag in translations:
                                translations.pop(tag, None)
                                translation_changes[tag] = None
                    def load_translation():
                        stage_translation()
                        tag = language_control.value
                        selected_language[0] = tag
                        direction = languages.get(tag, {}).get('direction', 'ltr')
                        for name,control in translated_fields.items():
                            control.value = translations.get(tag, {}).get(name, '')
                            control.props(f'input-style="direction: {direction}; unicode-bidi: isolate"')
                            control.set_enabled(bool(tag))
                    def remove_translation():
                        for control in translated_fields.values():
                            control.value = ''
                        stage_translation()
                    for control in translated_fields.values():
                        control.disable()
                    language_control.on_value_change(load_translation)
                    with ui.row().classes('w-full justify-end gap-1'):
                        ui.button(icon='refresh', on_click=load_translation).props('flat round dense').tooltip(translated_message('webui.open_editor.tooltip.load_translation_d75ce604'))
                        ui.button(icon='delete_outline', on_click=remove_translation).props('flat round dense color=negative').tooltip(translated_message('webui.open_editor.tooltip.remove_translation_01e5d951'))
                symmetric = ui.checkbox(text('symmetric'),value=(row or {}).get('is_symmetric',False))
                if row:
                    symmetric.disable()
                enabled = ui.switch(text('active'),value=(row or {}).get('is_active',True)) if row else None
                feedback = ui.label('').classes('text-negative').props('role=alert')
                async def commit():
                    if not alive() or not dialog.value:
                        return
                    payload = {name:control.value.strip() for name,control in fields.items()}
                    stage_translation()
                    if not all(payload.values()) or any(not all(names.values()) for names in translations.values()):
                        feedback.text = text('required')
                        return
                    if not translations.get('ar'):
                        feedback.text = render_message_plain('relationships.error.arabic_labels_required')
                        return
                    payload['translations'] = translation_changes if row else translations
                    button.disable()
                    try:
                        if row:
                            payload.pop('code')
                            payload['is_active'] = enabled.value
                            await api.request('PATCH', f'/api/v1/relationships/types/{selected_kind}/{row["id"]}',json=payload,headers={'If-Match':str(row['version'])})
                        else:
                            payload['is_symmetric'] = symmetric.value
                            await api.request('POST', f'/api/v1/relationships/types/{selected_kind}',json=payload)
                    except ApiError as error:
                        if alive() and dialog.value:
                            feedback.text = on_error(error)
                            button.enable()
                        return
                    dialog.close()
                    await page.load(reset=True)
                with ui.row().classes('w-full justify-end'):
                    ui.button(text('cancel'),on_click=dialog.close).props('flat')
                    button = ui.button(text('save'),on_click=commit)
            dialog.open()
        page.table.on('edit-type', lambda event: edit(event.args))
        async def delete(event):
            row = next((r for r in page.table.rows if r['id'] == event.args), None)
            if not alive() or row is None:
                return
            selected_kind = kind.value
            with ui.dialog() as dialog, ui.card().classes('messaging-workspace gap-3'):
                ui.label(text('confirm_delete')).classes('text-lg font-semibold')
                ui.label(row['forward_label'] + ' / ' + row['reverse_label'])
                feedback = ui.label('').classes('text-negative').props('role=alert')
                async def commit():
                    if not alive() or not dialog.value:
                        return
                    button.disable()
                    try:
                        await api.request('DELETE',f'/api/v1/relationships/types/{selected_kind}/{row["id"]}',headers={'If-Match':str(row['version'])})
                    except ApiError as error:
                        if alive() and dialog.value:
                            feedback.text = on_error(error)
                            button.enable()
                        return
                    dialog.close()
                    await page.load()
                with ui.row().classes('w-full justify-end'):
                    ui.button(text('cancel'),on_click=dialog.close).props('flat')
                    button = ui.button(text('delete_type'),on_click=commit,color='negative')
            dialog.open()
        page.table.on('delete-type', delete)
        kind.on_value_change(lambda _: page.load(reset=True))
        search.on_value_change(lambda _: page.load(reset=True))
        await page.load()
    return page
