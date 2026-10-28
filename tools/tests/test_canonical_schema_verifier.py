"""Protect against inheriting the server template's unintended locale provider."""
import pytest

from tools.verify_canonical_schema import archive_locale, create_database_statement


@pytest.mark.parametrize('options,expected', [
    ("ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'en_US.UTF-8'",
     {'provider':'libc','encoding':'UTF8','locale':'en_US.UTF-8'}),
    ("ENCODING = 'UTF8' LOCALE_PROVIDER = icu ICU_LOCALE = 'ar' LOCALE = 'en_US.UTF-8'",
     {'provider':'icu','encoding':'UTF8','icu_locale':'ar','locale':'en_US.UTF-8'}),
    ("ENCODING = 'UTF8' LOCALE_PROVIDER = builtin BUILTIN_LOCALE = 'C.UTF-8'",
     {'provider':'builtin','encoding':'UTF8','builtin_locale':'C.UTF-8'}),
    ("ENCODING = 'UTF8' LOCALE_PROVIDER = libc LC_COLLATE = 'C' LC_CTYPE = 'en_US.UTF-8'",
     {'provider':'libc','encoding':'UTF8','lc_collate':'C','lc_ctype':'en_US.UTF-8'}),
])
def test_archive_metadata_preserves_explicit_database_locale(options, expected):
    values = archive_locale('CREATE DATABASE source WITH TEMPLATE = template0 ' + options + ';\n')
    assert values == expected
    statement = create_database_statement('owned_disposable', values).as_string()
    assert 'LOCALE_PROVIDER ' + expected['provider'] in statement
    if expected['provider'] == 'icu':
        assert "ICU_LOCALE 'ar'" in statement


@pytest.mark.parametrize('source', [
    '',
    "CREATE DATABASE source WITH TEMPLATE = template0 ENCODING = 'UTF8';",
    "CREATE DATABASE source WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = icu;",
    "CREATE DATABASE source WITH TEMPLATE = template0 LOCALE_PROVIDER = libc LOCALE = 'C';",
])
def test_missing_locale_metadata_is_not_silently_inherited(source):
    with pytest.raises(ValueError):
        archive_locale(source)


def test_database_identifier_and_locale_literals_are_quoted_independently():
    statement = create_database_statement('owned"database', {
        'provider':'libc','encoding':'UTF8','locale':"unusual'locale",
    }).as_string()
    assert '"owned""database"' in statement
    assert "LOCALE 'unusual''locale'" in statement
    with pytest.raises(ValueError):
        create_database_statement('owned', {'provider':'libc; DROP DATABASE source'})
