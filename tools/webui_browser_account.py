"""Account appearance/focus followed by the established session lifecycle journey."""
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


def check_account(page):
    def profile():
        if page.visible('.erms-profile-menu'):return page.one('.erms-profile-menu')
        page.activate(next(b for b in page.visible('header button') if 'account_circle' in b.text))
        return page.one('.erms-profile-menu')
    def capture(name):page.capture('account-'+name+'-'+page.language)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('account menu, preferences and keyboard cancellation'):
            menu=profile();capture('profile')
            page.click(page.t('preferences.heading.personal'),menu)
            d=page.one('.erms-preferences-dialog')
            page.activate(d.find_element('css selector','.text-xl'))
            ActionChains(page.driver).send_keys(Keys.TAB).perform()
            active=page.driver.switch_to.active_element
            assert page.driver.execute_script('return arguments[0].contains(arguments[1])',d,active)
            page.report.setdefault('account_focus',[]).append({'language':language,'dialog':'preferences','tag':active.tag_name,'type':active.get_attribute('type'),'label':active.get_attribute('aria-label')})
            page.activate(d.find_element('css selector','.text-xl'));capture('preferences')
            page.click(page.t('preferences.action.cancel'),d)
            page.wait.until(lambda _:not page.visible('.erms-preferences-dialog'))
        with page.check('ordinary password dialog, keyboard and cancellation'):
            menu=profile()
            page.activate(next(b for b in menu.find_elements('css selector','button') if any(i.text=='key' for i in b.find_elements('css selector','.q-icon'))))
            d=page.one('.q-dialog__inner > .q-card')
            first=page.field(page.t('webui.show_change_password.input.current_password_00f4f73a'))
            page.activate(first);first.send_keys(Keys.TAB)
            active=page.driver.switch_to.active_element
            assert page.driver.execute_script('return arguments[0].contains(arguments[1])',d,active)
            page.report.setdefault('account_focus',[]).append({'language':language,'dialog':'password','tag':active.tag_name,'type':active.get_attribute('type'),'label':active.get_attribute('aria-label')})
            page.activate(d.find_element('css selector','.text-xl'));capture('password')
            page.click(page.t('webui.show_change_password.button.cancel_6a686362'),d)
            page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
            page.errors()
    page.settings();page.language_change('en')
    # A menu-show callback refreshes the profile asynchronously. Wait for its
    # completion before sign-out so comparison counts are independent of whether
    # logout clears the principal before that callback gets its event-loop turn.
    def settled_sign_out():
        started=len(page.events())
        page.activate(next(b for b in page.visible('header button') if 'account_circle' in b.text))
        page.wait.until(lambda _:any(e['method']=='GET' and e['path']=='/api/v1/auth/me' and e['status']==200 for e in page.events()[started:]))
        page.click(page.t('webui.index.button.sign_out_a4610dd4'))
        page.one('button.wathiq-login-submit');page.current_identity=None
    page.sign_out=settled_sign_out
    from tools.webui_browser_session import check_sessions
    check_sessions(page)
