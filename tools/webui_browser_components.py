"""Digital component upload and viewer parity using disposable synthetic files."""
import base64
import subprocess
from pathlib import Path
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def fixture_pdf():
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    stream=b'BT /F1 20 Tf 30 100 Td (Component preview fixture) Tj ET'
    objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    data=b'%PDF-1.4\n';offsets=[]
    for i,obj in enumerate(objects,1):offsets.append(len(data));data+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start=len(data);data+=b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets:data+=f'{offset:010d} 00000 n \n'.encode()
    return data+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def check_components(page):
    fixture=Path(page.args.output)/'synthetic-files';fixture.mkdir(exist_ok=True)
    (fixture/'image.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1cAAAAASUVORK5CYII='))
    (fixture/'document.pdf').write_bytes(fixture_pdf())
    parent=page.api.post('/api/v1/aggregations/search',json={'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0}).json()['items'][0]
    response=page.api.post('/api/v1/aggregations',json={'aggregation_number':'COMP-AGG','title':'Component fixture','classification_id':parent['classification_id'],'medium':'digital'});response.raise_for_status();aggregation=response.json()
    def icon(name,scope=None):return page.wait.until(lambda _:next((b for b in page.visible('button',scope) if any(i.text==name for i in b.find_elements('css selector','.q-icon'))),False))
    def cards():return page.visible('.component-card')
    def capture(name):page.capture('components-'+name+'-'+page.language,target=page.one('.component-list') if name in {'empty','cards','reordered','removed','removed-last'} else None)
    def enter(number):
        page.drawer('records');page.wait.until(lambda _:len(page.visible('.dashboard-personal-panel'))==2)
        page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),number)
        page.click(page.t('webui.index.button.search_4d02b714'),page.one('.erms-card'))
        page.one('button[aria-label="Open record"]',scope=page.one('.compact-result-item')).click()
        page.one('.record-uploader')
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        number='COMP-'+language.upper()
        response=page.api.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'record_number':number,'title':'Component fixture record','medium':'digital'});response.raise_for_status();record=response.json()
        with page.check('native saved-file upload and repeated component entry'):
            enter(number);page.one('.component-grid .col-span-full');capture('empty')
            page.driver.find_element('css selector','.record-uploader input[type=file]').send_keys(str((fixture/'image.png').resolve())+'\n'+str((fixture/'document.pdf').resolve()))
            page.wait.until(lambda _:len(cards())==2)
            # Stabilize fixture dates only; application writes remain unmodified.
            subprocess.run([page.args.api_python,'-c','''
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 c.execute("UPDATE digital_components SET date_created='2026-01-01',date_originated='2026-01-01'")
'''],check=True,timeout=30)
            page.settings();enter(number);page.wait.until(lambda _:len(cards())==2);capture('cards')
        with page.check('image/PDF switching, viewer keyboard focus, zoom and cleanup'):
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            page.activate(icon('visibility',cards()[0]));d=page.one('.q-dialog__inner > .q-card')
            page.one('.q-img',scope=d);page.one('.component-viewer-toolbar',scope=d);capture('image')
            first=page.visible('.component-switcher-button',d)[0];first.send_keys(Keys.TAB)
            focus=page.driver.switch_to.active_element
            assert 'component-switcher-button' in focus.get_attribute('class')
            page.report.setdefault('focus',[]).append({'language':language,'from':'component 1','to':focus.text})
            page.activate(focus);page.wait.until(lambda _:page.driver.execute_script('return [...document.querySelectorAll("canvas")].some(c=>c.width>300 && c.height>0)'))
            capture('pdf');page.activate(icon('zoom_in',d));capture('pdf-zoom')
            page.activate(icon('close',d));page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('component ordering and removal refresh through the real API'):
            page.activate(icon('arrow_downward',cards()[0]));page.wait.until(lambda _:page.visible('.component-filename')[0].text=='document.pdf')
            capture('reordered');started=len(page.events());page.activate(icon('delete_outline',cards()[0]))
            page.wait.until(lambda _:len(cards())==1 and any(e['method']=='DELETE' and e['path'].startswith('/api/v1/digital-components/') and e['status']==204 for e in page.events()[started:]))
            assert page.visible('.component-filename')[0].text=='image.png'
            result=page.api.post('/api/v1/digital-components/search',json={'where':{'field':'record_id','operator':'eq','value':record['id']},'limit':25,'offset':0});result.raise_for_status()
            assert result.json()['total']==1
            page.see(page.t('webui.remove_component.notify.digital_component_removed_3af94a83'))
            # The optimistic redraw retains the old total; only the automatic API
            # refresh can update this pager to the authoritative remaining count.
            page.wait.until(lambda _:any(plain(e.text)=='1–1 / 1' for e in page.visible('.component-grid .q-badge')))
            deletion_events=page.events()[started:]
            assert len([e for e in deletion_events if e['method']=='DELETE'])==1
            capture('removed')
            started=len(page.events());page.activate(icon('delete_outline',cards()[0]))
            page.see(page.t('webui.remove_component.notify.digital_component_removed_3af94a83'))
            page.wait.until(lambda _:not cards() and any(e['method']=='DELETE' and e['status']==204 for e in page.events()[started:]))
            page.wait.until(lambda _:any(e['method']=='POST' and e['path']=='/api/v1/digital-components/search' and e['status']==200 for e in page.events()[started:]))
            page.see(page.t('webui.render_current_components.label.no_digital_components_have_been_uploaded_y_3f61a29a'))
            assert not page.visible('.component-grid button')
            assert len([e for e in page.events()[started:] if e['method']=='DELETE'])==1
            capture('removed-last')
            page.report.setdefault('deletion_refresh',[]).append({'language':language,
                'localized_success_notification':True,'remaining_count_refreshed':True,
                'last_component_refreshed':True,'one_delete_per_click':True})
            result=page.api.post('/api/v1/digital-components/search',json={'where':{'field':'record_id','operator':'eq','value':record['id']},'limit':25,'offset':0});result.raise_for_status()
            assert result.json()['total']==0
            page.settings();enter(number);page.wait.until(lambda _:not cards())
            page.see(page.t('webui.render_current_components.label.no_digital_components_have_been_uploaded_y_3f61a29a'))
            page.errors()
    assert 'RuntimeError: The parent element this slot belongs to has been deleted.' not in (Path(page.args.output)/'webui.log').read_text()
    assert not [e for e in page.events() if e['status'] is None or e['status']>=400]
