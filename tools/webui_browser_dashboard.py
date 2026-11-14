"""Dashboard warm refresh, mutation freshness, favourite actions and focus."""
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_dashboard(page):
    response=page.api.post('/api/v1/records/search',json={'where':{'field':'record_number','operator':'eq','value':'TEST-REC'},'limit':1,'offset':0});response.raise_for_status();record=response.json()['items'][0]
    favourite='/api/v1/favourites/records/'+str(record['id'])
    response=page.api.post('/api/v1/aggregations/search',json={'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0});response.raise_for_status();aggregation=response.json()['items'][0]
    entities={'records':record,'aggregations':aggregation}
    success='webui.remove_dashboard_favourite.notify.removed_from_favourites_6953809b'
    summary='/api/v1/dashboard/summary'
    def count(started=False):return sum(e['path']==summary for e in page.events('requests-started.jsonl' if started else 'requests.jsonl'))
    def refresh():return page.button(page.t('webui.load_dashboard.button.refresh_938d7997'),page.one('.erms-card'))
    def enter():
        previous=count();page.drawer('dashboard');page.one('.dashboard-overview-primary');page.wait.until(lambda _:count()>previous and refresh().is_enabled())
    def favourites():return page.visible('.dashboard-personal-panel')[0]
    def rows():return page.visible('.dashboard-personal-item',favourites())
    def capture(name):page.capture('dashboard-'+name+'-'+page.language)
    def verify_identities(scope, resources):
        for resource in resources:
            item=entities[resource]
            row=next(r for r in page.visible('.dashboard-personal-item',scope)
                     if any(plain(label.text)==item['title'] for label in r.find_elements('css selector','.font-semibold')))
            number=item['record_number' if resource=='records' else 'aggregation_number']
            kind=page.t('dashboard.resource.record' if resource=='records' else 'dashboard.resource.aggregation')
            assert plain(page.one('.text-xs',scope=row).text)==plain(page.t('dashboard.resource.identity').format(type=kind,number=number))
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
            page.see(page.t(success))
            page.wait.until(lambda _:not rows());assert page.api.get('/api/v1/favourites').json()['records']==[];capture('removed')
            page.errors();page.settings()
        for surface in ('dashboard','dialog'):
            with page.check(f'{surface} record and aggregation removal notifies and retains fresh empty state'):
                for resource,item in entities.items():
                    page.api.put(f"/api/v1/favourites/{resource}/{item['id']}").raise_for_status()
                enter();page.wait.until(lambda _:len(rows())==2)
                verify_identities(favourites(),entities)
                d=None
                if surface=='dialog':
                    page.click(page.t('webui.render_favourites_dashboard.button.view_all_e1f7fcfb'),favourites())
                    d=page.one('.dashboard-personal-dialog');dialog_id=d.get_attribute('id')
                    verify_identities(d,entities)
                order=('records','aggregations') if surface=='dashboard' else ('aggregations','records')
                for position,resource in enumerate(order):
                    item=entities[resource]
                    if surface=='dialog':
                        assert len(page.visible('.dashboard-personal-item',d))==2-position
                    page.wait.until(lambda _:not page.visible('.q-notification'))
                    matches=[r for r in page.visible('.dashboard-personal-item',d or favourites())
                             if any(plain(label.text)==item['title'] for label in r.find_elements('css selector','.font-semibold'))]
                    assert len(matches)==1
                    row=matches[0]
                    remove=next(b for b in page.visible('button',row) if any(i.text=='favorite' for i in b.find_elements('css selector','.q-icon')))
                    start=len(page.events());page.activate(remove)
                    page.wait.until(lambda _:any(page.t(success) in plain(n.text) for n in page.visible('.q-notification')))
                    remaining=1-position
                    page.wait.until(lambda _:len(rows())==remaining)
                    assert page.one('.q-badge',scope=favourites()).text==str(remaining)
                    if d is not None:
                        page.wait.until(lambda _:len(page.visible('.dashboard-personal-item',d))==remaining)
                        assert page.one('.dashboard-personal-dialog').get_attribute('id')==dialog_id
                        verify_identities(d,order[position+1:])
                    verify_identities(favourites(),order[position+1:])
                    response=page.api.get('/api/v1/favourites');response.raise_for_status()
                    assert not response.json()[resource]
                    deletes=[e for e in page.events()[start:] if e['method']=='DELETE' and e['path']==f"/api/v1/favourites/{resource}/{item['id']}"]
                    assert len(deletes)==1 and deletes[0]['status']<300
                    capture(f'{surface}-{resource}-removed')
                    page.report.setdefault('favourite_removal',[]).append({'language':language,'surface':surface,'resource':resource,
                        'localized_notification':True,'remaining_count':remaining,'single_delete':True,'persisted':True,
                        'correct_identity':True,'dialog_stayed_open':surface=='dialog'})
                if d is not None:
                    page.see(page.t('webui.render_complete_list.label.no_favourites_8952ca8c'))
                    close=next(b for b in page.visible('button',d) if any(i.text=='close' for i in b.find_elements('css selector','.q-icon')))
                    close.send_keys(Keys.ENTER);page.wait.until(lambda _:not page.visible('.dashboard-personal-dialog'))
                page.see(page.t('webui.render_favourites_dashboard.label.you_haven_t_added_any_favourites_yet_selec_9fcb89ef'))
                # The warm snapshot must already reflect removal before its refresh returns.
                page.settings();started=count(True);completed=count();page.control(path=summary,hold=True)
                try:
                    page.drawer('dashboard');page.wait.until(lambda _:count(True)==started+1)
                    page.one('.dashboard-overview-primary');assert not rows();assert count()==completed
                finally:page.control()
                page.wait.until(lambda _:count()==completed+1 and refresh().is_enabled())
                assert not rows();page.errors();page.settings()
    assert not [e for e in page.events() if e['status'] is None or e['status']>=400]
