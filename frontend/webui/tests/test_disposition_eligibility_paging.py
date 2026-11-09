"""Page selection stays explicit; clearing removes selections from every page."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from nicegui import core,ui
from frontend.webui.api_client import ApiError
from frontend.webui.disposition import screens
from frontend.webui.disposition.messages import text
from frontend.webui.resource_relationships import PageTable
from frontend.webui.tests.test_disposition_tasks import host
from frontend.webui.tests.test_disposition_bulk import click


def root(identity,owner=1,**changes):
    return dict(dict(id=identity,version=2,aggregation_number=f'A-{identity:03}',title='Review material',
        selectable=True,redacted=False,disposition_status=2,owning_org_unit_id=owner,
        compatible_owning_org_unit_ids=[owner],owner=f'Unit {owner}',rule_source='classification',rule_source_label='C',
        calculated_disposition_at='2025-01-01',date_closed='2020-01-01',vital=False,security=False,held=False,
        blocked=False,job_id=None,vital_count=0,security_count=0,hold_count=0),**changes)


async def mount(host,monkeypatch,rows,*,scope=None,size=10,target=None):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    reads=[];pages=[];notices=[];mounted=[True]
    monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append(message))
    def table(**kw):
        page=PageTable(**kw);pages.append(page);return page
    monkeypatch.setattr(screens,'PageTable',table)
    async def request(path,**params):
        reads.append((path,deepcopy(params)))
        if path=='context':return {'roles':[{'id':7}]}
        if path=='suggested-owner':return await scope(params['root_ids'])
        if path=='jobs/5':return {'id':5,'version':7,'job_number':'DT-5','membership_add_role_id':7}
        assert path=='eligibility'
        visible=deepcopy(rows)
        if params.get('status') is not None:visible=[r for r in visible if r['disposition_status']==params['status']]
        if params.get('descending'):visible.reverse()
        return {'items':visible[params['offset']:params['offset']+params['limit']],'total':len(visible)}
    with host:
        await screens.eligibility_screen(api=SimpleNamespace(disposition_page=request),container=host,
            active=lambda:mounted[0],on_error=lambda e:'Safe selection error',bind_remote=lambda *a,**kw:None,
            open_job=lambda *a:None,open_resource=lambda *a:None,format_timestamp=str,saved={'size':size},target_job=target)
    def button(key):return next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text(key))
    def changed():
        next(e.handler for e in reversed(list(pages[0].table._event_listeners.values())) if e.type=='selection')()
    return SimpleNamespace(page=pages[0],button=button,reads=reads,notices=notices,mounted=mounted,changed=changed)


def selected_ids(h):return [r['id'] for r in h.page.table.selected]


@pytest.mark.asyncio
async def test_select_page_skips_locks_and_keeps_other_pages_while_clear_clears_every_page(host,monkeypatch):
    rows=[root(i) for i in range(1,36)]
    rows[1]=root(2,blocked=True,vital=True,selectable=False)
    rows[2]={'id':'redacted-2','redacted':True,'selectable':False}
    rows[3]=root(4,date_closed=None,selectable=False)
    rows[4]=root(5,job_id=99,job_number='DT-99',selectable=False)
    h=await mount(host,monkeypatch,rows)
    with host:
        assert not h.button('bulk_clear').enabled and not h.button('add').enabled
        await click(h.button('eligibility_select_page'))
        assert selected_ids(h)==[1,6,7,8,9,10]
        assert not h.button('eligibility_select_page').enabled
        await h.page.move(1)
        assert selected_ids(h)==[1,6,7,8,9,10]
        await click(h.button('eligibility_select_page'))
        assert len(selected_ids(h))==16 and h.button('add').enabled
        assert any(isinstance(e,ui.label) and e.text==text('bulk_selected_count',count=16) for e in host.descendants())
        await h.page.move(-1)
        assert ':model-value="true"' in h.page.table.slots['header-selection'].template
        await click(h.button('bulk_clear'))
        assert not selected_ids(h) and not h.button('bulk_clear').enabled and not h.button('add').enabled
        await h.page.move(1)
        assert not selected_ids(h) and ':model-value="false"' in h.page.table.slots['header-selection'].template
        assert len(h.reads)==5 and {p for p,_ in h.reads}=={'context','eligibility'}
        assert all(p['limit']==10 for path,p in h.reads if path=='eligibility')


@pytest.mark.asyncio
async def test_header_deselect_only_changes_visible_page_and_preserves_selected_versions(host,monkeypatch):
    rows=[root(i) for i in range(1,26)];h=await mount(host,monkeypatch,rows)
    with host:
        await click(h.button('eligibility_select_page'));rows[0]['version']=3
        await h.page.move(1);await click(h.button('eligibility_select_page'));await h.page.move(-1)
        assert h.page.table.selected[0]['version']==2 and h.page.table.rows[0]['version']==3
        handler=next(e.handler for e in h.page.table._event_listeners.values() if e.type=='selectVisible')
        handler(SimpleNamespace(args=False))
        assert selected_ids(h)==list(range(11,21)) and ':model-value="false"' in h.page.table.slots['header-selection'].template
        # A sort/page-size change preserves the complete explicit selection.
        await h.page.request(SimpleNamespace(args={'pagination':{'page':1,'rowsPerPage':25,'sortBy':'identity','descending':True}}))
        assert selected_ids(h)==list(range(11,21))
        assert ':model-value="null"' in h.page.table.slots['header-selection'].template
        await click(h.button('refresh'))
        assert not selected_ids(h)


@pytest.mark.asyncio
async def test_filter_change_and_addition_clear_selection_from_every_page(host,monkeypatch):
    h=await mount(host,monkeypatch,[root(i) for i in range(1,31)],target=5)
    confirms=[]
    async def confirm(**kwargs):confirms.append(kwargs)
    monkeypatch.setattr(screens,'command_dialog',confirm)
    with host:
        await click(h.button('eligibility_select_page'));await h.page.move(1);await click(h.button('eligibility_select_page'))
        await click(h.button('add'))
        assert len(confirms)==1
        assert [r['root_id'] for r in confirms[0]['build'](lambda:True)()['items']]==list(range(1,21))
        await confirms[0]['after']({'items':[{'root_id':i,'success':True} for i in range(1,21)]})
        assert not selected_ids(h)
        await click(h.button('eligibility_select_page'));await h.page.move(-1);await click(h.button('eligibility_select_page'))
        await click(h.button('filters'))
        assert not selected_ids(h)


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome',['valid','invalid','error','cleared','abandoned'])
async def test_cross_page_owner_check_is_bounded_and_never_repopulates_a_cleared_or_abandoned_view(host,monkeypatch,outcome):
    pending=asyncio.get_running_loop().create_future();ids=[]
    async def scope(selected):
        from frontend.webui import i18n_catalogue
        # Real event-created tasks can resume without a page slot or inherited
        # message catalogue. Updates must still use their owning client's UI.
        i18n_catalogue._active_messages.set({})
        ids.extend(selected)
        return await pending
    rows=[root(i,owner=1 if i<=10 else 2) for i in range(1,21)]
    h=await mount(host,monkeypatch,rows,scope=scope)
    with host:
        await click(h.button('eligibility_select_page'));await h.page.move(1);await click(h.button('eligibility_select_page'))
        await asyncio.sleep(0)
        assert ids==list(range(1,21)) and not h.button('add').enabled
        assert any(isinstance(e,ui.label) and e.text==text('eligibility_selection_checking') for e in host.descendants())
        if outcome=='cleared':await click(h.button('bulk_clear'))
        if outcome=='abandoned':h.mounted[0]=False
        if outcome=='error':pending.set_exception(ApiError(403,{'code':'disposition_resource_access_required'}))
        else:pending.set_result({'owner':{'id':9} if outcome!='invalid' else None})
        await asyncio.sleep(.01)
        assert not h.button('add').enabled if outcome!='valid' else h.button('add').enabled
        if outcome=='valid':
            assert any(isinstance(e,ui.label) and e.text==text('bulk_selected_count',count=20) for e in host.descendants())
            from html import escape
            assert escape(text('bulk_select_page')) in h.page.table.slots['header-selection'].template
            await h.page.move(-1)
            assert sum(p=='suggested-owner' for p,_ in h.reads)==1
        if outcome=='invalid':assert any(isinstance(e,ui.label) and e.text==text('selection_mixed_branches') for e in host.descendants())
        if outcome=='error':assert any(isinstance(e,ui.label) and e.text==text('disposition_resource_access_required') for e in host.descendants())
        if outcome=='cleared':assert not selected_ids(h) and not h.button('bulk_clear').enabled
        assert not h.notices


@pytest.mark.asyncio
async def test_select_page_keeps_existing_100_limit_without_partial_page_selection(host,monkeypatch):
    h=await mount(host,monkeypatch,[root(i) for i in range(1,111)],size=50)
    with host:
        await click(h.button('eligibility_select_page'));await h.page.move(1);await click(h.button('eligibility_select_page'))
        assert len(selected_ids(h))==100
        await h.page.move(1);await click(h.button('eligibility_select_page'))
        assert len(selected_ids(h))==100 and h.notices==[text('bulk_limit')]
        h.page.table.selected.append(h.page.table.rows[0]);h.changed()
        assert len(selected_ids(h))==100 and len(h.notices)==2
        await click(h.button('bulk_clear'))
        assert not selected_ids(h)
