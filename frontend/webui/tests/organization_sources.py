"""Locations for retained source-contract checks after organization extraction."""
from pathlib import Path


def organization_sources():
    root=Path(__file__).parents[1]
    return '\n'.join((root/(name+'.py')).read_text() for name in (
        'organization_units','organization_roles','organization_users',
        'organization_memberships','organization_deletion','organization_browser',
        'organization_editor','organization_collections','organization_collection_actions',
        'administration_cards','identity_presentation','organization_table',
    ))
