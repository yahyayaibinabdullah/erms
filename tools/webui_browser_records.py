"""Record results, metadata and draft staging in real Chrome/Edge sessions."""
from uuid import uuid4
from tools.webui_browser_components import fixture_pdf
import base64
from pathlib import Path
from selenium.webdriver.common.keys import Keys


def check_records(page):
    parent=page.api.post('/api/v1/aggregations/search',json={'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0}).json()['items'][0]
    response=page.api.post('/api/v1/aggregations', headers={'Idempotency-Key': str(uuid4()), 'X-Event-Source': 'seeding'},json={'aggregation_number':'DRAFT-DEST','title':'Draft destination','classification_id':parent['classification_id'],'medium':'digital','date_opened':'2026-01-01T00:00:00Z'});response.raise_for_status()
    fixture=Path(page.args.output)/'staged.png';fixture.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1cAAAAASUVORK5CYII='))
    def click(key,scope=None):page.click(page.t(key),scope)
    def dialog():return page.one('.q-dialog__inner > .q-card')
    def closed():page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def capture(name):page.capture('records-'+name+'-'+page.language)
    def search(resource,number):
        page.drawer(resource);page.wait.until(lambda _:len(page.visible('.dashboard-personal-panel'))==2 and not page.visible('.dashboard-personal-panel .q-spinner'))
        page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),number)
        click('webui.index.button.search_4d02b714',page.one('.erms-shared-control.items-end'))
        page.one('.compact-result-item')
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('record results, detail metadata keyboard focus and parent return'):
            search('records','TEST-REC');capture('results')
            page.one('button[aria-label="Open record"]',scope=page.one('.compact-result-item')).click()
            edit='webui.select_record_details.button.edit_metadata_d7742b94'
            page.one('.resource-detail-header');capture('detail')
            details=page.button(page.t('resource_details.details'),page.one('.resource-detail-header'))
            page.activate(details)
            drawer=page.one('.q-dialog__inner > .q-card')
            page.button(page.t(edit),drawer)
            assert len(page.visible('[role="tab"]',drawer))==3
            page.activate(page.button(page.t(edit),drawer))
            page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==2)
            d=page.visible('.q-dialog__inner > .q-card')[-1]
            title=page.field(page.t('entity_metadata.field.title')+' *');page.activate(title);title.send_keys(Keys.TAB)
            assert page.driver.switch_to.active_element==page.field(page.t('entity_metadata.field.description'))
            page.report.setdefault('focus',[]).append({'language':language,'from':'record title','to':'description'})
            capture('editor')
            click('webui.open_editor.button.cancel_c07bff03',d)
            page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==1)
            page.activate(drawer.find_element('css selector','button'))
            closed()
            page.one('button.resource-detail-parent').click();page.see(page.t('webui.open_aggregation.label.child_aggregations_cd3bce3a'));capture('parent')
        with page.check('digital record draft validation, staged upload, preview and cancellation'):
            search('aggregations','DRAFT-DEST');page.one('button[aria-label="Open aggregation"]',scope=page.one('.compact-result-item')).click()
            click('webui.index.button.add_record_fc8125c4');d=dialog();page.one('.record-uploader',scope=d)
            page.activate(d.find_element('css selector','.text-xl'));capture('draft')
            started=len(page.events());click('webui.open_record_draft_editor.button.create_record_dd0193d6',d)
            page.wait.until(lambda _:page.visible('.q-notification'));assert not any(e['path'].endswith('/commit') for e in page.events()[started:])
            page.fill(page.t('entity_metadata.field.record_number')+' *','NATIVE-'+language)
            page.fill(page.t('entity_metadata.field.title')+' *','Staged record fixture')
            page.driver.find_element('css selector','.record-uploader input[type=file]').send_keys(str(fixture.resolve()))
            page.wait.until(lambda _:len(page.visible('.component-card',d))==1)
            page.activate(d.find_element('css selector','.text-xl'));capture('staged')
            card=page.one('.component-card',scope=d)
            preview=next(b for b in page.visible('button',card) if any(i.text=='visibility' for i in b.find_elements('css selector','.q-icon')))
            page.activate(preview);page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==2)
            viewer=page.visible('.q-dialog__inner > .q-card')[-1];page.one('.q-img',scope=viewer);capture('staged-preview')
            close=next(b for b in page.visible('button',viewer) if any(i.text=='close' for i in b.find_elements('css selector','.q-icon')))
            page.activate(close);page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==1)
            # Exercise a native PDF and a converted, text-backed rendition.
            document = fixture.with_suffix('.txt' if language == 'ar' else '.pdf')
            if language == 'ar':
                document.write_text('معاينة المستند', encoding='utf-8')
            else:
                document.write_bytes(fixture_pdf(second_page=True))
            d.find_element('css selector', '.record-uploader input[type=file]').send_keys(str(document.resolve()))
            page.wait.until(lambda _:len(page.visible('.component-card', d)) == 2)
            card = next(card for card in page.visible('.component-card', d) if document.name in card.text)
            button = page.button(page.t('webui.render_compact_resource_result.tooltip.preview_digital_component_71925875'), card)
            page.activate(button)
            page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card')) == 2)
            viewer = page.visible('.q-dialog__inner > .q-card')[-1]
            frame = page.one('iframe', scope=viewer)
            page.driver.switch_to.frame(frame)
            try:
                page.wait.until(lambda _:page.visible('.page[data-page-number="1"] .textLayer span[role="presentation"]'))
                assert page.driver.execute_script('return document.documentElement.dir') == ('rtl' if language == 'ar' else 'ltr')
                assert not page.visible('#editorModeButtons, #printButton, #downloadButton')
                assert page.driver.execute_script('return PDFViewerApplication.pdfViewer.annotationEditorMode') == -1
                first_url = page.driver.execute_script('return PDFViewerApplication.url')
            finally:
                page.driver.switch_to.default_content()
            if language == 'ar':
                page.activate(page.visible('.component-switcher-button', viewer)[0])
                page.one('.q-img', scope=viewer)
                page.activate(page.visible('.component-switcher-button', viewer)[1])
                page.wait.until(lambda _: page.driver.execute_script("""
                    const app = document.querySelector('.q-dialog iframe')?.contentWindow?.PDFViewerApplication;
                    return app?.url === arguments[0] && app?.pdfViewer?.getPageView(0)?.renderingState === 3;
                """, first_url))
            toolbar = page.one('.component-viewer-toolbar', scope=viewer)
            assert len(page.visible('button', toolbar)) == 1
            page.activate(page.one('button', scope=toolbar))
            page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card')) == 1)
            started=len(page.events());click('webui.open_record_draft_editor.button.cancel_draft_84ea17b5',d);closed()
            assert any(e['method']=='DELETE' and '/record-drafts/' in e['path'] and e['status']==204 for e in page.events()[started:])
            page.errors()
