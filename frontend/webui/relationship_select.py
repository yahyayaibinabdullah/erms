"""Shared Wathiq relationship selector presentation."""
from typing import Any
from nicegui import ui
from .remote_select import RemoteSelect


def relationship_select(
    label: str,
    options: dict[int, str],
    *,
    value: Any = None,
    required: bool = False,
    multiple: bool = False,
    remote: bool = False,
    icon: str | None = None,
):
    lowered_label = label.lower()
    icon = icon or (
        "folder" if "aggregation" in lowered_label
        else "corporate_fare" if "organization" in lowered_label or "unit" in lowered_label
        else "badge" if "role" in lowered_label
        else "person" if "user" in lowered_label
        else "link"
    )
    control = (RemoteSelect if remote else ui.select)(
        options,
        label=label,
        value=value,
        with_input=True,
        clearable=not required,
        multiple=multiple,
    ).props(
        "outlined use-input input-debounce=0 behavior=menu options-dense"
    ).classes("w-full relationship-select")
    if remote:
        control.classes("remote-relationship-select")
    control.add_slot("prepend", f'<q-avatar size="34px" color="blue-1" text-color="primary" icon="{icon}" />')
    option_template = """
        <q-item v-bind="props.itemProps" class="relationship-option q-py-sm">
          <q-item-section avatar>
            <q-avatar color="blue-1" text-color="primary" icon="__ICON__" size="36px" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="text-weight-medium">{{ props.opt.label.includes(' · ') ? props.opt.label.split(' · ').slice(1).join(' · ') : props.opt.label }}</q-item-label>
            <q-item-label v-if="props.opt.email" caption dir="ltr">{{ props.opt.email }}</q-item-label>
            <q-item-label v-if="props.opt.reason" caption>{{ props.opt.reason }}</q-item-label>
            <q-item-label caption class="row items-center q-gutter-xs">
              <q-badge v-if="props.opt.label.includes(' · ')" outline color="primary" :label="props.opt.label.split(' · ')[0]" />
            </q-item-label>
          </q-item-section>
          <q-item-section side><q-icon name="chevron_right" color="grey-5" /></q-item-section>
        </q-item>
    """.replace("__ICON__", icon)
    control.add_slot("option", option_template)
    if multiple:
        # NiceGUI has no input-buffer or popup setter. Use QSelect's public
        # methods after selection so the old menu cannot intercept another field.
        def settle_selection():
            control.run_method("updateInputValue", "")
            control.run_method("hidePopup")
        control.on_value_change(settle_selection)
    return control


