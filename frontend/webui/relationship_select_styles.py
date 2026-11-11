"""Existing relationship-chip styling shared by resource selectors."""
from __future__ import annotations
from typing import Any
from nicegui import ui
from .i18n_catalogue import render_message

def style_relationship_chip_select(control: Any, field_name: str = "") -> None:
    """Render relationship choices as cards and the selected value compactly."""
    icon = {
        "aggregation_id": "folder",
        "parent_aggregation_id": "folder",
        "classification_id": "account_tree",
        "security_level_id": "shield",
        "owning_org_unit_id": "corporate_fare",
        "role_id": "badge",
        "user_id": "person",
    }.get(field_name, "link")
    control.props(
        'use-input input-debounce=0 behavior=menu options-dense '
        'popup-content-style="min-width:360px;max-width:calc(100vw - 48px)"'
    ).classes("relationship-chip-select")
    control.add_slot("option", """
        <q-item v-bind="props.itemProps" class="relationship-option-card q-ma-xs q-py-sm">
          <q-item-section avatar>
            <q-avatar color="blue-1" text-color="primary" icon="__ICON__" size="36px" />
          </q-item-section>
          <q-item-section style="min-width:0">
            <q-item-label class="text-weight-medium ellipsis">
              {{ props.opt.label.includes(' · ') ? props.opt.label.split(' · ').slice(1).join(' · ') : props.opt.label }}
            </q-item-label>
            <q-item-label caption>
              <q-badge v-if="props.opt.label.includes(' · ')" outline color="primary"
                :label="props.opt.label.split(' · ')[0]" />
            </q-item-label>
          </q-item-section>
        </q-item>
    """.replace("__ICON__", icon))
    control._props["hide-selected"] = False
    control._props["fill-input"] = False
    control.add_slot("selected-item", """
        <q-chip outline color="primary" text-color="blue-grey-9" class="relationship-value-chip">
          <q-badge v-if="props.opt.label.includes(' · ')" color="blue-1" text-color="primary"
            :label="props.opt.label.split(' · ')[0]" />
          <span class="text-weight-medium ellipsis">
            {{ props.opt.label.includes(' · ') ? props.opt.label.split(' · ').slice(1).join(' · ') : props.opt.label }}
          </span>
          <q-tooltip>{{ props.opt.label }}</q-tooltip>
        </q-chip>
    """)
