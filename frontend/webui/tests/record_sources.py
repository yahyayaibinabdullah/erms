"""Source contracts follow the record and shared collection owners."""
from pathlib import Path


def record_sources():
    root = Path(__file__).parents[1]
    return '\n'.join((root / (name + '.py')).read_text() for name in (
        'record_details', 'record_capture', 'record_editor', 'record_presentation',
        'record_state', 'entity_editor', 'collection_state', 'collection_table',
        'collection_navigation', 'resource_collection_results',
        'resource_row_hydration', 'resource_row_presentation',
    ))
