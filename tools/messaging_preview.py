"""Disposable-only browser fixture; called by the messaging acceptance runner."""
from uuid import uuid4

import json
import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient


def seed():
    assert psycopg.conninfo.conninfo_to_dict(os.environ["DATABASE_URL"])[
        "dbname"
    ].startswith("erms_messaging_test_")
    from backend.services.api.main import app
    from backend.services.api.authentication import hash_password
    from backend.services.api.localization import synchronize_generated_arabic_drafts
    from backend.services.api.messaging.models import Send
    from backend.services.api.messaging.service import send
    from backend.services.api.messaging.transactions import run
    from uuid import uuid4

    with TestClient(app) as client:
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
            c.execute("SELECT set_config('app.event_source','seeding',true)")
            org = c.execute(
                "INSERT INTO org_units(code,name) VALUES ('MESSAGE-PREVIEW','Message preview') RETURNING id"
            ).fetchone()["id"]
            profile = c.execute(
                "SELECT id FROM profiles WHERE code='ALL_PRIVS'"
            ).fetchone()["id"]
            role = c.execute(
                "INSERT INTO roles(org_unit_id,code,name,profile_id) VALUES (%s,'message-preview','Message preview',%s) RETURNING id",
                (org, profile),
            ).fetchone()["id"]
            scheme = c.execute(
                "INSERT INTO classification_schemes(code,title,date_published) VALUES('MESSAGE-PREVIEW','Message preview',CURRENT_TIMESTAMP) RETURNING id"
            ).fetchone()["id"]
            classification = c.execute(
                "INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,'MESSAGE-PREVIEW-01','Message preservation',true) RETURNING id",
                (scheme,),
            ).fetchone()["id"]
            c.execute(
                "INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",
                (classification,),
            )
            users = []
            for name, email in [
                ("Message Sender", "sender@messages.test"),
                ("Message Recipient", "recipient@messages.test"),
            ]:
                uid = c.execute(
                    "INSERT INTO users(name,email) VALUES (%s,%s) RETURNING id",
                    (name, email),
                ).fetchone()["id"]
                users.append(uid)
                c.execute(
                    "INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)",
                    (uid, role),
                )
                c.execute(
                    "INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
                    (uid, hash_password("Messaging-Preview-123!")),
                )
        synchronize_generated_arabic_drafts()
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "sender@messages.test",
                "password": "Messaging-Preview-123!",
            },
        )
        assert login.status_code == 200, login.text
        client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
        destination = client.post(
            "/api/v1/aggregations", headers={'Idempotency-Key': str(uuid4()), 'X-Event-Source': 'seeding'},
            json={
                "aggregation_number": "MESSAGE-CAPTURE-PREVIEW",
                "title": "Message capture destination",
                "classification_id": classification,
            },
        )
        assert destination.status_code == 201, destination.text
        # Publish fixture copies solely in this disposable database for RTL QA.
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
            items = c.execute(
                "SELECT message_key,version FROM ui_message_translations WHERE language_tag='ar' AND origin<>'source_copy'"
            ).fetchall()
        result = client.post(
            "/api/v1/admin/i18n/translations/ar/bulk-review-publish",
            json={"items": items},
            headers={
                "X-Change-Reason": "Publish disposable messaging browser fixtures"
            },
        )
        assert result.status_code == 200, result.text
        for i in range(28):
            source, target = (users[0], users[1]) if i % 2 else (users[1], users[0])
            run(
                source,
                lambda c: send(
                    c,
                    source,
                    Send(
                        request_id=uuid4(),
                        subject=f"Message preview {i+1}",
                        body_rich_text="<p>Review the message and respond when the action is complete.</p>",
                        selectors=[{"selector_kind": "user", "target_id": target}],
                        action_required=True,
                        read_receipt_requested=True,
                    ),
                ),
            )
    print(
        "Disposable browser accounts: sender@messages.test / recipient@messages.test; password: Messaging-Preview-123!",
        flush=True,
    )


if __name__ == "__main__":
    seed()
