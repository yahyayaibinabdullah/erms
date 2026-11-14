"""Dashboard warm refresh, mutation freshness, favourite actions and focus."""
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_dashboard(page):
    response=page.api.post('/api/v1/records/search',json={'where':{'field':'record_number','operator':'eq','value':'TEST-REC'},'limit':1,'offset':0});response.raise_for_status();record=response.json()['items'][0]
    favourite='/api/v1/favourites/records/'+str(record['id'])
    summary='/api/v1/dashboard/summary'
    def count(started=False):return sum(e['path']==summary for e in page.events('requests-started.jsonl' if started else 'requests.jsonl'))
    def refresh():return page.button(page.t('webui.load_dashboard.button.refresh_938d7997'),page.one('.erms-card'))
    def enter():
        previous=count();page.drawer('dashboard');page.one('.dashboard-overview-primary');page.wait.until(lambda _:count()>previous and refresh().is_enabled())
    def favourites():return page.visible('.dashboard-personal-panel')[0]
    def rows():return page.visible('.dashboard-personal-item',favourites())
    def capture(name):page.capture('dashboard-'+name+'-'+page.language)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        response=page.api.put(favourite);response.raise_for_status()
        with page.check('dashboard favourite keyboard navigation and connected detail'):
            enter();page.wait.until(lambda _:len(rows())==1);url=page.driver.current_url;history=page.driver.execute_script('return history.length');capture('overview')
            all_button=page.button(page.t('webui.render_favourites_dashboard.button.view_all_e1f7fcfb'),favourites());all_button.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            assert active.get_attribute('role')=='button' and 'dashboard-personal-item' in active.get_attribute('class')
            page.report.setdefault('focus',[]).append({'language':language,'sequence':['favourites view all','favourite row']})
            active.send_keys(Keys.ENTER);page.one('.component-list');enter();page.wait.until(lambda _:len(rows())==1)
            page.click(page.t('webui.render_favourites_dashboard.button.view_all_e1f7fcfb'),favourites());d=page.one('.dashboard-personal-dialog');capture('favourites')
            close=next(b for b in page.visible('button',d) if any(i.text=='close' for i in b.find_elements('css selector','.q-icon')));page.activate(close);page.wait.until(lambda _:not page.visible('.dashboard-personal-dialog'))
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('warm dashboard retains content, fetches once and reflects favourite mutation'):
            page.settings();page.api.delete(favourite).raise_for_status();started=count(True);completed=count()
            page.control(path=summary,hold=True)
            try:
                page.drawer('dashboard');page.wait.until(lambda _:count(True)==started+1);page.one('.dashboard-overview-primary');assert len(rows())==1
                assert page.t('webui.load_dashboard.label.loading_dashboard_30b6a7ab') not in page.text()
                assert not page.one('.erms-card button[disabled]').is_enabled();assert count()==completed
            finally:page.control()
            page.wait.until(lambda _:count()==completed+1 and refresh().is_enabled() and not rows());capture('fresh')
            assert count(True)==started+1
            page.api.put(favourite).raise_for_status();before=count();page.activate(refresh());page.wait.until(lambda _:count()==before+1 and refresh().is_enabled() and len(rows())==1)
            remove=next(b for b in page.visible('button',rows()[0]) if any(i.text=='favorite' for i in b.find_elements('css selector','.q-icon')));page.activate(remove)
            page.wait.until(lambda _:not rows());assert page.api.get('/api/v1/favourites').json()['records']==[];capture('removed')
            page.errors();page.settings()
