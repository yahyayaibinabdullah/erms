import hashlib
import json
from pathlib import Path
import subprocess

from frontend.webui.acl_editor import acl_grants_payload
from frontend.webui.entities import ENTITIES
from frontend.webui.i18n_catalogue import load_english_manifest

ROOT = Path(__file__).resolve().parents[3]
APP = (ROOT / "frontend/webui/app.py").read_text()


def test_contextual_principals_use_labels_not_role_selectors_or_anchors():
    for principal in ("owning_and_higher_level_unit_managers", "effective_file_administrator"):
        assert principal in APP
        assert acl_grants_payload([{"principal_type": principal, "role_id": None, "display_name": "Contextual", "permission_codes": ["record.view"]}]) == [
            {"principal_type": principal, "role_id": None, "permission_codes": ["record.view"]},
        ]
    assert 'render_message("authorization.oversight.dynamic", owner_name=owner_name)' in APP
    assert '"organization.browse" in (auth_state.get("principal") or {})' in APP
    assert 'result.get("acl", {}).get("contextual_matches", [])' in APP


def test_unit_designations_use_bounded_same_unit_search_and_retain_selected_values():
    unit = ENTITIES["org-units"]
    assert {"managing_role_id", "file_administrator_role_id"} <= {field.name for field in unit.fields}
    assert '{"field": "org_unit_id", "operator": "eq", "value": unit_id}' in APP
    assert 'page_loader=designated_roles, active=lambda: dialog.value' in APP
    assert '"sort": [{"field": "code", "direction": "asc"}], "limit": 25' in APP


def test_unit_details_show_both_designated_roles_with_details_links():
    section = APP.split("async def select_organization_unit_details", 1)[1].split("async def select_role_details", 1)[0]
    for label, field in (("Managing role", "managing_role"), ("File Administrator role", "file_administrator_role")):
        assert f'(entity_metadata_label("{label}"), unit.get("{field}"), "role")' in section
    assert 'role_id=value["id"]: select_role_details(role_id)' in section
    assert 'else "—"' in section
    assert 'api.list(' not in section


def test_org_unit_editor_reads_complete_record_before_initializing_role_controls():
    section = APP.split("async def open_editor", 1)[1].split("async def show_memberships", 1)[0]
    fresh_read = section.index('row = await api.get("org-units", row["id"])')
    assert fresh_read < section.index('selected_id = (')
    assert fresh_read < section.index('payload = form_payload(spec, controls, creating=creating)')


def test_contextual_details_page_on_server_and_ignore_closed_dialog_responses():
    section = APP.split("async def show_contextual_acl_roles", 1)[1].split("async def show_acl_editor", 1)[0]
    assert '"limit": 25, "offset": offset' in section
    assert 'if not dialog.value or revision != state["revision"]:' in section
    assert 'state["offset"]+25' in section
    assert 'result["has_more"]' in section
    assert 'api.list(' not in section
    assert 'ui.table(' not in section


def test_oversight_catalogue_covers_both_languages_and_preserves_curated_rows():
    source_path = ROOT / "frontend/webui/i18n/messages.en.json"
    artifact_path = ROOT / "frontend/webui/i18n/messages.ar.generated.json"
    manifest = load_english_manifest()
    current = json.loads(artifact_path.read_text())
    original = json.loads(subprocess.check_output(["git", "show", "HEAD:frontend/webui/i18n/messages.ar.generated.json"], cwd=ROOT))
    current_by_key = {item["message_key"]: item for item in current["items"]}
    assert all(current_by_key[item["message_key"]] == item for item in original["items"])
    assert current["catalogue_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert [item["message_key"] for item in current["items"]] == sorted(manifest)
    for key in manifest:
        if key.startswith("authorization.oversight."):
            assert current_by_key[key]["translated_text"].strip()
            assert current_by_key[key]["quality_flags"] == []
            assert "provenance" in current_by_key[key]
            assert set(manifest[key]["parameter_schema"]) <= {"owner_name", "unit_id"}
