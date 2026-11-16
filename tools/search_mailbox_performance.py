"""Mailbox workload for the disposable search-performance runner."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

MAILBOX_ROWS = 2400
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
RECEIPT_ENVELOPE = UUID("5ebfc233-df44-4924-ab0e-ea0de4018e05")
RECEIPT_SENT_OFFSET = MAILBOX_ROWS + 1


def seed_mailboxes(connection):
    connection.execute("SET LOCAL session_replication_role='replica'")
    connection.execute("""CREATE TEMP TABLE mailbox_benchmark_rows ON COMMIT DROP AS
        SELECT owner.id AS user_id, other.id AS other_id, owner.name, n,
               md5('envelope-'||owner.name||'-'||n)::uuid AS envelope_id,
               md5('delivery-'||owner.name||'-'||n)::uuid AS delivery_id,
               md5('draft-'||owner.name||'-'||n)::uuid AS draft_id,
               CASE WHEN n%%37=0 THEN 'Mailbox rare subject' ELSE 'Mailbox common subject' END AS subject,
               ('<p>Body '||CASE WHEN n%%29=0 THEN 'rare' ELSE 'common' END||'</p>'
                 ||repeat('<p>Review the <strong>budget</strong> and retention schedule.</p>',8)) AS body,
               %s + n*interval '1 second' AS sent_at,
               (SELECT id FROM security_levels ORDER BY level_number LIMIT 1) AS security_level_id
        FROM users owner JOIN users other ON other.name IN ('reader','denied') AND other.id<>owner.id
        CROSS JOIN generate_series(1,%s) n WHERE owner.name IN ('reader','denied')""",
        (START, MAILBOX_ROWS))
    connection.execute("""INSERT INTO message_envelopes
        (id,sender_user_id,sender_name,sender_kind,message_kind,subject,body_rich_text,security_level_id,
         action_required,read_receipt_requested,sent_at,expires_at,request_id)
        SELECT envelope_id,user_id,name,'user','user_message',subject,body,security_level_id,
               false,false,sent_at,CURRENT_TIMESTAMP+interval '30 days',md5('request-'||envelope_id)::uuid
        FROM mailbox_benchmark_rows""")
    connection.execute("""INSERT INTO message_deliveries
        (id,envelope_id,recipient_user_id,recipient_type,mailbox_sequence,created_at,language_tag_at_send)
        SELECT delivery_id,envelope_id,other_id,'to',n,sent_at,'en' FROM mailbox_benchmark_rows""")
    connection.execute("""INSERT INTO message_drafts
        (id,owner_user_id,subject,body_rich_text,security_level_id,action_required,read_receipt_requested,
         date_created,date_updated,expires_at)
        SELECT draft_id,user_id,subject,body,security_level_id,false,false,sent_at,sent_at,
               CURRENT_TIMESTAMP+interval '30 days' FROM mailbox_benchmark_rows""")
    for table, key in (("message_resource_links", "envelope_id"), ("message_draft_resource_links", "draft_id")):
        connection.execute(f"""INSERT INTO {table}
            ({key},link_token,ordinal,resource_kind,target_id_snapshot,aggregation_id,record_id,security_level_id_at_send)
            SELECT {key},md5('link-'||{key})::uuid,1,
                   CASE WHEN n%4=0 THEN 'aggregation' ELSE 'record' END,n,
                   CASE WHEN n%4=0 THEN n END,CASE WHEN n%4<>0 THEN n END,security_level_id
            FROM mailbox_benchmark_rows""")
    seed_receipts(connection)
    connection.commit()
    connection.autocommit = True
    try:
        for table in ("message_envelopes", "message_deliveries", "message_drafts",
                      "message_resource_links", "message_draft_resource_links",
                      "message_addressees", "message_action_completions", "users"):
            connection.execute(f"VACUUM ANALYZE {table}")
    finally:
        connection.autocommit = False


def seed_receipts(connection):
    from backend.services.api.messaging.config import LIMITS

    connection.execute("""INSERT INTO users(name,email)
        SELECT 'Receipt benchmark '||n,'receipt-'||n||'@performance.invalid'
        FROM generate_series(1,%s) n""", (LIMITS["MAX_RECIPIENTS_PER_SEND"],))
    connection.execute("""INSERT INTO message_envelopes
        (id,sender_user_id,sender_name,sender_kind,message_kind,subject,body_rich_text,security_level_id,
         action_required,read_receipt_requested,sent_at,expires_at,request_id)
        SELECT %s,id,name,'user','user_message','Large receipt fixture','<p>Receipt benchmark</p>',
               (SELECT id FROM security_levels ORDER BY level_number LIMIT 1),
               true,true,%s,CURRENT_TIMESTAMP+interval '30 days',gen_random_uuid()
        FROM users WHERE name='reader'""", (RECEIPT_ENVELOPE, START + timedelta(seconds=RECEIPT_SENT_OFFSET)))
    connection.execute("""INSERT INTO message_addressees(envelope_id,user_id,recipient_name,recipient_type,ordinal)
        SELECT %s,id,name,CASE WHEN row_number() OVER (ORDER BY id)%%4=0 THEN 'cc' ELSE 'to' END,
               row_number() OVER (ORDER BY id) - 1
        FROM users WHERE email LIKE 'receipt-%%@performance.invalid'""", (RECEIPT_ENVELOPE,))
    connection.execute("""INSERT INTO message_deliveries
        (id,envelope_id,recipient_user_id,recipient_type,mailbox_sequence,created_at,language_tag_at_send,read_at)
        SELECT gen_random_uuid(),envelope_id,user_id,recipient_type,1,CURRENT_TIMESTAMP,'en',
               CASE WHEN ordinal%%2=0 THEN CURRENT_TIMESTAMP END
        FROM message_addressees WHERE envelope_id=%s""", (RECEIPT_ENVELOPE,))
    connection.execute("""INSERT INTO message_action_completions
        (original_delivery_id,reply_envelope_id,completed_by_user_id,completed_at)
        SELECT d.id,gen_random_uuid(),a.user_id,CURRENT_TIMESTAMP
        FROM message_addressees a JOIN message_deliveries d ON
            d.envelope_id=a.envelope_id AND d.recipient_user_id=a.user_id
        WHERE a.envelope_id=%s AND a.ordinal%%4=0""", (RECEIPT_ENVELOPE,))


def _case_ids(folder, identity, matches):
    sender = ("denied" if identity == "reader" else "reader") if folder == "inbox" else identity
    kind = {"inbox": "delivery", "outbox": "envelope", "drafts": "draft"}[folder]
    return [
        (n, str(UUID(hashlib.md5(f"{kind}-{sender}-{n}".encode(), usedforsecurity=False).hexdigest())))
        for n in range(MAILBOX_ROWS, 0, -1) if matches(n)
    ]


def _explain(connection, user, folder, criteria, cursor, page_size):
    from backend.services.api.messaging import drafts, reading
    from backend.services.api.messaging.text_filters import TextFilters

    class ExplainedConnection:
        @property
        def info(self):
            return connection.info

        def execute(self, statement, params=None, **kwargs):
            query = statement if isinstance(statement, str) else statement.as_string(connection)
            if query.rstrip().endswith("LIMIT %s") and " FROM message_" in query:
                self.plan = connection.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params, prepare=False,
                ).fetchone()["QUERY PLAN"]
                # The benchmark already checked the emitted API results. Avoid
                # executing the listing a second time solely to hydrate rows.
                return connection.execute("SELECT 1 WHERE false")
            return connection.execute(statement, params, **kwargs)

    captured = ExplainedConnection()
    reader = {"inbox": reading.inbox, "outbox": reading.outbox, "drafts": drafts.listing}[folder]
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        connection.execute("SELECT set_config('app.user_id',%s,true)", (str(user),))
        reader(captured, user, page_size, cursor, text_filters=TextFilters(**criteria))
    return captured.plan


def exercise_mailboxes(output, repeats, page_size):
    from fastapi.testclient import TestClient
    from backend.services.api.main import app
    from backend.services.api.messaging.reading import cursor_encode
    from tools.check_search_performance import PASSWORD

    cases = (
        ("unfiltered", {}, lambda _: True),
        ("linked_broad", {"linked_q": "universal OR common"}, lambda _: True),
        ("linked_file_selective", {"linked_q": "contentprobe"}, lambda n: n <= 73 and n % 4 != 0),
        ("linked_aggregation_only", {"linked_q": "common"}, lambda n: n % 4 == 0),
        ("linked_empty", {"linked_q": "zzabsent"}, lambda _: False),
        ("subject_broad", {"q": "Mailbox"}, lambda _: True),
        ("subject_selective", {"q": "rare subject"}, lambda n: n % 37 == 0),
        ("body_broad", {"body_q": "review the budget"}, lambda _: True),
        ("body_selective", {"body_q": "Body rare"}, lambda n: n % 29 == 0),
        ("body_empty", {"body_q": "zzabsent"}, lambda _: False),
        ("combined", {"q": "Mailbox", "body_q": "Body rare", "linked_q": "universal OR common"},
         lambda n: n % 29 == 0),
    )
    rows = []
    failures = []
    plans = []
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, TestClient(app) as client:
        for identity in ("reader", "denied"):
            client.cookies.clear()
            login = client.post("/api/v1/auth/login", json={
                "email": identity + "@performance.invalid", "password": PASSWORD,
            })
            login.raise_for_status()
            user = client.get("/api/v1/auth/me").json()["user"]["id"]
            for folder in ("inbox", "outbox", "drafts"):
                for label, criterion, predicate in cases:
                    expected = _case_ids(folder, identity, predicate) if identity == "reader" or "linked_q" not in criterion else []
                    if label == "unfiltered" and folder == "outbox" and identity == "reader":
                        expected.insert(0, (RECEIPT_SENT_OFFSET, str(RECEIPT_ENVELOPE)))
                    pages = [0]
                    if len(expected) > page_size:
                        pages.append(page_size)
                    if len(expected) > 1000:
                        pages.append(len(expected) - page_size)
                    for offset in pages:
                        cursor = None
                        if offset:
                            n, previous_id = expected[offset - 1]
                            cursor = cursor_encode({"sent_at": START + timedelta(seconds=n), "id": previous_id}, "id")
                        params = {"limit": page_size, **criterion}
                        if cursor is not None:
                            params["cursor"] = cursor
                        expected_ids = [item[1] for item in expected[offset:offset + page_size]]
                        for sample in range(repeats):
                            start = perf_counter()
                            response = client.get(f"/api/v1/messages/{folder}", params=params)
                            elapsed = perf_counter() - start
                            response.raise_for_status()
                            result = response.json()
                            actual_ids = [row["id"] for row in result["items"]]
                            assert actual_ids == expected_ids, (folder, label, identity, offset, actual_ids, expected_ids)
                            assert result["has_more"] == (offset + page_size < len(expected))
                            measurement = dict(folder=folder, identity=identity, case=label, params=params, offset=offset,
                                               sample=sample, seconds=elapsed, expected_count=len(expected), ids=actual_ids)
                            rows.append(measurement)
                            if elapsed > 3:
                                failures.append(measurement)
                    if label in ("unfiltered", "linked_broad", "linked_file_selective", "linked_empty", "body_broad", "subject_selective"):
                        plans.append((user, identity, folder, label, criterion))
                print(f"Measured {identity} {folder}", flush=True)
        (output/"mailbox-results.json").write_text(json.dumps(dict(results=rows, failures=failures), indent=2))
        for user, identity, folder, label, criterion in plans:
            plan = _explain(connection, user, folder, criterion, None, page_size)
            (output/f"mailbox-plan-{identity}-{folder}-{label}.json").write_text(json.dumps(plan, indent=2))
        exercise_receipts(client, connection, output, repeats)
    assert not failures, f"{len(failures)} mailbox responses exceeded 3 seconds"


def exercise_receipts(client, connection, output, repeats):
    from backend.services.api.messaging.reading import RECIPIENT_PAGE_SQL, RECIPIENT_SUMMARY_SQL
    from tools.check_search_performance import PASSWORD

    path = f"/api/v1/messages/outbox/{RECEIPT_ENVELOPE}"
    recipients = connection.execute(
        """SELECT recipient_user_id,created_at FROM message_deliveries
           WHERE envelope_id=%s ORDER BY recipient_user_id""",
        (RECEIPT_ENVELOPE,),
    ).fetchall()
    identities = [row["recipient_user_id"] for row in recipients]
    delivered_at = [row["created_at"] for row in recipients]
    count = len(identities)
    sizes = (0, count - 3, count)
    expected_summary = {
        "delivered": count, "read": (count + 1) // 2, "action_total": count - count // 4,
        "completed": (count + 3) // 4, "action_status": "outstanding",
    }
    results = []
    for identity, expected_status in (("reader", 200), ("denied", 404)):
        client.cookies.clear()
        client.post("/api/v1/auth/login", json={
            "email": identity + "@performance.invalid", "password": PASSWORD,
        }).raise_for_status()
        user = client.get("/api/v1/auth/me").json()["user"]["id"]
        for start in (None, *sizes):
            endpoint = path if start is None else path + "/recipients"
            params = None if start is None else {"limit": 3, "after": identities[start - 1] if start else 0}
            for sample in range(repeats):
                began = perf_counter()
                response = client.get(endpoint, params=params)
                seconds = perf_counter() - began
                assert response.status_code == expected_status, response.text
                result = response.json()
                actual = None
                if expected_status == 200:
                    if start is None:
                        actual = result["recipient_summary"]
                        assert actual == expected_summary, actual
                    else:
                        actual = [row["recipient_user_id"] for row in result["items"]]
                        assert actual == identities[start:start + 3], actual
                        timestamps = [row["delivered_at"] for row in result["items"]]
                        assert [datetime.fromisoformat(value) for value in timestamps] == delivered_at[start:start + 3]
                        assert result["has_more"] == (start + 3 < count)
                results.append(dict(caller=identity, offset=start, sample=sample, seconds=seconds, result=actual))
            if identity == "reader":
                statement = RECIPIENT_SUMMARY_SQL if start is None else RECIPIENT_PAGE_SQL.format(read_field=",read_at")
                arguments = dict(identity=RECEIPT_ENVELOPE, receipts=True, action=True) if start is None else {
                    "identity": RECEIPT_ENVELOPE, "user": user, **params, "limit": 4,
                }
                plan = connection.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, arguments, prepare=False,
                ).fetchone()["QUERY PLAN"]
                (output/f"receipt-plan-{start}.json").write_text(json.dumps(plan, indent=2))
    (output/"receipt-results.json").write_text(json.dumps({
        "expected_summary": expected_summary, "results": results,
    }, indent=2))
    assert all(item["seconds"] <= 3 for item in results), "Outbox receipt responses exceeded 3 seconds"
