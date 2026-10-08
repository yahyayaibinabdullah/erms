"""Named aggregation/record links. Disposition integration is deliberately deferred."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg import Connection
from psycopg.errors import CheckViolation, ForeignKeyViolation, InsufficientPrivilege, UniqueViolation, RestrictViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from .authentication import principal_from_request
from .authorization_policy import require_global_privilege
from .concurrency import expected_version
from .database import get_connection

Kind = Literal['aggregation', 'record']
Language = str
router = APIRouter(prefix='/api/v1/relationships', tags=['resource relationships'],
                   dependencies=[Depends(principal_from_request)])


class TranslatedNames(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    forward_name: str = Field(min_length=1, max_length=250)
    reverse_name: str = Field(min_length=1, max_length=250)


class TypeCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    code: str = Field(pattern=r'^[a-z][a-z0-9_]*$', max_length=100)
    forward_name: str = Field(min_length=1, max_length=250)
    reverse_name: str = Field(min_length=1, max_length=250)
    # Legacy fields remain accepted for existing clients; the editor uses translations.
    arabic_forward_name: str | None = Field(None, min_length=1, max_length=250)
    arabic_reverse_name: str | None = Field(None, min_length=1, max_length=250)
    translations: dict[str, TranslatedNames | None] = Field(default_factory=dict)
    is_symmetric: bool = False



class TypeUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    forward_name: str = Field(min_length=1, max_length=250)
    reverse_name: str = Field(min_length=1, max_length=250)
    # Legacy fields remain accepted for existing clients; the editor uses translations.
    arabic_forward_name: str | None = Field(None, min_length=1, max_length=250)
    arabic_reverse_name: str | None = Field(None, min_length=1, max_length=250)
    translations: dict[str, TranslatedNames | None] = Field(default_factory=dict)
    is_active: bool


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    relationship_type_id: int = Field(gt=0)
    target_id: int = Field(gt=0)
    direction: Literal['forward', 'reverse'] = 'forward'


messages = {'relationship_access_denied': 'relationships.error.access_denied', 'relationship_duplicate': 'relationships.error.duplicate', 'relationship_type_in_use': 'relationships.error.type_in_use', 'relationship_type_scope_mismatch': 'relationships.error.type_scope_mismatch', 'relationship_type_inactive': 'relationships.error.type_inactive', 'relationship_arabic_labels_required': 'relationships.error.arabic_labels_required', 'relationship_resource_not_found': 'relationships.error.resource_not_found', 'relationship_type_not_found': 'relationships.error.type_not_found', 'relationship_not_found': 'relationships.error.not_found', 'relationship_invalid': 'relationships.error.invalid', 'stale_version': 'common.error.stale_version'}


def failure(code: str, status: int = 409):
    raise HTTPException(status, detail={'code': code, 'message_key': messages.get(code, messages['relationship_invalid']), 'parameters': {}})


def translate_error(error):
    if isinstance(error, InsufficientPrivilege):
        failure('relationship_access_denied', 403)
    if isinstance(error, UniqueViolation):
        failure('relationship_duplicate')
    if isinstance(error, (ForeignKeyViolation, RestrictViolation)):
        failure('relationship_type_in_use')
    failure(error.diag.message_primary if error.diag.message_primary in messages else 'relationship_invalid', 422)


def tables(kind: Kind):
    # Values are selected only from the closed path enum, never interpolated user input.
    return ('aggregations', 'aggregation_number') if kind == 'aggregation' else ('records', 'record_number')


def require_endpoint(c, kind, resource_id):
    table, _ = tables(kind)
    if not c.execute(f'SELECT 1 FROM {table} WHERE id=%s AND current_user_can_view_{kind}(id)',
                     (resource_id,)).fetchone():
        failure('relationship_resource_not_found', 404)


def labels(row, language):
    row = dict(row)
    localized = (row.get('translations') or {}).get(language, {})
    localized = localized or (row.get('translations') or {}).get(language.split('-')[0], {})
    row['forward_label'] = localized.get('forward_name', row['forward_name'])
    row['reverse_label'] = localized.get('reverse_name', row['reverse_name'])
    return row


@router.get('/types/{kind}')
def list_types(kind: Kind, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
               active_only: bool = True, language_tag: Language = 'en', q: str = Query('', max_length=200), descending: bool = False,
               c: Connection = Depends(get_connection, scope='function')):
    # Reading a type does not confer management authority or resource access.
    query = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    where = '''resource_kind=%s AND (NOT %s OR is_active) AND
        (code ILIKE %s OR forward_name ILIKE %s OR reverse_name ILIKE %s
         OR EXISTS (SELECT 1 FROM jsonb_each(translations) t WHERE t.value->>'forward_name' ILIKE %s OR t.value->>'reverse_name' ILIKE %s))'''
    parameters = (kind, active_only, query, query, query, query, query)
    total = c.execute(f'SELECT count(*) AS total FROM relationship_types WHERE {where}',
                      parameters).fetchone()['total']
    order = 'code DESC,id DESC' if descending else 'code,id'
    rows = c.execute(f'SELECT * FROM relationship_types WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s',
                     (*parameters, limit, offset)).fetchall()
    return {'items': [labels(row, language_tag) for row in rows], 'total': total, 'limit': limit, 'offset': offset}


@router.get('/types/{kind}/{type_id}')
def get_type(kind: Kind, type_id: int, language_tag: Language = 'en',
             c: Connection = Depends(get_connection, scope='function')):
    row = c.execute('SELECT * FROM relationship_types WHERE id=%s AND resource_kind=%s', (type_id, kind)).fetchone()
    if not row:
        failure('relationship_type_not_found', 404)
    return labels(row, language_tag)


def translated_names(c, payload, existing=None, symmetric=False):
    from .localization import _canonical_language_tag
    values = dict(existing or {})
    for tag, names in payload.translations.items():
        canonical = _canonical_language_tag(tag)
        if not c.execute(
            'SELECT 1 FROM supported_languages WHERE language_tag=%s AND is_enabled', (canonical,)
        ).fetchone():
            failure('relationship_invalid', 422)
        if names is None:
            values.pop(canonical, None)
        else:
            if symmetric and names.forward_name != names.reverse_name:
                failure('relationship_invalid', 422)
            values[canonical] = names.model_dump()
    if payload.arabic_forward_name is not None or payload.arabic_reverse_name is not None:
        values['ar'] = {'forward_name': payload.arabic_forward_name, 'reverse_name': payload.arabic_reverse_name}
    return values


@router.post('/types/{kind}', status_code=201,
             dependencies=[Depends(require_global_privilege('relationships.administer'))])
def create_type(kind: Kind, payload: TypeCreate, c: Connection = Depends(get_connection, scope='function')):
    try:
        with c.transaction():
            return c.execute('''INSERT INTO relationship_types(resource_kind,code,forward_name,reverse_name,
                translations,is_symmetric) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *''',
                (kind, payload.code, payload.forward_name, payload.reverse_name,
                 Jsonb(translated_names(c, payload, symmetric=payload.is_symmetric)), payload.is_symmetric)).fetchone()
    except (UniqueViolation, CheckViolation, InsufficientPrivilege) as error:
        translate_error(error)


@router.patch('/types/{kind}/{type_id}',
              dependencies=[Depends(require_global_privilege('relationships.administer'))])
def update_type(kind: Kind, type_id: int, payload: TypeUpdate, version: int = Depends(expected_version),
                c: Connection = Depends(get_connection, scope='function')):
    try:
        with c.transaction():
            row = c.execute('SELECT * FROM relationship_types WHERE id=%s AND resource_kind=%s FOR UPDATE',
                            (type_id, kind)).fetchone()
            if not row:
                failure('relationship_type_not_found', 404)
            if row['version'] != version:
                failure('stale_version')
            translations = translated_names(c, payload, row['translations'], row['is_symmetric'])
            return c.execute('''UPDATE relationship_types SET forward_name=%s,reverse_name=%s,
                translations=%s,is_active=%s WHERE id=%s RETURNING *''',
                (payload.forward_name, payload.reverse_name, Jsonb(translations), payload.is_active, type_id)).fetchone()
    except (CheckViolation, InsufficientPrivilege) as error:
        translate_error(error)


@router.delete('/types/{kind}/{type_id}', status_code=204,
               dependencies=[Depends(require_global_privilege('relationships.administer'))])
def delete_type(kind: Kind, type_id: int, version: int = Depends(expected_version),
                c: Connection = Depends(get_connection, scope='function')):
    try:
        with c.transaction():
            row = c.execute('SELECT version FROM relationship_types WHERE id=%s AND resource_kind=%s FOR UPDATE',
                            (type_id, kind)).fetchone()
            if not row:
                failure('relationship_type_not_found', 404)
            if row['version'] != version:
                failure('stale_version')
            c.execute('DELETE FROM relationship_types WHERE id=%s', (type_id,))
    except (ForeignKeyViolation, RestrictViolation, InsufficientPrivilege) as error:
        translate_error(error)
    return Response(status_code=204)


@router.get('/{kind}/{resource_id}/targets')
def targets(kind: Kind, resource_id: int, q: str = Query('', max_length=200),
            selected_id: int | None = Query(None, gt=0), limit: int = Query(25, ge=1, le=50),
            c: Connection = Depends(get_connection, scope='function')):
    require_endpoint(c, kind, resource_id)
    table, number = tables(kind)
    if selected_id is None and len(q.strip()) < 2:
        return {'items': []}
    query = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    return {'items': c.execute(f'''SELECT id,{number} AS number,title FROM {table}
        WHERE id<>%s AND current_user_can_view_{kind}(id)
        AND ((%s::bigint IS NOT NULL AND id=%s) OR (%s::bigint IS NULL AND (title ILIKE %s OR {number} ILIKE %s OR description ILIKE %s)))
        ORDER BY {number},id LIMIT %s''',
        (resource_id, selected_id, selected_id, selected_id, query, query, query, limit)).fetchall()}


@router.post('/{kind}/{resource_id}', status_code=201,
             dependencies=[Depends(require_global_privilege('relationships.link'))])
def create_link(kind: Kind, resource_id: int, payload: LinkCreate,
                c: Connection = Depends(get_connection, scope='function')):
    require_endpoint(c, kind, resource_id)
    require_endpoint(c, kind, payload.target_id)
    source, target = (resource_id, payload.target_id) if payload.direction == 'forward' else (payload.target_id, resource_id)
    try:
        with c.transaction():
            return c.execute(f'''INSERT INTO {kind}_relationships(relationship_type_id,source_id,target_id)
                VALUES (%s,%s,%s) RETURNING *''', (payload.relationship_type_id, source, target)).fetchone()
    except (UniqueViolation, CheckViolation, InsufficientPrivilege) as error:
        translate_error(error)


@router.delete('/{kind}/{resource_id}/{link_id}', status_code=204,
               dependencies=[Depends(require_global_privilege('relationships.link'))])
def delete_link(kind: Kind, resource_id: int, link_id: int,
                c: Connection = Depends(get_connection, scope='function')):
    require_endpoint(c, kind, resource_id)
    try:
        with c.transaction():
            row = c.execute(f'''SELECT * FROM {kind}_relationships
                WHERE id=%s AND (source_id=%s OR target_id=%s) FOR UPDATE''', (link_id, resource_id, resource_id)).fetchone()
            if not row:
                failure('relationship_not_found', 404)
            require_endpoint(c, kind, row['source_id'])
            require_endpoint(c, kind, row['target_id'])
            c.execute(f'DELETE FROM {kind}_relationships WHERE id=%s', (link_id,))
    except InsufficientPrivilege as error:
        translate_error(error)
    return Response(status_code=204)


@router.get('/{kind}/{resource_id}')
def list_links(kind: Kind, resource_id: int, language_tag: Language = 'en',
               limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
               type_id: int | None = Query(None, gt=0),
               sort: Literal['id', 'type'] = 'id', descending: bool = False,
               c: Connection = Depends(get_connection, scope='function')):
    require_endpoint(c, kind, resource_id)
    table, number = tables(kind)
    where = '(link.source_id=%s OR link.target_id=%s) AND (%s::bigint IS NULL OR link.relationship_type_id=%s)'
    params = (resource_id, resource_id, type_id, type_id)
    total = c.execute(f'SELECT count(*) AS total FROM {kind}_relationships link WHERE {where}', params).fetchone()['total']
    order = 'definition.code,link.id' if sort == 'type' else 'link.id'
    order = ','.join(column + (' DESC' if descending else ' ASC') for column in order.split(','))
    rows = c.execute(f'''SELECT link.date_created AS link_created_at,link.source_id=%s AS is_forward,
        definition.*, link.id AS link_id,
        CASE WHEN current_user_can_view_{kind}(target.id) THEN target.id END AS related_id,
        CASE WHEN current_user_can_view_{kind}(target.id) THEN target.{number} END AS related_number,
        CASE WHEN current_user_can_view_{kind}(target.id) THEN target.title END AS related_title
        FROM {kind}_relationships link JOIN relationship_types definition ON definition.id=link.relationship_type_id
        JOIN {table} target ON target.id=CASE WHEN link.source_id=%s THEN link.target_id ELSE link.source_id END
        WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s''',
        (resource_id, resource_id, *params, limit, offset)).fetchall()
    items = []
    for row in rows:
        definition = labels(row, language_tag)
        items.append({'id': row['link_id'], 'relationship_type_id': row['id'],
                      'label': definition['forward_label'] if row['is_forward'] else definition['reverse_label'],
                      'direction': 'forward' if row['is_forward'] else 'reverse',
                      'is_active': row['is_active'], 'date_created': row['link_created_at'],
                      'related': {'id': row['related_id'], 'number': row['related_number'], 'title': row['related_title'],
                                  'redacted': row['related_id'] is None}})
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}
