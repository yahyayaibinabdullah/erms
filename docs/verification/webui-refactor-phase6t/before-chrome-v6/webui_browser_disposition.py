"""Existing disposition pages, bounded selectors, focus and filter persistence."""
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_disposition(page):
    def text(key):return page.t('disposition.ui.'+key)
    def workspace():return page.one('.detail-surface.messaging-workspace')
    def enter(key):
        old=workspace().get_attribute('id') if page.visible('.detail-surface.messaging-workspace') else None
        page.activate(page.one('button.erms-nav-link',text({'disposition-jobs':'jobs','disposition-eligibility':'eligibility','disposition-tasks':'my_tasks'}[key])))
        page.wait.until(lambda _:workspace().get_attribute('id')!=old)
        page.wait.until(lambda _:not page.visible('.q-inner-loading'))
    def capture(key):page.capture('disposition-'+key+'-'+page.language)
    def expand(value=True):
        control=page.one('.q-expansion-item > .q-expansion-item__container > .q-item',scope=workspace())
        if (control.get_attribute('aria-expanded')=='true')!=value:page.activate(control)
        page.wait.until(lambda _:(control.get_attribute('aria-expanded')=='true')==value)
        page.wait.until(lambda _:page.driver.execute_script('return arguments[0].getAnimations({subtree:true}).every(a=>a.playState!=="running")',workspace()))
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('disposition jobs filters, bounded create selectors and keyboard focus'):
            enter('disposition-jobs');page.see(text('empty'));url=page.driver.current_url;history=page.driver.execute_script('return history.length');capture('jobs')
            expand();query=page.field(text('search'));query.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            page.report.setdefault('focus',[]).append({'language':language,'tag':active.tag_name,'role':active.get_attribute('role'),'label':plain(active.get_attribute('aria-label') or '')})
            capture('filters');expand(False);page.click(text('create'),workspace());dialog=page.one('[role=dialog]');page.field(text('owner'));page.wait.until(lambda _:text('loading') not in plain(dialog.text));capture('create')
            page.click(text('cancel'),dialog);page.wait.until(lambda _:not page.visible('[role=dialog]'))
            expand();page.settings();enter('disposition-jobs');assert page.field(text('search')).is_displayed()
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('disposition eligibility and task pages retain existing navigation and empty states'):
            enter('disposition-eligibility');page.see(text('empty'));capture('eligibility')
            enter('disposition-tasks');page.see(text('empty'));capture('tasks')
            page.activate(page.one('button.erms-nav-link',text('templates')));page.see(text('repository_default'));capture('templates')
            page.errors();page.settings()
