import ast
from pathlib import Path


APP_PATH = Path(__file__).parents[1] / "app.py"


def test_retired_classification_tables_are_not_restorable_destinations():
    """Both resources remain editable through the Classification workspace."""
    import asyncio
    from unittest.mock import AsyncMock
    import pytest
    from frontend.webui.api_client import ApiError
    from frontend.webui.entities import COLLECTION_ENTITIES, ENTITIES

    retired = {'classification-schemes', 'classifications'}
    for resource in retired:
        assert ENTITIES[resource].fields
        assert not ENTITIES[resource].columns
    assert set(COLLECTION_ENTITIES) == set(ENTITIES) - retired

    restore = next(node for node in ast.walk(ast.parse(APP_PATH.read_text()))
                   if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == 'restore_navigation_entry')
    select = AsyncMock()
    workspace = AsyncMock()
    namespace = dict(Any=object, COLLECTION_ENTITIES=COLLECTION_ENTITIES,
                     ApiError=ApiError, select_entity=select,
                     select_classification_workspace=workspace)
    exec(compile(ast.Module(body=[restore], type_ignores=[]), str(APP_PATH), 'exec'), namespace)
    for page in retired:
        with pytest.raises(ApiError) as error:
            asyncio.run(namespace['restore_navigation_entry']({'page': page, 'state': {}}))
        assert error.value.status_code == 404
    select.assert_not_awaited()
    workspace.assert_not_awaited()
    for entry, expected in [
        ({'page': 'classification-workspace'}, {}),
        ({'page': 'classification-scheme-details', 'entity_id': 7}, {'initial_scheme_id': 7}),
        ({'page': 'classification-details', 'entity_id': 8}, {'initial_classification_id': 8}),
    ]:
        asyncio.run(namespace['restore_navigation_entry'](entry))
        workspace.assert_awaited_with(**expected)


def test_security_administration_pages_can_be_restored_from_navigation_history():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    restore = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "restore_navigation_entry"
    )
    recognized_pages = {
        comparison.value
        for node in ast.walk(restore)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "page"
        for comparison in node.comparators
        if isinstance(comparison, ast.Constant) and isinstance(comparison.value, str)
    }
    assert {"governance-custody", "security-operations"} <= recognized_pages


def test_return_to_tree_does_not_replay_an_earlier_search():
    """Execute the real restoration callback without a database or UI server."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    restore = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == "restore_navigation_entry")
    for mode in ("browse", "search"):
        state = {}
        aggregation_state = {}
        select_entity = AsyncMock()
        load_rows = AsyncMock()
        namespace = {
            "Any": object, "state": state, "collection_state": state, "aggregation_state": aggregation_state,
            "COLLECTION_ENTITIES": {"aggregations": SimpleNamespace(search_first=True)},
            "ENTITIES": {"aggregations": SimpleNamespace(search_first=True)},
            "select_entity": select_entity, "load_rows": load_rows,
            "search_input": SimpleNamespace(value=""),
        }
        exec(compile(ast.Module(body=[restore], type_ignores=[]), str(APP_PATH), "exec"), namespace)
        entry = {"page": "aggregations", "state": {
            "aggregation_mode": mode, "searched": True, "search_text": "meeting",
        }}
        for _ in range(2):
            asyncio.run(namespace["restore_navigation_entry"](entry))
        assert select_entity.await_count == 2
        assert aggregation_state["aggregation_mode"] == mode
        assert load_rows.await_count == (0 if mode == "browse" else 2)


def test_job_and_task_navigation_restore_their_distinct_identities():
    import asyncio
    from unittest.mock import AsyncMock
    tree=ast.parse(APP_PATH.read_text())
    restore=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='restore_navigation_entry')
    select=AsyncMock();namespace={'Any':object,'select_disposition':select}
    exec(compile(ast.Module(body=[restore],type_ignores=[]),str(APP_PATH),'exec'),namespace)
    saved={'job_id':5,'task_id':8}
    asyncio.run(namespace['restore_navigation_entry']({'page':'disposition-task','entity_id':8,'state':{'disposition_view':saved}}))
    select.assert_awaited_with('disposition-task',5,saved,task_id=8)
    asyncio.run(namespace['restore_navigation_entry']({'page':'disposition-job','entity_id':5,'state':{}}))
    select.assert_awaited_with('disposition-job',5,{},task_id=None)
    from frontend.webui.navigation_data import append_navigation_entry
    trail=[]
    for page,identity in [('disposition-job',5),('disposition-task',8),('disposition-task',9)]:
        trail=append_navigation_entry(trail,{'page':page,'entity_id':identity})
    assert len(trail)==3
