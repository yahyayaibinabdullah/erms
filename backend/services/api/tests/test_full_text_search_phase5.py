import json
import os
import sys

import pytest
import psycopg
from fastapi import HTTPException

from backend.services.api import search
from backend.services.api.schemas import GlobalSearchRequest, SearchRequest
from backend.services.api import text_indexing_maintenance
from backend.services.api.text_indexing_maintenance import quality_gate


def test_quality_gate_accepts_phase2_observation(tmp_path):
    report = tmp_path / "quality.json"
    report.write_text(json.dumps({"summary": {
        "english_recall": 0.90, "arabic_recall": 0.75, "marker_recall": 0.90,
    }}), encoding="utf-8")
    result = quality_gate(report)
    assert result["passed"] is True
    assert result["thresholds"] == {
        "english_recall": 0.90, "arabic_recall": 0.75, "marker_recall": 0.90,
    }


def test_quality_gate_rejects_any_language_below_floor(tmp_path):
    report = tmp_path / "quality.json"
    report.write_text(json.dumps({"summary": {
        "english_recall": 0.99, "arabic_recall": 0.749, "marker_recall": 1.0,
    }}), encoding="utf-8")
    assert quality_gate(report)["passed"] is False


def test_cleanup_watch_runs_immediately_then_waits(monkeypatch, capsys):
    calls = []

    def fake_run_cleanup_pass(**settings):
        calls.append(settings)
        return {"leader": True, "credentials": 2},17

    def stop_after_first_pass(seconds):
        assert seconds == 17
        raise RuntimeError("watch loop stopped by test")

    monkeypatch.setattr(text_indexing_maintenance, "_run_cleanup_pass", fake_run_cleanup_pass)
    monkeypatch.setattr(text_indexing_maintenance.time, "sleep", stop_after_first_pass)
    monkeypatch.setattr(sys, "argv", [
        "text_indexing_maintenance", "cleanup", "--watch",
        "--interval-seconds", "17", "--batch-size", "23",
        "--retention-days", "31", "--credential-retention-days", "47",
    ])
    with pytest.raises(RuntimeError, match="watch loop stopped by test"):
        text_indexing_maintenance.main()
    assert calls == [{
        "batch_size": 23,
        "retention_days": 31,
        "credential_retention_days": 47,
        "dry_run": False, "watch":True,"interval_seconds":17,
    }]
    assert json.loads(capsys.readouterr().out) == {"leader": True, "credentials": 2}


def test_production_cleanup_service_runs_api_owned_watch_process():
    service = open(
        "backend/services/api/deploy/erms-text-indexing-maintenance.service",
        encoding="utf-8",
    ).read()
    assert "EnvironmentFile=/etc/erms/api.env" in service
    assert "backend.services.api.text_indexing_maintenance cleanup --watch" in service
    assert "User=erms" in service


def test_global_search_rollout_gate_precedes_database_access(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(search.settings_cache,"for_connection",lambda c:{"FULL_TEXT_SEARCH_ENABLED":False,"AUDIT_TRAIL_SEARCH_RESULT_LIMIT":1000})
    with pytest.raises(HTTPException) as error:
        search.global_search_rows(None, GlobalSearchRequest(
            record_where={"full_text": {"query": "water", "sources": ["metadata"]}},
            result_types=["records"],
        ))
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "full_text_search_disabled"


def test_resource_full_text_rollout_gate_does_not_disable_structured_search(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(search.settings_cache,"for_connection",lambda c:{"FULL_TEXT_SEARCH_ENABLED":False,"AUDIT_TRAIL_SEARCH_RESULT_LIMIT":1000})
    request = SearchRequest(where={"field": "title", "operator": "eq", "value": "x"})
    class Connection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("structured search passed rollout gate")
    with pytest.raises(RuntimeError, match="structured search passed rollout gate"):
        search.search_rows(Connection(), "records", request)


def test_automatic_scheduling_gate_keeps_pending_freshness(client, record, monkeypatch):
    from backend.services.api.tests.test_application_settings import save
    assert save(client,{"CONTENT_INDEXING_SCHEDULING_ENABLED":False}).status_code==200
    disabled = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 1}, files={"file": ("disabled.txt", b"disabled", "text/plain")},
    )
    assert disabled.status_code == 201, disabled.text
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT status FROM digital_component_search_documents WHERE digital_component_id=%s",
            (disabled.json()["id"],),
        ).fetchone()[0] == "pending"
        assert connection.execute(
            "SELECT count(*) FROM content_indexing_jobs WHERE digital_component_id=%s",
            (disabled.json()["id"],),
        ).fetchone()[0] == 0

    assert save(client,{"CONTENT_INDEXING_SCHEDULING_ENABLED":True}).status_code==200
    enabled = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 2}, files={"file": ("enabled.txt", b"enabled", "text/plain")},
    )
    assert enabled.status_code == 201, enabled.text
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM content_indexing_jobs WHERE digital_component_id=%s",
            (enabled.json()["id"],),
        ).fetchone()[0] == 1
