"""Safe, specific bilingual medium validation using real NiceGUI controls."""
import pytest
from nicegui import ui
from frontend.webui.app import clear_medium_error, error_message, highlight_medium_error
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain
from frontend.webui.tests.test_disposition_tasks import host


@pytest.mark.parametrize('code,key,field_error', [
    ('aggregation_medium_contents_conflict', 'contents_conflict', True),
    ('aggregation_medium_mismatch', 'parent_conflict', True),
    ('record_medium_not_allowed_by_parent', 'record_parent_conflict', True),
    ('medium_change_reason_required', 'reason_required', False),
    ('physical_record_has_digital_components', 'components_present', True),
])
def test_medium_error_is_specific_localized_and_marks_only_relevant_field(host, code, key, field_error):
    with host:
        control = ui.select(['digital', 'mixed'], value='digital')
        error = ApiError(422, {'code': code, 'message': 'Internal SQL and private identifiers'})
        expected = render_message_plain('resource_medium.error.' + key)
        assert error_message(error) == expected
        highlight_medium_error(error, control)
        assert bool(control.props.get('error')) == field_error
        if field_error:
            assert control.props['error-message'] == expected
        assert control.value == 'digital'


def test_unknown_error_never_displays_internal_details_or_marks_medium(host):
    with host:
        control = ui.select(['digital'], value='digital')
        error = ApiError(422, {'code': 'unknown', 'message': 'Secret database details'})
        assert 'Secret' not in error_message(error)
        highlight_medium_error(error, control)
        assert not control.props.get('error')


def test_repeated_medium_changes_keep_nicegui_validation_state_intact(host):
    with host:
        control = ui.select(['digital', 'physical', 'mixed'], value='digital')
        control.on_value_change(lambda _: clear_medium_error(control))
        error = ApiError(422, {'code': 'aggregation_medium_contents_conflict'})
        for target in ['physical', 'mixed', 'digital', 'mixed']:
            highlight_medium_error(error, control)
            control.value = target
            assert 'error' in control.props
            assert not control.props['error']
            assert not control.props.get('error-message')
            assert control.error is None
