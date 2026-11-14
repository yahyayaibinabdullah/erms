import ast,json
from pathlib import Path
p=Path('frontend/webui/assembled/tests/test_application.py');t=ast.parse(p.read_text());dest=next(ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='DESTINATIONS' for x in n.targets))
Path('.runtime/webui-refactor-phase7/destinations.json').write_text(json.dumps(dest,indent=2)+'\n')
source='''"""Application-wide repeated destination traversal; no UI or product changes."""
import time
from collections import Counter
from tools.check_webui_browser import plain

DESTINATIONS = '''+repr(dest)+'''
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
'''
Path('tools/webui_browser_application.py').write_text(source)
for name in ('tools/run_webui_integration.py','tools/check_webui_browser.py'):
 p=Path(name);s=p.read_text().replace("'disposition', 'messaging']","'disposition', 'messaging', 'application']")
 if name.endswith('check_webui_browser.py'):s=s.replace("        if self.args.scope == 'messaging':", "        if self.args.scope == 'application':\n            from tools.webui_browser_application import check_application\n            check_application(self)\n            self.report['complete'] = True\n            return\n        if self.args.scope == 'messaging':")
 else:s=s.replace("'webui_browser_messaging.py',", "'webui_browser_messaging.py', 'webui_browser_application.py',")
 p.write_text(s)
print(len(dest),'destinations')
