"""Existing disposition screen dispatch, saved views, navigation and dirty guards."""
from __future__ import annotations
from ..api_client import ApiError
from nicegui import app
import asyncio
from ..capabilities import can_navigate_disposition
from frontend.webui.disposition.messages import text as disposition_text
from frontend.webui.disposition.screens import eligibility_screen
from frontend.webui.event_labels import event_label
from frontend.webui.disposition.screens import job_screen
from frontend.webui.disposition.screens import jobs_screen
from frontend.webui.disposition.tasks import tasks_screen
from nicegui import ui

def build_disposition_controller(
    *, add_button, add_record_button, aggregation_mode_bar, aggregation_state, api, bind_remote_relationship_select, browse_advanced_aggregation, collection_state, current_navigation_snapshot, disposition_state, enter_disposition, error_message, format_timestamp, get_principal, get_resource, guarded_page_navigation, guidance, navigation_controller, open_related_resource, persist_navigation_trail, preview_record_components, register_navigation, search_bar, set_discard_guard, show_authenticated_view, subtitle, table_container, title,
):
    async def select_disposition(page="disposition-eligibility", identity=None, saved=None, target_job=None, task_id=None):
        principal=get_principal()
        if not principal or not can_navigate_disposition(page, principal):
            return
        task_id=task_id or (saved or {}).get("task_id")
        if task_id and page=="disposition-job":page="disposition-task"
        token=object()
        label=disposition_text("templates" if page=="disposition-templates" else "current_task" if task_id else "workspace_details" if page=="disposition-job" else "my_tasks" if page=="disposition-tasks" else "eligibility" if page=="disposition-eligibility" else "jobs")
        register_navigation(page,label,entity_id=task_id if page=="disposition-task" else identity)
        enter_disposition(page); disposition_state.update(disposition_page_token=token); collection_state.update(rows=[], searched=True); disposition_state.update(disposition_view={**dict(saved or {}), **({'task_id': task_id, 'job_id': identity} if task_id else {})}); aggregation_state.update(aggregation_detail=None)
        show_authenticated_view();title.text=label;subtitle.text="";guidance.text=""
        for control in (search_bar,aggregation_mode_bar,add_button,add_record_button):control.set_visibility(False)
        table_container.clear()
        def active():
            return get_principal() is principal and get_resource()==page and disposition_state.get("disposition_page_token") is token
        def remember(value):
            if active():
                disposition_state["disposition_view"]=value
                if navigation_controller.trail and navigation_controller.trail[-1]["page"]==page:
                    navigation_controller.trail[-1]["state"]=current_navigation_snapshot();persist_navigation_trail()
        async def open_tasks():await select_disposition("disposition-tasks")
        async def open_approval_results(identity):await select_disposition("disposition-job",identity,saved={"section":"documents","approval_results":True})
        async def open_job(identity):await select_disposition("disposition-job",identity)
        async def open_task(job_id,identity):await select_disposition("disposition-job",job_id,task_id=identity)
        async def refresh_workspace(view):
            await select_disposition(page,identity,saved=view,task_id=task_id)
        def register_dirty(dirty):
            async def guard(action):
                if dirty():
                    ui.notify(disposition_text("unsaved_warning"),type="warning");return False
                return True
            set_discard_guard(guard)
        async def open_eligibility(job_id):await select_disposition("disposition-eligibility",target_job=job_id)
        async def open_resource(kind,identity):await guarded_page_navigation(lambda:open_related_resource(kind,identity))
        common=dict(api=api,container=table_container,active=active,on_error=error_message,
                    bind_remote=bind_remote_relationship_select,open_job=open_job)
        try:
            if page in ("disposition-job","disposition-task"):
                await job_screen(**common,identity=identity,open_eligibility=open_eligibility,
                                 open_resource=open_resource,format_timestamp=format_timestamp,event_label=event_label,preview=preview_record_components,task_id=task_id,register_dirty=register_dirty,browse_resource=browse_advanced_aggregation,open_task=open_task,open_tasks=open_tasks,open_approval_results=open_approval_results,saved=saved,remember=remember,refresh_workspace=refresh_workspace)
            elif page=="disposition-templates":
                from .templates import templates_screen
                await templates_screen(api=api,container=table_container,active=active,on_error=error_message,format_timestamp=format_timestamp)
            elif page=="disposition-tasks":
                filter_preference_key=f"disposition_task_filters:{principal['user']['id']}"
                def remember_task_filters(expanded):
                    if active():
                        app.storage.user[filter_preference_key]=bool(expanded)
                await tasks_screen(**common,open_task=open_task,format_timestamp=format_timestamp,saved=saved,remember=remember,
                                   filters_expanded=app.storage.user.get(filter_preference_key,False),
                                   remember_filters=remember_task_filters)
            elif page=="disposition-eligibility":
                filter_preference_key=f"disposition_eligibility_filters:{principal['user']['id']}"
                def remember_eligibility_filters(expanded):
                    if active():
                        app.storage.user[filter_preference_key]=bool(expanded)
                await eligibility_screen(**common,open_resource=open_resource,format_timestamp=format_timestamp,
                                         saved=saved,remember=remember,target_job=target_job,
                                         filters_expanded=app.storage.user.get(filter_preference_key,False),
                                         remember_filters=remember_eligibility_filters)
            else:
                filter_preference_key=f"disposition_job_filters:{principal['user']['id']}"
                def remember_job_filters(expanded):
                    if active():
                        app.storage.user[filter_preference_key]=bool(expanded)
                await jobs_screen(**common,saved=saved,remember=remember,
                                  filters_expanded=app.storage.user.get(filter_preference_key,False),
                                  remember_filters=remember_job_filters)
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if active():
                with table_container:ui.label(error_message(error)).classes("text-negative").props("role=alert")


    return select_disposition
