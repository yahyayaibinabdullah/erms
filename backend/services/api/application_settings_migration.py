"""Explicit reviewed legacy imports and per-database consumer readiness.

No HTTP service, environment fallback, automatic import, or private-file writes.
The closed active inventory expands only when the next consumer phase cuts over.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values
from psycopg.rows import dict_row

from .application_settings import apply_changes, load_snapshot
from .application_settings_registry import REGISTRY, SettingsInvalid, validate_value

MIGRATION_ID = 'application-settings-v1'
GENERAL_INTERFACE_KEYS = (
    'DEFAULT_WORKING_TIMEZONE', 'DEFAULT_ROOT_AGGREGATION_MEDIUM', 'REVIEW_WARNING_WINDOW_DAYS',
    'DASHBOARD_FAVOURITE_ITEM_LIMIT', 'DASHBOARD_RECENT_ITEM_LIMIT', 'DASHBOARD_RECENT_DAYS',
    'DASHBOARD_REVIEW_PREVIEW_LIMIT', 'CLASSIFICATION_RECENT_SELECTION_LIMIT', 'USER_DETAILS_SESSION_LIMIT',
)

CONTENT_KEYS = (
    'MAX_UPLOAD_SIZE_BYTES', 'CONTENT_SEGMENT_SIZE_BYTES', 'CONTENT_SEGMENT_CHECKSUMS_ENABLED',
    'CONTENT_UPLOAD_SESSION_TTL_SECONDS', 'CONTENT_CLEANUP_INTERVAL_SECONDS',
    'DOCUMENT_CONVERSION_TIMEOUT_SECONDS', 'MAX_RENDITION_SIZE_BYTES',
)
AUTHENTICATION_KEYS = (
    'AUTH_SESSION_IDLE_MINUTES', 'AUTH_SESSION_ABSOLUTE_HOURS', 'AUTH_LOCKOUT_ATTEMPTS',
    'AUTH_LOCKOUT_MINUTES', 'AUTH_PASSWORD_MIN_LENGTH', 'AUTH_SESSION_RETENTION_DAYS',
    'AUTH_SESSION_CLEANUP_INTERVAL_SECONDS', 'AUTH_SESSION_CLEANUP_BATCH_SIZE',
)
MIGRATED_KEYS = GENERAL_INTERFACE_KEYS + CONTENT_KEYS + AUTHENTICATION_KEYS


class MigrationInvalid(ValueError):
    """Safe operator errors contain codes/registered keys, never connection data."""


def source_values(path):
    values = dotenv_values(Path(path), interpolate=False)
    return {key: values[key] for key in MIGRATED_KEYS if key in values}


def parse_legacy(key, raw):
    definition = REGISTRY[key]
    if raw is None or not raw.strip():
        raise SettingsInvalid('legacy_value_invalid')
    if definition.kind == 'boolean':
        normalized = raw.strip().lower()
        if normalized not in {'true','false','1','0','yes','no','on','off'}:
            raise SettingsInvalid('legacy_value_invalid')
        value = normalized in {'true','1','yes','on'}
    else:
        value = int(raw.strip()) if definition.kind == 'integer' else raw.strip()
    if definition.kind == 'enum':
        value = value.lower()
    validate_value(definition, value)
    return value


def _state(connection):
    connection.row_factory = dict_row
    # Validate the complete registry, not a partial/default fallback.
    snapshot = load_snapshot(connection)
    completed = {r['key'] for r in connection.execute(
        'SELECT key FROM application_settings_migration_keys WHERE migration_id=%s', (MIGRATION_ID,)).fetchall()}
    rows = {r['key']:r for r in connection.execute(
        'SELECT key,value,version,provenance FROM application_settings WHERE key=ANY(%s) ORDER BY key',
        (list(MIGRATED_KEYS),)).fetchall()}
    return snapshot, completed, rows


def readiness(connection, legacy_keys=(), *, snapshot=None):
    snapshot = snapshot if snapshot is not None else load_snapshot(connection)
    # An empty fresh installation needs no legacy import. A local fresh database
    # with explicit legacy entries still requires a reviewed initialization.
    required = set(MIGRATED_KEYS) if snapshot.installation_kind == 'upgrade' else set(legacy_keys) & set(MIGRATED_KEYS)
    completed = {r['key'] for r in connection.execute(
        'SELECT key FROM application_settings_migration_keys WHERE migration_id=%s', (MIGRATION_ID,)).fetchall()} if required else set()
    return {'database':connection.info.dbname, 'database_id':snapshot.database_id,
            'ready':required.issubset(completed), 'pending':sorted(required - completed)}


def preview(connection, source, *, keep_database=(), use_legacy=()):
    keep_database, use_legacy = set(keep_database), set(use_legacy)
    if (keep_database | use_legacy) - set(MIGRATED_KEYS) or keep_database & use_legacy:
        raise MigrationInvalid('invalid_resolution_keys')
    snapshot, completed, rows = _state(connection)
    result = {'format_version':1, 'migration_id':MIGRATION_ID, 'database':connection.info.dbname,
              'database_id':snapshot.database_id, 'items':[], 'issues':[],
              'obsolete_entries':sorted(set(source) & set(MIGRATED_KEYS))}
    for key in sorted(MIGRATED_KEYS):
        row = rows[key]
        item = {'key':key, 'expected_version':row['version'], 'database_value':row['value'],
                'provenance':row['provenance'], 'resolution':None}
        if key in completed:
            item.update(action='completed', proposed_value=row['value'])
        elif key in keep_database:
            item.update(action='keep_database', proposed_value=row['value'], resolution='keep_database')
        else:
            try:
                value = parse_legacy(key,source[key]) if key in source else REGISTRY[key].default
            except (ValueError,TypeError):
                result['issues'].append({'key':key,'code':'legacy_value_invalid'})
                item.update(action='invalid', proposed_value=None)
            else:
                if row['provenance'] != 'default' and key not in source:
                    item.update(action='keep_database', proposed_value=row['value'])
                elif row['provenance'] != 'default' and value != row['value'] and key not in use_legacy:
                    item.update(action='conflict', proposed_value=value)
                    result['issues'].append({'key':key,'code':'configured_value_conflict'})
                else:
                    item.update(action='legacy' if key in source else 'default', proposed_value=value,
                                resolution='use_legacy' if key in use_legacy else None)
        result['items'].append(item)
    # Hash registered unfinished inputs only. Never persist the file or invalid
    # raw inputs; unrelated settings/credentials have no effect on this plan.
    unfinished = {}
    for key in sorted(set(MIGRATED_KEYS)-completed):
        try:
            legacy = parse_legacy(key,source[key]) if key in source else None
        except (ValueError,TypeError):
            legacy = {'invalid':True}  # Never hash an accidentally supplied secret.
        unfinished[key] = {'present':key in source,'value':legacy}
    result['source_sha256'] = hashlib.sha256(json.dumps(unfinished,sort_keys=True).encode()).hexdigest()
    return result


def _change(item, *, value=False, version=None):
    return SimpleNamespace(key=item['key'], expected_version=version or item['expected_version'],
        value=item['proposed_value'] if value else None,
        model_fields_set={'key','expected_version','value'} if value else {'key','expected_version'},
        secret_value=None, clear_secret=False)


def apply_preview(connection, plan, source, *, user_id, reason):
    if not isinstance(reason,str) or not reason.strip():
        raise MigrationInvalid('change_reason_required')
    if type(user_id) is not int or user_id < 1:
        raise MigrationInvalid('person_actor_required')
    if plan.get('format_version') != 1 or plan.get('migration_id') != MIGRATION_ID:
        raise MigrationInvalid('invalid_preview')
    items = plan.get('items')
    if not isinstance(items,list) or not all(isinstance(i,dict) for i in items) or {i.get('key') for i in items} != set(MIGRATED_KEYS) or len(items) != len(MIGRATED_KEYS):
        raise MigrationInvalid('invalid_preview')
    # Caller owns this transaction. Serialize with administration before rebuilding
    # the reviewed plan; a changed row/source cannot be silently accepted.
    connection.execute('SELECT key FROM application_settings WHERE key=ANY(%s) ORDER BY key FOR UPDATE', (list(MIGRATED_KEYS),))
    keep = [i['key'] for i in items if i.get('resolution') == 'keep_database']
    use = [i['key'] for i in items if i.get('resolution') == 'use_legacy']
    current = preview(connection,source,keep_database=keep,use_legacy=use)
    if current['database_id'] != plan.get('database_id') or current['database'] != plan.get('database'):
        raise MigrationInvalid('preview_target_changed')
    pending = [i for i in current['items'] if i['action'] != 'completed']
    # A completed rerun ignores later legacy edits and ordinary Settings versions.
    if pending and current != plan:
        raise MigrationInvalid('preview_stale_or_changed')
    if current['issues']:
        raise MigrationInvalid('resolve_preview_issues_before_apply')
    actor = connection.execute("SELECT id,name,email FROM users WHERE id=%s AND account_type='person' AND status='active' AND user_has_global_privilege(id,'app.settings.manage')", (user_id,)).fetchone()
    if not actor:
        raise MigrationInvalid('settings_authority_required')
    if not pending:
        return current
    connection.execute("SELECT set_config('app.user_id',%s,true),set_config('app.actor_name',%s,true),set_config('app.actor_email',%s,true),set_config('app.actor_type','user',true),set_config('app.event_source','migration',true),set_config('app.change_reason',%s,true)", (str(user_id),actor['name'],actor['email'],reason.strip()))
    # Explicitly choosing a differing legacy value is an ordinary governed edit
    # first, followed by completion, in the same all-or-nothing transaction.
    overrides = [i for i in pending if i['resolution'] == 'use_legacy' and i['provenance'] != 'default' and i['proposed_value'] != i['database_value']]
    if overrides:
        apply_changes(connection,[_change(i,value=True) for i in overrides],reason.strip())
    overridden = {i['key'] for i in overrides}
    changes = [_change(i,value=i['action'] in {'legacy','default'},
                       version=i['expected_version'] + (i['key'] in overridden)) for i in pending]
    apply_changes(connection,changes,reason.strip(),migration_id=MIGRATION_ID)
    # Verify the saved non-secret values and readiness in this transaction.
    verified = preview(connection,source)
    if any(i['action'] != 'completed' for i in verified['items']):
        raise MigrationInvalid('migration_verification_failed')
    return verified
