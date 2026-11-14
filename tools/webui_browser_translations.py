"""Translation administration and Inspector parity without changing catalogue artifacts."""
from selenium.webdriver.common.keys import Keys
from urllib.parse import parse_qs


def check_translations(page):
    key='navigation.item.translations'
    def enter():
        page.activate(page.one('button.erms-nav-link',page.t(key)))
        page.field(page.t('webui.select_translation_administration.input.key_16b82d81'))
    def dialog():return page.one('.q-dialog__inner > .q-card')
    def closed():page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def capture(name):page.capture('translations-'+name+'-'+page.language)
    def action(key):page.click(page.t(key))
    def profile():
        # Menu-show refreshes the principal and restores Inspector state. Observe
        # that existing restore before interacting with its toggle, so the test
        # does not race the profile callback and reset its own pinned target.
        restored=page.driver.execute_script("""
            const inspector=window.wathiqTranslationInspector;
            if (!inspector.__testRestoreCount) {
                const restore=inspector.restore;
                inspector.__testRestoreCount={value:0};
                inspector.restore=function(...args) {
                    const value=restore.apply(this,args);
                    this.__testRestoreCount.value++; return value;
                };
            }
            return inspector.__testRestoreCount.value;
        """)
        page.activate(next(b for b in page.visible('header button') if 'account_circle' in b.text))
        page.wait.until(lambda _:page.driver.execute_script('return window.wathiqTranslationInspector.__testRestoreCount.value')>restored)
        return page.one('.erms-profile-menu')
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('translation filters, repeated entry, root URL and history'):
            enter();history=page.driver.execute_script('return history.length');url=page.driver.current_url
            page.settings();enter()
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            field=page.field(page.t('webui.select_translation_administration.input.key_16b82d81'))
            page.activate(field);field.send_keys(key,Keys.TAB)
            page.wait.until(lambda _:any(e['path']=='/api/v1/admin/i18n/messages' and 'key=navigation.item.translations' in e['query'] for e in page.events()))
            page.wait.until(lambda _:any('edit'==i.text for b in page.visible('main button') for i in b.find_elements('css selector','.q-icon')))
            page.activate(page.one('main .text-lg.font-semibold',page.t('webui.select_translation_administration.label.supported_languages_0a3fd31a')))
            capture('filtered')
        with page.check('translation editor validation, keyboard focus and cancellation'):
            page.activate(next(b for b in page.visible('main button') if any(i.text=='edit' for i in b.find_elements('css selector','.q-icon'))))
            d=dialog();field=page.field(page.t('webui.edit_translation.textarea.translation_f0b41724'))
            page.activate(field);field.send_keys(Keys.TAB)
            active=page.driver.switch_to.active_element
            assert page.driver.execute_script('return arguments[0].contains(arguments[1])',d,active)
            page.report.setdefault('focus',[]).append({'language':language,'tag':active.tag_name,'role':active.get_attribute('role'),'label':active.get_attribute('aria-label')})
            assert not page.button(page.t('webui.edit_translation.accessible_name.save_translation_draft_99ac0e72'),d).is_enabled()
            page.activate(d.find_element('css selector','.font-mono'));capture('editor')
            action('webui.edit_translation.accessible_name.close_translation_editor_da93bee8');closed()
        with page.check('language and import dialogs retain cancellation and reason gates'):
            for open_key,cancel_key,name in [
                ('webui.select_translation_administration.accessible_name.add_supported_language_e7682117','webui.language_dialog.button.cancel_8d45c1e5','language'),
                ('localization.artifact.import.action','common.action.cancel','import'),
            ]:
                action(open_key);d=dialog();capture(name)
                
                if name=='language':page.click(page.t(cancel_key),d)
                else:page.activate(next(b for b in page.visible('button',d) if any(i.text=='close' for i in b.find_elements('css selector','.q-icon'))))
                closed()
        with page.check('export preview preserves complete artifact controls'):
            action('localization.artifact.export.action');d=dialog()
            page.wait.until(lambda _:any(e['path'].endswith('/export-preview') for e in page.events()))
            capture('export');page.activate(next(b for b in page.visible('button',d) if any(i.text=='close' for i in b.find_elements('css selector','.q-icon'))));closed()
        with page.check('Inspector toggle, inspect and guarded administration destination'):
            menu=profile();toggle=page.one('[role=switch]',scope=menu)
            page.activate(toggle)
            page.wait.until(lambda _:page.visible('#wathiq-translation-inspector'))
            page.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
            # Click the translated brand to pin it; the Inspector prevents its normal action.
            brand=page.one('header [data-i18n-key="webui.index.label.wathiq_d1dfb800"]')
            page.activate(brand);capture('inspector')
            page.report.setdefault('inspector_diagnostics',[]).append(page.driver.execute_script("return {bridge:document.getElementById('translation-inspector-bridge')?.outerHTML, keys:document.querySelector('#wathiq-translation-inspector [data-x=keys]')?.textContent, connected:window.socket?.connected}"))
            page.activate(page.one('#wathiq-translation-inspector [data-a=open]'))
            page.report['inspector_diagnostics'].append(page.driver.execute_script("return {bridge:document.getElementById('translation-inspector-bridge')?.outerHTML,connected:window.socket?.connected}"))
            page.wait.until(lambda _:page.field(page.t('webui.select_translation_administration.input.key_16b82d81')).get_attribute('value')=='webui.index.label.wathiq_d1dfb800')
            menu=profile();page.activate(page.one('[role=switch]',scope=menu))
            page.wait.until(lambda _:not page.visible('#wathiq-translation-inspector'))
            page.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
            page.errors()
    writes=[e for e in page.events() if e['method'] in {'POST','PATCH','PUT','DELETE'} and '/admin/i18n/' in e['path']]
    assert not writes,writes
    searches=[e for e in page.events() if e['path']=='/api/v1/admin/i18n/messages']
    assert searches and all(parse_qs(e['query']).get('limit')==['10'] for e in searches)
    page.report['translation_search_requests']=len(searches)
