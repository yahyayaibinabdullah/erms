"""Source contracts follow the extracted aggregation owners."""
from pathlib import Path


def aggregation_sources():
    root=Path(__file__).parents[1]
    return '\n'.join((root/(name+'.py')).read_text() for name in (
        'aggregation_actions','aggregation_selector','aggregation_details',
        'aggregation_browser','aggregation_toolbar','aggregation_editor',
        'aggregation_presentation','aggregation_state','relationship_select_styles',
    ))
