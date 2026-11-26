"""Real-browser create/reopen stress, restricted to the owning disposable runner."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
import json
import os
from pathlib import Path
import threading
import time

from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.support import expected_conditions as EC

from tools.check_webui_browser import Acceptance, create_driver, plain


DEPTHS = (0, 1, 2, 5, 10)


def check_translation_stress(host):
    assert 'dbname=erms_webui_test_' in os.environ.get('DATABASE_URL', '')
    total = host.args.translation_cycles
    workers = min(host.args.translation_workers, total)
    stop = threading.Event()
    lock = threading.Lock()
    driver_lock = threading.Lock()
    event_lock = threading.Lock()
    started = time.monotonic()
    progress = {'requested': total, 'completed': 0, 'failures': [], 'navigation_retries': [], 'depths': {}, 'workers': {},
                'title_only': 0, 'title_and_description': 0, 'immediate_switches': 0, 'waited_switches': 0}
    active_drivers = []

    def record(worker, depth, cycle):
        with lock:
            progress['completed'] += 1
            progress['depths'][str(depth)] = progress['depths'].get(str(depth), 0) + 1
            progress['workers'][str(worker)] = cycle + 1
            progress['title_only' if cycle % 2 == 0 else 'title_and_description'] += 1
            progress['immediate_switches' if cycle % 3 == 0 else 'waited_switches'] += 1
            progress['seconds'] = round(time.monotonic() - started, 2)
            target = host.args.output / 'translation-stress-progress.json'
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(progress, indent=2) + '\n')
            temporary.replace(target)
            if progress['completed'] % 25 == 0:
                print('UI translation cycles ' + str(progress['completed']) + '/' + str(total), flush=True)

    def worker_run(worker, count):
        directory = host.args.output / ('worker-' + str(worker))
        directory.mkdir()
        args = copy(host.args)
        args.output = directory
        driver = None
        page = None
        stage = 'start'
        code = None
        try:
            # Selenium Manager updates one local driver-metadata file. Serialize
            # startup only; the browser UI journeys still run concurrently.
            with driver_lock:
                driver = create_driver(args.browser, directory)
            with lock:
                active_drivers.append(driver)
            page = Acceptance(driver, args)
            def shared_events(filename='requests.jsonl'):
                with event_lock:
                    return list(host.events(filename))
            page.events = shared_events
            driver.set_window_size(1440, 1100)
            driver.get(args.url + '/')
            page.login()

            def navigation_panel(phase):
                def loaded(_):
                    panels = page.visible('.classification-actions-panel')
                    if panels:
                        return panels[0]
                    if page.t('common.error.service_unavailable') in page.text():
                        return 'retry'
                    return False
                panel = page.wait.until(loaded)
                if panel != 'retry':
                    return panel
                # This is preparation/navigation outside the translation dialog.
                # Record the visible error and use the existing Retry action once.
                # Never retry or relax an Arabic-field assertion.
                entry = {'worker': worker, 'code': code, 'phase': phase,
                         'seconds': round(time.monotonic() - started, 2)}
                with lock:
                    progress['navigation_retries'].append(entry)
                    retry_index = len(progress['navigation_retries'])
                page.capture('navigation-unavailable-' + str(retry_index))
                page.click(page.t('classification_browser.retry'))
                return page.one('.classification-actions-panel')

            def create(resource, payload):
                response = page.api.post('/api/v1/' + resource, json=payload)
                response.raise_for_status()
                return response.json()

            scheme_code = 'DEMO' if worker == 0 else 'DEMO-STRESS-W' + str(worker)
            scheme = create('classification-schemes', {'code': scheme_code, 'title': 'Demo Classification Scheme' if worker == 0 else scheme_code})
            scheme_label = scheme_code + ' — ' + scheme['title']
            chain = []
            parent = None
            for depth in range(max(DEPTHS)):
                parent = create('classifications', {
                    'classification_scheme_id': scheme['id'],
                    'parent_classification_id': parent['id'] if parent else None,
                    'code': 'P' + str(depth).zfill(2), 'title': 'Parent ' + str(depth),
                })
                chain.append(parent)

            def select_parent(depth):
                page.drawer('classification_schemes')
                page.see(page.t('webui.render_workspace_right.label.classification_tree_69593539'))
                label = page.t('webui.select_classification_workspace.input.filter_schemes_a7f4591e')
                query = page.field(label)
                page.select_field_text(query)
                query.send_keys(scheme_code, Keys.ENTER)
                if depth == 0:
                    page.activate(page.one('button.classification-node-button', scheme_label))
                else:
                    labels = [scheme_label] + [
                        item['code'] + ' — ' + item['title'] for item in chain[:depth]
                    ]
                    for text in labels[:-1]:
                        def expand_node(_):
                            node = page.one('button.classification-node-button', text)
                            row = node.find_element('xpath', '../..')
                            collapsed = [button for button in row.find_elements('css selector', 'button')
                                         if any(icon.text.strip() == 'chevron_right'
                                                for icon in button.find_elements('css selector', '.q-icon'))]
                            if collapsed:
                                page.activate(collapsed[0])
                            return True
                        page.wait.until(expand_node)
                    page.activate(page.one('button.classification-node-button', labels[-1]))
                navigation_panel('open hierarchy parent')

            def translation_field(dialog, key):
                return page.wait.until(lambda _: next((
                    field.find_element('css selector', 'input,textarea')
                    for field in page.visible('.q-expansion-item .q-field', dialog)
                    if any(plain(label.text) == page.t(key)
                           for label in field.find_elements('css selector', '.q-field__label'))
                ), None))

            def expand(dialog):
                stable_click(page.one('.q-expansion-item .q-item__label',
                                      page.t('entity_translation_editor.expansion.title'), scope=dialog))

            def stable_click(element):
                # QDialog enters with a geometry animation. Inspect the hit
                # target and settled bounds before issuing a native click.
                driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});", element)
                previous = [None]
                def ready(_):
                    observed = driver.execute_script("""
                        const e=arguments[0], r=e.getBoundingClientRect();
                        const top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                        return {rect:[r.x,r.y,r.width,r.height].map(Math.round),hit:top===e||e.contains(top)};
                    """, element)
                    settled = observed['rect'] == previous[0]
                    previous[0] = observed['rect']
                    if settled and observed['hit']:
                        try:
                            element.click()
                            return True
                        except ElementClickInterceptedException:
                            previous[0] = None
                    return False
                page.wait.until(ready)

            def language(dialog, tag):
                stable_click(translation_field(dialog, 'webui.open_editor.select.language_a1337600'))
                stable_click(page.one('[role=option]', 'English · English' if tag == 'en' else 'العربية · Arabic'))

            previous_depth = None
            for cycle in range(count):
                if stop.is_set():
                    break
                depth = DEPTHS[min(len(DEPTHS) - 1, cycle * len(DEPTHS) // count)]
                if depth != previous_depth:
                    stage = 'select hierarchy parent'
                    select_parent(depth)
                    previous_depth = depth
                if worker % 2 and cycle % 50 == 0:
                    stage = 'browser reload'
                    page.reload()
                    # reload() observes the test hooks before authentication
                    # and route restoration finish. Clicking the drawer then
                    # can abandon auth/me. Wait for the authenticated route.
                    page.wait.until(lambda _: driver.execute_script(
                        'return window.socket?.connected && window.did_handshake'))
                    navigation_panel('restored parent after browser reload')
                parent_label = scheme_label if depth == 0 else (
                    chain[depth - 1]['code'] + ' — ' + chain[depth - 1]['title'])
                code = 'DEMO-2000' if worker == 0 and cycle == 0 else 'T' + str(worker) + '-' + str(cycle).zfill(5)
                expected = 'عرض توضيحي 2000' if worker == 0 and cycle == 0 else 'عرض توضيحي ' + str(worker) + '-' + str(cycle)
                description = 'وصف ' + str(cycle) if cycle % 2 else ''
                stage = 'create'
                old_panel = page.one('.classification-actions-panel')
                page.click(page.t('classification_browser.add_root' if depth == 0 else 'classification_browser.add_child'), old_panel)
                dialog = page.one('.q-dialog__inner > .q-card')
                page.field(page.t('entity_metadata.field.code') + ' *').send_keys(code)
                page.field(page.t('entity_metadata.field.title') + ' *').send_keys('Demo 2000' if code == 'DEMO-2000' else 'Demo ' + code)
                expand(dialog)
                language(dialog, 'ar')
                title = translation_field(dialog, 'entity_translation_editor.input.title')
                page.wait.until(lambda _: title.is_enabled())
                title.send_keys(expected)
                if description:
                    translation_field(dialog, 'entity_translation_editor.input.description').send_keys(description)
                page.click(page.t('webui.open_editor.button.save_46081ed6'), dialog)
                page.wait.until(lambda _: not page.visible('.q-dialog__inner > .q-card'))
                page.wait.until(EC.staleness_of(old_panel))
                navigation_panel('created item details')
                page.see(code)
                stage = 'reopen'
                page.click(page.t('webui.render_workspace_right.button.edit_a536c992'), page.one('.classification-actions-panel'))
                dialog = page.one('.q-dialog__inner > .q-card')
                expand(dialog)
                language(dialog, 'en')
                title = translation_field(dialog, 'entity_translation_editor.input.title')
                if cycle % 3:
                    page.wait.until(lambda _: title.is_enabled() and title.get_attribute('value') == '')
                stage = 'English to Arabic'
                language(dialog, 'ar')
                page.wait.until(lambda _: title.is_enabled() and title.get_attribute('value') == expected)
                assert translation_field(dialog, 'entity_translation_editor.input.description').get_attribute('value') == description
                if cycle % 100 == 0:
                    page.capture('visible-arabic-depth-' + str(depth) + '-cycle-' + str(cycle))
                page.click(page.t('webui.open_editor.button.cancel_c07bff03'), dialog)
                page.wait.until(lambda _: not page.visible('.q-dialog__inner > .q-card'))
                stage = 'return to parent'
                child_panel = page.one('.classification-actions-panel')
                # The identity card has one link to each actual ancestor.
                # Navigation history can legitimately contain the same parent
                # more than once after a reload; it is not a hierarchy selector.
                page.activate(page.one('button.classification-node-button', parent_label))
                page.wait.until(EC.staleness_of(child_panel))
                navigation_panel('return to parent')
                record(worker, depth, cycle)
        except Exception as error:
            stop.set()
            if page is not None:
                details = {'worker': worker, 'code': code, 'stage': stage, 'error': str(error)}
                try:
                    page.capture('failure')
                    details['visible_fields'] = driver.execute_script(
                        "return Array.from(document.querySelectorAll('.q-dialog input,.q-dialog textarea')).map(e=>({value:e.value,disabled:e.disabled}));")
                    response = page.api.post('/api/v1/classifications/search', json={
                        'where': {'field': 'code', 'operator': 'eq', 'value': code or ''}, 'limit': 1,
                    })
                    details['stored'] = response.json()
                except Exception as diagnostic_error:
                    details['diagnostic_error'] = str(diagnostic_error)
                with lock:
                    progress['failures'].append(details)
                (directory / 'failure.json').write_text(json.dumps(details, ensure_ascii=False, indent=2) + '\n')
            raise
        finally:
            if page is not None:
                page.api.close()
            if driver is not None:
                try:
                    driver.quit()
                finally:
                    with lock:
                        if driver in active_drivers:
                            active_drivers.remove(driver)

    try:
        with host.check(str(total) + ' real UI creation/reopen cycles at depths ' + str(DEPTHS)):
            executor = ThreadPoolExecutor(max_workers=workers)
            try:
                futures = [executor.submit(worker_run, worker, total // workers + int(worker < total % workers))
                           for worker in range(workers)]
                for future in as_completed(futures):
                    future.result()
            except BaseException:
                stop.set()
                with lock:
                    drivers = list(active_drivers)
                for driver in drivers:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                raise
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            assert progress['completed'] == total
    finally:
        progress['seconds'] = round(time.monotonic() - started, 2)
        (host.args.output / 'translation-stress-results.json').write_text(json.dumps(progress, ensure_ascii=False, indent=2) + '\n')
