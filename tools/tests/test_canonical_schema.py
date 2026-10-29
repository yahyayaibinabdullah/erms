"""Prevent a final schema from accumulating upgrade replays again."""
from pathlib import Path
import re
import pytest
from tools.canonical_schema import assert_canonical,statements

ROOT=Path(__file__).resolve().parents[2]


def test_current_schema_defines_final_objects_without_replaying_changes():
    result=assert_canonical((ROOT/'database/schema.sql').read_text())
    assert result['functions']>300
    assert not any(s.startswith('CREATE TABLE IF NOT EXISTS') for s in statements((ROOT/'database/schema.sql').read_text()))


@pytest.mark.parametrize('extra',[
    'INSERT INTO schema_migrations(version) VALUES(\'new\');',
    'UPDATE profiles SET name=\'Changed\';',
    'DROP FUNCTION old_function();',
    'DO $$BEGIN UPDATE profiles SET name=\'changed\'; END$$;',
    'ALTER TABLE profiles ADD COLUMN old_column text;',
    'CREATE OR REPLACE FUNCTION test() RETURNS void LANGUAGE sql AS $$SELECT 1$$;',
])
def test_appended_upgrade_or_data_repair_is_rejected(extra):
    with pytest.raises(AssertionError):assert_canonical('BEGIN;\n'+extra+'\nCOMMIT;')


def test_function_bodies_and_quoted_semicolons_are_not_top_level_upgrades():
    source='''BEGIN;
    /* a nested /* comment */ is legal */
    CREATE FUNCTION public.worker() RETURNS void LANGUAGE plpgsql AS $worker$
    BEGIN
      UPDATE profiles SET name='semi;colon';
      -- Old-looking SQL inside the function is application logic.
      DELETE FROM sessions WHERE true;
    END $worker$;
    COMMIT;'''
    assert assert_canonical(source)['functions']==1
    assert len(statements(source))==3


def test_required_data_and_version_bookkeeping_are_separate():
    seed=(ROOT/'database/seeds/000_required_reference_data.sql').read_text()
    baseline=(ROOT/'database/baseline.sql').read_text()
    assert "set_config('app.event_source','seeding'" in seed
    assert 'schema_migrations' not in seed
    assert 'INSERT INTO schema_migrations' in baseline
    assert len([s for s in statements(baseline) if s.startswith('INSERT INTO')])==1
    assert '091_explicit_certificate_task_completion' in baseline


# These final definitions previously differed between a fresh installation and
# the same feature's approved upgrade. Compare with independent migration sources.
MIGRATION_ALIGNED_FUNCTIONS = (
    'aggregation_medium_contents_compatible',
    'enforce_aggregation_medium_hierarchy',
    'aggregation_effective_assigned_location_source_id',
    'aggregation_effective_current_location_source_id',
    'aggregation_has_vital_descendants',
    'append_hold_assignment_domain_events',
    'current_hold_actor_is_manager',
    'enforce_one_enabled_default_language',
    'enforce_saved_search_change_reason',
    'org_unit_effectively_active',
    'protect_vital_resource_deletion',
    'record_entity_history',
    'record_localization_catalogue_history',
    'record_user_preference_history',
    'require_localization_change_reason',
    'touch_localization_row',
    'touch_saved_search',
    'validate_saved_search_owner',
    'validate_user_management_lifecycle_dates',
)


def function_body(statement):
    match = re.search(r'\bAS\s+(\$[A-Za-z_0-9]*\$)(.*?)\1', statement, re.S | re.I)
    assert match, 'Expected a dollar-quoted SQL function body'
    return match[2].strip()


@pytest.fixture(scope='module')
def final_migration_functions():
    functions = {}
    pattern = re.compile(r'CREATE(?: OR REPLACE)? FUNCTION (?:public\.)?(\w+)\(', re.I)
    for path in sorted((ROOT / 'database/migrations').glob('*.sql')):
        for statement in statements(path.read_text()):
            if match := pattern.match(statement):
                if match[1] in MIGRATION_ALIGNED_FUNCTIONS:
                    functions[match[1]] = (path.name, statement)
    return functions


@pytest.mark.parametrize('name', MIGRATION_ALIGNED_FUNCTIONS)
def test_final_functions_match_the_last_approved_migration(name, final_migration_functions):
    schema = (ROOT / 'database/schema.sql').read_text()
    current = next(s for s in statements(schema) if s.startswith('CREATE FUNCTION public.' + name + '('))
    migration, expected = final_migration_functions[name]
    assert function_body(current) == function_body(expected), migration


@pytest.mark.parametrize('table,migration', [
    ('supported_languages', '019_add_internationalization_foundation.sql'),
    ('user_preferences', '019_add_internationalization_foundation.sql'),
    ('ui_message_definitions', '020_add_ui_message_catalogue.sql'),
    ('ui_message_translations', '020_add_ui_message_catalogue.sql'),
])
def test_named_checks_preserve_the_approved_upgrade_names(table, migration):
    expected = next(s for s in statements((ROOT / 'database/migrations' / migration).read_text())
                    if s.startswith('CREATE TABLE ' + table + ' ('))
    current = next(s for s in statements((ROOT / 'database/schema.sql').read_text())
                   if s.startswith('CREATE TABLE public.' + table + ' ('))
    names = re.findall(r'CONSTRAINT (\w+) CHECK', expected)
    assert names
    assert set(names) <= set(re.findall(r'CONSTRAINT (\w+) CHECK', current))


@pytest.mark.parametrize('table,before,after', [
    ('org_units', 'version bigint', 'status text GENERATED'),
    ('roles', 'is_information_governance boolean', 'status text GENERATED'),
    ('users', 'date_suspended timestamp', 'status text GENERATED'),
])
def test_lifecycle_columns_follow_the_migration_004_final_order(table, before, after):
    current = next(s for s in statements((ROOT / 'database/schema.sql').read_text())
                   if s.startswith('CREATE TABLE public.' + table + ' ('))
    assert current.index(before) < current.index(after)


@pytest.mark.parametrize('name', [
    'accelerate', 'allowed_transition', 'guard_resource', 'guard_workflow',
    'assert_unit',
])
def test_in_job_acceleration_functions_match_the_upgrade(name):
    prefix='CREATE FUNCTION disposition_private.'+name+'('
    canonical=next(s for s in statements((ROOT/'database/schema.sql').read_text()) if s.startswith(prefix))
    migration=next(s for s in statements((ROOT/'database/migrations/093_restore_reopened_job_members.sql').read_text())
                   if s.startswith(prefix.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION')))
    assert function_body(canonical)==function_body(migration)
