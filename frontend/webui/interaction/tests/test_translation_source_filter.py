"""Exercise the production translation screen with bounded API responses."""
import ast
import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import pytest
from nicegui import background_tasks, ui

from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message, set_active_messages, strip_diagnostic_metadata

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).parents[4]
SCREEN = next(node for node in ast.walk(ast.parse((ROOT/'frontend/webui/app.py').read_text()))
              if isinstance(node, ast.AsyncFunctionDef) and node.name == 'select_translation_administration')
AR = {item['message_key']: item['translated_text'] for item in
      json.loads((ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']}


class Api:
    def __init__(self):
        self.calls = []
        self.gates = {}
        self.generation_calls = []

    async def localization_languages(self):
        return [dict(language_tag=tag, native_name=name, english_name=name, direction=direction,
                     is_enabled=True, is_default=tag == 'en', catalogue_revision=1)
                for tag, name, direction in [('en', 'English', 'ltr'), ('ar', 'العربية', 'rtl')]]

    async def localization_messages(self, **params):
        self.calls.append(params)
        if gate := self.gates.get(params.get('source_text')):
            await gate.wait()
        return dict(items=[], total=0, group_total=0, context_groups=[])

    async def localization_generation_report(self, language):
        self.generation_calls.append(language)
        return dict(total=0, drafts=0, reviewed=0, unreviewed=0, published=0, unpublished=0, quality_attention=0)


async def open_translation_page(user, language='en'):
    api = Api()
    state = dict(translation_offset=10)

    @ui.page('/translation-source-filter')
    async def page():
        set_active_messages(AR if language == 'ar' else {})
        scope = dict(ui=ui, api=api, state=state, Any=Any, Callable=Callable, ApiError=ApiError,
                     background_tasks=background_tasks, render_message=render_message,
                     strip_diagnostic_metadata=strip_diagnostic_metadata, error_message=str,
                     register_navigation=lambda *args: None, show_authenticated_view=lambda: None,
                     page_client=ui.context.client)
        for name in ['title', 'subtitle', 'guidance']:
            scope[name] = ui.label('')
        for name in ['search_bar', 'aggregation_mode_bar', 'table_container']:
            scope[name] = ui.column()
        scope['add_button'] = ui.button('')
        scope['add_record_button'] = ui.button('')
        exec(compile(ast.Module(body=[SCREEN], type_ignores=[]), '<translation-screen>', 'exec'), scope)
        await scope['select_translation_administration']()

    await user.open('/translation-source-filter')
    assert api.calls[-1]['offset'] == 10
    source_label = AR['localization.filter.source_text'] if language == 'ar' else 'English source text'
    source = next(control for control in user.find(ui.input).elements
                  if strip_diagnostic_metadata(control._props.get('label', '')) == source_label)
    translated_label = AR['webui.select_translation_administration.input.translated_text_054048b6'] if language == 'ar' else 'Translated text'
    translated = next(control for control in user.find(ui.input).elements
                      if strip_diagnostic_metadata(control._props.get('label', '')) == translated_label)
    return api, state, source, translated


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_source_filter_resets_paging_combines_filters_and_clear_all_restores_listing(user, language):
    api, state, source, translated = await open_translation_page(user, language)
    assert source._props['debounce'] == '350'
    with user:
        source.value = 'requested language'
    await asyncio.sleep(.05)
    assert api.calls[-1]['source_text'] == 'requested language' and api.calls[-1]['offset'] == 0
    with user:
        translated.value = 'اللغة'
    await asyncio.sleep(.05)
    assert api.calls[-1]['source_text'] == 'requested language' and api.calls[-1]['translated_text'] == 'اللغة'
    clear = next(button for button in user.find(ui.button).elements if button._props.get('icon') == 'filter_alt_off')
    clear.mark('clear-translation-filters')
    user.find(marker='clear-translation-filters').click()
    await asyncio.sleep(.05)
    assert source.value == translated.value == ''
    assert api.calls[-1]['source_text'] == api.calls[-1]['translated_text'] == ''
    assert api.calls[-1]['offset'] == 0 and api.calls[-1]['limit'] == 10
    if language == 'ar':
        assert AR['localization.administration.result_count'].replace('{count}', '0') in [
            label.text.replace('\u2068', '').replace('\u2069', '') for label in user.find(ui.label).elements]


@pytest.mark.parametrize('abandoned', ['newer_filter', 'page'])
async def test_source_filter_ignores_obsolete_response_after_filter_change_or_navigation(user, abandoned):
    api, state, source, _ = await open_translation_page(user)
    gate = api.gates['slow'] = asyncio.Event()
    with user:
        source.value = 'slow'
    await asyncio.sleep(.03)
    assert api.calls[-1]['source_text'] == 'slow'
    if abandoned == 'page':
        state['resource'] = 'records'
    else:
        with user:
            source.value = 'latest'
        await asyncio.sleep(.03)
    generation_calls = len(api.generation_calls)
    gate.set()
    await asyncio.sleep(.04)
    assert len(api.generation_calls) == generation_calls
