"""Session baselines against the real root and API in a disposable stack."""


def check_sessions(page):
    from tools.check_webui_browser import Acceptance, create_driver

    second_driver = create_driver(page.args.browser, page.args.output)
    second = None
    try:
        second = Acceptance(second_driver, page.args)
        with page.check('independent simultaneous clients retain identity and language'):
            second_driver.set_window_size(1440, 1100)
            second_driver.get(page.args.url + '/')
            second.login('viewer@test.invalid')
            page.language_change('ar')
            assert second_driver.execute_script('return document.documentElement.lang') == 'en'
            assert len(second.visible('button.erms-nav-link')) == 2
            assert page.visible('.application-settings-page')
            page.capture('session-admin-ar')
            second.capture('session-viewer-en')

        with page.check('disconnect and reconnect retain current page and restart unread reconciliation'):
            before = sum(e['path'] == '/api/v1/messages/unread-count' for e in page.events())
            page.driver.execute_script('window.socket.disconnect()')
            page.wait.until(lambda _: not page.driver.execute_script('return window.socket.connected'))
            page.driver.execute_script('window.socket.connect()')
            page.wait.until(lambda _: page.driver.execute_script('return window.socket.connected && window.did_handshake'))
            page.wait.until(lambda _: sum(e['path'] == '/api/v1/messages/unread-count' for e in page.events()) > before)
            assert page.visible('.application-settings-page')
            assert len(second.visible('button.erms-nav-link')) == 2

        with page.check('abandoned old-identity read cannot replace the next identity or affect another client'):
            page.control(path='/api/v1/application-settings', hold=True)
            started = len(page.events('requests-started.jsonl'))
            page.drawer('application_settings')
            page.wait.until(lambda _: any(e['controlled'] for e in page.events('requests-started.jsonl')[started:]))
            page.sign_out()
            page.login('viewer@test.invalid')
            finished = len(page.events())
            page.control()
            page.wait.until(lambda _: any(e['controlled'] and e['path']=='/api/v1/application-settings'
                                         for e in page.events()[finished:]))
            assert not page.visible('.application-settings-page')
            assert len(page.visible('button.erms-nav-link')) == 2
            second.reload()
            second.one('.dashboard-overview-primary')
            assert len(second.visible('button.erms-nav-link')) == 2
            second.errors()
            page.sign_out()
            assert page.visible('button.wathiq-login-submit')

        with page.check('administrator-issued temporary password requires replacement and can be abandoned'):
            created = page.api.post('/api/v1/users', json={
                'name': 'Disposable recovery person', 'email': 'recovery@test.invalid', 'account_type': 'person'})
            created.raise_for_status()
            issued = page.api.post(f"/api/v1/auth/users/{created.json()['id']}/temporary-password")
            issued.raise_for_status()
            temporary = issued.json()['temporary_password']

            def restricted_login():
                page.language = page.driver.execute_script('return document.documentElement.lang') or 'en'
                page.fill(page.t('webui.index.input.email_address_2569f0e9'), 'recovery@test.invalid')
                page.fill(page.t('webui.index.input.password_f76ddde6'), temporary)
                start = len(page.events())
                page.activate(page.one('button.wathiq-login-submit'))
                page.see(page.t('webui.show_change_password.label.set_a_new_password_f6a268ba'))
                assert not page.visible('button.erms-nav-link')
                assert not page.visible('.application-settings-page')
                # Forced sessions must not start ordinary workspace reads.
                assert not [e for e in page.events()[start:] if e['path'] in (
                    '/api/v1/dashboard/summary', '/api/v1/application-settings', '/api/v1/favourites')]

            restricted_login()
            page.capture('session-forced-password')
            page.click(page.t('webui.show_change_password.button.back_to_sign_in_a4e9c09d'))
            page.one('button.wathiq-login-submit')
            restricted_login()
            page.fill(page.t('webui.show_change_password.input.temporary_password_b83bc142'), temporary)
            page.fill(page.t('webui.show_change_password.input.new_password_28399c5b'), 'Changed-Test-Password-456!')
            page.fill(page.t('webui.show_change_password.input.confirm_new_password_abd1d774'), 'Changed-Test-Password-456!')
            page.click(page.t('webui.show_change_password.button.set_new_password_067753d1'))
            page.one('.dashboard-overview-primary')
            page.language = page.driver.execute_script('return document.documentElement.lang') or 'en'
            page.current_identity = 'recovery@test.invalid'
            page.capture('session-recovered')
            assert not page.visible('button.wathiq-login-submit')
            assert len(second.visible('button.erms-nav-link')) == 2

        with page.check('session journey has no unexpected browser or API failures'):
            page.errors(); second.errors()
            assert all((e['status'] is not None and e['status'] < 400) or
                       (e['controlled'] and e['path']=='/api/v1/application-settings' and e['status']==401)
                       for e in page.events())
        page.report['secondary_client_screenshots'] = second.report['screenshots']
    finally:
        if second is not None:
            second.api.close()
        second_driver.quit()
