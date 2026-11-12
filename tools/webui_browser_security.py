"""Security administration/access dialog parity on disposable browser sessions."""
import time
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_security(page):
    def capture(name):page.capture('security-'+name+'-'+page.language)
    def dialog():return page.one('.q-dialog__inner > .q-card')
    def close(key):
        page.click(page.t(key),dialog())
        page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def focus(name):
        d=dialog();controls=[e for e in d.find_elements('css selector','input:not([type=checkbox]),textarea') if e.is_displayed() and e.is_enabled()]
        page.activate(controls[0]);time.sleep(.5);controls[0].send_keys(Keys.TAB);time.sleep(.3)
        target=page.driver.switch_to.active_element
        assert page.driver.execute_script('return arguments[0].contains(arguments[1])',d,target)
        page.report.setdefault('security_focus',[]).append(dict(language=page.language,scene=name,tag=target.tag_name,type=target.get_attribute('type'),label=target.get_attribute('aria-label')))
        headings=d.find_elements('css selector','.text-xl,.text-lg')
        if headings:page.activate(headings[0])
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('profile privilege editor, search and keyboard cancellation'):
            page.drawer('profiles');page.wait.until(lambda _:page.visible('.governance-list-card'))
            cards=page.visible('.governance-list-card')
            card=next(c for c in cards if 'ALL_PRIVS' in c.text)
            page.activate(next(b for b in card.find_elements('css selector','button') if b.text.strip()=='key'))
            dialog();focus('profile-privileges');capture('profile-privileges')
            field=page.field(page.t('webui.show_profile_privilege_editor.input.find_privileges_1fa8656a'))
            field.send_keys('record.view');time.sleep(.3);capture('profile-filter')
            close('webui.show_profile_privilege_editor.button.cancel_d03380ff')
            page.errors()
        with page.check('record access, explanation and security-level dialogs'):
            page.drawer('records')
            page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),'TEST-REC')
            page.click(page.t('webui.index.button.search_4d02b714'),page.one('.erms-card'))
            page.one('button[aria-label="Open record"]',scope=page.one('.compact-result-item')).click()
            page.see(page.t('webui.select_record_details.button.why_this_access_a28abcce'))
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            for scene,entry,cancel in [
                ('record-acl','webui.select_record_details.button.access_489ef75d','webui.show_acl_editor.button.cancel_256f9c91'),
                ('record-explanation','webui.select_record_details.button.why_this_access_a28abcce','webui.show_access_explanation.accessible_name.close_access_explanation_347ccd8f'),
                ('record-level','webui.select_record_details.button.security_level_2f483a84','webui.show_security_level_change.button.cancel_d37961e9'),
            ]:
                page.click(page.t(entry));dialog()
                if scene.endswith('explanation'):page.see(page.t('webui.load_explanation.label.decision_gates_1847ec0e'))
                focus(scene);capture(scene);close(cancel)
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('aggregation resource/default ACLs and inherited access'):
            page.one('button.detail-linked-entity').click()
            page.see(page.t('webui.open_aggregation.label.aggregation_overview_bb8398e3'))
            for scene,entry,cancel in [
                ('aggregation-acl','webui.open_aggregation.button.access_2361cbee','webui.show_acl_editor.button.cancel_256f9c91'),
                ('aggregation-explanation','webui.open_aggregation.button.why_this_access_bb85ae4d','webui.show_access_explanation.accessible_name.close_access_explanation_347ccd8f'),
                ('aggregation-level','webui.open_aggregation.button.security_level_5d0b4408','webui.show_security_level_change.button.cancel_d37961e9'),
            ]:
                page.click(page.t(entry));dialog()
                if scene.endswith('explanation'):page.see(page.t('webui.load_explanation.label.decision_gates_1847ec0e'))
                capture(scene);close(cancel)
            page.activate(page.one('.q-expansion-item .q-item__label',page.t('webui.open_aggregation.expansion.advanced_2d1fcc81')))
            for scene,entry in [('child-defaults','webui.open_aggregation.button.child_defaults_8ac3012b'),('record-defaults','webui.open_aggregation.button.record_defaults_3e8c0414')]:
                page.click(page.t(entry));dialog();capture(scene);close('webui.show_acl_editor.button.cancel_256f9c91')
            page.reload();page.see(page.t('webui.open_aggregation.label.aggregation_overview_bb8398e3'))
        with page.check('security dialog browser errors and no cancelled writes'):
            page.errors()
    writes=[e for e in page.events() if e['method'] in {'PUT','PATCH','POST','DELETE'} and (('/acl' in e['path'] or '/permissions' in e['path']) or '/privileges' in e['path'] or 'security-level-change' in e['path'])]
    assert not writes,writes
