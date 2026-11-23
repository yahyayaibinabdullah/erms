"""Exercise real NiceGUI events with a bounded fake API; no database is used."""
import asyncio
from collections import Counter
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.testing import User

from frontend.webui.classification_workspace import classification_workspace

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


class Api:
    def __init__(self):
        self.calls = []
        self.schemes = [dict(id=i, code=f'S{i:02}', title=f'Scheme {i}', version=1,
                             date_deactivated='2026-09-29' if i == 2 else None)
                        for i in range(1, 28)]
        self.nodes = [dict(id=i, code=f'{i:04}', title=f'Node {i}', version=1,
                           classification_scheme_id=1, parent_classification_id=None,
                           is_terminal=False, date_deactivated='2026-09-29' if i == 1 else None)
                      for i in range(1, 29)]
        self.nodes.append(dict(id=101, code='1000', title='Child', version=1,
                               classification_scheme_id=1, parent_classification_id=1,
                               is_terminal=True))
        self.block = None

    async def list(self, resource, **params):
        self.calls.append((resource, params.copy()))
        assert params['limit'] <= 26
        if self.block:
            await self.block.wait()
        if resource == 'classification-schemes':
            rows = self.schemes
        else:
            rows = [n for n in self.nodes if n['classification_scheme_id'] == params['classification_scheme_id']
                    and n['parent_classification_id'] == params.get('parent_classification_id')]
        return rows[params.get('offset', 0):params.get('offset', 0) + params['limit']]

    async def search_request(self, resource, payload):
        self.calls.append(('search', payload))
        rows = self.nodes[:28] if resource == 'classifications' else self.schemes
        offset = payload['offset']
        return {'items': rows[offset:offset + payload['limit']], 'total': len(rows)}

    async def get(self, resource, entity_id):
        self.calls.append(('get', (resource, entity_id)))
        return dict(next(row for row in (self.schemes if resource == 'classification-schemes' else self.nodes) if row['id'] == entity_id))

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path))
        return [dict(classification_scheme_id=1, branch_count=28, terminal_count=1)]

    async def classification_path(self, entity_id):
        self.calls.append(('path', entity_id))
        node = next(n for n in self.nodes if n['id'] == entity_id)
        return [self.nodes[0], node] if entity_id == 101 else [node]

    async def classification_retention_rule(self, entity_id):
        return dict(defined_by_classification_id=entity_id, current_period_years=2,
                    intermediate_period_years=3, final_disposition='destroy', instructions='Retain evidence')

    async def classification_effective_rule(self, entity_id):
        rule = await self.classification_retention_rule(entity_id)
        rule['defined_by_classification_id'] = 1
        return rule


async def open_workspace(user, *, preferences=None, direction='ltr', can_transfer=False, empty=False, localized=False):
    api = Api()
    if empty:
        api.schemes = []
    if localized:
        api.schemes[0]["localized"] = {"title": "مخطط الاختبار"}
        api.nodes[0]["localized"] = {"title": "فرع الاختبار"}
        api.nodes[-1]["localized"] = {"title": "تصنيف الاختبار"}
    editor = AsyncMock()
    pages = []
    live = {'active': True}

    @ui.page('/test-workspace')
    async def page():
        await classification_workspace(
            api=api, container=ui.column(), open_editor=editor,
            show_entity_history=AsyncMock(), format_timestamp=lambda v: v or '—',
            display_value=lambda v: v or '—', error_message=str,
            entity_metadata_label=lambda v: v, localized_disposition_value=str,
            register_page=lambda page, item: pages.append((page, item)),
            active=lambda: live['active'], preferences=preferences or {},
            direction=lambda: direction,
            can_transfer=can_transfer,
        )
    await user.open('/test-workspace')
    return api, editor, pages, live


def button(user, *, icon=None, label=None, occurrence=0):
    candidates = [b for b in user.find(ui.button).elements
                  if (icon is None or b.props.get('icon') == icon)
                  and (label is None or label in b.props.get("aria-label", b.text))]
    candidates.sort(key=lambda b: b.id)
    chosen = candidates[occurrence]
    return _marked(user, chosen)


def _marked(user, element):
    element.mark(f'test-{element.id}')
    return user.find(marker=f'test-{element.id}')


async def test_node_navigation_retains_fields_timeline_and_direct_inactivity(user: User):
    api, _, pages, _ = await open_workspace(user, preferences={'expanded_schemes': [1], 'expanded': [1]})
    await user.should_see('Inactive via parent')
    button(user, label='1000 — Child').click()
    await user.should_see('Classification information')
    await user.should_see('Retain evidence')
    await user.should_see('Inherited')
    assert pages[-1][0] == 'classification-details'
    assert Counter(kind for kind, _ in api.calls)['path'] == 1
    filter_input = next(iter(user.find('Filter schemes').elements))
    assert not filter_input.parent_slot.parent.parent_slot.parent.visible
    button(user, label='Back to classification tree').click()
    await asyncio.sleep(0.05)
    await user.should_see('— Child')
    assert pages[-1][0] == 'classification-workspace'


async def test_scheme_and_each_branch_page_independently(user: User):
    api, _, _, _ = await open_workspace(user, preferences={'expanded_schemes': [1]})
    await user.should_not_see('— Scheme 26')
    await user.should_not_see('— Node 26')
    button(user, label='Load more', occurrence=0).click()
    await user.should_see('— Node 26')
    button(user, label='Load more').click()
    await user.should_see('— Scheme 26')
    assert any(r == 'classifications' and p.get('offset') == 25 for r, p in api.calls)
    assert any(r == 'classification-schemes' and p.get('offset') == 25 for r, p in api.calls)


async def test_creation_context_and_terminal_has_no_child_action(user: User):
    _, editor, _, _ = await open_workspace(user, preferences={'expanded_schemes': [1], 'expanded': [1]})
    # Header Add scheme, first scheme root, then first branch child.
    button(user, icon='add', occurrence=2).click()
    await asyncio.sleep(0.05)
    assert editor.call_args.kwargs['initial_values'] == {'classification_scheme_id': 1, 'parent_classification_id': 1}
    assert editor.call_args.kwargs['locked_fields'] == {'classification_scheme_id', 'parent_classification_id'}
    button(user, label='1000 — Child').click()
    await user.should_see('Classification information')
    await user.should_not_see('Child classification')


async def test_abandoned_branch_response_does_not_render(user: User):
    api, _, _, live = await open_workspace(user)
    api.block = asyncio.Event()
    button(user, icon='chevron_right').click()
    await asyncio.sleep(0.05)
    live['active'] = False
    api.block.set()
    await asyncio.sleep(0.05)
    await user.should_not_see('— Node 1')


async def test_return_refreshes_changed_metadata_and_rtl_expanders(user: User):
    api, _, _, _ = await open_workspace(user, direction='rtl')
    assert any(b.props.get('icon') == 'chevron_left' for b in user.find(ui.button).elements)
    button(user, label='S01 — Scheme 1').click()
    await user.should_see('Scheme information')
    api.schemes[0]['title'] = 'Changed scheme'
    button(user, label='Back to classification tree').click()
    await user.should_see('— Changed scheme')


async def test_search_is_scoped_and_paged_without_loading_the_hierarchy(user: User):
    api, _, _, _ = await open_workspace(user, preferences={'search_scheme_id': 1, 'query': 'employment'})
    await user.should_see('matching classifications')
    request = next(payload for kind, payload in api.calls if kind == 'search')
    assert request['where']['and'][0] == {'field': 'classification_scheme_id', 'operator': 'eq', 'value': 1}
    assert {condition['field'] for condition in request['where']['and'][1]['or']} == {'code', 'title', 'description', 'keywords'}
    assert not any(kind == 'classifications' for kind, _ in api.calls)
    button(user, label='Load more').click()
    await user.should_see('— Node 26')
    assert [payload['offset'] for kind, payload in api.calls if kind == 'search'] == [0, 25]


async def test_node_keeps_code_and_full_accessible_title_with_tooltip(user: User):
    _, _, _, _ = await open_workspace(user)
    node = next(b for b in user.find(ui.button).elements if b.props.get('aria-label') == 'S01 — Scheme 1')
    descendants = list(node.descendants())
    assert any(isinstance(e, ui.tooltip) and e.text == 'Scheme 1' for e in descendants)
    assert any(isinstance(e, ui.label) and e.text == 'S01' and 'shrink-0' in e.classes for e in descendants)
    assert any(isinstance(e, ui.label) and e.text == '— Scheme 1' and 'truncate' in e.classes for e in descendants)


@pytest.mark.parametrize('classification', [False, True])
async def test_details_group_commands_beside_summary_and_keep_back_in_summary(user: User, classification):
    await open_workspace(user, preferences={'expanded_schemes': [1]})
    button(user, label='0001 — Node 1' if classification else 'S01 — Scheme 1').click()
    await user.should_see('Classification actions' if classification else 'Scheme actions')
    await user.should_see('Metadata and hierarchy')
    await user.should_see('Lifecycle')
    await user.should_see('Audit')
    panel = next(card for card in user.find(ui.card).elements if 'classification-actions-panel' in card.classes)
    panel_buttons = [element for element in panel.descendants() if isinstance(element, ui.button)]
    assert any('Edit' in element.text for element in panel_buttons)
    assert any('Event history' in element.text for element in panel_buttons)
    assert any(('Child classification' if classification else 'Root classification') in element.text for element in panel_buttons)
    assert not any('Back to classification tree' in element.text for element in panel_buttons)
    summary = next(element for element in user.find(ui.column).elements if 'aggregation-command-summary' in element.classes)
    assert any(isinstance(element, ui.button) and 'Back to classification tree' in element.text for element in summary.descendants())
    assert 'aggregation-command-controls' in panel.parent_slot.parent.classes


@pytest.mark.parametrize('direction',['ltr','rtl'])
@pytest.mark.parametrize('empty',[False,True])
async def test_transfer_placement_and_permission(user: User, direction, empty):
    api, _, pages, _ = await open_workspace(user, direction=direction, can_transfer=True, empty=empty)
    await user.should_see('Import')
    await user.should_see('Add scheme')
    assert not any('/export' in str(call) for call in api.calls)
    if not empty:
        button(user,label='S01 — Scheme 1').click()
        await user.should_see('Export')
        importer = next(b for b in user.find(ui.button).elements if b.text == 'Import')
        assert not importer.parent_slot.parent.parent_slot.parent.visible
        button(user,label='Back to classification tree').click()
        await user.should_see('Import')


async def test_transfer_hidden_without_administer(user: User):
    await open_workspace(user, can_transfer=False)
    await user.should_not_see('Import')
    button(user,label='S01 — Scheme 1').click()
    await user.should_see('Scheme information')
    await user.should_not_see('Export')


async def test_import_refresh_preserves_sort_filter_and_loaded_pages(user: User):
    from io import BytesIO
    from starlette.datastructures import UploadFile
    preferences = {'scheme_sort':'title','scheme_sort_direction':'desc','scheme_query':'Scheme','scheme_pages':2}
    api, _, pages, _ = await open_workspace(user, preferences=preferences, can_transfer=True)
    original_search_sort = [payload['sort'] for kind,payload in api.calls if kind=='search'][-1]
    old_request = api.request
    async def request(method,path,**kwargs):
        if path.endswith('/import'):
            api.schemes.append(dict(id=28,code='S28',title='Scheme 28',version=1))
            return {'id':28,'code':'S28','date_published':None}
        return await old_request(method,path,**kwargs)
    api.request = request
    button(user,label='Import').click()
    await user.should_see('Import classification scheme')
    next(iter(user.find(ui.upload).elements)).handle_uploads([UploadFile(BytesIO(b'{}'),filename='scheme.json')])
    await asyncio.sleep(.05)
    confirm = sorted([b for b in user.find(ui.button).elements if b.text=='Import'],key=lambda b:b.id)[-1]
    _marked(user,confirm).click()
    await user.should_see('S28')
    assert pages[-1][0] == 'classification-workspace'
    assert {k:preferences[k] for k in ('scheme_sort','scheme_sort_direction','scheme_query','scheme_pages')} == {'scheme_sort':'title','scheme_sort_direction':'desc','scheme_query':'Scheme','scheme_pages':2}
    searches = [payload for kind,payload in api.calls if kind=='search']
    assert searches[-1]['offset'] == 25
    assert searches[-1]['sort'] == original_search_sort


async def test_localized_tree_details_paths_and_refresh_preserve_canonical_editor_values(user: User):
    api, editor, pages, _ = await open_workspace(
        user, preferences={'expanded_schemes': [1], 'expanded': [1]},
        localized=True, direction='rtl',
    )
    await user.should_see('— مخطط الاختبار')
    await user.should_see('— فرع الاختبار')
    await user.should_see('— تصنيف الاختبار')
    # A nontranslated sibling falls back while codes and ordering stay stable.
    await user.should_see('— Node 2')
    node = next(b for b in user.find(ui.button).elements if b.props.get('aria-label') == '1000 — تصنيف الاختبار')
    assert any(getattr(e, 'text', None) == 'تصنيف الاختبار' for e in node.descendants())
    button(user, label='1000 — تصنيف الاختبار').click()
    await user.should_see('تصنيف الاختبار')
    await user.should_see('0001 — فرع الاختبار')
    assert pages[-1][1]['title'] == 'Child'
    button(user, label='Edit').click()
    await asyncio.sleep(.03)
    assert editor.call_args.args[0]['title'] == 'Child'
    # Return reloads localized paths/branches after a translation change.
    api.nodes[0]['localized']['title'] = 'فرع محدث'
    api.nodes[-1]['localized']['title'] = 'تصنيف محدث'
    button(user, label='Back to classification tree').click()
    await user.should_see('— تصنيف محدث')
    button(user, label='1000 — تصنيف محدث').click()
    await user.should_see('0001 — فرع محدث')
    assert api.nodes[-1]['title'] == 'Child'


async def test_search_result_titles_use_localized_projection_with_canonical_fallback(user: User):
    api, _, _, _ = await open_workspace(
        user, preferences={'search_scheme_id': 1, 'query': '0001'}, localized=True,
    )
    await user.should_see('— فرع الاختبار')
    await user.should_see('— Node 2')
    button(user, label='0001 — فرع الاختبار').click()
    await user.should_see('فرع الاختبار')
    assert api.nodes[0]['title'] == 'Node 1'
