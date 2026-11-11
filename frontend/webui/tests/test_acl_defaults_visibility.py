"""Default ACL actions require both the endpoint privilege and resource capability."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize('manage_acl,admin,expected', [
    (False, False, False), (True, False, False),
    (False, True, False), (True, True, True),
])
def test_acl_defaults_visibility_matches_endpoint_gates(manage_acl, admin, expected):
    source = ast.parse((Path(__file__).parents[1] / 'aggregation_details.py').read_text())
    assignment = next(n for n in ast.walk(source) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'show_acl_defaults'
                              for t in n.targets))
    result = eval(compile(ast.Expression(assignment.value), 'app.py', 'eval'), {
        'capabilities': {'manage_acl': manage_acl},
        'auth_state': {'principal': {'global_privileges': ['authorization.administer'] if admin else []}},
        'principal': lambda: {'global_privileges': ['authorization.administer'] if admin else []},
    })
    assert result is expected


@pytest.mark.parametrize('page', ['select_record_details', 'open_aggregation'])
@pytest.mark.parametrize('manage_acl,admin,expected', [
    (False, False, False), (True, False, False),
    (False, True, False), (True, True, True),
])
def test_access_button_uses_resource_capability_without_admin_gate(page, manage_acl, admin, expected):
    source = ast.parse((Path(__file__).parents[1] / ('aggregation_details.py' if page == 'open_aggregation' else 'record_details.py')).read_text())
    function = next(n for n in ast.walk(source) if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == page)
    condition = next(n.test for n in ast.walk(function) if isinstance(n, ast.If)
                     and ast.unparse(n.test) == "capabilities.get('manage_acl')")
    result = eval(compile(ast.Expression(condition), 'app.py', 'eval'), {
        'capabilities': {'manage_acl': manage_acl},
        'auth_state': {'principal': {'global_privileges': ['authorization.administer'] if admin else []}},
        'principal': lambda: {'global_privileges': ['authorization.administer'] if admin else []},
    })
    assert bool(result) is manage_acl
