"""PR #72 regressions, runnable before and after the display fix.

Use tools/run_disposable_acl_tests.py; the shared fixtures reject persistent DBs.
"""
import os

import psycopg
import pytest
from psycopg.types.json import Jsonb

from backend.services.api.tests.test_browse import _classification, _published_scheme


def _translate(client, resource, row, **titles):
    version = row['version']
    for language, title in titles.items():
        response = client.patch(
            f"/api/v1/entity-translations/{resource}/{row['id']}/{language}",
            json={'title': title},
            headers={'If-Match': str(version), 'X-Change-Reason': 'Verify localized title display'},
        )
        assert response.status_code == 200, response.text
        version = response.json()['version']


def _prefer(client, language):
    preference = client.get('/api/v1/preferences').json()
    response = client.put(
        '/api/v1/preferences',
        headers={'If-Match': str(preference['version'])},
        json={'language_tag': language, 'working_timezone': 'Asia/Dubai'},
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def translated_classification_tree(client):
    scheme = _published_scheme(client, 'PR72')
    branch = _classification(client, scheme['id'], 'PR72-01')
    terminal = _classification(client, scheme['id'], 'PR72-01.01',
                               parent_id=branch['id'], terminal=True)
    fallback = _classification(client, scheme['id'], 'PR72-02')
    child_fallback = _classification(client, scheme['id'], 'PR72-01.02',
                                     parent_id=branch['id'], terminal=True)
    for resource, row in [('classification-schemes', scheme),
                          ('classifications', branch), ('classifications', terminal)]:
        # Both explicit translations differ from canonical metadata. This also
        # catches accidentally treating English as an unconditional fallback.
        _translate(client, resource, row, ar='عنوان مترجم', en='Translated English title')
    return scheme, branch, terminal, fallback, child_fallback


@pytest.mark.parametrize('route', ['schemes', 'roots', 'children'])
def test_browse_resolves_saved_language_without_changing_canonical_titles(
    client, translated_classification_tree, route,
):
    scheme, branch, terminal, fallback, child_fallback = translated_classification_tree
    paths = {
        'schemes': ('/api/v1/browse/classification-schemes', scheme, None),
        'roots': (f"/api/v1/browse/classification-schemes/{scheme['id']}/roots", branch, fallback),
        'children': (f"/api/v1/browse/classifications/{branch['id']}/children", terminal, child_fallback),
    }
    path, canonical, untranslated = paths[route]
    for language, expected in [('ar', 'عنوان مترجم'), ('en', 'Translated English title'),
                               ('ar', 'عنوان مترجم')]:
        _prefer(client, language)
        response = client.get(path, params={'limit': 1, **({'q': 'PR72'} if route == 'schemes' else {})})
        assert response.status_code == 200, response.text
        body = response.json()
        row = body[0] if route == 'schemes' else body['items'][0]
        assert row['id'] == canonical['id']
        assert row['code'] == canonical['code']
        assert row['title'] == canonical['title']
        assert (row.get('localized') or {}).get('title') == expected
        if untranslated is not None:
            assert body['next_cursor'] is not None
            second = client.get(path, params={'limit': 1, 'cursor': body['next_cursor']})
            assert second.status_code == 200, second.text
            fallback_row = second.json()['items'][0]
            assert fallback_row['id'] == untranslated['id']
            assert (fallback_row.get('localized') or {}).get('title') == untranslated['title']
            assert 'translations' not in row and 'translations' not in fallback_row


def test_scheme_typeahead_finds_the_title_displayed_to_the_user(client):
    scheme = _published_scheme(client, 'PR72-TYPEAHEAD')
    _translate(client, 'classification-schemes', scheme, ar='الأرشيف المترجم')
    _prefer(client, 'ar')
    visible = client.get('/api/v1/browse/classification-schemes', params={'q': scheme['code']})
    assert visible.status_code == 200, visible.text
    assert visible.json()[0]['id'] == scheme['id']
    # Type the label shown in the dropdown rather than its canonical title.
    result = client.get('/api/v1/browse/classification-schemes', params={'q': 'الأرشيف المترجم'})
    assert result.status_code == 200, result.text
    assert [row['id'] for row in result.json()] == [scheme['id']]


def test_scheme_typeahead_checks_enabled_title_values_and_keeps_publication_scope(client):
    scheme = _published_scheme(client, 'PR72-LANGUAGES')
    unpublished = client.post('/api/v1/classification-schemes',
                              json={'code': 'PR72-DRAFT', 'title': 'Draft scheme'}).json()
    _translate(client, 'classification-schemes', scheme, ar='العنوان القابل للبحث')
    _translate(client, 'classification-schemes', unpublished, ar='العنوان القابل للبحث')
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("SELECT set_config('app.change_reason','Seed selector language regression',true)")
        connection.execute("""INSERT INTO supported_languages
            (language_tag,english_name,native_name,direction,is_enabled)
            VALUES ('fr','French','Français','ltr',true)""")
        connection.execute("UPDATE classification_schemes SET translations=translations || %s WHERE id=%s",
                           (Jsonb({'fr': {'title': 'Hidden language title'},
                                   'en': {'description': 'Description-only needle'}}), scheme['id']))
        connection.execute("UPDATE supported_languages SET is_enabled=false WHERE language_tag='fr'")
    for language in ('en', 'ar'):
        _prefer(client, language)
        for query, expected in [('العنوان القابل للبحث', [scheme['id']]),
                                ('Hidden language title', []), ('Description-only needle', []),
                                ('title', []), ('zzabsent', [])]:
            response = client.get('/api/v1/browse/classification-schemes', params={'q': query})
            assert response.status_code == 200, response.text
            assert [row['id'] for row in response.json()] == expected, (language, query)
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("SELECT set_config('app.change_reason','Enable selector test language',true)")
        connection.execute("UPDATE supported_languages SET is_enabled=true WHERE language_tag='fr'")
    response = client.get('/api/v1/browse/classification-schemes', params={'q': 'Hidden language title'})
    assert response.status_code == 200, response.text
    assert [row['id'] for row in response.json()] == [scheme['id']]
    response = client.get('/api/v1/browse/classification-schemes', params={'q': "' OR true --"})
    assert response.status_code == 200 and response.json() == []


def test_scheme_title_sort_uses_displayed_titles_before_page_selection(client):
    first = _published_scheme(client, 'PR72-ORDER-A')
    second = _published_scheme(client, 'PR72-ORDER-B')
    _translate(client, 'classification-schemes', first, ar='زيت')
    _translate(client, 'classification-schemes', second, ar='أرشيف')
    _prefer(client, 'ar')
    pages = [client.get('/api/v1/browse/classification-schemes',
                        params={'q': 'PR72-ORDER', 'limit': 1, 'offset': offset})
             for offset in (0, 1)]
    assert all(response.status_code == 200 for response in pages)
    # Arabic and deterministic Unicode ordering both place أرشيف before زيت.
    # Checking IDs keeps the ordering failure distinct from missing projections.
    assert [response.json()[0]['id'] for response in pages] == [second['id'], first['id']]


@pytest.mark.parametrize('force_unicode_order', [False, True])
def test_scheme_sort_matches_regional_fallback_and_stable_code_ties(
    client, monkeypatch, force_unicode_order,
):
    from backend.services.api import browse

    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("SELECT set_config('app.change_reason','Seed regional selector regression',true)")
        connection.execute("""INSERT INTO supported_languages
            (language_tag,english_name,native_name,direction)
            VALUES ('ar-AE','Arabic (UAE)','العربية (الإمارات)','rtl')""")
    schemes = [_published_scheme(client, code) for code in ('PR72-REG-Z', 'PR72-REG-A', 'PR72-REG-F')]
    for row in schemes[:2]:
        _translate(client, 'classification-schemes', row, ar='Zulu')
        current = client.get(f"/api/v1/classification-schemes/{row['id']}").json()
        _translate(client, 'classification-schemes', current, **{'ar-AE': 'Alpha'})
    base = _published_scheme(client, 'PR72-REG-B')
    _translate(client, 'classification-schemes', base, ar='Bravo')
    _prefer(client, 'ar-AE')
    if force_unicode_order:
        monkeypatch.setattr(browse, '_scheme_browse_collation', lambda *_: 'C')
    rows = []
    for offset in range(4):
        response = client.get('/api/v1/browse/classification-schemes',
                              params={'q': 'PR72-REG', 'limit': 1, 'offset': offset})
        assert response.status_code == 200, response.text
        rows.extend(response.json())
    assert [row['id'] for row in rows] == [schemes[1]['id'], schemes[0]['id'], base['id'], schemes[2]['id']]
    assert [row['localized']['title'] for row in rows] == ['Alpha', 'Alpha', 'Bravo', schemes[2]['title']]
    assert [row['title'] for row in rows] == [schemes[1]['title'], schemes[0]['title'], base['title'], schemes[2]['title']]
