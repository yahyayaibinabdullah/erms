"""Application-wide repeated destination traversal; no UI or product changes."""
import time
from collections import Counter
from tools.check_webui_browser import plain

DESTINATIONS = {'dashboard': 'navigation.item.dashboard', 'advanced-search': 'navigation.item.advanced_search', 'aggregations': 'navigation.item.aggregations', 'records': 'navigation.item.records', 'classification-workspace': 'navigation.item.classification_schemes', 'relationship-types': 'relationships.ui.catalogue', 'disposition-tasks': 'disposition.ui.my_tasks', 'disposition-eligibility': 'disposition.ui.eligibility', 'disposition-jobs': 'disposition.ui.jobs', 'disposition-templates': 'disposition.ui.templates', 'messages-inbox': 'messaging.navigation.inbox', 'messages-outbox': 'messaging.navigation.outbox', 'messages-drafts': 'messaging.navigation.drafts', 'messages-monitor': 'messaging.monitor.title', 'messages-notifications': 'messaging.admin.title', 'organization-browser': 'navigation.item.organization_browser', 'org-units': 'navigation.item.org_units', 'roles': 'navigation.item.roles', 'users': 'navigation.item.users', 'text-indexers': 'navigation.item.text_indexers', 'application-settings': 'navigation.item.application_settings', 'audit-trail': 'navigation.item.audit_trail', 'login-sessions': 'navigation.item.login_sessions', 'security-operations': 'navigation.item.security_operations', 'saved-search-administration': 'privilege.search.saved_search.administrator.name', 'security-levels': 'navigation.item.security_levels', 'profiles': 'navigation.item.profiles', 'governance-custody': 'navigation.item.governance_custody', 'holds': 'navigation.item.holds', 'translations': 'navigation.item.translations'}
POLLING = {'/api/v1/messages/catch-up','/api/v1/messages/unread-count','/api/v1/messages/events'}


def settled(page):
    last=[None,time.monotonic()]
    def ready(_):
        started=Counter((e['method'],e['path'],e['query']) for e in page.events('requests-started.jsonl') if e['path'] not in POLLING)
        finished=Counter((e['method'],e['path'],e['query']) for e in page.events() if e['path'] not in POLLING)
        signature=(started,finished)
        if signature!=last[0]:last[:]=[signature,time.monotonic()]
        return not (started-finished) and time.monotonic()-last[1]>.5
    page.wait.until(ready,'Application requests did not settle')


def check_application(page):
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        settled(page)
        labels=[page.t(key) for key in DESTINATIONS.values()]
        for label in labels:assert page.visible('button.erms-nav-link') and page.one('button.erms-nav-link',label)
        url=page.driver.current_url;history=page.driver.execute_script('return history.length')
        for cycle,items in [('forward',list(DESTINATIONS.items())),('reverse',list(reversed(DESTINATIONS.items())))]:
            with page.check('all application destinations in '+cycle+' order'):
                for name,key in items:
                    label=page.t(key);start=time.monotonic();before=len(page.events())
                    page.activate(page.one('button.erms-nav-link',label))
                    page.wait.until(lambda _:plain(page.one('.erms-breadcrumb-row [aria-current=page]').text)==label)
                    settled(page)
                    heading=page.one('.erms-page-title-row');assert plain(heading.text)
                    assert not page.visible('[role=dialog]')
                    assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
                    result={'destination':name,'language':language,'cycle':cycle,'heading':plain(heading.text),'milliseconds':round((time.monotonic()-start)*1000,2),'requests':[e for e in page.events()[before:] if e['path'] not in POLLING]}
                    page.report.setdefault('destinations',[]).append(result)
                    if cycle=='forward':page.capture('application-'+name+'-'+language)
                    page.errors()
        page.settings()
    with page.check('all destination requests succeeded'):
        failed=[e for e in page.events() if e['status'] is None or e['status']>=400]
        assert not failed,failed
