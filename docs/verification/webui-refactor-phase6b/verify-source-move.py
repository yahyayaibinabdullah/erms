from pathlib import Path
import ast,json,hashlib
root=Path('.runtime/webui-refactor-phase6b');out=Path('docs/verification/webui-refactor-phase6b')
before=ast.parse((root/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text());feature=ast.parse(Path('frontend/webui/audit_workspace.py').read_text())
def direct(tree):
 index=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='index')
 return {n.name:n for n in index.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
b,a=direct(before),direct(after);m={n.name:n for n in ast.walk(feature) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
dump=lambda n:ast.dump(n,include_attributes=False)
moved=['event_value','event_reference_value','event_entity_identity','hydrate_historical_audit_identities','event_actor_identity','can_open_event_entity','navigate_to_event_entity','show_event_detail','render_event_timeline','show_entity_history','select_audit_trail']
assert set(b)-set(a)==set(moved)
unchanged=[k for k in b if k not in moved]
assert all(dump(b[k])==dump(a[k]) for k in unchanged)
exact=['event_value','event_reference_value','event_entity_identity','hydrate_historical_audit_identities','event_actor_identity','render_event_timeline','show_entity_history']
assert all(dump(b[k])==dump(m[k]) for k in exact)
# Verify the only edits inside moved bodies are explicit dependency substitutions.
class Adapt(ast.NodeTransformer):
 def visit_Call(self,node):
  self.generic_visit(node)
  if dump(node)==dump(ast.parse('auth_state.get("principal")',mode='eval').body):return ast.parse('principal()',mode='eval').body
  if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='application_settings_controller':
   node.func=ast.Name(id={'can_open':'can_open_settings','open_from_event':'open_settings'}[node.func.attr],ctx=ast.Load())
  return node
for name in ['can_open_event_entity','show_event_detail']:
 assert dump(Adapt().visit(b[name]))==dump(m[name]),name
oldnav=b['navigate_to_event_entity'];dispatch_index=next(i for i,n in enumerate(oldnav.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='entity_type' for t in n.targets))
assert dump(ast.Module(body=oldnav.body[dispatch_index+1:],type_ignores=[]))==dump(ast.Module(body=a['open_audit_entity'].body,type_ignores=[]))
oldnav.body=oldnav.body[:dispatch_index]+ast.parse('await open_destination(event["entity_type"], entity)').body
assert dump(Adapt().visit(oldnav))==dump(m['navigate_to_event_entity'])
oldpage=b['select_audit_trail'];newpage=m['select_audit_trail'];shellstart=next(i for i,n in enumerate(oldpage.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='register_navigation');shellend=next(i for i,n in enumerate(oldpage.body) if isinstance(n,ast.With))
assert dump(ast.Module(body=oldpage.body[shellstart:shellend],type_ignores=[]))==dump(ast.Module(body=a['enter_audit_trail'].body,type_ignores=[]))
newwith=next(i for i,n in enumerate(newpage.body) if isinstance(n,ast.With))
assert dump(ast.Module(body=oldpage.body[shellend:],type_ignores=[]))==dump(ast.Module(body=newpage.body[newwith:],type_ignores=[]))
baseline=json.loads((root/'before-chrome-6/source-environment.json').read_text())['sha256']
changed=[p for p,h in baseline.items() if p.startswith('frontend/webui/') and hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
assert changed==['frontend/webui/app.py'],changed
result={'unchanged_other_direct_host_functions':len(unchanged),'unchanged_helpers_and_renderers':exact,'dependency_substitutions_verified':['principal','Settings permission and opener','destination dispatch'],'shell_entry_and_destination_dispatch_AST_identical':True,'audit_filter_and_paging_body_AST_identical':True,'private_state_change':'audit page revision moves from shared host dictionary to per-client factory closure; selected resource remains a host callback','changed_existing_runtime_files':changed,'new_runtime_file':'frontend/webui/audit_workspace.py','other_baseline_runtime_files_byte_identical':True}
(out/'source-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
