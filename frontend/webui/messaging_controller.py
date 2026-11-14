"""Existing mailbox, monitor, notification and linked-resource navigation."""
from __future__ import annotations
from .api_client import ApiError
from .capabilities import can_navigate
from .entity_editor_controls import entity_metadata_label
from .messaging_monitor import messaging_monitor
from .messaging_workspace import messaging_workspace
from .notification_administration import notification_administration
from .relationship_select import relationship_select
from .i18n_catalogue import render_message
from .resource_inspector import resource_inspector
from nicegui import ui

def build_messaging_controller(
    *, add_button, add_record_button, aggregation_mode_bar, aggregation_state, api, bind_remote_relationship_select, collection_state, enter_messages, error_message, format_timestamp, get_principal, get_resource, guarded_page_navigation, guidance, localized_navigation, medium_label, messaging_state, open_aggregation, open_record_draft_editor, preview_record_components, refresh_message_unread, register_navigation, search_bar, select_audit_trail, select_disposition, show_authenticated_view, show_organization_structure, show_record_details, subtitle, table_container, title,
):
    async def select_messages(mailbox: str = "inbox") -> None:
        principal = get_principal()
        if principal is None:
            return
        key = "messages-" + mailbox
        if not can_navigate(key, principal.get("global_privileges", [])):
            return
        show_authenticated_view()
        enter_messages(key); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        token = object()
        messaging_state["messaging_workspace_token"] = token
        register_navigation(key, localized_navigation[key])
        title.text = localized_navigation[key]
        subtitle.text = ""
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()

        async def open_message_resource(kind, identity):
            if kind == "aggregation":
                await open_aggregation(await api.get("aggregations", identity))
            elif kind == "record":
                await show_record_details(await api.get("records", identity))
            else:
                component = await api.get("digital-components", identity)
                await show_record_details(await api.get("records", component["record_id"]))

        async def inspect_message_resource(kind, identity, picker_active):
            await resource_inspector(api=api, kind=kind, identity=identity,
                active=picker_active, preview=preview_record_components,
                field_label=entity_metadata_label, format_timestamp=format_timestamp,
                medium_label=medium_label, on_error=lambda error: ui.notify(
                    error_message(error), color="negative", close_button=True))

        async def capture_message(envelope_id, root_id):
            capture_dialog = ui.dialog().props("persistent")
            opening = {"closed": False}
            def capture_active():
                return (not opening["closed"] and get_principal() is principal
                        and messaging_state.get("messaging_workspace_token") is token)
            def cancel_opening():
                opening["closed"] = True
                capture_dialog.close()
            with capture_dialog, ui.card().classes("w-full gap-4").style("width: 1050px; max-width: calc(100vw - 32px)"):
                ui.label(render_message("webui.open_record_draft_editor.label.create_record_080740e1")).classes("text-xl font-semibold")
                with ui.row().classes("w-full items-center"):
                    ui.spinner(size="sm")
                    ui.label(render_message("messaging.capture.preparing")).classes("grow")
                ui.skeleton().classes("w-full h-24")
                with ui.row().classes("w-full justify-end"):
                    ui.button(render_message("webui.open_record_draft_editor.button.cancel_draft_84ea17b5"), on_click=cancel_opening).props("flat")
                    ui.button(render_message("webui.open_record_draft_editor.button.create_record_dd0193d6"), icon="check").disable()
            capture_dialog.open()
            params = {"root_id":root_id} if root_id else {}
            try:
                draft = await api.request("GET", f"/api/v1/messages/{envelope_id}/capture-preview", params=params)
            except ApiError as error:
                capture_dialog.close()
                if capture_active():
                    ui.notify(error_message(error),color="negative",close_button=True)
                return
            if not capture_active():
                capture_dialog.close()
                return
            async def prepare_pdfs():
                return await api.request("POST", f"/api/v1/messages/{envelope_id}/capture", params=params,timeout=660)
            await open_record_draft_editor(existing_capture_draft=draft,
                on_committed=lambda _:select_messages(mailbox),capture_active=capture_active,
                capture_loader=prepare_pdfs,capture_dialog=capture_dialog)

        if mailbox == "monitor":
            await messaging_monitor(api=api,container=table_container,
                active=lambda:get_principal() is principal and messaging_state.get("messaging_workspace_token") is token and get_resource()==key,
                format_timestamp=format_timestamp,
                open_audit=lambda:guarded_page_navigation(
                    lambda:select_audit_trail(initial_entity_type="system_notification")))
            return
        if mailbox == "notifications":
            await notification_administration(
                api=api, container=table_container,
                relationship_select=relationship_select,
                bind_relationship=bind_remote_relationship_select,
                format_timestamp=format_timestamp,
                active=lambda: get_principal() is principal
                and messaging_state.get("messaging_workspace_token") is token and get_resource() == key,
            )
            return
        messaging_state["messaging_workspace"] = await messaging_workspace(
            api=api, container=table_container, mailbox=mailbox,
            can_exchange="messaging.user_messages.exchange" in principal.get("global_privileges", []),
            relationship_select=relationship_select,
            bind_relationship=bind_remote_relationship_select,
            open_resource=open_message_resource, format_timestamp=format_timestamp,
            open_disposition_eligibility=lambda:guarded_page_navigation(lambda:select_disposition("disposition-eligibility")),
            open_disposition_job=lambda job_id:guarded_page_navigation(lambda:select_disposition("disposition-job",job_id)),
            open_disposition_task=lambda job_id,task_id:guarded_page_navigation(lambda:select_disposition("disposition-job",job_id,task_id=task_id)),
            inspect_resource=inspect_message_resource,
            on_read=refresh_message_unread,
            browse_recipients=show_organization_structure if "organization.browse" in principal.get("global_privileges", []) else None,
            capture_record=capture_message if "record.create" in principal.get("global_privileges",[]) else None,
            active=lambda: get_principal() is principal
            and messaging_state.get("messaging_workspace_token") is token and get_resource() == key,
        )


    return select_messages
