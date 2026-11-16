import os

import psycopg
from fastapi.testclient import TestClient

from backend.services.api.authentication import hash_password


def favourite_data(response):
    from backend.services.api.application_configuration import UI_CONFIGURATION_KEYS
    data=response.json()
    assert set(data.pop("application_configuration"))==set(UI_CONFIGURATION_KEYS)
    return data


def test_favourite_aggregation_and_record_are_idempotent_and_hydrated(
    client: TestClient, aggregation: dict, record: dict,
):
    for _ in range(2):
        assert client.put(
            f"/api/v1/favourites/aggregations/{aggregation['id']}"
        ).status_code == 204
        assert client.put(
            f"/api/v1/favourites/records/{record['id']}"
        ).status_code == 204

    response = client.get("/api/v1/favourites")
    assert response.status_code == 200
    assert favourite_data(response) == {
        "aggregations": [{
            "id": aggregation["id"],
            "aggregation_number": aggregation["aggregation_number"],
            "title": aggregation["title"],
            "parent_aggregation_id": None,
            "date_favourited": response.json()["aggregations"][0]["date_favourited"],
        }],
        "records": [{
            "id": record["id"],
            "record_number": record["record_number"],
            "title": record["title"],
            "aggregation_id": aggregation["id"],
            "aggregation_number": aggregation["aggregation_number"],
            "aggregation_title": aggregation["title"],
            "date_favourited": response.json()["records"][0]["date_favourited"],
        }],
    }

    for _ in range(2):
        assert client.delete(
            f"/api/v1/favourites/aggregations/{aggregation['id']}"
        ).status_code == 204
        assert client.delete(
            f"/api/v1/favourites/records/{record['id']}"
        ).status_code == 204
    assert favourite_data(client.get("/api/v1/favourites")) == {
        "aggregations": [], "records": [],
    }


def test_favourite_missing_targets_return_not_found(client: TestClient):
    assert client.put("/api/v1/favourites/aggregations/999999").status_code == 404
    assert client.put("/api/v1/favourites/records/999999").status_code == 404
    assert client.delete("/api/v1/favourites/aggregations/999999").status_code == 204
    assert client.delete("/api/v1/favourites/records/999999").status_code == 204


def test_favourite_pages_include_creator_for_only_the_returned_items(
    client: TestClient, aggregation: dict, record: dict,
):
    assert client.put(f"/api/v1/favourites/aggregations/{aggregation['id']}").status_code == 204
    assert client.put(f"/api/v1/favourites/records/{record['id']}").status_code == 204
    first = client.get('/api/v1/favourites', params={'limit': 1}).json()
    second = client.get('/api/v1/favourites', params={'limit': 1, 'offset': 1}).json()
    assert first['total'] == second['total'] == 2
    assert not first['aggregations'] and not second['records']
    assert first['records'][0]['id'] == record['id'] and first['records'][0]['created_by']
    assert second['aggregations'][0]['id'] == aggregation['id'] and second['aggregations'][0]['created_by']
    records = client.get('/api/v1/favourites', params={'kind': 'record', 'limit': 1}).json()
    assert records['total'] == 1 and records['records'][0]['id'] == record['id']
    empty = client.get('/api/v1/favourites', params={'limit': 1, 'offset': 2}).json()
    assert empty['total'] == 2 and not empty['records'] and not empty['aggregations']
    dashboard = client.get('/api/v1/dashboard/summary').json()['favourites']
    assert dashboard['records'][0]['created_by'] == first['records'][0]['created_by']
    assert dashboard['aggregations'][0]['created_by'] == second['aggregations'][0]['created_by']


def test_favourites_are_isolated_by_authenticated_user(
    client: TestClient, aggregation: dict,
):
    assert client.put(
        f"/api/v1/favourites/aggregations/{aggregation['id']}"
    ).status_code == 204

    second_password = "Second-Test-Password-123!"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        second_id = connection.execute(
            "INSERT INTO users (name,email) VALUES ('Second User','second@test.invalid') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO user_credentials (user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
            (second_id, hash_password(second_password)),
        )

    login = client.post("/api/v1/auth/login", json={
        "email": "second@test.invalid", "password": second_password,
    })
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
    assert favourite_data(client.get("/api/v1/favourites")) == {
        "aggregations": [], "records": [],
    }
    assert favourite_data(client.get("/api/v1/favourites", params={"limit": 1})) == {
        "aggregations": [], "records": [], "total": 0,
    }
    assert client.delete(
        f"/api/v1/favourites/aggregations/{aggregation['id']}"
    ).status_code == 204

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM user_favourite_aggregations"
        ).fetchone()[0] == 1


def test_deleting_targets_cascades_favourites(
    client: TestClient, aggregation: dict, record: dict,
):
    client.put(f"/api/v1/favourites/aggregations/{aggregation['id']}")
    client.put(f"/api/v1/favourites/records/{record['id']}")

    assert client.delete(
        f"/api/v1/records/{record['id']}",
        headers={"If-Match": str(record["version"])},
    ).status_code == 204
    assert client.delete(
        f"/api/v1/aggregations/{aggregation['id']}",
        headers={"If-Match": str(aggregation["version"])},
    ).status_code == 204
    assert favourite_data(client.get("/api/v1/favourites")) == {
        "aggregations": [], "records": [],
    }


def test_favourite_changes_do_not_create_event_history(
    client: TestClient, aggregation: dict,
):
    before = client.post("/api/v1/event-history/search", json={"limit": 1}).json()["total"]
    client.put(f"/api/v1/favourites/aggregations/{aggregation['id']}")
    client.delete(f"/api/v1/favourites/aggregations/{aggregation['id']}")
    after = client.post("/api/v1/event-history/search", json={"limit": 1}).json()["total"]
    assert after == before
