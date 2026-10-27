"""Request presentation controls use the shared localized Settings page."""
from types import SimpleNamespace
import pytest
from nicegui import ui
from backend.services.api.application_settings_registry import REGISTRY
from frontend.webui.application_settings import settings_page,SETTINGS_CHOICE_MESSAGE_KEYS
from frontend.webui.i18n_catalogue import render_message_plain
from frontend.webui.tests.test_disposition_tasks import host


@pytest.mark.asyncio
async def test_disposition_request_settings_are_visible_and_language_choices_localized(host):
    calls=[]
    async def read():
        calls.append('read')
        return {'items':[dict(key=s.key,category=s.category,category_label=render_message_plain('settings.category.disposition'),kind=s.kind,default=s.default,value=s.default,effective_value=s.default,label=render_message_plain(s.label_key),description=render_message_plain(s.description_key),validation=dict(minimum=s.minimum,maximum=s.maximum,choices=s.choices,nullable=s.nullable,group=s.group),editable=True,sensitive=False,secret_is_set=None,provenance='default',version=1,date_updated=None,updated_by_user_id=None) for s in REGISTRY.values() if s.category=='disposition']}
    async def noop(*a,**kw):pass
    with host:
        await settings_page(api=SimpleNamespace(application_settings=read),container=host,bind_relationship=lambda *a,**kw:noop,active=lambda:True,on_error=str,initial_category='disposition')
        labels={e.label for e in host.descendants() if isinstance(e,ui.input)}
        for key in ('DISPOSITION_ORGANIZATION_NAME','DISPOSITION_RECORDS_UNIT_EMAIL','DISPOSITION_RECORDS_UNIT_PHONE'):
            assert render_message_plain(REGISTRY[key].label_key) in labels
        selector=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==render_message_plain(REGISTRY['DISPOSITION_REQUEST_LANGUAGE'].label_key))
        assert selector.value=='arabic_first_bilingual'
        assert selector.options=={key:render_message_plain(SETTINGS_CHOICE_MESSAGE_KEYS[key]) for key in ('manager_preference','arabic_first_bilingual')}
        assert calls==['read']
