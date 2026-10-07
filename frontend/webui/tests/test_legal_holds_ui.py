from pathlib import Path
from frontend.webui.tests.localization_assertions import with_english_messages


APP = Path(__file__).parents[1] / "app.py"
CLIENT = Path(__file__).parents[1] / "api_client.py"
HOLDS_API = Path(__file__).parents[3] / "backend" / "services" / "api" / "holds.py"


def test_holds_workspace_and_navigation_are_wired():
    source = with_english_messages(APP.read_text(encoding="utf-8"))
    assert '"Holds", "gavel", navigation_key="holds"' in source
    assert 'async def select_holds()' in source
    assert 'async def select_hold_details(hold_id: int)' in source
    assert 'async def open_hold_editor(' in source
    assert '"Create hold"' in source
    assert 'ui.label("Filter holds").classes("text-lg font-semibold text-slate-800")' in source
    assert 'with ui.row().classes("w-full items-center"):' in source
    assert '"Add held items"' in source
    assert '"Search number, title or description"' in source
    assert 'first_page=ui.button("First"' in source
    assert 'last_page=ui.button("Last"' in source
    assert '.tooltip("Open resource")' in source
    assert '.tooltip("Remove from this hold")' in source
    assert '"Remove direct holds"' in source
    assert 'color="positive" if hold["state"]=="active" else "blue-grey"' in source
    assert 'render_user_avatar(contributor, size="25px").style(' in source
    assert '"margin-inline-end:5px !important"' in source
    assert 'held_item_assigned_from=ui.input("Assignment date from")' in source
    assert 'held_item_assigned_before=ui.input("Assignment date before")' in source
    assert '"hold-command-layout w-full"' in source
    assert 'ui.label("Hold actions")' in source
    assert 'ui.button("Edit hold"' in source
    assert 'ui.button("Manage contributors"' in source
    assert 'ui.button("View history"' in source
    assert source.count('await show_entity_history("holds", hold)') == 2
    assert 'ui.label("Hold history").classes("text-2xl font-bold")' not in source
    assert 'ui.button("Delete hold"' in source
    assert 'control.add_slot("selected-item"' in source
    assert 'control._props["hide-selected"] = False' in source
    assert 'control._props["fill-input"] = False' in source
    assert 'value=(hold or {}).get("owner_user_id"), label="Owner", with_input=True' in source
    assert 'control._props["display-value"]' not in source
    assert '"hold-held-item-filter-primary w-full"' in source
    assert 'with ui.grid(columns=4).classes("w-full gap-3")' in source
    assert 'with ui.row().classes("w-full items-center justify-end gap-2")' in source
    assert '"width:1280px;max-width:calc(100vw - 48px)"' in source
    assert 'update_held_item_selection(row: dict[str, Any], selected: bool)' in source
    assert 'update_candidate_selection(row: dict[str, Any], selected: bool)' in source
    assert source.count('with ui.element("div").classes("governance-card-list w-full")') >= 3
    assert 'selected = ui.checkbox(value=row["selection_key"] in held_item_selection)' in source
    assert 'selected = ui.checkbox(value=row["selection_key"] in picker["selected"])' in source
    assert 'on_click=lambda: select_user_details(hold["owner"]["id"])' in source
    assert '"folder" if row["resource_type"] == "aggregation" else "description"' in source
    assert 'row["assigned_at_display"] = format_timestamp(row["assigned_at"])' in source
    assert 'props.row.security_level_code' not in source  # composed once in Python
    assert 'row["security_level_display"] = f"{row[\'security_level_code\']} — {row[\'security_level_name\']}"' in source
    assert 'select_user_details(user_id)' in source


def test_hold_details_localizes_state_validity_and_protection_values():
    source = APP.read_text(encoding="utf-8")
    details = source[source.index("async def select_hold_details("):]
    assert 'localized_hold_states = {' in details
    assert 'render_message("webui.select_holds.select.active_f5bdb37b")' in details
    assert 'render_message("webui.select_holds.select.valid_from_ebec3edf")' in details
    assert 'render_message("webui.select_holds.select.valid_until_5ebd52b4")' in details
    assert 'render_message("common.value.no_expiry")' in details
    assert 'render_message("webui.select_holds.select.protection_517995ff")' in details
    assert 'render_message("webui.select_holds.select.enhanced_state_preservation_39552bdf")' in details
    assert 'render_message("webui.select_holds.select.core_protection_6f52e26e")' in details
    assert 'ui.badge(hold["state"].title()' not in details
    assert '("Valid from",' not in details
    assert '"No scheduled end"' not in details
    assert '"Enhanced state preservation" if hold' not in details


def test_hold_listing_localizes_card_labels_states_and_open_ended_validity():
    source = APP.read_text(encoding="utf-8")
    listing = source[source.index("async def select_holds()"):source.index("async def select_hold_details(")]
    assert 'ui.badge(hold_state_label' in listing
    assert 'render_message("webui.select_hold_details.label.owner_7d141da3")' in listing
    assert 'render_message("webui.select_hold_details.label.contributors_008a0e27")' in listing
    assert 'render_message("webui.select_holds.select.valid_from_ebec3edf")' in listing
    assert 'render_message("webui.select_holds.select.valid_until_5ebd52b4")' in listing
    assert 'render_message("common.value.no_expiry")' in listing
    assert 'render_message("webui.select_hold_details.label.held_items_244f35b3")' in listing
    assert '"hold-list-card--effective"' in listing
    assert 'hold["state"].title()' not in listing
    assert '("Owner",' not in listing
    assert '("Contributors",' not in listing
    assert '("Validity",' not in listing
    assert '"Until released"' not in listing
    assert '("Held items",' not in listing


def test_hold_api_projects_owner_and_contributor_names_in_preferred_language():
    source = HOLDS_API.read_text(encoding="utf-8")
    assert "from .entity_localization import localize_rows, localized_projection, preferred_language" in source
    assert "localized: dict[str, Any] | None = None" in source
    assert "user_account.status,user_account.translations" in source
    assert "u.status,u.translations FROM hold_contributors" in source
    assert 'localize_rows(result["contributors"], language_tag, "name")' in source
    assert 'localize_rows([result["owner"]], language_tag, "name")' in source
    assert 'localize_rows(hold_contributors, language_tag, "name")' in source
    assert "preferred_language(connection, request)" in source


def test_hold_person_buttons_keep_avatars_on_the_rtl_leading_edge():
    source = APP.read_text(encoding="utf-8")
    assert 'html[dir="rtl"] .hold-person-button .q-btn__content' in source
    assert '"hold-person-button self-start -ml-2"' in source
    assert '"hold-person-button gap-1"' in source
    assert 'ui.label((contributor.get("localized") or {}).get("name") or contributor["name"]).classes("text-sm")' in source


def test_hold_mutations_collect_reasons_and_refresh_live_state():
    source = with_english_messages(APP.read_text(encoding="utf-8"))
    assert 'async def hold_reason_dialog(' in source
    assert 'Reason for updating this hold' in source
    assert 'Reason for removing this direct assignment' in source
    assert 'Remove all directly assigned holds? Protection inherited from parent aggregations will remain.' in source
    assert 'api.effective_holds("record", record_id)' in source
    assert 'api.effective_holds("aggregation", current["id"])' in source
    assert 'effective_holds, "record", record_id' in source
    assert 'effective_holds, "aggregation", current["id"]' in source
    assert 'Remove from this hold' in source


def test_hold_editor_datetime_conversion_uses_application_timezone_without_javascript():
    source = with_english_messages(APP.read_text(encoding="utf-8"))
    hold_editor = source[source.index("async def open_hold_editor("):source.index("async def add_resource_to_hold_dialog(")]
    assert "ui.run_javascript" not in hold_editor
    assert 'return parsed.astimezone().strftime("%Y-%m-%dT%H:%M")' in hold_editor
    assert "parsed.replace(tzinfo=local_timezone).astimezone(timezone.utc).isoformat()" in source
    assert "Dates currently use the application timezone." in source


def test_aggregation_command_centre_matches_the_approved_two_column_layout():
    source = with_english_messages(APP.read_text(encoding="utf-8"))
    assert '"aggregation-command-layout w-full p-5"' in source
    assert '"Aggregation overview"' in source
    assert '"detail-surface aggregation-actions-panel shadow-none p-4 gap-3"' in source
    assert '"Metadata and review"' in source
    assert '"Lifecycle"' in source
    assert '"Security, access and audit"' in source
    assert '"detail-surface aggregation-hold-controls shadow-none p-4 gap-3"' in source
    assert '"Hold controls"' in source
    assert '"Remove direct holds"' in source
    assert '"aggregation-child-preview-grid mx-5 mb-3"' in source
    assert 'for child in children:' in source
    assert 'f"{child[\'aggregation_number\']} · {child_status}"' in source
    assert '"aggregation-retention-stages w-full"' in (APP.parent / "retention_timeline.py").read_text()
    assert '"aggregation-retention-footer w-full"' in source
    assert 'grid-column: 1 / -1; grid-row: 2' in source
    assert '"w-full text-sm font-semibold text-slate-800"' in (APP.parent / "retention_timeline.py").read_text()
    assert 'disposition_label(rule["final_disposition"])' in (APP.parent / "retention_timeline.py").read_text()
    assert '.aggregation-retention-stage:not(:last-child)::after' in source
    assert 'padding-inline-start: 30px' in source
    assert 'html[dir="rtl"] .aggregation-retention-stage:not(:last-child)::after' in source
    assert 'content: "←"' in source
    assert '.aggregation-overview-actions .q-btn' in source


def test_access_explainer_renders_redaction_safe_hold_constraints():
    source = with_english_messages(APP.read_text(encoding="utf-8"))
    assert 'result.get("resource_state_constraints", [])' in source
    assert 'details restricted' in source
    assert 'An effective legal hold prevents this' in source


def test_security_level_change_remains_separate_from_hold_frozen_metadata():
    source = with_english_messages(APP.read_text(encoding="utf-8"))
    assert 'async def show_security_level_change(' in source
    assert 'if capabilities.get("change_security_level"):' in source
    assert 'await api.preview_security_level_change({' in source
    assert 'await api.apply_security_level_change({' in source
    assert '"Reason *"' in source
    assert '"security_level_id",' in source
    assert "Level action for a reviewed security-level change." in source
    assert '"none": "Change only this resource"' in source
    assert '"raise_ancestors": "Also raise parent aggregations as needed"' in source
    assert '"downgrade_subtree": "Also lower contained resources as needed"' in source
    assert "__REMEDY_DESCRIPTIONS__[props.opt.value]" in source
    assert 'popup-content-style="width:572px;max-width:calc(100vw - 64px)"' in source
    assert "white-space:normal; overflow-wrap:anywhere" in source


def test_api_client_exposes_complete_hold_workflow():
    source = CLIENT.read_text(encoding="utf-8")
    for method in (
        "holds", "hold", "create_hold", "update_hold", "delete_hold",
        "hold_held_items", "hold_contributors", "replace_hold_contributors",
        "add_hold_held_item", "hold_held_item_candidates", "add_hold_held_items_bulk",
        "remove_hold_held_item", "effective_holds",
        "add_resource_to_hold", "remove_resource_from_hold",
        "remove_all_direct_holds", "hold_history",
    ):
        assert f"async def {method}(" in source
