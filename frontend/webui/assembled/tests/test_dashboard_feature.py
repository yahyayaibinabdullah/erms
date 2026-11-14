"""Dashboard navigation refreshes real mutations and favourite actions."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.i18n_catalogue import render_message_plain as t
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def test_dashboard_return_obtains_fresh_counts_and_favourites(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    def count():
        cards=[e for e in user.client.elements.values() if 'dashboard-overview-primary-card' in e.classes]
        card=next(c for c in cards if any(plain(e)==t('navigation.item.records') for e in c.descendants()))
        return int(next(e.text for e in card.descendants() if 'tabular-nums' in e.classes))
    await eventually(lambda:user.pending_requests==0);before=count()
    parent=(await api.search_request('aggregations',{'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0}))['items'][0]
    created=await api.create('records',{'record_number':'DASH-FRESH','title':'Dashboard freshness fixture','aggregation_id':parent['id'],'medium':'physical'})
    await api.favourite('records',created['id'])
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('navigation.item.application_settings')]);await eventually(lambda:current_page(user)=='application-settings' and user.pending_requests==0)
    reads=sum(r['path']=='/api/v1/dashboard/summary' for r in user.api_requests)
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('navigation.item.dashboard')]);await eventually(lambda:current_page(user)=='dashboard' and count()==before+1 and user.pending_requests==0)
    assert sum(r['path']=='/api/v1/dashboard/summary' for r in user.api_requests)==reads+1
    row=next(e for e in user.client.elements.values() if 'dashboard-personal-item' in e.classes and any(plain(c)=='Dashboard freshness fixture' for c in e.descendants()))
    click_one(user,[b for b in row.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='favorite'])
    await user.should_see(t('webui.remove_dashboard_favourite.notify.removed_from_favourites_6953809b'))
    assert created['id'] not in {r['id'] for r in (await api.favourites())['records']}
    assert not user.api_failures
