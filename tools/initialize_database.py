"""Install the current schema, required reference data and fresh baseline separately.

This is for NEW databases. Existing databases use the numbered migrations.
The schema file is independently executable and contains only object definitions.
"""
from pathlib import Path
import argparse
import os
import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
INSTALL_FILES = (
    ROOT / 'database/schema.sql',
    ROOT / 'database/seeds/000_required_reference_data.sql',
    ROOT / 'database/baseline.sql',
)


def initialize(connection):
    """Initialize an empty database only; never reconcile an existing installation."""
    row = connection.execute("SELECT to_regclass('public.schema_migrations') AS existing").fetchone()
    if (row['existing'] if isinstance(row, dict) else row[0]) is not None:
        raise ValueError('Database is already initialized; apply missing migrations instead')
    connection.commit()
    for path in INSTALL_FILES:
        connection.execute(path.read_text(), prepare=False)
        connection.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', default=None)
    args = parser.parse_args()
    configuration = {**dotenv_values(ROOT / '.env'), **os.environ}
    with psycopg.connect(args.database_url or configuration['DATABASE_URL']) as connection:
        initialize(connection)
    print('Installed current schema, required reference data and included-version baseline.')


if __name__ == '__main__':
    main()
