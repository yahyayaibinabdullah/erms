"""Read a pinned historical schema for UPGRADE TEST FIXTURES only.

Never use this snapshot to initialize a new application database. Current
initialization uses tools.initialize_database and database/schema.sql.
Keeping the history in Git avoids duplicating the old migration replay in the
canonical schema or another checked-in SQL file. CI needs this commit available.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRE_CONSOLIDATION_REF = 'a476ff2dc6e96f29d8d1047ccbbc656fa5455657'


def historical_schema():
    result = subprocess.run(
        ['git', 'show', PRE_CONSOLIDATION_REF + ':database/schema.sql'],
        cwd=ROOT, text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(
            'Upgrade tests need historical commit ' + PRE_CONSOLIDATION_REF
            + '; fetch repository history before running them.'
        )
    return result.stdout
