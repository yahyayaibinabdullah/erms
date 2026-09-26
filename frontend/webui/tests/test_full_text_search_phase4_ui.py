from pathlib import Path


APP = Path(__file__).parents[1] / "app.py"
CLIENT = Path(__file__).parents[1] / "api_client.py"
LOCAL_STACK = Path(__file__).parents[3] / "run-local-stack.sh"


def test_global_search_header_results_and_safe_snippets_are_present():
    source = APP.read_text()
    assert 'placeholder="Search records, files and aggregations"' in source
    assert 'global_search_input.on("keydown.enter"' in source
    assert 'classes("erms-global-search-wrap no-wrap")' in source
    assert "global_search_wrap.set_visibility(full_text_search_enabled())" in source
    assert "left: 50%; transform: translateX(-50%)" in source
    assert "if full_text_search_enabled():" in source
    assert 'async def run_global_search(' in source
    assert 'async def change_global_search_page(' in source
    assert "aria-label='Previous page'" in source
    assert "aria-label='Next page'" in source
    assert '"Load more results"' not in source
    assert '"Recently added content may still be indexing' in source
    assert 'def render_safe_snippet(' in source
    assert 'text = " ".join(text.split())' in source
    assert 'render_safe_snippet(component.get("snippet"), compact=True)' in source
    assert 'ui.html(' not in source[source.index("def render_safe_snippet("):source.index("async def copy_diagnostic_json(")]
    assert 'await api.full_text_search(payload)' in source
    assert 'async def full_text_search(' in CLIENT.read_text()
    assert 'result_item["authorized_component_details"] = component_details.get' in source
    assert 'for component in item.get("matching_components", [])' in source
    assert '{**authorized_component_details.get(int(component["id"]), {}), **component}' in source
    assert 'preview_record_components(selected, component_id)' in source
    assert "aria-label='Preview digital component'" in source
    assert 'can_expand_components=bool(' in source
    assert 'record_capabilities.get("list_components") and matching_components' in source
    assert 'record_capabilities.get("view_component")' in source
    assert 'metadata_matched=bool(item.get("matched_record_metadata"))' in source
    assert 'content_matched=bool(matching_components)' in source
    assert 'classes("compact-result-component-badge")' in source
    assert 'components_are_matches=True' in source
    assert "f\"{'matching ' if components_are_matches else ''}digital component\"" in source
    assert 'async def open_global_record(record_id: int)' in source
    assert 'async def open_global_aggregation(aggregation: dict[str, Any])' in source
    assert 'global_search_return_anchor' in source
    assert 'global_search_expanded_results' in source
    assert 'initially_expanded=(' in source
    assert 'restore_compact_result_anchor(' in source
    assert source.count('state.pop("discard_navigation_guard", None)') >= 7


def test_diagnostics_are_privileged_opt_in_transient_and_failure_aware():
    source = APP.read_text()
    assert '"search.query.debug" in set(' in source
    assert '"search_diagnostics_enabled": False' in source
    assert 'Diagnostics will apply to the next explicit search.' in source
    assert '"debug"] = True' in source
    assert 'Unavailable — the API did not accept or return this diagnostic request.' in source
    assert 'state["search_diagnostics_sent"] = None' in source


def test_service_credentials_are_service_only_and_one_time_reveal_is_transient():
    source = APP.read_text()
    assert 'if person.get("account_type") == "service"' in source
    assert 'ui.badge("Non-interactive"' in source
    assert 'ui.label("API credentials")' in source
    assert 'Copy and store this key now. It will not be shown again.' in source
    assert 'api_key = ""' in source
    assert 'Downloads a sensitive plaintext file' in source
    assert 'Internal text-indexing API only' in source


def test_text_indexer_health_and_bounded_backfill_are_administered_in_the_ui():
    source = APP.read_text()
    client = CLIENT.read_text()
    assert 'api.text_indexers_health()' in source
    assert 'ui.label("Health")' in source
    assert '"Active workers"' in source
    assert '"Expired leases"' in source
    assert 'API liveness is reported separately by /health.' in source
    assert 'ui.label("Queue backfill batch")' in source
    assert '"Maximum components", value=500, min=1, max=500, step=1' in source
    assert 'await api.queue_text_indexers_backfill(requested)' in source
    assert 'async def text_indexers_health(' in client
    assert 'async def queue_text_indexers_backfill(' in client
    assert '"/api/v1/text-indexers/health"' in client
    assert '"/api/v1/text-indexers/backfill"' in client
    assert 'ui.label("Retry failed documents")' in source
    assert '"Maximum failed documents", value=100, min=1, max=500, step=1' in source
    assert 'await api.retry_failed_text_indexer_documents(requested)' in source
    assert '"Failed documents", health.get("failed_documents", 0)' in source
    assert 'async def retry_failed_text_indexer_documents(' in client
    assert '"/api/v1/text-indexers/retry-failed"' in client
    assert 'ui.label("Failure diagnostics")' in source
    assert '"Current failures by cause and format"' in source
    assert '"Unsupported formats currently encountered"' in source
    assert 'open_diagnostic_component' in source
    assert 'select_record_details(record_id)' in source
    assert 'focused_component_id=component_id' in source
    assert 'async def text_indexer_diagnostics(' in client
    assert '"/api/v1/text-indexers/diagnostics"' in client


def test_local_stack_uses_a_unique_default_worker_identity_per_invocation():
    source = LOCAL_STACK.read_text()
    assert '${TEXT_INDEXER_WORKER_ID:-local-stack-indexer-$$}' in source
    assert '${TEXT_INDEXER_PROCESS_COUNT:-2}' in source
    assert 'export TEXT_INDEXER_WORKER_ID="${STACK_INDEXER_WORKER_ID}"' in source
    assert 'export TEXT_INDEXER_PROCESS_COUNT="${STACK_INDEXER_PROCESS_COUNT}"' in source
    assert 'worker_prefix="${STACK_INDEXER_WORKER_ID}-${INDEXER_PID}-"' in source
    assert 'worker_id LIKE \'${sql_worker_prefix}%\'' in source
    assert '${CONTENT_INDEXING_MAINTENANCE_ENABLED:-true}' in source
    assert 'backend.services.api.text_indexing_maintenance cleanup --watch' in source
    assert 'INDEXING_MAINTENANCE_PID' in source
    assert 'maintenance worker stopped unexpectedly' in source


def test_builtin_roles_are_visible_read_only_and_link_to_text_indexers():
    source = APP.read_text()
    assert 'await api.list(spec.key, include_system=True)' in source
    assert 'ui.badge("Built-in · read-only"' in source
    assert '"Built-in roles are provisioned by the platform and cannot be edited, "' in source
    assert 'role.get("code") == "text-indexer-service"' in source
    assert '"Open Text Indexers", icon="manage_search"' in source
    assert 'if not (spec.key == "roles" and row.get("is_system")):' in source
    assert "not a role for a person" in source


def test_text_indexer_credentials_are_server_paginated_with_retention_guidance():
    source = APP.read_text()
    client = CLIENT.read_text()
    assert "api.text_indexer_credentials" in source
    assert '"All credentials"' in source
    assert '"Revoked or expired"' in source
    assert "Showing {start}–{end}" in source
    assert "scheduled API maintenance job" in source
    assert "async def text_indexer_credentials(" in client
