"""Keep feature ownership independent of the application composition root."""
import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_runtime_features_do_not_import_application_entry_point():
    violations = []
    for path in [*ROOT.glob('*.py'), *ROOT.joinpath('disposition').glob('*.py')]:
        if path.name == 'app.py':
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                invalid = any(alias.name == 'frontend.webui.app' for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                invalid = node.module == 'frontend.webui.app' or (
                    node.module == 'app' and node.level > 0
                ) or (
                    (node.module == 'frontend.webui' or (node.module is None and node.level > 0))
                    and any(alias.name == 'app' for alias in node.names)
                )
            else:
                continue
            if invalid:
                violations.append(f'{path.relative_to(ROOT)}:{node.lineno}')
    assert not violations, violations


def test_feature_factories_do_not_receive_the_entire_shell_state():
    tree = ast.parse(ROOT.joinpath('app.py').read_text())
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        values = [*node.args, *(keyword.value for keyword in node.keywords)]
        if any(isinstance(value, ast.Name) and value.id == 'state' for value in values):
            violations.append(node.lineno)
    assert not violations, violations
