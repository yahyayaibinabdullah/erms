"""Verify complete collection paging against a disposable database."""
import subprocess
from urllib.parse import parse_qs

from selenium.webdriver.common.keys import Keys

from tools.check_webui_browser import plain


def seed(page):
    subprocess.run([page.args.api_python, '-c', '''
import psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url()) as c:
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    c.execute("SET CONSTRAINTS ALL IMMEDIATE")
    parent, classification, unit = c.execute(
        "SELECT id,classification_id,owning_org_unit_id FROM aggregations WHERE aggregation_number='TEST-AGG'"
    ).fetchone()
    c.execute("""
        INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,medium,date_opened)
        SELECT 'PAGING-AGG-'||lpad(i::text,3,'0'),'Paging aggregation '||i,%s,%s,'physical','2026-01-01'
        FROM generate_series(0,102) i
    """, (classification, unit))
    c.execute("""
        INSERT INTO records(aggregation_id,record_number,title,medium,date_originated)
        SELECT %s,'PAGING-REC-'||lpad(i::text,3,'0'),'Paging record '||i,'physical','2026-01-01'
        FROM generate_series(0,102) i
    """, (parent,))
    # Emulate historical unclassified roots. Current creation rules reject them.
    c.execute("ALTER TABLE aggregations DROP CONSTRAINT aggregations_root_classification_consistent")
    c.execute("ALTER TABLE aggregations DISABLE TRIGGER aggregations_validate_classification")
    c.execute("""
        INSERT INTO aggregations(aggregation_number,title,owning_org_unit_id,medium,date_opened)
        SELECT 'PAGING-ROOT-'||lpad(i::text,3,'0'),'Historical unclassified root '||i,%s,'physical','2026-01-01'
        FROM generate_series(0,102) i
    """, (unit,))
    c.execute("ALTER TABLE aggregations ENABLE TRIGGER aggregations_validate_classification")
    c.execute("""
        WITH fixture_roles AS (
            INSERT INTO roles(code,name,profile_id,security_level_id,org_unit_id)
            SELECT 'PAGING-ROLE-'||lpad(i::text,3,'0'),'Paging role '||lpad(i::text,3,'0'),
                   r.profile_id,r.security_level_id,%s
            FROM roles r CROSS JOIN generate_series(0,52) i WHERE r.code='admin'
            RETURNING id
        )
        INSERT INTO user_role_assignments(user_id,role_id,valid_from)
        SELECT u.id,r.id,'2026-01-01' FROM fixture_roles r
        CROSS JOIN users u WHERE u.email='viewer@test.invalid'
    """, (unit,))
'''], check=True, timeout=45)


def check_collection_paging(page):
    seed(page)
    summary = 'webui.render_results.text.showing_value_value_2_of_row_count_results_3d5b1825'
    primary = 'webui.index.input.search_by_number_title_or_description_e21ed520'
    last = 'webui.render_entity_compact_results.accessible_name.last_page_9a6fde18'
    filter_key = 'webui.render_entity_compact_results.input.filter_results_bb36c793'
    assignment_range = 'webui.render_assignment_cards.text.start_end_of_row_count_f306a12a'

    def see_range(start, end, total):
        page.see(page.t(summary).format(value=start, value_2=end, row_count=total))

    def page_click(key):
        page.button(page.t(key)).send_keys(Keys.ENTER)

    def search(resource, query):
        page.drawer(resource)
        page.wait.until(lambda _:len(page.visible('.dashboard-personal-panel'))==2)
        page.fill(page.t(primary), query)
        page.field(page.t(primary)).send_keys(Keys.ENTER)

    for language in ('en', 'ar'):
        if page.language != language:
            page.settings()
            page.language_change(language)
        for resource, prefix in (('records', 'PAGING-REC-'), ('aggregations', 'PAGING-AGG-')):
            with page.check(f'{resource} search reaches matches after 100'):
                search(resource, prefix)
                see_range(1, 10, 103)
                page.fill(page.t(primary), 'Unsubmitted primary search')
                page_click(last)
                see_range(101, 103, 103)
                page.see(prefix + '102')
                assert page.field(page.t(primary)).get_attribute('value') == 'Unsubmitted primary search'
                open_label, detail_header, back = (
                    ('Open record', '.record-detail-header-actions', 'webui.select_record_details.button.back_f6cea7ff')
                    if resource == 'records' else
                    ('Open aggregation', '.aggregation-detail-header-actions', 'webui.open_aggregation.button.back_4d496e53')
                )
                row = page.wait.until(lambda _:next((item for item in page.visible('.compact-result-item')
                                                    if prefix + '102' in plain(item.text)), False))
                page.one(f'button[aria-label="{open_label}"]',scope=row).send_keys(Keys.ENTER)
                header = page.one(detail_header)
                back_button = page.wait.until(lambda _:next((
                    button for button in page.visible('button',header) if page.t(back) in plain(button.text)
                ), False))
                back_button.send_keys(Keys.ENTER)
                see_range(101, 103, 103)
                assert page.field(page.t(primary)).get_attribute('value') == 'Unsubmitted primary search'
                page.capture(f'{resource}-beyond-100-{language}')
                page.fill(page.t(filter_key), prefix + '102')
                see_range(1, 1, 1)
                page.see(prefix + '102')
                page.errors()

        with page.check('user role assignments reach assignments after 50'):
            page.drawer('users')
            card = page.wait.until(lambda _:next((row for row in page.visible('.governance-list-card')
                                                if 'viewer@test.invalid' in plain(row.text)), False))
            button = next(b for b in page.visible('button', card) if b.text == 'open_in_new')
            page.activate(button)
            label = page.t(assignment_range)
            page.see(label.format(start=1, end=5, row_count=53))
            for offset in range(5, 51, 5):
                started = len(page.events())
                displayed_range = label.format(start=offset-4, end=offset, row_count=53)
                next_label = page.t('webui.select_user_details.button.next_8ec4fd0d')
                following = page.wait.until(lambda _:next((
                    b for b in page.visible('main button')
                    if plain(b.text).endswith(next_label)
                    and displayed_range in plain(b.find_element('xpath','..').text)
                ), False))
                following.send_keys(Keys.ENTER)
                page.see(label.format(start=offset+1, end=min(offset+5, 53), row_count=53))
                reads = [e for e in page.events()[started:] if e['path'].endswith('/roles') and e['method']=='GET']
                assert len(reads) == 1 and parse_qs(reads[0]['query']) == {'limit':['5'], 'offset':[str(offset)]}
            page.see('PAGING-ROLE-052')
            page.capture('role-assignments-beyond-50-'+language)
            page.fill(page.t('webui.select_user_details.input.filter_role_name_or_code_e534534c'), 'PAGING-ROLE-052')
            page.see(label.format(start=1, end=1, row_count=1))
            page.see('PAGING-ROLE-052')
            page.errors()

        with page.check('dashboard unclassified roots reach matches after 100'):
            page.drawer('dashboard')
            label = page.t('webui.load_dashboard.label.unclassified_root_aggregations_efcbac0c')
            page.see(label)
            card = page.wait.until(lambda _:next((e for e in page.visible('.q-card.cursor-pointer') if label in plain(e.text)), False))
            page.activate(card)
            see_range(1, 10, 103)
            page_click(last)
            see_range(101, 103, 103)
            page.see('PAGING-ROOT-102')
            page.capture('dashboard-unclassified-beyond-100-'+language)
            page.errors()
