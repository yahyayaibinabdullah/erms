from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from .authentication import SYSTEM_ADMIN_ROLE, hash_password, revoke_sessions_for_user, temporary_password
from .config import required_environment
from .application_settings import load_snapshot


BOOTSTRAP_ORG_UNIT_CODE = "SYSTEM"
BOOTSTRAP_ORG_UNIT_NAME = "Platform Administration"
BOOTSTRAP_ROLE_NAME = "SYSTEM — System Administrator"
BOOTSTRAP_USER_NAME = "Bootstrap Administrator"
BOOTSTRAP_USER_EMAIL = "bootstrap@erms.local"
SYSTEM_ADMIN_PROFILE = "SYS_ADMIN"
TEMPORARY_PASSWORD_HOURS = 24


@dataclass(frozen=True)
class BootstrapResult:
    user_id: int
    org_unit_id: int
    role_id: int
    email: str
    temporary_password: str
    expires_at: datetime


def _temporary_credential(connection) -> tuple[str, str, datetime]:
    password = temporary_password(load_snapshot(connection))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TEMPORARY_PASSWORD_HOURS)
    return password, hash_password(password), expires_at


def _set_provisioning_audit_context(connection: Connection, email: str) -> None:
    metadata = json.dumps(
        {"provisioning_operation": "bootstrap_administrator", "bootstrap_email": email}
    )
    connection.execute(
        """
        SELECT set_config('app.actor_type', 'automated_process', true),
               set_config('app.event_source', 'administrative_tool', true),
               set_config('app.change_reason', 'Initial system bootstrap', true),
               set_config('app.correlation_id', %s, true),
               set_config('app.event_metadata', %s, true)
        """,
        (str(uuid4()), metadata),
    )


def bootstrap_administrator(
    connection: Connection,
    *,
    name: str = BOOTSTRAP_USER_NAME,
    email: str = BOOTSTRAP_USER_EMAIL,
) -> BootstrapResult:
    """Provision the sole initial interactive administrator in an empty database."""
    name = name.strip()
    email = email.strip().lower()
    if not name:
        raise ValueError("bootstrap administrator name cannot be blank")
    if not email:
        raise ValueError("bootstrap administrator email cannot be blank")

    active_admin = connection.execute(
        """
        SELECT u.email
        FROM users AS u
        JOIN user_role_assignments AS assignment ON assignment.user_id = u.id
        JOIN roles AS role ON role.id = assignment.role_id
        WHERE lower(role.code) = lower(%s)
          AND u.account_type = 'person'
          AND u.status = 'active'
          AND role_effectively_active(role.id)
          AND assignment.valid_from <= CURRENT_TIMESTAMP
          AND (assignment.valid_until IS NULL OR assignment.valid_until > CURRENT_TIMESTAMP)
        ORDER BY u.id
        LIMIT 1
        """,
        (SYSTEM_ADMIN_ROLE,),
    ).fetchone()
    if active_admin:
        raise RuntimeError(
            f"an active system administrator already exists ({active_admin['email']}); "
            "bootstrap made no changes"
        )

    user_count = connection.execute("SELECT count(*) AS count FROM users").fetchone()["count"]
    if user_count:
        raise RuntimeError(
            "bootstrap is permitted only when the users table is empty; use the "
            "password recovery command to promote an existing user"
        )

    _set_provisioning_audit_context(connection, email)
    org_unit = connection.execute(
        "INSERT INTO org_units (code, name) VALUES (%s, %s) RETURNING id",
        (BOOTSTRAP_ORG_UNIT_CODE, BOOTSTRAP_ORG_UNIT_NAME),
    ).fetchone()
    user = connection.execute(
        """
        INSERT INTO users (name, email, external_id, account_type)
        VALUES (%s, %s, 'SYSTEM-BOOTSTRAP', 'person')
        RETURNING id
        """,
        (name, email),
    ).fetchone()
    role = connection.execute(
        """
        INSERT INTO roles (org_unit_id, code, name, description, profile_id)
        SELECT %s, %s, %s, 'Reserved platform administration role', id
          FROM profiles WHERE code=%s
        RETURNING id
        """,
        (org_unit["id"], SYSTEM_ADMIN_ROLE, BOOTSTRAP_ROLE_NAME, SYSTEM_ADMIN_PROFILE),
    ).fetchone()
    connection.execute(
        "INSERT INTO user_role_assignments (user_id, role_id) VALUES (%s, %s)",
        (user["id"], role["id"]),
    )
    password, password_hash, expires_at = _temporary_credential(connection)
    connection.execute(
        """
        INSERT INTO user_credentials (
            user_id, password_hash, must_change_password, temporary_expires_at
        )
        VALUES (%s, %s, true, %s)
        """,
        (user["id"], password_hash, expires_at),
    )
    return BootstrapResult(
        user_id=user["id"],
        org_unit_id=org_unit["id"],
        role_id=role["id"],
        email=email,
        temporary_password=password,
        expires_at=expires_at,
    )


def set_temporary_password(
    connection: Connection,
    email: str,
    *,
    make_admin: bool,
    org_unit_code: str | None,
) -> str:
    user = connection.execute(
        "SELECT id, account_type FROM users WHERE lower(email)=lower(%s)", (email,)
    ).fetchone()
    if not user:
        raise RuntimeError(f"no user exists with email {email}")
    if user["account_type"] != "person":
        raise RuntimeError("interactive passwords can only be issued to person accounts")
    connection.execute(
        """
        SELECT set_config('app.actor_type', 'automated_process', true),
               set_config('app.actor_name', 'Authentication recovery tool', true),
               set_config('app.event_source', 'administrative_tool', true),
               set_config('app.change_reason', 'Administrative password recovery', true),
               set_config('app.correlation_id', %s, true)
        """,
        (str(uuid4()),),
    )
    password, password_hash, expires_at = _temporary_credential(connection)
    connection.execute(
        """
        INSERT INTO user_credentials (user_id,password_hash,must_change_password,temporary_expires_at)
        VALUES (%s,%s,true,%s)
        ON CONFLICT (user_id) DO UPDATE SET password_hash=EXCLUDED.password_hash,
          must_change_password=true, temporary_expires_at=EXCLUDED.temporary_expires_at,
          failed_attempt_count=0, locked_until=NULL, date_updated=CURRENT_TIMESTAMP
        """,
        (user["id"], password_hash, expires_at),
    )
    revoked = revoke_sessions_for_user(
        connection,
        user["id"],
        revoked_by=None,
        reason="password_reset",
    )
    connection.execute(
        "SELECT append_domain_event('user', %s, 'PASSWORD_RESET', %s::jsonb)",
        (
            user["id"],
            json.dumps({
                "temporary": True,
                "expires_at": expires_at.isoformat(),
                "sessions_revoked": revoked,
            }),
        ),
    )
    if make_admin:
        if not org_unit_code:
            raise RuntimeError("--org-unit-code is required when assigning system administrator")
        org = connection.execute(
            "SELECT id FROM org_units WHERE lower(code)=lower(%s)", (org_unit_code,)
        ).fetchone()
        if not org:
            raise RuntimeError(f"organization unit {org_unit_code} does not exist")
        role = connection.execute(
            "SELECT id FROM roles WHERE lower(code)=lower(%s)", (SYSTEM_ADMIN_ROLE,)
        ).fetchone()
        if not role:
            role = connection.execute(
                """
                INSERT INTO roles (org_unit_id,code,name,description,profile_id)
                SELECT %s,%s,%s,'Reserved platform administration role',id
                  FROM profiles WHERE code=%s
                RETURNING id
                """,
                (org["id"], SYSTEM_ADMIN_ROLE, BOOTSTRAP_ROLE_NAME, SYSTEM_ADMIN_PROFILE),
            ).fetchone()
        connection.execute(
            """
            INSERT INTO user_role_assignments (user_id,role_id)
            SELECT %s,%s WHERE NOT EXISTS (
              SELECT 1 FROM user_role_assignments
              WHERE user_id=%s AND role_id=%s AND valid_until IS NULL
            )
            """,
            (user["id"], role["id"], user["id"], role["id"]),
        )
    return password


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ERMS authentication provisioning and recovery")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser(
        "bootstrap", help="create the first administrator in an empty database"
    )
    bootstrap.add_argument("--name", default=BOOTSTRAP_USER_NAME)
    bootstrap.add_argument("--email", default=BOOTSTRAP_USER_EMAIL)
    reset = commands.add_parser(
        "reset-password", help="issue a temporary password to an existing person account"
    )
    reset.add_argument("email")
    reset.add_argument("--make-system-administrator", action="store_true")
    reset.add_argument("--org-unit-code")
    return parser


def main() -> None:
    arguments = sys.argv[1:]
    # Preserve the original `manage_auth EMAIL ...` recovery syntax.
    if arguments and arguments[0] not in {"bootstrap", "reset-password", "-h", "--help"}:
        arguments.insert(0, "reset-password")
    args = _parser().parse_args(arguments)
    with psycopg.connect(required_environment("DATABASE_URL"), row_factory=dict_row) as connection:
        if args.command == "bootstrap":
            result = bootstrap_administrator(connection, name=args.name, email=args.email)
            print(f"Bootstrap administrator created: {result.email}")
            print("Temporary password (shown once):")
            print(result.temporary_password)
            print(
                f"It expires in {TEMPORARY_PASSWORD_HOURS} hours and must be changed "
                "at first login."
            )
            return
        password = set_temporary_password(
            connection,
            args.email,
            make_admin=args.make_system_administrator,
            org_unit_code=args.org_unit_code,
        )
    print("Temporary password (shown once):")
    print(password)
    print(
        f"It expires in {TEMPORARY_PASSWORD_HOURS} hours and must be changed at first login."
    )


if __name__ == "__main__":
    main()
