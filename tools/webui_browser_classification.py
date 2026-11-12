"""Classification feature parity on disposable Chrome/Edge sessions."""
import time
from urllib.parse import parse_qs
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_classification(page):
    def t(key):return page.t(key)
    def capture(name):page.capture('classification-'+name+'-'+page.language)
    def tree():page.see(t('webui.render_workspace_right.label.classification_tree_69593539'))
    def enter():page.drawer('classification_schemes');tree()
    def back():page.click(t('classification_browser.back_to_tree'));tree()
    def close():
        page.click(t('webui.open_editor.button.cancel_c07bff03'),page.one('.q-dialog__inner > .q-card'))
        page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def row(label):
        return page.one('button.classification-node-button', label).find_element('xpath', '../..')
    def icon(label,name):
        target=row(label)
        page.activate(next(b for b in target.find_elements('css selector','button') if b.text.strip()==name))
    def filter_scheme(value):
        field=page.field(t('webui.select_classification_workspace.input.filter_schemes_a7f4591e'))
        field.click();field.send_keys(Keys.COMMAND,'a',Keys.NULL);field.send_keys(value,Keys.ENTER)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        scheme_code='WORKSPACE-'+language.upper()
        scheme_title='Workspace verification scheme '+language
        response=page.api.post('/api/v1/classification-schemes',json={
            'code':scheme_code,'title':scheme_title,
        })
        response.raise_for_status();audit_scheme=response.json()
        with page.check('classification entry, retained preferences, URL and bounded hierarchy'):
            enter();url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            filter_scheme('T01');page.see('Test scheme 1')
            page.wait.until(lambda _:len(page.visible('button.classification-node-button'))==1)
            page.activate(page.one('.classification-workspace .text-lg'))
            capture('filtered-tree')
            icon('Test scheme 1','chevron_left' if language=='ar' else 'chevron_right')
            page.see('Test branch 01')
            icon('Test branch 01','chevron_left' if language=='ar' else 'chevron_right')
            page.see('Test child 01')
            # Child and root pages each have their own Load more action.
            page.activate(next(b for b in page.visible('button') if plain(b.text).casefold()==t('webui.render_collection.button.load_more_755f4879').casefold()))
            page.see('Test child 26');capture('paged-branch')
            page.settings();enter();page.see('Test child 26')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('inherited retention, details, reload and keyboard editor'):
            page.click('C26 — Test child 26')
            page.one('.classification-actions-panel')
            capture('inherited-detail')
            page.reload();page.one('.classification-actions-panel');page.see('Test child 26')
            page.click(t('webui.render_workspace_right.button.edit_a536c992'))
            dialog=page.one('.q-dialog__inner > .q-card')
            inputs=[e for e in dialog.find_elements('css selector','input,textarea') if e.is_enabled()]
            inputs[0].click();time.sleep(.6);inputs[0].send_keys(Keys.TAB);time.sleep(.3)
            focus=page.driver.switch_to.active_element
            assert page.driver.execute_script('return arguments[0].contains(arguments[1])',dialog,focus)
            page.report.setdefault('classification_focus',[]).append({'language':language,'tag':focus.tag_name,'type':focus.get_attribute('type'),'label':focus.get_attribute('aria-label')})
            page.activate(dialog.find_element('css selector','.text-xl'));capture('classification-editor');close()
            page.click(t('webui.render_workspace_right.button.event_history_6802c7be'))
            page.one('.q-dialog__inner > .q-card')
            page.close_dialog()
        with page.check('scheme editing, transfer entry, empty state and restoration'):
            # Return to tree through the feature's existing back command.
            page.click(t('classification_browser.back_to_tree'));tree()
            page.click('T01 — Test scheme 1');page.one('.classification-actions-panel')
            capture('scheme-detail')
            page.click(t('webui.render_workspace_right.button.edit_scheme_4406dbed'))
            dialog=page.one('.q-dialog__inner > .q-card');capture('scheme-editor');close()
            page.click(t('classification_transfer.export'))
            page.activate(page.one('.q-menu .q-item','MS Word'))
            page.see(t('classification_transfer.word_title'));capture('word-dialog')
            page.click(t('classification_transfer.cancel'),page.one('.q-dialog__inner > .q-card'))
            page.click(t('classification_browser.back_to_tree'));tree()
            page.click(t('classification_transfer.import'));page.one('.classification-transfer-dialog');capture('import-dialog')
            page.click(t('classification_transfer.cancel'),page.one('.classification-transfer-dialog'))
            filter_scheme('zz_missing_phase6d');page.see(t('webui.render_scheme_list.label.no_matching_schemes_2a601365'))
            page.activate(page.one('.classification-workspace .text-lg'));capture('empty')
            filter_scheme('T01');page.see('Test scheme 1')
        with page.check('dedicated scheme publish and lifecycle refresh, reload and return'):
            filter_scheme(scheme_code);page.see(scheme_title)
            page.click(scheme_code+' — '+scheme_title);page.one('.classification-actions-panel')
            def read_scheme():
                result=page.api.get(f'/api/v1/classification-schemes/{audit_scheme["id"]}')
                result.raise_for_status();return result.json()
            if read_scheme().get('date_published') is None:
                page.click(t('webui.render_workspace_right.button.publish_2e621852'))
                page.see(t('webui.render_workspace_right.button.unpublish_57f099a0'))
            assert read_scheme().get('date_published')
            capture('published')
            for deactivated in (True,False):
                key=('webui.render_workspace_right.button.deactivate_ee74ba2e' if deactivated
                     else 'webui.render_workspace_right.button.reactivate_b2117181')
                page.click(t(key));dialog=page.one('.q-dialog__inner > .q-card')
                reason=dialog.find_element('css selector','textarea')
                page.activate(reason);reason.send_keys('Verify dedicated workspace refresh')
                # The last button is the existing localized confirmation action.
                page.activate(dialog.find_elements('css selector','button')[-1])
                page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
                opposite=('webui.render_workspace_right.button.reactivate_b2117181' if deactivated
                          else 'webui.render_workspace_right.button.deactivate_ee74ba2e')
                page.see(t(opposite));assert bool(read_scheme().get('date_deactivated'))==deactivated
                capture('deactivated' if deactivated else 'reactivated')
            page.reload();page.one('.classification-actions-panel')
            page.see(t('webui.render_workspace_right.button.deactivate_ee74ba2e'))
            back();filter_scheme('T01');page.see('Test scheme 1')
        with page.check('classification errors and bounded requests'):
            assert not page.errors(),page.errors()
            requests=[e for e in page.events() if e['method']=='GET' and e['path']=='/api/v1/classifications']
            assert requests and all(0<int(parse_qs(e['query'])['limit'][0])<=26 for e in requests)
