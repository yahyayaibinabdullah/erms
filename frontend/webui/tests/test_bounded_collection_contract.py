from __future__ import annotations

from frontend.webui.tests.record_sources import record_sources
import ast
from pathlib import Path


APP_PATH = Path(__file__).parents[1] / "app.py"
TENANT_GROWN_RESOURCES = {
    "aggregations", "classifications", "digital-components", "org-units",
    "records", "roles", "users",
}


def test_tenant_grown_list_calls_always_declare_a_bound() -> None:
    """Prevent the old implicit-500 relationship/listing pattern returning."""
    tree = ast.parse((APP_PATH.read_text(encoding="utf-8") + record_sources()))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "list"
            and isinstance(function.value, ast.Name)
            and function.value.id == "api"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in TENANT_GROWN_RESOURCES
        ):
            continue
        keywords = {keyword.arg for keyword in node.keywords}
        if "limit" not in keywords:
            violations.append(f"line {node.lineno}: api.list({node.args[0].value!r})")
            continue
        limit_keyword = next(keyword for keyword in node.keywords if keyword.arg == "limit")
        if (
            isinstance(limit_keyword.value, ast.Constant)
            and isinstance(limit_keyword.value.value, int)
            and limit_keyword.value.value > 50
        ):
            violations.append(
                f"line {node.lineno}: api.list({node.args[0].value!r}) "
                f"uses limit={limit_keyword.value.value}"
            )
    assert not violations, "Unbounded tenant-grown collection reads:\n" + "\n".join(violations)


def test_webui_does_not_use_legacy_digital_component_array() -> None:
    source = (APP_PATH.read_text(encoding="utf-8") + record_sources())
    client_source = (APP_PATH.parent / "api_client.py").read_text(encoding="utf-8")
    assert "api.components(" not in source
    assert '"GET", "/api/v1/digital-components"' not in client_source
    assert "async def component_page(" in client_source
