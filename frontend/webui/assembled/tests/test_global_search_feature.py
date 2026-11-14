"""Global search through the real assembled application and authorized API."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,click_one,eventually
from frontend.webui.i18n_catalogue import render_message_plain as t
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def test_global_search_record_destination_and_empty_query(assembled):
    user=assembled;await login(user)
    api=user.api_clients[0]
    setting=next(i for i in (await api.application_settings())['items'] if i['key']=='FULL_TEXT_SEARCH_ENABLED')
    await api.save_application_settings([{'key':setting['key'],'expected_version':setting['version'],'value':True}], 'Disposable search regression')
    try:
        # Use the existing header container so localization metadata cannot affect lookup.
        header=next(e for e in user.client.elements.values() if 'erms-global-search-wrap' in e.classes)
        query=next(e for e in header.descendants() if isinstance(e,ui.input))
        submit=next(e for e in header.descendants() if isinstance(e,ui.button))
        with user:query.value='Test'
        click_one(user,[submit])
        await eventually(lambda:current_page(user)=='full-text-search' and any('compact-result-item' in e.classes for e in user.client.elements.values()) and user.pending_requests==0)
        buttons=[b for b in user.find(ui.button).elements if b.props.get('aria-label')=='Open record'];assert buttons
        click_one(user,[buttons[0]]);await eventually(lambda:current_page(user)=='record-details' and user.pending_requests==0)
        with user:query.value='zz_phase6q_absent'
        click_one(user,[submit]);await user.should_see(t('webui.render_global_search_results.label.no_results_found_ab1c85dc'))
        assert not user.api_failures
    finally:
        current=next(i for i in (await api.application_settings())['items'] if i['key']==setting['key'])
        await api.save_application_settings([{'key':setting['key'],'expected_version':current['version'],'value':setting['value']}], 'Restore disposable search fixture')
