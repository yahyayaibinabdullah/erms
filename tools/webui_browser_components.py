"""Digital component upload and viewer parity using disposable synthetic files."""
import base64
import subprocess
from pathlib import Path
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from tools.check_webui_browser import plain


def fixture_pdf(text=b'Component preview fixture'):
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    stream=b'BT /F1 20 Tf 30 100 Td ('+text+b') Tj ET'
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
    check_component_cutoffs(page, aggregation)


def check_component_cutoffs(page, aggregation):
    number = 'COMP-PAGING'
    response = page.api.post('/api/v1/records', json={
        'aggregation_id': aggregation['id'], 'record_number': number,
        'title': 'Component paging fixture', 'medium': 'digital',
    })
    response.raise_for_status()
    record_id = response.json()['id']
    subprocess.run([page.args.api_python, '-c', '''
import sys, psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url()) as c:
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    c.execute("""
        INSERT INTO digital_components(record_id,component_order,file_name,mime_type,
                                       size_in_bytes,checksum_algo,checksum_value)
        SELECT %s,i,'Pending fixture '||i||'.pdf','application/pdf',0,'sha256','pending'
        FROM generate_series(1,51) i
    """, (int(sys.argv[1]),))
''', str(record_id)],
        check=True, timeout=30)
    query = 'uniquepreviewanchor'
    filename = 'Preview fixture 102.pdf'
    pdf = fixture_pdf()
    for order in range(52, 103):
        response = page.api.post(
            f'/api/v1/records/{record_id}/digital-components/upload',
            data={'component_order': str(order)},
            files={'file': (f'Preview fixture {order}.pdf',
                            fixture_pdf(query.encode()) if order == 102 else pdf, 'application/pdf')},
        )
        response.raise_for_status()
    anchor_id = response.json()['id']
    subprocess.run([page.args.api_python, '-c', '''
import sys, psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url()) as c:
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    component_id, phrase = int(sys.argv[1]), sys.argv[2]
    indexed = c.execute("""
        UPDATE digital_component_search_documents
        SET status='indexed',indexed_at=CURRENT_TIMESTAMP WHERE digital_component_id=%s
    """, (component_id,))
    assert indexed.rowcount == 1
    c.execute("""
        INSERT INTO digital_component_search_chunks(
            digital_component_id,chunk_no,extracted_text,search_vector,text_search_config)
        VALUES (%s,0,%s,to_tsvector('pg_catalog.english',%s),'pg_catalog.english')
    """, (component_id, phrase, phrase))
''', str(anchor_id), query], check=True, timeout=30)

    def compact(resource, identity):
        return page.one(f'#compact-result-{resource}-{identity}')

    def search_collection(resource, value):
        page.drawer(resource)
        if resource == 'aggregations' and page.visible('#aggregation-browser-tree'):
            page.click(page.t('webui.index.button.search_4d02b714'),
                       page.one('.erms-shared-control.items-center'))
        page.wait.until(lambda _:len(page.visible('.dashboard-personal-panel')) == 2)
        page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'), value)
        page.click(page.t('webui.index.button.search_4d02b714'),
                   page.one('.erms-shared-control.items-end'))

    def expand_files():
        row = compact('records', record_id)
        page.click(page.t('webui.render_compact_resource_result.accessible_name.show_digital_components_08467816'), row)
        return page.one('.compact-result-components', scope=row)

    def page_files():
        files = expand_files()
        page.wait.until(lambda _:len(page.visible('.compact-result-component', files)) == 25)
        assert 'Pending fixture 1.pdf' in files.text and 'Pending fixture 26.pdf' not in files.text
        page.click(page.t('webui.render_entity_compact_results.accessible_name.next_page_66adc3fc'), files)
        page.wait.until(lambda _:'Pending fixture 26.pdf' in files.text)
        assert 'Pending fixture 1.pdf' not in files.text and '26–50 / 102' in plain(files.text)
        page.click(page.t('webui.render_entity_compact_results.accessible_name.previous_page_2ba84275'), files)
        page.wait.until(lambda _:'Pending fixture 1.pdf' in files.text)

    def open_viewer(action, expected_file, position):
        started = len(page.events())
        action()
        dialog = page.one('.q-dialog__inner > .q-card')
        expect_file(dialog, expected_file, position)
        return dialog, started

    def expect_file(dialog, expected_file, position):
        page.one('.component-switcher-filename', expected_file, scope=dialog)
        page.one('canvas', scope=dialog)
        position_label = plain(page.one('.component-switcher-position', scope=dialog).text)
        assert position_label == plain(page.t(
            'webui.render_switcher.label.active_index_of_previewable_count_8114d6d6'
        ).format(active_index=position, previewable_count=51))

    def close_viewer(dialog):
        page.click(page.t('webui.select_component.accessible_name.close_viewer_7a596c99'), dialog)
        page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))

    def check_match():
        files = expand_files()
        page.wait.until(lambda _:filename in files.text)
        assert len(page.visible('.compact-result-component', files)) == 1
        page.one('.global-search-highlight', query, scope=files)
        dialog, started = open_viewer(
            lambda:page.click(page.t('webui.render_compact_resource_result.accessible_name.preview_digital_component_f8b12cac'), files),
            filename, 51,
        )
        assert any(e['path'] == f'/api/v1/digital-components/{anchor_id}/rendition' and e['status'] == 200
                   for e in page.events()[started:])
        close_viewer(dialog)

    def open_saved(name):
        from tools.webui_browser_advanced_search import saved_search_dialog
        page.click(page.t('webui.select_advanced_search.button.open_saved_search_8bef667f'))
        dialog = saved_search_dialog(page)
        card = page.wait.until(lambda _:next((item for item in page.visible('.q-card', dialog)
            if any(plain(label.text) == name for label in item.find_elements('css selector','.font-semibold'))),False))
        page.click(page.t('webui.load_saved_page.button.open_2606a7e0'), card)
        page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
        page.click(page.t('webui.select_advanced_search.button.search_97989f23'), page.one('.advanced-search-submit-row'))
        compact('records', record_id)

    searches = {
        'Component paging structured': {'field': 'record_number', 'operator': 'eq', 'value': number},
        'Component paging full text': {'full_text': {'query': query, 'sources': ['components']}},
    }
    for name, where in searches.items():
        request = {'where': where, 'limit': 25}
        if 'full_text' in where:
            request['include'] = ['full_text_matches']
        response = page.api.post('/api/v1/saved-searches', json={
            'name': name, 'audience_mode': 'private',
            'definition': {'schema_version': 1, 'resource_type': 'record', 'max_results': 1000,
                           'request': request},
        })
        response.raise_for_status()

    for language in ('en', 'ar'):
        if page.language != language:
            # A URL with ?q= restores Global Search on reload instead of Settings.
            page.driver.get(page.args.url + '/')
            page.one('.erms-breadcrumb-row [aria-current=page]')
            page.settings()
            page.language_change(language)
        with page.check('record search files page independently and the viewer passes unavailable files'):
            search_collection('records', number)
            page_files()
            row = compact('records', record_id)
            page.activate(page.one('button[aria-label="Open record"]', scope=row))
            page.one('.component-list')
            dialog, _ = open_viewer(
                lambda:page.click(page.t('webui.select_record_details.accessible_name.preview_digital_components_d68f8cab')),
                'Preview fixture 52.pdf', 1,
            )
            page.click(page.t('webui.render_entity_compact_results.accessible_name.next_page_66adc3fc'),
                       page.one('.component-switcher-bar', scope=dialog))
            expect_file(dialog, filename, 51)
            page.capture('components-viewer-last-page-' + language, target=dialog)
            page.click(page.t('webui.render_entity_compact_results.accessible_name.previous_page_2ba84275'),
                       page.one('.component-switcher-bar', scope=dialog))
            expect_file(dialog, 'Preview fixture 52.pdf', 1)
            close_viewer(dialog)
        with page.check('contained record files page beyond the first 25'):
            search_collection('aggregations', aggregation['aggregation_number'])
            row = compact('aggregations', aggregation['id'])
            page.activate(page.one('button[aria-label="Open aggregation"]', scope=row))
            page_files()
        with page.check('structured and full-text Advanced Search expose the correct files'):
            page.drawer('advanced_search')
            open_saved('Component paging structured')
            page_files()
            open_saved('Component paging full text')
            check_match()
        with page.check('Global Search previews a matching file beyond the first 25'):
            previous_result = compact('records', record_id)
            field = page.one('header input')
            page.activate(field)
            field.send_keys(Keys.COMMAND, 'a', Keys.NULL, query)
            page.wait.until(lambda _:field.get_attribute('value') == query)
            field.send_keys(Keys.ENTER)
            page.wait.until(EC.staleness_of(previous_result))
            page.wait.until(lambda _:page.driver.current_url.endswith('/?q=' + query))
            check_match()
        page.errors()
