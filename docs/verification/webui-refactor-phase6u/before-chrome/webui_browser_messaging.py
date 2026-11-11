"""Native mailbox compose/draft controls, focus and administration destinations."""
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_messaging(page):
    def text(key):return page.t('messaging.'+key)
    def nav(key):page.activate(page.one('button.erms-nav-link',text(key)))
    def capture(key):page.capture('messaging-'+key+'-'+page.language)
    def rows(subject):return [e for e in page.visible('[role=button].cursor-pointer') if subject in plain(e.text)]
    def drafts(deleted=False):
        r=page.api.get('/api/v1/messages/drafts',params={'deleted':deleted});r.raise_for_status();return r.json()['items']
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        subject='Browser draft '+language
        with page.check('mailbox compose, native focus, draft save and existing URL/history'):
            nav('navigation.inbox');page.see(text('state.empty'));url=page.driver.current_url;history=page.driver.execute_script('return history.length');capture('inbox')
            page.click(text('action.compose'));dialog=page.one('[role=dialog]');field=page.field(text('field.subject'));capture('compose')
            page.activate(field);field.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            page.report.setdefault('focus',[]).append({'language':language,'tag':active.tag_name,'role':active.get_attribute('role'),'label':plain(active.get_attribute('aria-label') or '')})
            page.fill(text('field.subject'),subject);editor=page.one('[contenteditable=true]',scope=dialog);page.activate(editor);editor.send_keys('Preserved draft content');capture('draft-content')
            page.click(text('action.save_draft'),dialog);page.see(text('state.saved'));draft=next(x for x in drafts() if x['subject']==subject)
            page.click(text('action.cancel'),dialog);page.wait.until(lambda _:not page.visible('[role=dialog]'))
            nav('navigation.drafts');page.wait.until(lambda _:len(rows(subject))==1);page.activate(rows(subject)[0]);page.field(text('field.subject'));page.click(text('action.discard'))
            page.wait.until(lambda _:not page.visible('[role=dialog]') and not rows(subject));assert draft['id'] not in {r['id'] for r in drafts()}
            switch=page.one('.q-toggle');page.activate(switch);page.wait.until(lambda _:len(rows(subject))==1);page.activate(rows(subject)[0]);page.click(text('action.restore'))
            page.wait.until(lambda _:not page.visible('[role=dialog]') and not rows(subject));assert draft['id'] in {r['id'] for r in drafts()}
            # Delete only this synthetic draft through the existing API so the
            # next language starts with the same empty active mailbox.
            saved=next(r for r in drafts() if r['id']==draft['id']);response=page.api.delete('/api/v1/messages/drafts/'+draft['id'],headers={'If-Match':str(saved['version'])});response.raise_for_status()
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('message monitor and notification administration remain reachable'):
            monitor_reads=sum(e['path']=='/api/v1/messages/monitor/producers' for e in page.events());nav('monitor.title');page.see(text('monitor.title'));page.wait.until(lambda _:sum(e['path']=='/api/v1/messages/monitor/producers' and e['status']==200 for e in page.events())>monitor_reads);capture('monitor')
            nav('admin.title');page.see(text('admin.title'));page.wait.until(lambda _:not page.visible('.q-inner-loading'));capture('notifications')
            page.errors();page.settings()
