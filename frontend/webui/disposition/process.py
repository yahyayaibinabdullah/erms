"""The approved destruction flow, rendered by NiceGUI's native Mermaid element."""
from html import escape
from nicegui import ui
from .messages import text


def process_source(job):
    names={'START':'start','CREATE':'job_created','A':'manager_preparation' if job['review_route']=='records_manager_only' else 'officer_preparation',
        'V':'review_route_question','X':'fa_configured','B':'file_administrator_review','C':'unit_manager_review',
        'D':'marked_removals','E':'correction','T':'officer_correction','F':'records_manager_review','G':'marked_removals',
        'Q':'apply_proposals','R':'remove_blocked_units','H':'generate_request','I':'external_approval_pending','S':'authority_decision',
        'J':'record_approval','K':'physical_scope','L':'confirm_physical','U':'digital_scope','M':'digital_destruction',
        'N':'generate_certificate','O':'certificate_download','P':'completed','END':'end','MC':'manager_correction','EMPTY':'empty_after_execution'}
    decisions={'V','X','D','G','S','K','U'};lines=['flowchart TD']
    for node,key in names.items():
        label=escape(text(key),quote=True)
        if node in ('B','C') and job['review_route']!='standard' or node=='B' and job.get('file_administrator_skipped') or node=='F' and job['review_route']=='records_manager_only':label+=' · '+escape(text('skipped'))
        shape=('(["','"])') if node in ('START','END') else ('{"','"}') if node in decisions else ('["','"]')
        lines.append(node+shape[0]+label+shape[1])
    def edge(a,b,key=None,dotted=False):
        lines.append(a+(' -.->' if dotted else ' -->')+('|"'+escape(text(key),quote=True)+'"|' if key else '')+' '+b)
    edge('START','CREATE');edge('CREATE','A');edge('A','V','submit');edge('A','Q','records_manager_only')
    edge('V','X','standard');edge('V','F','simplified');edge('X','B','yes');edge('B','C');edge('C','D');edge('X','C','skipped')
    edge('D','E','yes');edge('E','T');edge('T','V');edge('D','F','no');edge('F','G');edge('G','E','yes');edge('G','Q','no')
    edge('Q','R');edge('R','H');edge('R','EMPTY',dotted=True);edge('EMPTY','T',dotted=True);edge('EMPTY','MC',dotted=True)
    edge('H','I');edge('I','S');edge('S','E','rejected');edge('S','MC','records_manager_only');edge('MC','Q','approve')
    edge('S','J','approved');edge('J','K');edge('K','L','yes');edge('L','U');edge('U','M','yes');edge('U','P','no');edge('K','M','no')
    edge('M','N');edge('N','P');edge('P','END');edge('P','O',dotted=True)
    lines+=['classDef boundary fill:#e3f2fd,stroke:#1565c0,stroke-width:3px;','class START,END boundary;']
    active={'officer_preparation':'A','manager_preparation':'A','officer_correction':'T','manager_correction':'MC',
        'file_administrator_review':'B','unit_manager_review':'C','records_manager_review':'F','external_approval_pending':'I',
        'physical_destruction':'L','digital_destruction':'M','certificate_generation':'N','completed':'P'}.get(job.get('workflow_stage'))
    if active:lines+=['classDef current stroke:#1565c0,stroke-width:4px;','class '+active+' current;']
    return '\n'.join(lines)


def process_diagram(job):
    source=process_source(job)
    with ui.expansion(text('workflow'),icon='account_tree').classes('w-full') as expansion:
        ui.label(text('review_route')+' · '+text(job['review_route'])).classes('font-semibold')
        host=ui.column().classes('w-full min-w-0');rendered=False
        def opened(event):
            nonlocal rendered
            if event.value and not rendered:
                rendered=True
                with host:ui.mermaid(source,config={'securityLevel':'strict','flowchart':{'htmlLabels':False}}).classes('w-full')
        expansion.on_value_change(opened)
