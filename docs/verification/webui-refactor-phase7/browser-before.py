"""Actual-product browser acceptance, launched by the owning disposable runner.

Install frontend/webui/requirements-browser-test.txt in a separate environment.
Never use this script against a persistent application stack.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback

import httpx
from PIL import Image, ImageChops
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
EN = {i['message_key']:i['default_text'] for i in json.loads((ROOT/'frontend/webui/i18n/messages.en.json').read_text())}
AR = {i['message_key']:i['translated_text'] for i in json.loads((ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']}
PASSWORD = 'Temporary-Test-Password-123!'


def plain(value):
    return re.sub('[\u2063\u2064\u2066-\u2069\ufe00-\ufe0f]', '', value or '').strip()


def create_driver(name, output):
    # Third-party Selenium settings only; no ERMS environment/configuration change.
    os.environ.update(SE_CACHE_PATH=str(ROOT/'.runtime/selenium'), SE_AVOID_STATS='true', SE_AVOID_BROWSER_DOWNLOAD='true')
    if name == 'chrome':
        options = webdriver.ChromeOptions()
        options.binary_location = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        options.add_argument('--headless=new')
        options.set_capability('goog:loggingPrefs', {'browser':'ALL'})
        return webdriver.Chrome(options=options)
    if name == 'edge':
        options = webdriver.EdgeOptions()
        options.binary_location = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        options.add_argument('--headless=new')
        return webdriver.Edge(options=options)
    if name == 'firefox':
        from selenium.webdriver.firefox.service import Service
        options = webdriver.FirefoxOptions()
        options.binary_location = '/Applications/Firefox.app/Contents/MacOS/firefox'
        options.add_argument('-headless')
        return webdriver.Firefox(options=options, service=Service(log_output=str(output/'driver.log')))
    return webdriver.Safari()


class Acceptance:
    def __init__(self, driver, args):
        self.driver, self.args, self.language = driver, args, 'en'
        self.current_identity = None
        self.report = {'browser':args.browser, 'version':driver.capabilities['browserVersion'],
                       'scope':args.scope, 'maildev_enabled':bool(args.maildev_url),
                       'checks':[], 'screenshots':[], 'complete':False}
        self.wait = WebDriverWait(driver, 20, poll_frequency=.1,
                                 ignored_exceptions=(StaleElementReferenceException,NoSuchElementException))
        self.api = httpx.Client(base_url=args.api, trust_env=False, timeout=20)
        response = self.api.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':PASSWORD})
        response.raise_for_status()
        self.api.headers['X-CSRF-Token'] = self.api.cookies['erms_csrf']

    def t(self, key): return (AR if self.language == 'ar' else EN)[key]

    def visible(self, selector, scope=None):
        return [e for e in (scope or self.driver).find_elements(By.CSS_SELECTOR,selector) if e.is_displayed()]

    def one(self, selector, label=None, scope=None):
        def found(_):
            matches=self.visible(selector,scope)
            if label is not None:
                matches=[e for e in matches if plain(e.text).casefold().endswith(label.casefold()) or plain(e.get_attribute('aria-label'))==label]
            return matches[0] if len(matches)==1 else False
        return self.wait.until(found, f'Expected exactly one visible {selector}: {label}')

    def button(self, label, scope=None): return self.one('button',label,scope)
    def activate(self,element):
        # WebDriver's nearest-edge scroll can place an input under the fixed
        # footer. Center it through ordinary scrolling before the native click.
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'})",element)
        if self.args.browser=='safari':
            ActionChains(self.driver).move_to_element(element).pause(.2).click().perform()
        else:
            element.click()
    def click(self,label,scope=None): self.activate(self.button(label,scope))
    def text(self): return plain(self.driver.find_element(By.TAG_NAME,'body').text)
    def see(self,text): self.wait.until(lambda _:text in self.text(),f'Missing text: {text}')
    def field(self,label):
        def found(_):
            fields=[e for e in self.visible('.q-field') if any(plain(l.text)==label for l in e.find_elements(By.CSS_SELECTOR,'.q-field__label'))]
            return fields[0].find_element(By.CSS_SELECTOR,'input,textarea') if len(fields)==1 else False
        return self.wait.until(found,f'Missing field: {label}')
    def fill(self,label,value):
        field=self.field(label);self.activate(field)
        # Replace the selection without an intermediate empty numeric value;
        # that value is normalized by the existing controlled number component.
        if self.args.browser == 'safari':
            ActionChains(self.driver).key_down(Keys.COMMAND).send_keys('a').key_up(Keys.COMMAND).perform()
        else:
            field.send_keys(Keys.COMMAND, 'a', Keys.NULL)
        if self.args.browser == 'safari':
            field.send_keys(str(value))
        else:
            for character in str(value):
                field.send_keys(character)
                time.sleep(.15)
        if not str(value):field.send_keys(Keys.BACKSPACE)
        self.wait.until(lambda _:field.get_attribute('value')==str(value),f'Input did not retain {label}: {value}')
        field.send_keys(Keys.TAB)
    def drawer(self,key):
        label=self.t('navigation.item.'+key)
        self.activate(self.one('button.erms-nav-link',label))
    def tab(self,category):
        label=self.t('settings.category.'+category)
        def select(_):
            tabs=[e for e in self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]') if plain(e.get_attribute('textContent'))==label]
            if len(tabs)!=1:return False
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'center'})",tabs[0])
            tabs[0].click()
            return True
        self.wait.until(select)
        self.wait.until(lambda _: plain(self.one('[role=tab][aria-selected=true]').text)==self.t('settings.category.'+category))
    def settings(self):
        previous_id=self.driver.execute_script("return document.querySelector('.application-settings-page')?.id")
        self.drawer('application_settings')
        if previous_id:
            self.wait.until(lambda _:not self.driver.find_elements(By.ID,previous_id))
        self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]'))==7)
    def reload(self):
        self.errors()
        self.driver.refresh()
        self.wait.until(lambda _:self.driver.execute_script('return !!window.__webuiTestErrors'))
    def events(self, filename='requests.jsonl'):
        p=self.args.output/filename
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []
    def settings_reads(self):
        return [e for e in self.events() if e['method']=='GET' and e['path']=='/api/v1/application-settings']
    def values(self):
        result=self.api.get('/api/v1/application-settings');result.raise_for_status()
        return {i['key']:i for i in result.json()['items']}
    def control(self,**values):
        target=self.args.output/'control.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(values));temp.replace(target)
    def errors(self):
        errors=self.driver.execute_script('return window.__webuiTestErrors || []')
        self.report.setdefault('browser_errors',[]).extend(errors)
        self.driver.execute_script('if(window.__webuiTestErrors)window.__webuiTestErrors=[]')
        assert not errors, errors
    def capture(self,name,*,target=None):
        self.wait.until(lambda _:self.driver.execute_script('return document.fonts.status')=='loaded')
        if not name.startswith('failure-'):
            self.wait.until(lambda _:not self.visible('.q-notification'))
        # Scroll position is part of the visual contract; normalize by ordinary
        # scrolling only, never by modifying CSS, hiding controls or masking data.
        self.driver.execute_script('window.scrollTo(0,0)')
        # Move the real pointer out of the scrollable drawer so its existing
        # hover scrollbar finishes fading in the same state for each capture.
        ActionChains(self.driver).move_to_element(self.one('header.q-header')).perform()
        if target is not None:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'})",target)
        time.sleep(2)
        path=self.args.output/(name+'.png');self.driver.save_screenshot(str(path))
        self.report['screenshots'].append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'language':self.language,'identity':self.current_identity,
            'dynamic_content': ['Saved-search update time reflects the real run'] if name.startswith('unsaved-') else [],
            'environment':self.driver.execute_script('return {width:innerWidth,height:innerHeight,scale:devicePixelRatio,zoom:visualViewport.scale,dir:document.documentElement.dir,fonts:document.fonts.status,fontFamily:getComputedStyle(document.body).fontFamily,browserTimezone:Intl.DateTimeFormat().resolvedOptions().timeZone}')})
        return path
    @contextmanager
    def check(self,name):
        start=time.monotonic()
        row={'name':name,'language':self.language,'status':'running'};self.report['checks'].append(row)
        try:
            yield
            row['status']='pass'
            print('PASS '+self.language+' '+name,flush=True)
        except Exception as error:
            row.update(status='fail',error=str(error),traceback=traceback.format_exc())
            self.report.setdefault('browser_errors',[]).extend(
                self.driver.execute_script('return window.__webuiTestErrors || []'))
            row['recent_native_clicks']=self.driver.execute_script('return (window.__webuiTestClicks || []).slice(-20)')
            self.capture('failure-'+str(len(self.report['checks'])))
            raise
        finally:
            row['milliseconds']=round(1000*(time.monotonic()-start),2)
            (self.args.output/'browser-results.json').write_text(json.dumps(self.report,indent=2,ensure_ascii=False)+'\n')

    def login(self,email='admin@test.invalid'):
        self.wait.until(lambda _:self.driver.execute_script('return window.socket?.connected && window.did_handshake'))
        dashboards=sum(e['path']=='/api/v1/dashboard/summary' for e in self.events())
        self.language=self.driver.execute_script('return document.documentElement.lang') or 'en'
        self.fill(self.t('webui.index.input.email_address_2569f0e9'),email)
        self.fill(self.t('webui.index.input.password_f76ddde6'),PASSWORD)
        submit=self.one('button.wathiq-login-submit')
        if self.args.browser=='safari':submit.send_keys(Keys.ENTER)
        else:submit.click()
        self.wait.until(lambda _:not self.visible('button.wathiq-login-submit'))
        self.wait.until(lambda _:self.driver.execute_script('return !!window.__webuiTestErrors'))
        self.wait.until(lambda _:sum(e['path']=='/api/v1/dashboard/summary' and e['status']==200 for e in self.events())>dashboards)
        self.wait.until(lambda _:self.visible('.dashboard-overview-primary'))
        if email=='viewer@test.invalid':
            # A preference-language change performs a second root render after
            # sign-in; wait for this identity's completed drawer, not the old DOM.
            self.wait.until(lambda _:len(self.visible('button.erms-nav-link'))==2)
        self.language=self.driver.execute_script('return document.documentElement.lang') or 'en'
        self.current_identity=email

    def language_change(self,language):
        buttons=[e for e in self.visible('header button') if 'account_circle' in e.text]
        assert len(buttons)==1;buttons[0].click()
        self.click(self.t('preferences.heading.personal'))
        self.field(self.t('preferences.field.language')).click()
        self.one('[role=option]','العربية (ar)' if language=='ar' else 'English (en)').click()
        self.click(self.t('preferences.action.save'))
        self.language=language
        self.wait.until(lambda _:self.driver.execute_script('return document.documentElement.lang')==language)
        self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]'))==7)

    def general(self):
        window=self.t('settings.field.review_warning_window_days.label')
        reason=self.t('settings.field.reason')
        with self.check('seven categories, root URL and browser history'):
            count=self.driver.execute_script('return history.length')
            for category in ['content','authentication','interface_limits','search','disposition','email','general']:
                self.tab(category)
            assert self.driver.current_url==self.args.url+'/'
            assert self.driver.execute_script('return history.length')==count
        with self.check('required reason, save, current value on return and reload'):
            old=int(self.field(window).get_attribute('value'));new=old+1
            before=sum(e['method']=='PUT' and e['path']=='/api/v1/application-settings' for e in self.events())
            self.fill(window,new);self.click(self.t('common.action.save'))
            self.see(self.t('settings.error.reason_required'))
            assert self.field(window).get_attribute('value')==str(new)
            assert sum(e['method']=='PUT' and e['path']=='/api/v1/application-settings' for e in self.events())==before
            self.fill(reason,'Disposable browser regression')
            self.click(self.t('common.action.save'));self.see(self.t('settings.page.saved'))
            assert sum(e['method']=='PUT' and e['path']=='/api/v1/application-settings' for e in self.events())==before+1
            self.drawer('dashboard');self.see(self.t('navigation.item.dashboard'));self.settings();self.tab('general')
            assert self.field(window).get_attribute('value')==str(new)
            self.reload();assert self.field(window).get_attribute('value')==str(new)
        with self.check('optimistic conflict keeps draft and reason'):
            conflicts=sum(e['status']==409 for e in self.events() if e['path']=='/api/v1/application-settings')
            item=self.values()['REVIEW_WARNING_WINDOW_DAYS']
            response=self.api.put('/api/v1/application-settings',json={'changes':[{'key':item['key'],'expected_version':item['version'],'value':new+1}]},headers={'X-Change-Reason':'Concurrent disposable session'})
            response.raise_for_status()
            self.fill(window,new+2);self.fill(reason,'Preserve browser draft');self.click(self.t('common.action.save'))
            self.wait.until(lambda _:sum(e['status']==409 for e in self.events() if e['path']=='/api/v1/application-settings')==conflicts+1)
            assert self.field(window).get_attribute('value')==str(new+2)
            assert self.field(reason).get_attribute('value')=='Preserve browser draft'
            self.click(self.t('settings.action.refresh'))
            self.wait.until(lambda _:self.field(window).get_attribute('value')==str(new+1))
        with self.check('repeated navigation uses one Settings read per visit'):
            for _ in range(3):
                self.drawer('dashboard');before=len(self.settings_reads());self.settings();self.field(window)
                assert len(self.settings_reads())==before+1
        with self.check('controlled error, recovery and abandoned delayed read'):
            self.drawer('dashboard')
            self.control(path='/api/v1/application-settings',status=503)
            self.drawer('application_settings');self.see(self.t('common.error.service_unavailable'))
            self.capture('settings-error-'+self.language)
            self.control();self.click(self.t('settings.action.refresh'));self.field(window)
            self.drawer('dashboard')
            self.control(path='/api/v1/application-settings',hold=True)
            start=len(self.events('requests-started.jsonl'))
            completed_before=len(self.settings_reads())
            self.drawer('application_settings');self.see(self.t('settings.page.loading'))
            self.capture('settings-loading-'+self.language)
            self.wait.until(lambda _:any(e['controlled'] for e in self.events('requests-started.jsonl')[start:]))
            self.drawer('dashboard')
            self.wait.until(lambda _:not self.visible('.application-settings-page'))
            assert not self.settings_reads()[completed_before:]
            self.control()
            self.wait.until(lambda _:any(e['controlled'] for e in self.settings_reads()[completed_before:]))
            assert not self.visible('.application-settings-page')
            self.settings();self.field(window)
        with self.check('reload visual repeatability'):
            self.reload();self.field(window)
            # Allow the existing transient scrollbar to settle; no product timing assertion.
            time.sleep(1)
            a=self.capture('settings-general-'+self.language+'-first')
            self.reload();self.field(window);time.sleep(1)
            b=self.capture('settings-general-'+self.language+'-repeat')
            left,right=Image.open(a).convert('RGB'),Image.open(b).convert('RGB')
            assert left.size==right.size
            scale=self.driver.execute_script('return devicePixelRatio')
            region=(0,int(72*scale),left.width,left.height)
            difference=ImageChops.difference(left.crop(region),right.crop(region))
            pixels=sum(p!=(0,0,0) for p in difference.getdata())
            self.report.setdefault('visual_comparisons',[]).append({'images':[a.name,b.name],'region':region,'different_pixels':pixels,'excluded':'Animated header and compression margin; full images retained for review'})
            assert not pixels, f'{pixels} pixels differ outside animated header'
        with self.check('category keyboard arrows and Enter preserve focus'):
            selected=self.one('[role=tab][aria-selected=true]')
            old_id=selected.get_attribute('id')
            selected.send_keys(Keys.ARROW_RIGHT)
            self.wait.until(lambda _:self.driver.switch_to.active_element.get_attribute('role')=='tab'
                            and self.driver.switch_to.active_element.get_attribute('id')!=old_id)
            focused=self.driver.switch_to.active_element
            focused.send_keys(Keys.ENTER)
            self.wait.until(lambda _:focused.get_attribute('aria-selected')=='true')
            self.report.setdefault('focus_observations',[]).append({
                'language':self.language,'category_after_arrow_enter':plain(focused.text)})
            self.tab('general')

    def callers(self):
        with self.check('custody warning and audit event Settings callers'):
            self.drawer('governance_custody');self.click(self.t('settings.custody.open'))
            self.wait.until(lambda _:plain(self.one('[role=tab][aria-selected=true]').text)==self.t('settings.category.disposition'))
            self.drawer('audit_trail')
            label=self.t('webui.render_event_timeline.tooltip.open_current_entity_208e2a65')
            self.wait.until(lambda _:len(self.visible('button[aria-label]'))>0)
            def links():return [e for e in self.visible('button[aria-label]') if plain(e.get_attribute('aria-label'))==label]
            self.wait.until(lambda _:links());links()[0].click()
            self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]'))==7)
            assert plain(self.one('[role=tab][aria-selected=true]').text)==self.t('settings.category.general')

    def setting_box(self,key): return self.one('[data-setting-key="'+key+'"]')
    def selected_label(self,key):
        return plain(self.setting_box(key).find_element(By.CSS_SELECTOR,'input').get_attribute('value'))
    def browse(self,key):
        self.click(self.t('settings.action.browse'),self.setting_box(key))
        return self.one('.application-settings-browser')
    def close_dialog(self):
        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
        self.wait.until(lambda _:not self.visible('.q-dialog'))

    def selectors(self):
        scheme='DISPOSITION_CLASSIFICATION_SCHEME_ID'
        evidence='DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID'
        reports='DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID'
        with self.check('scheme-first selector and paged scheme/branch browsing'):
            self.tab('disposition')
            assert not self.setting_box(evidence).find_element(By.CSS_SELECTOR,'input').is_enabled()
            dialog=self.browse(scheme)
            self.button('T01 · Test scheme 1',dialog)
            self.capture('scheme-browser-'+self.language)
            self.click(self.t('settings.action.next'),dialog)
            self.button('T26 · Test scheme 26',dialog)
            self.click(self.t('settings.action.previous'),dialog)
            self.click('T01 · Test scheme 1',dialog)
            self.wait.until(lambda _:not self.visible('.application-settings-browser'))
            dialog=self.browse(evidence)
            self.click('B01 · Test branch 01',dialog)
            self.button('C01 · Test child 01',dialog)
            self.click(self.t('settings.action.next'),dialog)
            self.button('C26 · Test child 26',dialog)
            self.capture('classification-browser-'+self.language)
            self.click('C26 · Test child 26',dialog)
            self.wait.until(lambda _:not self.visible('.application-settings-browser'))
            dialog=self.browse(reports)
            self.click(self.t('settings.action.next'),dialog)
            self.click('TERM · Test terminal',dialog)
            self.wait.until(lambda _:not self.visible('.application-settings-browser'))
            self.fill(self.t('settings.field.reason'),'Atomic destination browser test')
            self.click(self.t('common.action.save'));self.see(self.t('settings.page.saved'))
            self.reload()
            self.wait.until(lambda _:'Test child 26' in self.selected_label(evidence))
            assert 'Test terminal' in self.selected_label(reports)
        with self.check('selected values survive cancelled browse, bounded typeahead and clear'):
            dialog=self.browse(evidence);self.close_dialog()
            assert 'Test child 26' in self.selected_label(evidence)
            control=self.setting_box(evidence).find_element(By.CSS_SELECTOR,'input')
            control.click();control.send_keys('Te')
            self.wait.until(lambda _:self.visible('[role=option]'))
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            self.wait.until(lambda _:'Test child 26' in self.selected_label(evidence))
            requests=[e for e in self.events() if e['path']=='/api/v1/classifications' and e['query']]
            assert requests and all('limit=' in e['query'] for e in requests)
            clear=self.t('settings.action.clear_selection')
            self.one('button[aria-label]',clear,self.setting_box(scheme)).click()
            self.wait.until(lambda _:not self.setting_box(evidence).find_element(By.CSS_SELECTOR,'input').is_enabled())
            self.fill(self.t('settings.field.reason'),'Restore unset disposable destinations')
            self.click(self.t('common.action.save'));self.see(self.t('settings.page.saved'))
            current=self.values()
            assert all(current[key]['value'] is None for key in (scheme,evidence,reports))

    def email(self):
        with self.check('masked secret replacement and explicit clear'):
            self.tab('email')
            self.fill(self.t('settings.secret.replace'),'disposable-smtp-fixture-only')
            self.fill(self.t('settings.field.reason'),'Disposable masked secret fixture')
            self.click(self.t('common.action.save'));self.see(self.t('settings.page.saved'))
            self.see(self.t('settings.secret.set'))
            assert self.field(self.t('settings.secret.replace')).get_attribute('value')==''
            self.one('[role=checkbox]',self.t('settings.secret.clear')).click()
            assert not self.field(self.t('settings.secret.replace')).is_enabled()
            self.fill(self.t('settings.field.reason'),'Clear disposable masked secret')
            self.click(self.t('common.action.save'));self.see(self.t('settings.page.saved'))
            self.see(self.t('settings.secret.unset'))
        with self.check('email dialog validation, keyboard, busy state and cancel'):
            self.click(self.t('settings.email_test.action'))
            dialog=self.one('[role=dialog]')
            self.click(self.t('settings.email_test.send'),dialog)
            self.see(self.t('settings.email_test.invalid_recipient'))
            self.capture('email-validation-'+self.language)
            self.fill(self.t('settings.email_test.recipient'),'recipient@test.invalid')
            self.control(path='/api/v1/application-settings/test-send',method='POST',hold=True,status=503)
            before=sum(e['path']=='/api/v1/application-settings/test-send' for e in self.events('requests-started.jsonl'))
            self.click(self.t('settings.email_test.send'),dialog)
            self.wait.until(lambda _:not self.button(self.t('settings.email_test.send'),dialog).is_enabled())
            assert not self.field(self.t('settings.email_test.recipient')).is_enabled()
            self.capture('email-busy-'+self.language)
            self.control()
            self.see(self.t('settings.email_test.unknown'))
            assert sum(e['path']=='/api/v1/application-settings/test-send' for e in self.events('requests-started.jsonl'))==before+1
            self.button(self.t('settings.email_test.close'),dialog).send_keys(Keys.TAB)
            focused=self.driver.switch_to.active_element
            assert focused.is_displayed()
            self.report.setdefault('focus_observations',[]).append({'language':self.language,'email_dialog_tab':plain(focused.text)})
            self.close_dialog()
            self.wait.until(lambda _:self.button(self.t('settings.email_test.action')).is_enabled())
        if self.args.maildev_url:
            with self.check('real test email is accepted by local MailDev with verified TLS'):
                current=self.values()
                values={'SMTP_HOST':'localhost','SMTP_PORT':self.args.smtp_port,
                        'SMTP_SECURITY':'implicit_tls','SMTP_AUTH_ENABLED':False,
                        'SMTP_SENDER_EMAIL':'phase2-sender@test.invalid'}
                changes=[]
                for key,item in current.items():
                    if item['category']=='email':
                        change={'key':key,'expected_version':item['version']}
                        if key!='SMTP_PASSWORD':change['value']=values.get(key,item['value'])
                        changes.append(change)
                response=self.api.put('/api/v1/application-settings',json={'changes':changes},
                    headers={'X-Change-Reason':'Disposable local MailDev transport'})
                response.raise_for_status()
                self.click(self.t('settings.email_test.action'))
                dialog=self.one('[role=dialog]')
                recipient=f'phase2-{self.args.browser}-{self.language}@test.invalid'
                with httpx.Client(base_url=self.args.maildev_url,trust_env=False,timeout=10) as mailbox:
                    prior=mailbox.get('/api/email/summary',params={'search':recipient,'limit':10})
                    prior.raise_for_status()
                    before_ids={message['id'] for message in prior.json()['items']}
                    before_total=prior.json()['total']
                self.fill(self.t('settings.email_test.recipient'),recipient)
                self.click(self.t('settings.email_test.send'),dialog)
                self.see(self.t('settings.email_test.accepted'))
                with httpx.Client(base_url=self.args.maildev_url,trust_env=False,timeout=10) as mailbox:
                    def delivered(_):
                        response=mailbox.get('/api/email/summary',params={'search':recipient,'limit':10});response.raise_for_status()
                        assert response.json()['total']<=before_total+1, 'Duplicate test email delivery'
                        return [message for message in response.json()['items']
                                if message['id'] not in before_ids and any(address.get('address')==recipient for address in message.get('to',[]))]
                    messages=self.wait.until(delivered)
                assert len(messages)==1
                self.report.setdefault('maildev_deliveries',[]).append({
                    'language':self.language,'recipient':recipient,'count':1,
                    'subject':messages[0].get('subject'),'tls_certificate_validation':True})
                self.capture('email-accepted-'+self.language)
                self.close_dialog()

    def identity_and_history(self):
        with self.check('browser Back/Forward retains existing exit behavior'):
            self.report['history_request_index']=len(self.events())
            self.driver.get(self.args.api+'/health')
            self.driver.get(self.args.url+'/')
            self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]'))==7)
            count=self.driver.execute_script('return history.length')
            self.drawer('dashboard');self.settings()
            assert self.driver.execute_script('return history.length')==count
            self.driver.back();self.wait.until(lambda _:self.driver.current_url==self.args.api+'/health')
            self.driver.forward();self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]'))==7)
        with self.check('ordinary sign-out clears a private Settings draft'):
            self.fill(self.t('settings.field.reason'),'Private identity draft')
            self.sign_out()
            assert not self.visible('.application-settings-page')
            self.login('viewer@test.invalid')
            assert 'Private identity draft' not in self.text()
            assert not self.visible('.application-settings-page')
            self.sign_out()
            self.login()
            # Administrator preference is Arabic; wait for that root render.
            self.wait.until(lambda _:self.driver.execute_script('return document.documentElement.lang')=='ar')
            self.language='ar';self.settings();self.tab('general')
        with self.check('expired session returns to sign-in'):
            self.report['expiry_request_index']=len(self.events())
            command="""import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL']
assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute(\"UPDATE login_sessions SET expires_at=CURRENT_TIMESTAMP-interval '1 second' WHERE user_id=(SELECT id FROM users WHERE email='admin@test.invalid') AND date_created<CURRENT_TIMESTAMP-interval '1 second'\")
"""
            subprocess.run([self.args.api_python,'-c',command],check=True,timeout=30)
            self.reload();self.one('button.wathiq-login-submit')
        with self.check('restricted identity has no Settings or previous private draft'):
            self.login('viewer@test.invalid')
            assert not [e for e in self.visible('button.erms-nav-link') if plain(e.get_attribute('aria-label')) in ('Settings','الإعدادات')]
            assert not self.visible('.application-settings-page')
            assert 'Preserve browser draft' not in self.text()
            self.capture('restricted-dashboard')

    def sign_out(self):
        buttons=[e for e in self.visible('header button') if 'account_circle' in e.text]
        assert len(buttons)==1
        buttons[0].click()
        self.click(self.t('webui.index.button.sign_out_a4610dd4'))
        self.one('button.wathiq-login-submit')
        self.current_identity=None

    def run(self):
        self.driver.set_window_size(1440,1100)
        if self.args.scope == 'performance':
            from tools.webui_browser_performance import check_performance
            check_performance(self)
            self.report['complete'] = True
            return
        self.driver.get(self.args.url+'/')
        width,height=self.driver.execute_script('return [innerWidth,innerHeight]')
        outer=self.driver.get_window_size()
        self.driver.set_window_size(outer['width']+1440-width,outer['height']+1000-height)
        with self.check('real sign-in and Settings drawer caller'):
            self.login();self.settings()
        if self.args.scope == 'application':
            from tools.webui_browser_application import check_application
            check_application(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'messaging':
            from tools.webui_browser_messaging import check_messaging
            check_messaging(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'disposition':
            from tools.webui_browser_disposition import check_disposition
            check_disposition(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'dashboard':
            from tools.webui_browser_dashboard import check_dashboard
            check_dashboard(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'advanced-search':
            from tools.webui_browser_advanced_search import check_advanced_search
            check_advanced_search(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'global-search':
            from tools.webui_browser_global_search import check_global_search
            check_global_search(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'governance-custody':
            from tools.webui_browser_governance_custody import check_governance_custody
            check_governance_custody(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'security-operations':
            from tools.webui_browser_security_operations import check_security_operations
            check_security_operations(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'records':
            from tools.webui_browser_records import check_records
            check_records(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'aggregations':
            from tools.webui_browser_aggregations import check_aggregations
            check_aggregations(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'components':
            from tools.webui_browser_components import check_components
            check_components(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'holds':
            from tools.webui_browser_holds import check_holds
            check_holds(self)
            self.report['complete'] = True
            return

        if self.args.scope == 'translations':
            from tools.webui_browser_translations import check_translations
            check_translations(self)
            self.report['complete'] = True
            return

        if self.args.scope == 'account':
            from tools.webui_browser_account import check_account
            check_account(self)
            self.report['complete'] = True
            return

        if self.args.scope == 'text-indexers':
            from tools.webui_browser_text_indexers import check_text_indexers
            check_text_indexers(self)
            self.report['complete'] = True
            return

        if self.args.scope == 'organization':
            from tools.webui_browser_organization import check_organization
            check_organization(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'login-sessions':
            from tools.webui_browser_login_sessions import check_login_sessions
            check_login_sessions(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'security':
            from tools.webui_browser_security import check_security
            check_security(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'classification':
            from tools.webui_browser_classification import check_classification
            check_classification(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'collections':
            from tools.webui_browser_collections import check_collections
            check_collections(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'audit':
            from tools.webui_browser_audit import check_audit
            check_audit(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'relationships':
            from tools.webui_browser_relationships import check_relationships
            check_relationships(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'session':
            from tools.webui_browser_session import check_sessions
            check_sessions(self)
            self.report['complete'] = True
            return
        if self.args.scope == 'shell':
            from tools.webui_browser_shell import check_shell, check_restricted_shell
            for language in ('en', 'ar'):
                if language == 'ar':
                    self.language_change('ar')
                check_shell(self)
            check_restricted_shell(self)
            with self.check('shell journey browser errors and API failures'):
                self.errors()
                assert all(e['status'] is not None and e['status'] < 400 for e in self.events())
            self.report['complete'] = True
            return
        if self.args.scope == 'keyboard':
            from tools.webui_browser_keyboard import check_keyboard
            for language in ('en', 'ar'):
                if language == 'ar':
                    self.language_change('ar')
                check_keyboard(self)
            with self.check('keyboard journey browser errors and API failures'):
                self.errors()
                assert all(e['status'] is not None and e['status'] < 400 for e in self.events())
            self.report['complete'] = True
            return
        from tools.webui_browser_navigation import check_navigation
        for language in ('en','ar'):
            if language=='ar':
                with self.check('ordinary Preferences changes language and direction'):
                    self.language_change('ar')
                    assert self.driver.execute_script('return document.documentElement.dir')=='rtl'
            if self.args.scope=='full':
                self.general()
                self.callers();self.selectors();self.email();self.tab('general')
            check_navigation(self)
        self.identity_and_history()
        with self.check('browser console and unhandled errors'):
            self.errors()
        with self.check('failed API requests match deliberately exercised outcomes'):
            failed=[]
            for index,event in enumerate(self.events()):
                if event['status'] is not None and event['status']<400:continue
                expected=(event['status']==409 and event['path']=='/api/v1/application-settings'
                          or event['status']==503 and event['controlled']
                          # The preceding API health document has no favicon;
                          # this browser request is not a WebUI asset failure.
                          or event['status']==404 and event['method']=='GET' and event['path']=='/favicon.ico'
                          and index>=self.report['history_request_index']
                          or event['status']==401 and index>=self.report['expiry_request_index'])
                failed.append({**event,'expected':expected})
            self.report['failed_requests']=failed
            assert all(event['expected'] for event in failed),failed
        self.report['complete']=True


def main():
    parser=argparse.ArgumentParser()
    for name in ('browser','url','api','api-python'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--scope',choices=['full','navigation','keyboard','shell','session','relationships','audit','collections','classification','security','login-sessions', 'organization', 'text-indexers', 'account', 'translations', 'holds', 'components', 'aggregations', 'records', 'security-operations', 'governance-custody', 'global-search', 'advanced-search', 'dashboard', 'disposition', 'messaging', 'application', 'performance'],default='full')
    parser.add_argument('--maildev-url')
    parser.add_argument('--smtp-port',type=int)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    if 'dbname=erms_webui_test_' not in os.environ.get('DATABASE_URL',''):
        raise RuntimeError('Use the disposable owning runner')
    driver=None; acceptance=None
    try:
        driver=create_driver(args.browser,args.output)
        acceptance=Acceptance(driver,args);acceptance.run();return 0
    except Exception:
        traceback.print_exc();return 1
    finally:
        if acceptance:
            (args.output/'browser-results.json').write_text(json.dumps(acceptance.report,indent=2,ensure_ascii=False)+'\n')
            acceptance.api.close()
        if driver:driver.quit()

if __name__=='__main__':raise SystemExit(main())
