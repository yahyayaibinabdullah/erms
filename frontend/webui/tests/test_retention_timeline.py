from datetime import date

import pytest

from frontend.webui.retention_timeline import disposition_dates


@pytest.mark.parametrize('closed,current,intermediate,expected', [
    ('2026-09-30T00:00:00Z', 2, 3, date(2031, 9, 30)),
    ('2024-02-29T00:00:00Z', 1, 0, date(2025, 2, 28)),
    ('2024-02-29T00:00:00Z', 1, 3, date(2028, 2, 29)),
    ('2026-09-30T22:00:00Z', 0, 0, date(2026, 10, 1)),
])
def test_calendar_years_in_working_timezone(closed, current, intermediate, expected):
    rule = dict(current_period_years=current, intermediate_period_years=intermediate)
    dates = disposition_dates(rule, {'date_closed': closed}, 'Asia/Dubai')
    assert dates[1] == expected


@pytest.mark.parametrize('root', [None, {}, {'date_closed': None}])
def test_no_date_for_open_or_unavailable_root(root):
    assert disposition_dates(dict(current_period_years=2, intermediate_period_years=3), root, 'UTC') is None


@pytest.mark.parametrize('period', [None, -1, '2', True])
def test_no_fabricated_date_for_invalid_period(period):
    assert disposition_dates(dict(current_period_years=period, intermediate_period_years=3),
                             {'date_closed': '2026-09-30T00:00:00Z'}, 'UTC') is None


from nicegui import ui
from frontend.webui.tests.test_disposition_tasks import host
from frontend.webui.retention_timeline import render_disposition_date
from frontend.webui.i18n_catalogue import render_message
from frontend.webui.locale_services import current_locale_context, format_local_date, format_instant
from frontend.webui.disposition.messages import status_label


@pytest.mark.parametrize('status', [2, 3, 4, 5, 6, 10])
def test_acceleration_keeps_normal_date_and_shows_current_status_and_literal_provenance(host, status):
    root = dict(date_closed='2026-10-22T05:33:04Z', disposition_status=status)
    acceleration = dict(occurred_at='2026-10-22T05:33:04Z', actor_name='Yahya يحيى', reason='<script>Literal reason</script>\nسبب استثنائي')
    rule = dict(current_period_years=2, intermediate_period_years=3, acceleration=acceleration)
    with host:
        language, zone = current_locale_context()
        render_disposition_date(rule, root, language, zone)
        labels = [e.text for e in host.descendants() if isinstance(e, ui.label)]
        assert render_message('webui.open_aggregation.retention.normal_disposition_date') in labels
        assert format_local_date(date(2031, 10, 22), language) in labels
        assert status_label(status) in labels
        assert render_message('webui.open_aggregation.retention.accelerated_on', date=format_instant(acceleration['occurred_at'], zone, language)) in labels
        assert any(acceleration['reason'] in label for label in labels)
        assert any(acceleration['actor_name'] in label for label in labels)
        assert not any(isinstance(e, ui.html) for e in host.descendants())


def test_ordinary_retention_has_no_acceleration_banner(host):
    with host:
        render_disposition_date(dict(current_period_years=2, intermediate_period_years=3), {'date_closed': '2026-10-22T05:33:04Z'}, *current_locale_context())
        labels = [e.text for e in host.descendants() if isinstance(e, ui.label)]
        assert render_message('webui.open_aggregation.retention.calculated_disposition_date') in labels
        assert render_message('webui.open_aggregation.retention.acceleration_effect') not in labels
