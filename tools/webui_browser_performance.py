"""Paired local UI timings with actual controls, fresh data and raw samples.

Only used by the disposable runner. No injected delays, DOM styling, API caches
or mock responses. Setup/typing and screenshot waits are outside timed actions.
"""
import time
from collections import Counter
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import StaleElementReferenceException,NoSuchElementException
from tools.check_webui_browser import PASSWORD

POLLING={'/api/v1/messages/catch-up','/api/v1/messages/unread-count','/api/v1/messages/events'}


def check_performance(page):
    wait=WebDriverWait(page.driver,20,poll_frequency=.02,ignored_exceptions=(StaleElementReferenceException,NoSuchElementException))
    def visible(selector):return page.driver.execute_script("return [...document.querySelectorAll(arguments[0])].some(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length))",selector)
    def requests_finished():
        def counts(filename):
            return Counter((e['method'],e['path'],e['query']) for e in page.events(filename) if e['path'] not in POLLING)
        return not (counts('requests-started.jsonl')-counts('requests.jsonl'))
    def record(name,action,ready,*,cycle,language):
        first=len(page.events());started=time.perf_counter();action();wait.until(lambda _:ready() and requests_finished())
        # Give pending callback batches two animation frames to commit their
        # visible result; no sleep or artificial minimum enters the measurement.
        page.driver.execute_async_script('const done=arguments[arguments.length-1];requestAnimationFrame(()=>requestAnimationFrame(done))')
        elapsed=(time.perf_counter()-started)*1000
        events=[e for e in page.events()[first:] if e['path'] not in POLLING]
        assert not [e for e in events if e['status'] is None or e['status']>=400],events
        page.report.setdefault('performance_samples',[]).append({'workflow':name,'language':language,'cycle':cycle,'warmup':cycle<0,'milliseconds':round(elapsed,3),'requests':events})
    with page.check('cold page and authenticated bootstrap measurements'):
        record('page_to_sign_in',lambda:page.driver.get(page.args.url+'/'),lambda:visible('button.wathiq-login-submit') and page.driver.execute_script("return !!(window.socket?.connected && window.did_handshake && document.fonts.status==='loaded')"),cycle=0,language='en')
        width,height=page.driver.execute_script('return [innerWidth,innerHeight]');outer=page.driver.get_window_size();page.driver.set_window_size(outer['width']+1440-width,outer['height']+1000-height)
        page.fill(page.t('webui.index.input.email_address_2569f0e9'),'admin@test.invalid');page.fill(page.t('webui.index.input.password_f76ddde6'),PASSWORD)
        button=page.one('button.wathiq-login-submit')
        record('sign_in_to_dashboard',button.click,lambda:not visible('button.wathiq-login-submit') and visible('.dashboard-overview-primary') and not visible('.dashboard-overview .q-spinner'),cycle=0,language='en')
        page.current_identity='admin@test.invalid'
    def nav_ready(label,selector):
        return page.driver.execute_script("return document.querySelector('.erms-breadcrumb-row [aria-current=page]')?.innerText?.includes(arguments[0])",label) and visible(selector)
    def counter(path):return sum(e['path']==path and e['status']==200 for e in page.events())
    cases=[
        ('settings','navigation.item.application_settings','.application-settings-page','/api/v1/application-settings'),
        ('dashboard_fresh','navigation.item.dashboard','.dashboard-overview-primary','/api/v1/dashboard/summary'),
        ('records','navigation.item.records','.dashboard-personal-panel',None),
        ('classification','navigation.item.classification_schemes','.classification-workspace',None),
        ('inbox','messaging.navigation.inbox','.messaging-workspace','/api/v1/messages/inbox'),
        ('custody','navigation.item.governance_custody','.governance-metric-card',None),
    ]
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        page.language=language
        with page.check('repeated fresh navigation and cross-feature detail timings '+language):
            for cycle in range(-1,12):
                for name,key,selector,path in cases:
                    label=page.t(key);button=page.one('button.erms-nav-link',label);before=counter(path) if path else 0
                    def ready():
                        if not nav_ready(label,selector):return False
                        if path and counter(path)<=before:return False
                        return not visible('.erms-card .q-spinner') and not visible('.erms-card .q-inner-loading') and not visible('.dashboard-personal-panel .q-spinner')
                    record(name,button.click,ready,cycle=cycle,language=language)
                # Connected Records -> result -> record -> parent aggregation.
                page.drawer('records');wait.until(lambda _:nav_ready(page.t('navigation.item.records'),'.dashboard-personal-panel') and not visible('.dashboard-personal-panel .q-spinner'))
                field=page.field(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'))
                # This is an ordinary input update via native keys, before timing.
                if field.get_attribute('value')!='TEST-REC':page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),'TEST-REC')
                search=page.button(page.t('webui.index.button.search_4d02b714'),page.one('.erms-shared-control.items-end'))
                previous=page.driver.execute_script("return document.querySelector('.compact-result-item')?.id")
                record('record_search',search.click,lambda:visible('.compact-result-item') and page.driver.execute_script("return document.querySelector('.compact-result-item')?.id!==arguments[0]",previous),cycle=cycle,language=language)
                open_record=page.one('button[aria-label="Open record"]',scope=page.one('.compact-result-item'))
                record('record_detail',open_record.click,lambda:visible('.component-list'),cycle=cycle,language=language)
                parent=page.one('button.detail-linked-entity')
                record('parent_aggregation',parent.click,lambda:page.t('webui.open_aggregation.label.aggregation_overview_bb8398e3') in page.text() and not visible('.erms-card .q-spinner'),cycle=cycle,language=language)
        page.errors()
    page.report['performance_method']={'cycles_per_language':12,'warmup_cycles_excluded':1,'poll_seconds':.02,'readiness':'Visible destination, all non-stream API requests complete, loading indicators absent, and two animation frames.','timed_actions':'Native click through ready UI; excludes finding controls, typing, screenshots and fixture setup.','startup_limit':'One cold browser load and login per independent process; compare repeated processes separately.','concurrency':'Benchmark sessions run sequentially after functional test processes exit.'}
