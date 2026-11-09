"""Catalogue output is literal text; only markup boundaries encode HTML."""
import ast
from html import escape
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.props import Props
from frontend.webui import i18n_catalogue as i18n
from frontend.webui.tests.test_disposition_tasks import host

KEY = 'webui.show_memberships.label.capitalize_assignments_heading_ecd9d308'
VALUES = ["File Administrator (General Manager's Office)", 'Research & Development "Office"',
          'مكتب المدير العام · General Manager’s Office', 'Literal &amp; and &#x27; text',
          '<img src=x onerror="alert(1)">', '{capitalize} {{heading}}']


@pytest.mark.parametrize('value', VALUES)
def test_shared_renderer_preserves_literal_values_in_labels_and_nested_messages(host, value):
    with host:
        rendered = i18n.render_message(KEY, capitalize='User', heading=value)
        assert i18n.ISOLATE_START + value + i18n.ISOLATE_END in rendered
        label = ui.label(rendered)
        assert label.text == rendered
        nested = i18n.render_message(KEY, capitalize=rendered, heading=value)
        assert rendered in nested
        # An explicit markup/template boundary escapes the whole message once.
        assert '<img' not in escape(rendered)
        # Native NiceGUI props parse Python-quoted text, including both quotes
        # and backslashes, without exposing a second property or event handler.
        props = Props.parse(f'role=group aria-label={rendered!r}')
        assert props == {'role': 'group', 'aria-label': rendered}


def test_template_values_never_expand_other_placeholders_or_literal_braces():
    assert i18n._interpolate_text('{{title}} {name} {count}', {
        'name': '{count} {{title}}', 'count': 3,
    }) == '{title} \u2068{count} {{title}}\u2069 \u20683\u2069'


def test_diagnostic_framing_uses_the_literal_text_length(host):
    with host:
        value = "Manager's <Office> & Office"
        plain = i18n.render_message_plain(KEY, capitalize='User', heading=value)
        i18n.enable_diagnostic_metadata(host.client.id)
        try:
            marked = i18n.render_message(KEY, capitalize='User', heading=value)
            assert i18n.strip_diagnostic_metadata(marked) == plain
            assert i18n._encoded_diagnostic_length(len(plain)) in marked
        finally:
            i18n.disable_diagnostic_metadata(host.client.id)


def test_no_catalogue_message_is_sent_directly_to_an_html_sink():
    root = Path(__file__).parents[1]
    for path in root.glob('*.py'):
        for call in ast.walk(ast.parse(path.read_text())):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr not in {'html', 'markdown', 'add_head_html', 'add_body_html'}:
                continue
            for arg in [*call.args, *(k.value for k in call.keywords)]:
                assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                               and n.func.id in {'render_message', 'render_message_plain'}
                               for n in ast.walk(arg)), (path, call.lineno)
