"""Shared identity, status summaries and details tabs for governed resources."""
import asyncio

from nicegui import ui

from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain, strip_diagnostic_metadata
from .navigation_data import PAGE_ICONS


async def detail_read(request, on_error):
    try:
        return await request
    except ApiError as error:
        on_error(error)
        return None


async def read_closure(request, on_error):
    try:
        return True, await request
    except ApiError as error:
        on_error(error)
        return False, None


def metadata_layout():
    with ui.row().classes('resource-metadata w-full items-start gap-4', remove='row').style('flex-wrap: wrap'):
        facts = ui.column().classes('resource-metadata-facts grow min-w-0 gap-3').style('flex-basis: 20rem')
        actions = ui.column().classes('resource-metadata-actions grow min-w-0 gap-1 rounded-lg bg-slate-50 p-2').style('flex-basis: 11rem')
    return facts, actions


def detail_action_group(title: str):
    group = ui.column().classes('w-full gap-1').props('role=group')
    with group:
        heading = ui.label(title).classes('w-full text-xs font-semibold text-slate-600')
    group.props['aria-labelledby'] = f'c{heading.id}'
    return group


def open_details_dialog(item, number, loaders, active):
    dialog = ui.dialog().classes('resource-details-dialog')
    hosts = {}
    tasks = {}
    loaded = set()
    with dialog, ui.card().classes('p-0 gap-0 flex-nowrap rounded-xl').style(
        'width: 680px; max-width: calc(100vw - 32px); max-height: min(76dvh, 680px)',
    ):
        with ui.row().classes('w-full items-start justify-between no-wrap gap-2 px-4 pt-4 pb-2 shrink-0', remove='row'):
            with ui.row().classes('items-start no-wrap gap-3 min-w-0', remove='row'):
                ui.avatar(icon='folder' if 'aggregation_number' in item else 'description',
                          color='blue-1', text_color='primary', size='36px').props('rounded')
                with ui.column().classes('gap-0 min-w-0'):
                    ui.label(number).classes('text-xs text-primary font-semibold break-all').props('dir=ltr')
                    heading = ui.label(item['title']).classes('text-lg font-semibold break-words min-w-0 line-clamp-3').props('dir=auto').tooltip(item['title'])
                    dialog.props['aria-labelledby'] = f'c{heading.id}'
            close = render_message_plain('webui.show_effective_holds_dialog.button.close_7cfb3209')
            close_button = ui.button(icon='close')
            close_button.props['aria-label'] = close
            close_button.props('flat round dense').tooltip(close)
        labels = {
            'metadata': render_message('resource_details.metadata'),
            'retention': render_message('resource_details.retention_rule'),
            'relationships': render_message('relationships.ui.title'),
            'holds': render_message('navigation.item.holds'),
        }
        with ui.tabs(value='metadata').props('align=start dense active-color=primary indicator-color=primary').classes(
            'w-full border-b border-slate-200 px-2 shrink-0',
        ) as tabs:
            for key in loaders:
                ui.tab(key, labels[key]).props('no-caps')
        with ui.tab_panels(tabs, value='metadata', animated=False).classes('w-full min-h-0 overflow-y-auto'):
            for key in loaders:
                with ui.tab_panel(key).classes('p-4'):
                    hosts[key] = ui.column().classes('w-full gap-3')

    async def load(key):
        if key not in hosts or key in loaded or key in tasks or not active() or not dialog.value:
            return
        task = asyncio.current_task()
        tasks[key] = task
        host = hosts[key]
        host.clear()
        with host:
            spinner = ui.spinner()
            try:
                await loaders[key]()
                if active() and dialog.value:
                    loaded.add(key)
            except ApiError:
                if active() and dialog.value:
                    ui.label(render_message('resource_details.unavailable'))
            finally:
                if not spinner.is_deleted:
                    spinner.delete()
                if tasks.get(key) is task:
                    del tasks[key]

    def cancel_reads():
        for task in tuple(tasks.values()):
            task.cancel()
        tasks.clear()
        loaded.clear()

    async def change_tab(event):
        await load(event.value)

    tabs.on_value_change(change_tab)
    dialog.on('hide', cancel_reads)

    return_focus = None

    async def dismiss():
        dialog.close()
        if return_focus is not None and active():
            await dialog.client.run_javascript(f'document.getElementById("c{return_focus}")?.focus()')

    close_button.on_click(dismiss)
    dialog.on('escape-key', dismiss)

    default_trigger = None

    async def show(key='metadata', *, trigger=None):
        nonlocal return_focus
        if not active():
            return
        return_focus = trigger.id if trigger is not None else default_trigger
        tabs.set_value(key)
        dialog.open()
        await load(key)

    def set_default_trigger(button):
        nonlocal default_trigger
        default_trigger = button.id

    return show, dialog.close, set_default_trigger


def render_resource_detail_header(
    item, *, kind, closure, closure_known, hold_count, get_holds, open_details, set_default_trigger,
    format_timestamp, render_actions, render_context=None,
):
    number = item[f'{kind}_number']
    icon = PAGE_ICONS[f'{kind}-details']
    details_label = render_message('resource_details.details')
    unavailable = render_message('resource_details.unavailable')
    marked_vital = item.get('is_vital')
    contains_vital = kind == 'aggregation' and bool(item.get('has_vital_descendants'))
    vital_status = (
        unavailable if marked_vital is None else render_message(
            'resource_details.marked_vital' if marked_vital else 'resource_details.not_marked_vital',
        )
    )
    vital_descendants = (
        render_message('webui.open_aggregation.label.contains_vital_resources_006b2b72')
        if contains_vital else None
    )
    descendants_only = marked_vital is False and contains_vital
    if not closure_known:
        closure_status = unavailable
    elif closure is None:
        closure_status = render_message('webui.open_aggregation.badge.open_88407b0f')
    elif kind == 'aggregation' and closure.get('id') == item['id']:
        closure_status = render_message('webui.open_aggregation.label.closed_directly_77d7dcfc')
    else:
        closure_status = render_message(
            'resource_details.closed_by_aggregation' if kind == 'record'
            else 'webui.open_aggregation.label.closed_by_an_ancestor_aggregation_dab7c6d7',
        )
    menus = []

    def hold_status(count):
        if count is None:
            return unavailable
        if not count:
            return render_message('resource_details.no_active_holds')
        return render_message('webui.open_aggregation.label.protected_by_hold_count_effective_value_065566e7', hold_count=count)

    def summary_button(label, status, symbol, color, render_content):
        with ui.button(icon=symbol, color=color) as button:
            button.props['aria-label'] = label
            button.props['aria-description'] = strip_diagnostic_metadata(status)
            button.props['aria-expanded'] = 'false'
            button.props('flat round size=sm')
            tooltip = ui.tooltip(status)
            with ui.menu().props('anchor="bottom start" self="top start"').classes('resource-status-summary') as menu:
                menus.append(menu)
                host = ui.column().classes('gap-2 p-3 w-72 max-w-[85vw] break-words')
                host.props['tabindex'] = '-1'

        async def opened():
            button.props['aria-expanded'] = 'true'
            button.update()
            for other in menus:
                if other is not menu and other.value:
                    other.close()
            host.clear()
            with host, ui.column().classes('w-full gap-2') as content:
                await render_content(menu, button, content, tooltip)

        def closed():
            if not button.is_deleted:
                button.props['aria-expanded'] = 'false'
                button.update()

        async def dismiss_with_escape():
            menu.close()
            await button.client.run_javascript(f'document.getElementById("c{button.id}")?.focus()')

        menu.on('show', opened)
        menu.on('hide', closed)
        menu.on('escape-key', dismiss_with_escape)

    async def show_vital(_menu, _button, _content, _tooltip):
        ui.label(vital_status)
        if vital_descendants:
            ui.label(vital_descendants)

    async def show_closure(_menu, _button, _content, _tooltip):
        ui.label(closure_status)
        if not closure_known or closure is None:
            return
        if closure.get('restricted'):
            ui.label(render_message('resource_details.closure_source_restricted'))
        else:
            ui.label(f"{closure['aggregation_number']} — {closure['title']}").props('dir=auto')
            ui.label(format_timestamp(closure.get('date_closed')))

    async def show_holds(menu, button, content, tooltip):
        spinner = ui.spinner()
        try:
            holds = await get_holds()
        except ApiError:
            holds = None
        finally:
            if not spinner.is_deleted:
                spinner.delete()
        if content.is_deleted or not menu.value:
            return
        status = hold_status(len(holds) if holds is not None else None)
        ui.label(status)
        if holds is not None:
            tooltip.set_text(status)
            button.props['aria-description'] = strip_diagnostic_metadata(status)
            button.props('icon=gavel color=warning' if holds else 'icon=gavel color=blue-grey-7')
            button.update()
        if holds:
            names = [hold['name'] for hold in holds if hold.get('name')]
            for name in names[:3]:
                ui.label(name).props('dir=auto')
            if len(names) > 3:
                ui.label('…')
            if len(names) < len(holds):
                ui.label(render_message('webui.show_effective_holds_dialog.label.effective_hold_details_restricted_6e99756d'))

        async def view_holds():
            menu.close()
            await open_details('holds', trigger=button)

        ui.button(render_message('webui.open_aggregation.button.view_holds_b4a3f017'), on_click=view_holds).props('flat no-caps')

    async def show_metadata(event):
        await open_details(trigger=event.sender)

    with ui.row().classes('resource-detail-header w-full items-start justify-between gap-2 px-4 pt-4 pb-3', remove='row').style('flex-wrap: wrap'):
        with ui.row().classes('items-start no-wrap gap-2 grow min-w-0', remove='row').style('flex-basis: 14rem'):
            ui.avatar(icon=icon, color='blue-1', text_color='primary', size='42px').props('rounded').classes('shrink-0')
            with ui.column().classes('gap-0 min-w-0 items-start'):
                with ui.button(on_click=show_metadata, color='blue-grey-10').props(
                    'flat no-caps align=start aria-haspopup=dialog',
                ).classes('px-1 py-0 max-w-full text-start'):
                    with ui.column().classes('items-start gap-0 min-w-0'):
                        ui.label(number).classes('text-xs text-primary font-semibold break-all').props('dir=ltr')
                        ui.label(item['title']).classes('text-xl font-semibold break-words leading-tight min-w-0 line-clamp-3').props('dir=auto')
                with ui.row().classes('items-center gap-1', remove='row'):
                    vital_tooltip = f'{vital_status} · {vital_descendants}' if vital_descendants else vital_status
                    vital_icon = 'help_outline' if marked_vital is None else 'o_emergency' if descendants_only else 'emergency'
                    vital_color = 'red-8' if marked_vital or descendants_only else 'blue-grey-7'
                    summary_button(render_message_plain('webui.open_aggregation.button.vital_status_69064d77'),
                                   vital_tooltip, vital_icon, vital_color, show_vital)
                    summary_button(render_message_plain('resource_details.closure'), closure_status,
                                   ('lock' if closure else 'lock_open') if closure_known else 'help_outline',
                                   'warning' if closure else 'blue-grey-7', show_closure)
                    summary_button(render_message_plain('navigation.item.holds'), hold_status(hold_count),
                                   'gavel' if hold_count is not None else 'help_outline',
                                   'warning' if hold_count else 'blue-grey-7', show_holds)
                if render_context is not None:
                    render_context()
        with ui.row().classes('items-center gap-1 shrink-0', remove='row'):
            details_button = ui.button(details_label, icon='info_outline', on_click=show_metadata).props('flat dense no-caps aria-haspopup=dialog')
            set_default_trigger(details_button)
            render_actions()
