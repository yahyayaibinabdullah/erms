"""Source checks follow the feature owners without changing their assertions."""
from pathlib import Path


def search_sources():
    root = Path(__file__).parents[1]
    return "\n".join((root / name).read_text() for name in (
        "advanced_search_model.py", "saved_search_audiences.py",
        "saved_search_administration.py", "advanced_search.py", "advanced_search_state.py",
    ))
