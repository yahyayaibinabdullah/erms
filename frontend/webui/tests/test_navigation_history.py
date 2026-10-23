import ast
from pathlib import Path


APP_PATH = Path(__file__).parents[1] / "app.py"


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
        select_entity = AsyncMock()
        load_rows = AsyncMock()
        namespace = {
            "Any": object, "state": state,
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
        assert state["aggregation_mode"] == mode
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
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('navigation_entry_identity','append_navigation_entry')]
    namespace.update(NAVIGATION_TRAIL_LIMIT=20)
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(APP_PATH),'exec'),namespace)
    trail=[]
    for page,identity in [('disposition-job',5),('disposition-task',8),('disposition-task',9)]:
        trail=namespace['append_navigation_entry'](trail,{'page':page,'entity_id':identity})
    assert len(trail)==3
