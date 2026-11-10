"""Existing shell behavior, measured before and after presentation extraction."""
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


def viewport(page, width, height):
    current = page.driver.execute_script('return [innerWidth,innerHeight]')
    outer = page.driver.get_window_size()
    page.driver.set_window_size(outer['width'] + width - current[0], outer['height'] + height - current[1])
    page.wait.until(lambda _: page.driver.execute_script('return [innerWidth,innerHeight]') == [width, height])


def record_resize_notifications(page):
    # Observed before shell extraction, during native viewport changes. Retain
    # these explicitly; no other browser error is allowed by this exception.
    errors = page.driver.execute_script('return window.__webuiTestErrors || []')
    known = [e for e in errors if e.get('kind') == 'error'
             and e.get('eventType') == 'ErrorEvent'
             and e.get('message') == 'ResizeObserver loop completed with undelivered notifications.'
             and e.get('filename') == page.args.url + '/']
    page.report.setdefault('baseline_resize_notifications', []).extend(known)
    unexpected = [e for e in errors if e not in known]
    page.report.setdefault('browser_errors', []).extend(unexpected)
    assert not unexpected, unexpected
    page.driver.execute_script('window.__webuiTestErrors=[]')


def dismiss_drawer(page):
    backdrop = page.one('.q-drawer__backdrop')
    offset = 150 if page.language == 'en' else -150
    ActionChains(page.driver).move_to_element_with_offset(backdrop, offset, 0).click().perform()


def observe(page, name):
    # Measure the real DOM. Do not hide the canvas, restyle or change focus.
    last = [None]
    def settled(_):
        boxes = page.driver.execute_script("return [...document.querySelectorAll('header,.erms-drawer,.erms-breadcrumb-row,footer')].map(e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})")
        stable = boxes == last[0]
        last[0] = boxes
        return stable
    page.wait.until(settled)
    data = page.driver.execute_script('''return {
      direction: document.documentElement.dir,
      elements: [...document.querySelectorAll('header, .erms-brand, .erms-global-search-wrap, .erms-drawer, .erms-breadcrumb-row, footer')].map(e => {
        const r=e.getBoundingClientRect(), s=getComputedStyle(e);
        return {tag:e.tagName, classes:e.className, box:[r.x,r.y,r.width,r.height].map(x=>Math.round(x*100)/100),
                direction:s.direction, display:s.display, font:s.fontFamily, color:s.color};
      }),
      focus: {tag:document.activeElement.tagName, label:document.activeElement.getAttribute('aria-label'),
              text:document.activeElement.innerText || ''}
    }''')
    page.report.setdefault('shell_observations', []).append({'name':name, 'language':page.language, **data})
    page.capture('shell-' + name + '-' + page.language)


def check_shell(page):
    with page.check('shell expanded desktop and breadcrumb overflow'):
        viewport(page, 1440, 1000)
        for _ in range(3):
            page.drawer('dashboard')
            page.one('.dashboard-overview-primary')
            page.settings()
        row = page.one('.erms-breadcrumb-row')
        assert page.visible('button', row)
        assert len(page.visible('[aria-current=page]', row)) == 1
        more = page.one('button[aria-label$="hidden navigation entries"]', scope=row)
        observe(page, 'expanded')
        page.activate(more)
        page.one('.q-menu')
        observe(page, 'overflow')
        page.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
        page.wait.until(lambda _: not page.visible('.q-menu'))

    with page.check('desktop collapse and expand preserve current page and history'):
        url = page.driver.current_url
        history = page.driver.execute_script('return history.length')
        page.activate(page.one('.erms-drawer-toggle'))
        page.one('.erms-drawer--collapsed')
        # Icon ligatures remain text in WebDriver even though captions disappear.
        page.wait.until(lambda _: page.driver.execute_script('''return [...document.querySelectorAll('button.erms-nav-link')].every(e=>{
          const copy=e.cloneNode(true); copy.querySelectorAll('i,.q-tooltip').forEach(n=>n.remove());
          return !copy.textContent.trim();
        })'''))
        observe(page, 'collapsed')
        page.activate(page.one('.erms-drawer-toggle'))
        page.wait.until(lambda _: not page.visible('.erms-drawer--collapsed'))
        assert page.visible('.application-settings-page')
        assert page.driver.current_url == url and page.driver.execute_script('return history.length') == history

    with page.check('account menu and preferences keyboard return'):
        account = page.one('header button', 'account_circle')
        page.activate(account)
        page.one('.erms-profile-menu')
        observe(page, 'account-menu')
        page.click(page.t('preferences.heading.personal'))
        page.one('[role=dialog]')
        observe(page, 'preferences')
        page.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
        # Preferences is an existing persistent dialog: Escape leaves it open.
        page.one('.erms-preferences-dialog')
        page.button(page.t('preferences.action.cancel'), page.one('[role=dialog]')).send_keys(Keys.ENTER)
        page.wait.until(lambda _: not page.visible('[role=dialog]'))
        page.driver.switch_to.active_element.send_keys(Keys.TAB)
        observe(page, 'preferences-return')
        if page.visible('.q-menu'):
            page.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
            page.wait.until(lambda _: not page.visible('.q-menu'))

    with page.check('narrow viewport native drawer opens and closes'):
        # Headless desktop Chrome enforces a minimum window width. Use an actual
        # measured narrow viewport below the existing native drawer breakpoint.
        viewport(page, 600, 844)
        menu = page.one('header button', 'menu')
        # Resizing and the server-backed value update finish separately. Wait
        # for the measured drawer position and accessible state to agree and
        # remain stable across the resize transition. The NiceGUI class belongs
        # to the inner content, so do not assume native ancestor class names.
        previous, stable = [None], [0]
        def settled_drawer(_):
            position = page.driver.execute_script('''const r=document.querySelector('.erms-drawer').getBoundingClientRect();
              return [Math.round(r.left),Math.round(r.right),document.documentElement.clientWidth]''')
            expanded = menu.get_attribute('aria-expanded') == 'true'
            backdrop = bool(page.visible('.q-drawer__backdrop'))
            closed = position[1] <= 0 if page.language == 'en' else position[0] >= position[2]
            value = [position, expanded, backdrop]
            stable[0] = stable[0] + 1 if value == previous[0] else 0
            previous[0] = value
            return stable[0] >= 3 and expanded == backdrop and closed != expanded
        page.wait.until(settled_drawer)
        if page.visible('.q-drawer__backdrop'):
            dismiss_drawer(page)
        page.wait.until(lambda _: menu.get_attribute('aria-expanded') == 'false' and not page.visible('.q-drawer__backdrop'))
        observe(page, 'narrow-closed')
        page.activate(menu)
        page.wait.until(lambda _: menu.get_attribute('aria-expanded') == 'true')
        page.one('.erms-drawer')
        observe(page, 'narrow-open')
        # The open native drawer covers the header toggle at this width. Use
        # the visible backdrop on the opposite side, with a native pointer click.
        dismiss_drawer(page)
        page.wait.until(lambda _: menu.get_attribute('aria-expanded') == 'false')
        assert page.visible('.application-settings-page')
        viewport(page, 1440, 1000)
        # Resizing back does not reopen the existing drawer after backdrop
        # dismissal. Record that behavior, then reload for the next test scene.
        observe(page, 'wide-after-close')
        record_resize_notifications(page)
        page.reload()
        page.wait.until(lambda _: len(page.driver.find_elements('css selector', '[role=tab]')) == 7)
        page.wait.until(lambda _: page.visible('button.erms-nav-link'))


def check_restricted_shell(page):
    with page.check('restricted shell hides privileged links and diagnostics'):
        page.sign_out()
        page.login('viewer@test.invalid')
        assert len(page.visible('button.erms-nav-link')) == 2
        page.activate(page.one('header button', 'account_circle'))
        page.one('.erms-profile-menu')
        assert not page.visible('.erms-profile-diagnostics')
        observe(page, 'restricted-account')
