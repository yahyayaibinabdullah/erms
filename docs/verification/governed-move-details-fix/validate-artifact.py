"""Run the existing pure artifact validator without importing DB-backed API startup."""
import ast
import hashlib
import json
import re
from pathlib import Path
source = Path('backend/services/api/tests/test_localization_catalogue.py')
name = 'test_generated_arabic_artifact_is_complete_contextual_and_placeholder_safe'
function = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
scope = {'Path': Path, 'json': json, 're': re, '__file__': str(source.resolve())}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
scope[name]()
start = json.loads(Path('.runtime/governed-move-details-fix/start.json').read_text())
for path, digest in start['sha256'].items():
    if '/i18n/' in path:
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
print('Existing pure artifact validator passed: exact ordered coverage, nonblank, placeholders, provenance; catalogue hashes unchanged.')
