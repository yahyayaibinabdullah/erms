"""Existing navigation journeys shared by the disposable browser acceptance run."""
def check_navigation(page):
    with page.check('Settings breadcrumb preserves selected category'):
        page.settings()
        page.tab('disposition')
        page.drawer('dashboard')
        label=page.t('navigation.item.application_settings')
        def crumbs():
            return [button for button in page.visible('button.max-w-52') if label in button.text]
        page.wait.until(lambda _:crumbs())
        # The latest Settings breadcrumb is the visit immediately before this
        # Dashboard; earlier Settings visits may also remain in the trail.
        page.activate(crumbs()[-1])
        page.wait.until(lambda _: page.t('settings.category.disposition') in
                        page.one('[role=tab][aria-selected=true]').text)
        page.tab('general')

    with page.check('existing search URL restores query and empty results'):
        page.errors()
        page.driver.get(page.args.url + '/?q=zz_phase2_absent')
        page.see(page.t('webui.render_global_search_results.label.no_results_found_ab1c85dc'))
        assert page.driver.current_url.endswith('/?q=zz_phase2_absent')
        page.capture('search-empty-' + page.language)
        page.reload()
        page.see(page.t('webui.render_global_search_results.label.no_results_found_ab1c85dc'))
        assert page.driver.current_url.endswith('/?q=zz_phase2_absent')
        # Entering the existing root is an ordinary browser navigation.
        page.driver.get(page.args.url + '/')
        page.drawer('dashboard')

    with page.check('saved search keeps existing unsaved-change confirmation'):
        page.drawer('advanced_search')
        value_label = page.t('webui.render_condition.input.value_8dc59edc')
        page.click(page.t('webui.select_advanced_search.button.new_search_635c50cb'))
        page.wait.until(lambda _:page.visible('[role=dialog]') or page.field(value_label).get_attribute('value')=='')
        if page.visible('[role=dialog]'):
            page.click(page.t('webui.confirm_discard_changes.button.discard_changes_81df7dc9'),
                       page.one('[role=dialog]'))
        page.wait.until(lambda _:page.field(value_label).get_attribute('value')=='')
        page.fill(value_label, 'Test')
        page.click(page.t('webui.refresh_saved_actions.text.save_search_76b8ff5b'))
        dialog = page.one('[role=dialog]')
        page.fill(page.t('webui.save_search.input.name_76ae569a'),
                  'Disposable navigation ' + page.language)
        page.click(page.t('webui.save_search.button.save_53b01f94'), dialog)
        page.wait.until(lambda _: not page.visible('[role=dialog]'))
        page.fill(value_label, 'Changed draft')
        page.drawer('dashboard')
        dialog = page.one('[role=dialog]')
        page.see(page.t('webui.confirm_discard_changes.label.discard_unsaved_changes_8aacea70'))
        page.capture('unsaved-confirmation-' + page.language)
        page.click(page.t('webui.confirm_discard_changes.button.keep_editing_965cc0ca'), dialog)
        assert page.field(value_label).get_attribute('value') == 'Changed draft'
        page.drawer('dashboard')
        page.click(page.t('webui.confirm_discard_changes.button.discard_changes_81df7dc9'),
                   page.one('[role=dialog]'))
        page.wait.until(lambda _: not page.visible('.advanced-search-page'))

    with page.check('record parent aggregation stays visible after reload'):
        page.drawer('records')
        page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'), 'TEST-REC')
        page.click(page.t('webui.index.button.search_4d02b714'),page.one('.erms-card'))
        page.see('TEST-REC')
        page.capture('records-table-' + page.language)
        row = page.one('.compact-result-item')
        page.one('button[aria-label="Open record"]', scope=row).click()
        parent = page.one('button.detail-linked-entity')
        assert 'Test aggregation' in parent.text
        parent.click()
        heading = page.t('webui.open_aggregation.label.aggregation_overview_bb8398e3')
        page.see(heading)
        page.reload()
        page.see(heading)
        assert page.one('.erms-card').is_displayed()
        page.capture('aggregation-restored-' + page.language)
    with page.check('existing relationship types table renders with bounded results'):
        page.activate(page.one('button.erms-nav-link',page.t('relationships.ui.catalogue')))
        table=page.one('.erms-page-table')
        page.wait.until(lambda _:len(table.find_elements('css selector','tbody tr'))>0)
        assert len(table.find_elements('css selector','tbody tr'))<=25
        page.capture('relationship-types-table-'+page.language)
    page.settings()
    page.tab('general')
    page.driver.get(page.args.url + '/')
    page.wait.until(lambda _:len(page.driver.find_elements('css selector','[role=tab]'))==7)
