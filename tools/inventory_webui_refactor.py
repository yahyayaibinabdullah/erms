"""Read-only source inventory for the WebUI refactor baseline; imports no app code.

Run from the repository root. Output is evidence, not proof of runtime coverage.
Dynamic callbacks and dictionaries still require manual review.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import symtable

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "frontend/webui"
OUTPUT = ROOT / "docs/verification/webui-refactor-phase1"


def text(node):
    return ast.unparse(node)


def main():
    modules, dialogs, navigation, state_accesses, test_files = [], [], [], [], []
    runtime_files = sorted(
        p for p in WEBUI.rglob("*.py")
        if not set(p.relative_to(WEBUI).parts) & {
            ".venv", "__pycache__", "tests", "interaction_tests", "scripts", "deploy"
        }
    )
    for path in runtime_files:
        source = path.read_text()
        tree = ast.parse(source)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        relative = str(path.relative_to(ROOT))

        def owner(node):
            names = []
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(node.name)
            return ".".join(reversed(names)) or "<module>"

        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append({"name": node.name, "owner": owner(node), "line": node.lineno,
                                  "end_line": node.end_lineno, "async": isinstance(node, ast.AsyncFunctionDef)})
            if isinstance(node, ast.Call):
                called = text(node.func)
                if called in {"ui.dialog", "ui.page"}:
                    item = {"file": relative, "line": node.lineno, "owner": owner(node), "call": text(node)}
                    (dialogs if called == "ui.dialog" else navigation).append(item)
                if called in {"register_navigation", "guarded_page_navigation", "breadcrumb_back"}:
                    navigation.append({"file": relative, "line": node.lineno, "owner": owner(node), "call": text(node)})
            if isinstance(node, ast.Subscript) and text(node.value) in {
                "state", "auth_state", "navigation_state", "message_live", "app.storage.user"
            }:
                state_accesses.append({"file": relative, "line": node.lineno, "owner": owner(node),
                                       "container": text(node.value), "key": text(node.slice),
                                       "operation": type(node.ctx).__name__})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                container = text(node.func.value)
                if container in {"state", "auth_state", "navigation_state", "message_live", "app.storage.user"}:
                    state_accesses.append({"file": relative, "line": node.lineno, "owner": owner(node),
                                           "container": container, "key": text(node.args[0]) if node.args else None,
                                           "operation": node.func.attr, "call": text(node)})
        modules.append({"file": relative, "lines": len(source.splitlines()),
                        "sha256": hashlib.sha256(source.encode()).hexdigest(),
                        "imports": [text(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))],
                        "functions": sorted(functions, key=lambda n: n["line"])})
    app_source = (WEBUI / "app.py").read_text()
    index = next(t for t in symtable.symtable(app_source, "app.py", "exec").get_children() if t.get_name() == "index")
    closures = [{"name": t.get_name(), "line": t.get_lineno(), "free_variables": sorted(t.get_frees())}
                for t in index.get_children() if t.get_type() == "function"]
    for folder in (WEBUI / "tests", WEBUI / "interaction/tests"):
        for path in sorted(folder.glob("test_*.py")):
            source = path.read_text()
            tree = ast.parse(source)
            test_files.append({"file": str(path.relative_to(ROOT)),
                               "tests": [{"name": n.name, "line": n.lineno} for n in ast.walk(tree)
                                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")],
                               "source_inspection": any(s in source for s in ("ast.parse", "inspect.getsource", ".read_text(")),
                               "nicegui_simulator": "nicegui.testing" in source,
                               "app_reference": "app.py" in source or "frontend.webui.app" in source})
    result = {"baseline_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "limitations": "Static inventory: callsites are not unique dialog variants; source-reading flags can include catalogues. No runtime coverage inferred.",
              "modules": modules, "dialog_callsites": dialogs, "navigation_callsites": navigation,
              "shared_state_accesses": state_accesses, "index_closures": closures, "test_files": test_files}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "source-inventory.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# WebUI source inventory", "", "Generated by `tools/inventory_webui_refactor.py`; application code is not imported.", "",
             "Static callsites are an inventory, not runtime verification. Dialog variants and dynamic callbacks require the companion baseline review.", "",
             "## Runtime modules", "", "| Module | Lines | Functions |", "| --- | ---: | ---: |"]
    for m in modules:
        lines.append(f"| `{m['file']}` | {m['lines']} | {len(m['functions'])} |")
    lines += ["", "## Function scopes enclosed by index", "", "Includes named functions, lambdas, and comprehensions. These free variables show direct closure coupling, including callbacks captured by deeper nested functions.", "",
              "| Function | Line | Captured names |", "| --- | ---: | --- |"]
    for c in closures:
        lines.append(f"| `{c['name']}` | {c['line']} | {', '.join('`'+n+'`' for n in c['free_variables']) or 'None'} |")
    lines += ["", "## Dialog construction sites", "", "| Module | Line | Enclosing function |", "| --- | ---: | --- |"]
    for d in dialogs:
        lines.append(f"| `{d['file']}` | {d['line']} | `{d['owner']}` |")
    (OUTPUT / "source-inventory.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"runtime_modules": len(modules), "dialog_callsites": len(dialogs),
                      "navigation_callsites": len(navigation), "index_closures": len(closures),
                      "shared_state_accesses": len(state_accesses), "test_files": len(test_files)}))


if __name__ == "__main__":
    main()
