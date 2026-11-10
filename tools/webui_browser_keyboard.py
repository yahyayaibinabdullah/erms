"""Record existing keyboard behavior for human review; never change UI focus/CSS.

Only invoked through the disposable browser runner. Native WebDriver keys drive
the page; read-only DOM observations and original screenshots preserve evidence.
"""
import hashlib
import re
import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


def plain(value):
    return re.sub('[\u2063\u2064\u2066-\u2069\ufe00-\ufe0f]', '', value or '').strip()


def press(page, key, *, reverse=False):
    action = ActionChains(page.driver)
    if reverse:
        action.key_down(Keys.SHIFT).send_keys(key).key_up(Keys.SHIFT)
    else:
        action.send_keys(key)
    action.perform()


def observe(page, name, *, screenshot=False):
    # Allow existing component focus/transition callbacks to finish. This is not
    # a performance threshold, and nothing injects focus or rewrites the page.
    time.sleep(.35)
    result = page.driver.execute_script("""
        const e=document.activeElement, box=e.getBoundingClientRect(), s=getComputedStyle(e);
        const field=e.closest('.q-field'), button=e.closest('button'), tab=e.closest('[role=tab]');
        const indicator=(button && button.querySelector('.q-focus-helper')) || field || tab || e;
        const i=getComputedStyle(indicator);
        return {tag:e.tagName,id:e.id,role:e.getAttribute('role'),
          label:field?.querySelector('.q-field__label')?.innerText || e.getAttribute('aria-label') ||
            (e.tagName==='BODY'?'':e.innerText),
          setting:e.closest('[data-setting-key]')?.getAttribute('data-setting-key'),
          inDialog:!!e.closest('[role=dialog]'),focusVisible:e.matches(':focus-visible'),
          visible:box.width>0 && box.height>0 && s.visibility!=='hidden',
          rect:{x:box.x,y:box.y,width:box.width,height:box.height},
          indicator:{className:indicator.className,opacity:i.opacity,outline:i.outline,
            border:i.border,background:i.backgroundColor}};
    """)
    result['label']=plain(result['label'])
    row = {'name':name, 'language':page.language, **result}
    page.report.setdefault('keyboard_observations', []).append(row)
    if screenshot:
        page.wait.until(lambda _:page.driver.execute_script('return document.fonts.status')=='loaded')
        # Preserve the actual keyboard-induced scroll and pointer position.
        path=page.args.output/('focus-'+page.language+'-'+name+'.png')
        page.driver.save_screenshot(str(path))
        row['screenshot']=path.name
        page.report['screenshots'].append({
            'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'language':page.language,'identity':page.current_identity,
            'dynamic_content':['Audit-event timestamps reflect the real run'] if 'audit' in name else [],
            'environment':page.driver.execute_script('return {width:innerWidth,height:innerHeight,scale:devicePixelRatio,zoom:visualViewport.scale,dir:document.documentElement.dir,fonts:document.fonts.status,fontFamily:getComputedStyle(document.body).fontFamily,browserTimezone:Intl.DateTimeFormat().resolvedOptions().timeZone}')})
    return row


def check_keyboard(page):
    reason=page.t('settings.field.reason')
    window=page.t('settings.field.review_warning_window_days.label')
    with page.check('General forward and reverse Tab order, validation and save focus'):
        page.tab('general')
        new=int(page.field(window).get_attribute('value'))+1
        page.fill(window,new)  # Existing helper ends with a real Tab.
        assert page.driver.switch_to.active_element == page.field(reason)
        observe(page,'reason-tab',screenshot=True)
        press(page,Keys.TAB)
        assert page.driver.switch_to.active_element == page.button(page.t('common.action.save'))
        observe(page,'save-tab',screenshot=True)
        press(page,Keys.TAB,reverse=True)
        assert page.driver.switch_to.active_element == page.field(reason)
        press(page,Keys.TAB,reverse=True)
        assert page.driver.switch_to.active_element == page.field(window)
        observe(page,'number-reverse-tab',screenshot=True)
        press(page,Keys.TAB);press(page,Keys.TAB)
        before=sum(e['method']=='PUT' for e in page.events())
        press(page,Keys.ENTER)
        page.see(page.t('settings.error.reason_required'))
        observe(page,'required-reason-validation',screenshot=True)
        assert page.field(window).get_attribute('value')==str(new)
        assert sum(e['method']=='PUT' for e in page.events())==before
        page.fill(reason,'Disposable keyboard baseline '+page.language)
        press(page,Keys.ENTER)
        page.see(page.t('settings.page.saved'))
        observe(page,'saved-setting')
        assert sum(e['method']=='PUT' for e in page.events())==before+1

    with page.check('Category keyboard selection and focus observation'):
        selected=page.one('[role=tab][aria-selected=true]')
        old=selected.get_attribute('id')
        selected.send_keys(Keys.ARROW_RIGHT)
        page.wait.until(lambda _:page.driver.switch_to.active_element.get_attribute('id')!=old)
        press(page,Keys.ENTER)
        page.wait.until(lambda _:page.driver.switch_to.active_element.get_attribute('aria-selected')=='true')
        observe(page,'category-enter',screenshot=True)

    with page.check('Email dialog forward/reverse traversal, validation and close focus'):
        page.tab('email')
        opener=page.button(page.t('settings.email_test.action'))
        opener.send_keys(Keys.ENTER)
        dialog=page.one('[role=dialog]')
        observe(page,'email-open',screenshot=True)
        recipient=page.field(page.t('settings.email_test.recipient'))
        # Start from the input with a genuine key. Observe the boundary rather
        # than inventing a focus-trap requirement: existing browsers can leave
        # document focus after the final dialog control (activeElement=BODY).
        recipient.send_keys(Keys.ARROW_LEFT)
        for index in range(4):
            press(page,Keys.TAB)
            observe(page,'email-tab-'+str(index),screenshot=True)
            if index < 2:
                key='settings.email_test.close' if index==0 else 'settings.email_test.send'
                assert page.driver.switch_to.active_element==page.button(page.t(key),dialog)
        for index in range(4):
            press(page,Keys.TAB,reverse=True)
            observe(page,'email-reverse-tab-'+str(index),screenshot=True)
        page.button(page.t('settings.email_test.send'),dialog).send_keys(Keys.ENTER)
        page.see(page.t('settings.email_test.invalid_recipient'))
        observe(page,'email-invalid-recipient',screenshot=True)
        page.close_dialog()
        page.wait.until(lambda _:page.button(page.t('settings.email_test.action')).is_enabled())
        observe(page,'email-escape-return',screenshot=True)
        press(page,Keys.TAB)
        observe(page,'email-next-tab',screenshot=True)

    with page.check('Classification dialog keyboard order and close focus'):
        page.tab('disposition')
        box=page.setting_box('DISPOSITION_CLASSIFICATION_SCHEME_ID')
        page.button(page.t('settings.action.browse'),box).send_keys(Keys.ENTER)
        page.one('.application-settings-browser')
        observe(page,'browse-open',screenshot=True)
        press(page,Keys.TAB)
        row=observe(page,'browse-tab',screenshot=True)
        assert row['inDialog'] and row['visible']
        previous=page.driver.switch_to.active_element
        press(page,Keys.TAB)
        observe(page,'browse-next-tab',screenshot=True)
        press(page,Keys.TAB,reverse=True)
        observe(page,'browse-reverse-tab')
        assert page.driver.switch_to.active_element==previous
        page.close_dialog()
        observe(page,'browse-escape-return',screenshot=True)

    with page.check('Breadcrumb, custody and audit navigation focus baseline'):
        page.drawer('dashboard');page.settings();page.tab('general')
        observe(page,'drawer-return',screenshot=True)
        page.drawer('dashboard')
        label=page.t('navigation.item.application_settings')
        crumbs=lambda:[e for e in page.visible('button.max-w-52') if label in e.text]
        page.wait.until(lambda _:crumbs())
        crumbs()[-1].send_keys(Keys.ENTER)
        page.field(window)
        observe(page,'breadcrumb-return',screenshot=True)
        press(page,Keys.TAB)
        observe(page,'breadcrumb-next-tab',screenshot=True)
        page.drawer('governance_custody')
        page.button(page.t('settings.custody.open')).send_keys(Keys.ENTER)
        page.wait.until(lambda _:page.t('settings.category.disposition') in page.one('[role=tab][aria-selected=true]').text)
        observe(page,'custody-return',screenshot=True)
        page.drawer('audit_trail')
        label=page.t('webui.render_event_timeline.tooltip.open_current_entity_208e2a65')
        links=lambda:[e for e in page.visible('button[aria-label]') if plain(e.get_attribute('aria-label'))==label]
        page.wait.until(lambda _:links())
        links()[0].send_keys(Keys.ENTER)
        page.field(window)
        observe(page,'audit-return',screenshot=True)
        press(page,Keys.TAB)
        observe(page,'audit-next-tab',screenshot=True)
        assert not [e for e in page.events() if e['path']=='/api/v1/application-settings/test-send']
