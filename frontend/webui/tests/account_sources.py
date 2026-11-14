"""Source contracts follow the actual account owners after extraction."""
import ast
from pathlib import Path

FILES=tuple(Path(__file__).parents[1]/('account_'+name+'.py') for name in (
    'localization','preferences','profile','password','sign_in','bootstrap',
))


def account_sources():
    return '\n'.join(p.read_text() for p in FILES)


def account_function(name):
    for p in FILES:
        source=p.read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name:
                return ast.get_source_segment(source,node)
    raise AssertionError(name)
