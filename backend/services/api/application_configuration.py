"""Finite non-secret values needed by ordinary page/bootstrap responses.

The API's existing validated 30-second cache is the sole configuration authority.
No localized or identity-specific data is cached here.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from psycopg import Connection
from .application_settings import cache
from .application_settings_registry import REGISTRY

UI_CONFIGURATION_KEYS = tuple(key for key, definition in REGISTRY.items()
                              if definition.category in {"general", "interface_limits"})
from .authentication import Principal, principal_from_request
from .database import get_connection


def ui_configuration(connection, *, snapshot=None):
    settings = snapshot if snapshot is not None else cache.for_connection(connection)
    return {key:settings[key] for key in UI_CONFIGURATION_KEYS}


def recent_since_default(days):
    now = datetime.now(timezone.utc)
    # Registry integers can exceed datetime's day range. An all-history interval
    # remains valid without inventing a lower setting limit or overflowing.
    return datetime.min.replace(tzinfo=timezone.utc) if days >= now.toordinal() else now - timedelta(days=days)


router = APIRouter(tags=['application configuration'])


@router.get('/api/v1/application-configuration',response_model=dict[str, object])
def effective_configuration(principal:Principal=Depends(principal_from_request),
                            connection:Connection=Depends(get_connection,scope='function')):
    """One bounded response for a page/dialog that needs effective defaults."""
    return ui_configuration(connection)
