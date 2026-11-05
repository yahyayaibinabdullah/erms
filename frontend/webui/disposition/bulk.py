"""Mounted-job bulk selection; no collection downloads or cross-view cache.

Selection holds at most 100 explicit row/version snapshots, survives server
paging/sorting, and is cleared on filters, successful mutation or view disposal.
Rereading a page never silently upgrades the version the user selected.
"""
from copy import deepcopy
from html import escape
from nicegui import ui
from ..api_client import ApiError
from .messages import text


class BulkSelection:
    def __init__(self, *, eligible, label, active, actions, on_change=lambda:None):
        self.eligible, self.label, self.active = eligible, label, active
        self.on_change = on_change
        self.rows = {}
        self.page = None
        with ui.row().classes('w-full items-center gap-3 flex-wrap bg-blue-50 rounded-lg p-3') as self.bar:
            self.count = ui.label('').props('role=status aria-live=polite').classes('grow')
            for key, callback in actions:
                ui.button(text(key), on_click=lambda _, cb=callback: cb(self.selected())).props('outline no-caps').tooltip(text(key))
            ui.button(text('bulk_clear'), on_click=self.clear).props('flat no-caps')
        self.bar.set_visibility(False)

    def selected(self):
        return deepcopy(list(self.rows.values()))

    def attach(self, page):
        self.page = page
        page.table.bulk_selection = self
        page.table.add_slot('body-selection', '''<span class="inline-flex items-center" :tabindex="props.row.bulk_selectable ? -1 : 0">
          <q-checkbox :model-value="props.selected" :disable="!props.row.bulk_selectable"
            :aria-label="props.row.bulk_selection_label" @update:model-value="props.selected = $event"/>
          <q-tooltip v-if="!props.row.bulk_selectable">{{ props.row.bulk_unavailable }}</q-tooltip></span>''')
        page.table.on_select(self.changed)
        page.table.on('bulk-select-page', self.select_page)

    def loaded(self, page, result):
        # Called before PageTable assigns rows; decorate only this server page.
        for row in result['items']:
            row['bulk_selectable'] = bool(self.eligible(row))
            row['bulk_selection_label'] = self.label(row)
            row['bulk_unavailable'] = text('bulk_unavailable')
        self.sync(result['items'])

    def sync(self, visible=None):
        if not self.active() or self.bar._deleted:
            return
        self.count.text = text('bulk_selected_count', count=len(self.rows))
        self.bar.set_visibility(bool(self.rows))
        if self.page is None:
            return
        visible = self.page.table.rows if visible is None else visible
        eligible = {row['id'] for row in visible if self.eligible(row)}
        checked = eligible & self.rows.keys()
        value = 'true' if eligible and checked == eligible else 'null' if checked else 'false'
        self.page.table.selected = self.selected()
        self.page.table.add_slot('header-selection', f'''<q-checkbox :model-value="{value}"
          :disable="{'false' if eligible else 'true'}" aria-label="{escape(text('bulk_select_page'))}"
          @update:model-value="$parent.$emit('bulk-select-page',$event)"><q-tooltip>{escape(text('bulk_select_page'))}</q-tooltip></q-checkbox>''')
        self.page.table.update()
        self.on_change()

    def changed(self, event):
        if not self.active():
            return
        selected = {row['id']: row for row in event.selection}
        self.rows = {identity: self.rows.get(identity, deepcopy(row))
                     for identity, row in selected.items() if self.eligible(row)}
        if len(self.rows) > 100:
            self.rows = dict(list(self.rows.items())[:100])
            ui.notify(text('bulk_limit'), type='warning')
        self.sync()

    def select_page(self, event):
        if not self.active():
            return
        visible = self.page.table.rows
        for row in visible:
            if event.args and self.eligible(row):
                if row['id'] not in self.rows and len(self.rows) >= 100:
                    ui.notify(text('bulk_limit'), type='warning')
                    break
                self.rows.setdefault(row['id'], deepcopy(row))
            elif not event.args:
                self.rows.pop(row['id'], None)
        self.sync()

    def clear(self):
        self.rows.clear()
        self.sync()


async def bulk_dialog(*, operation, rows, active, execute, on_error, refresh):
    """One explicit confirmation; an uncertain retry retains the caller's UUID."""
    if not rows or not active():
        return
    required = operation == 'remove'
    with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-[640px] max-w-full gap-4'):
        ui.label(text('bulk_'+operation+'_title', count=len(rows))).classes('text-xl font-semibold')
        ui.label(text('bulk_'+operation+'_hint')).classes('text-sm')
        ui.label(text('bulk_all_or_none')).classes('text-sm text-slate-600')
        reason = ui.textarea(text('bulk_reason_required' if required else 'reason_optional')).props('outlined autogrow').classes('w-full')
        feedback = ui.label('').classes('text-negative whitespace-pre-wrap').props('role=alert')
        state = {'busy': False, 'refresh': False}

        async def confirm():
            if not active() or not dialog.value or state['busy']:
                return
            if state['refresh']:
                try:
                    await refresh()
                except ApiError as error:
                    if active():feedback.text=on_error(error)
                    return
                dialog.close()
                return
            if required and not str(reason.value or '').strip():
                feedback.text = text('required')
                return
            state['busy'] = True
            button.disable();cancel.disable();reason.disable()
            try:
                success = await execute(rows, str(reason.value or '').strip(), feedback)
            except ApiError as error:
                if not active() or not dialog.value:
                    return
                definitive=error.status_code in (403,404,409,422)
                feedback.text = text('bulk_failed' if definitive else 'bulk_uncertain')+'\n'+on_error(error)
                # A transport error may follow a commit: retain the exact payload
                # for retry. A definitive version/eligibility failure needs refresh.
                if definitive:
                    state['refresh'] = True
                    button.text = text('bulk_refresh_selection')
                success = False
            else:
                if not success and active() and dialog.value:
                    feedback.text = text('bulk_failed')+'\n'+feedback.text
                    # ReviewForm reports its existing failure itself; its retained
                    # command UUID still makes a connection-error retry safe.
            finally:
                state['busy'] = False
                if active() and not button._deleted:
                    button.enable();cancel.enable();reason.enable()
            if success and not dialog._deleted:
                dialog.close()

        with ui.row().classes('w-full justify-end gap-2'):
            cancel = ui.button(text('cancel'), on_click=dialog.close).props('flat no-caps')
            button = ui.button(text('bulk_'+operation+'_confirm', count=len(rows)), on_click=confirm).props('no-caps')
        def validity():
            button.set_enabled(state['refresh'] or not required or bool(str(reason.value or '').strip()))
        reason.on_value_change(validity)
        validity()
    dialog.open()
    return dialog
