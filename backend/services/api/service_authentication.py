from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from psycopg import Connection


TEXT_INDEXING_ROUTE_PREFIX = "/api/v1/internal/text-indexing/"
TEXT_INDEXER_PRIVILEGE = "content.index.execute"
_IDENTIFIER_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_KEY_PATTERN = re.compile(
    r"\Awti_([0-9A-HJKMNP-TV-Z]{26})\.([A-Za-z0-9_-]{43})\Z"
)
_DUMMY_HASH = "0" * 64
_RATE_LOCK = threading.Lock()
_RATE_WINDOWS: dict[int, deque[float]] = defaultdict(deque)


@dataclass(frozen=True)
class ServicePrincipal:
    user_id: int
    credential_id: int
    identifier: str
    name: str
    account_type: str = "service"


def service_request_allowed(credential_id: int, limit_per_minute: int) -> bool:
    now = time.monotonic()
    with _RATE_LOCK:
        window = _RATE_WINDOWS[credential_id]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit_per_minute:
            return False
        window.append(now)
        return True


def generate_api_key() -> tuple[str, str, str]:
    """Return the display-once key, its lookup identifier, and stored digest."""
    identifier = "".join(secrets.choice(_IDENTIFIER_ALPHABET) for _ in range(26))
    secret = secrets.token_urlsafe(32)
    key = f"wti_{identifier}.{secret}"
    return key, identifier, hashlib.sha256(secret.encode("ascii")).hexdigest()


def parse_api_key(value: str) -> tuple[str, str] | None:
    match = _KEY_PATTERN.fullmatch(value)
    return (match.group(1), match.group(2)) if match else None


def resolve_text_indexer_principal(
    connection: Connection, value: str, *, worker_id: str | None = None,
) -> ServicePrincipal | None:
    parsed = parse_api_key(value)
    identifier, secret = parsed if parsed else ("0" * 26, "")
    candidate_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
    row = connection.execute(
        """
        SELECT credential.id AS credential_id, credential.service_user_id,
               credential.credential_identifier, credential.secret_hash,
               account.name
          FROM service_account_credentials credential
          JOIN users account ON account.id=credential.service_user_id
         WHERE credential.credential_identifier=%s
           AND credential.status='active'
           AND credential.date_revoked IS NULL
           AND credential.expires_at>CURRENT_TIMESTAMP
           AND account.account_type='service'
           AND account.status='active'
           AND user_has_global_privilege(account.id,%s)
        """,
        (identifier, TEXT_INDEXER_PRIVILEGE),
    ).fetchone()
    expected_hash = row["secret_hash"] if row else _DUMMY_HASH
    valid = parsed is not None and hmac.compare_digest(candidate_hash, expected_hash)
    if not valid:
        return None
    connection.execute(
        """
        UPDATE service_account_credentials
           SET last_used_at=CURRENT_TIMESTAMP,
               last_worker_id=COALESCE(%s,last_worker_id)
         WHERE id=%s
           AND (last_used_at IS NULL OR last_used_at<CURRENT_TIMESTAMP-interval '5 minutes')
        """,
        (worker_id[:255] if worker_id else None, row["credential_id"]),
    )
    return ServicePrincipal(
        user_id=row["service_user_id"], credential_id=row["credential_id"],
        identifier=row["credential_identifier"], name=row["name"],
    )
