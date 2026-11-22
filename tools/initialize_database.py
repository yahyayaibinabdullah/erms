"""Install a fresh ERMS database, or emit the identical transaction for psql."""
import argparse
import os
from pathlib import Path
import re
import sys

if __package__:
    from .canonical_schema import statements
else:
    from canonical_schema import statements

ROOT = Path(__file__).resolve().parents[1]
INSTALL_FILES = (
    ROOT / 'database/schema.sql',
    ROOT / 'database/seeds/000_required_reference_data.sql',
    ROOT / 'database/baseline.sql',
)

# The receipt writer consumes this transaction-local marker. A partial or older
# installation must fail before it can acquire one, even with an empty ledger.
PREFLIGHT = """
DO $$
BEGIN
    IF to_regnamespace('disposition_private') IS NOT NULL OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_class
        WHERE relnamespace = 'public'::regnamespace
          AND relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
    ) THEN
        RAISE EXCEPTION 'Database already contains a schema; apply missing migrations instead'
            USING ERRCODE = '55000';
    END IF;
END
$$;
CREATE TEMP TABLE erms_fresh_install () ON COMMIT DROP;
"""


def installation_body():
    parts = [PREFLIGHT]
    for path in INSTALL_FILES:
        # Reuse each standalone file's statements under one transaction owner.
        commands = statements(path.read_text(encoding='utf-8'))
        if commands[:1] != ['BEGIN'] or commands[-1:] != ['COMMIT']:
            raise ValueError(f'{path.name} must have a single explicit transaction')
        for command in commands[1:-1]:
            if re.match(r'^(?:BEGIN|START\s+TRANSACTION|COMMIT|END|ROLLBACK|ABORT|PREPARE\s+TRANSACTION)\b', command, re.I):
                raise ValueError(f'Unexpected transaction boundary in {path.name}')
            parts.append(command + ';')
    return '\n'.join(parts)


def initialize(connection):
    """Initialize a fresh target atomically, respecting any caller-owned transaction."""
    import psycopg

    try:
        with connection.transaction():
            connection.execute(installation_body(), prepare=False)
    except psycopg.errors.ObjectNotInPrerequisiteState as error:
        if error.diag.message_primary == 'Database already contains a schema; apply missing migrations instead':
            raise ValueError(error.diag.message_primary) from error
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--database-url')
    modes.add_argument('--print-sql', action='store_true',
                       help='Print the complete atomic installation for psql, without connecting')
    args = parser.parse_args()
    if args.print_sql:
        sys.stdout.write('BEGIN;\n' + installation_body() + '\nCOMMIT;\n')
        return

    import psycopg
    from dotenv import dotenv_values

    configuration = {**dotenv_values(ROOT / '.env'), **os.environ}
    with psycopg.connect(args.database_url or configuration['DATABASE_URL']) as connection:
        initialize(connection)
    print('Installed current schema, required reference data and included-version baseline.')


if __name__ == '__main__':
    main()
