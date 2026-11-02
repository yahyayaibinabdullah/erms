"""Native drawer visibility control available outside the mobile overlay."""
import json

from nicegui import ui


def navigation_menu(drawer, *, expand_label: str, collapse_label: str):
    button = ui.button(icon='menu', on_click=drawer.toggle).props(
        'flat dense round'
    ).classes('lg:hidden')
    button.set_visibility(False)
    with button:
        tooltip = ui.tooltip(expand_label)

    def synchronize(_=None):
        expanded = bool(drawer.value)
        label = collapse_label if expanded else expand_label
        button.props('aria-label=' + json.dumps(label, ensure_ascii=False)
                     + ' aria-expanded=' + str(expanded).lower())
        tooltip.text = label

    drawer.on_value_change(synchronize)
    synchronize()
    return button
