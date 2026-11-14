"""Direct coordinator tests; assertions established against the original host."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from frontend.webui.api_client import ApiError


def host():
    h = {
        'navigation_state': {'trail': [{'page': 'dashboard'}, {'page': 'records'}, {'page': 'application-settings'}], 'restoring': False},
        'state': {}, 'persist_navigation_trail': Mock(),
        'restore_navigation_entry': AsyncMock(), 'select_dashboard': AsyncMock(),
        'render_navigation_breadcrumbs': Mock(), 'ui': SimpleNamespace(notify=Mock()),
        'render_message': lambda key: key, 'error_message': str,
        'api': SimpleNamespace(cancel_pending_reads=Mock()),
    }
    from frontend.webui.navigation_controller import NavigationController
    controller = NavigationController(
        stored=h['navigation_state']['trail'],
        write_trail=lambda trail: h['persist_navigation_trail'](),
        prepare=Mock(), snapshot=Mock(), label_key=lambda page: None,
        get_guard=lambda: h['state'].get('discard_navigation_guard'),
        clear_guard=lambda: h['state'].pop('discard_navigation_guard', None),
        cancel_reads=h['api'].cancel_pending_reads,
        restore=h['restore_navigation_entry'], dashboard=h['select_dashboard'],
        render=h['render_navigation_breadcrumbs'], notify=h['ui'].notify, on_error=str,
    )
    h['controller'] = controller
    for name in ('navigate_to_breadcrumb', 'breadcrumb_back', 'guarded_page_navigation'):
        h[name] = getattr(controller, name)
    return h


@pytest.mark.parametrize('index', [-1, 3])
async def test_out_of_range_breadcrumb_has_no_effect(index):
    h = host()
    await h['navigate_to_breadcrumb'](index)
    h['persist_navigation_trail'].assert_not_called()
    h['restore_navigation_entry'].assert_not_awaited()


async def test_cancelled_breadcrumb_retains_trail_and_guard():
    h = host(); guard = AsyncMock(return_value=False)
    h['state']['discard_navigation_guard'] = guard
    await h['navigate_to_breadcrumb'](0)
    assert len(h['controller'].trail) == 3
    assert h['state']['discard_navigation_guard'] is guard
    h['persist_navigation_trail'].assert_not_called()
    h['restore_navigation_entry'].assert_not_awaited()


async def test_breadcrumb_truncates_before_restore_and_resets_restoring_afterwards():
    h = host(); guard = AsyncMock(return_value=True)
    h['state']['discard_navigation_guard'] = guard

    async def restore(entry):
        assert h['controller'].restoring
        assert h['controller'].trail == [{'page': 'dashboard'}, {'page': 'records'}]
        assert entry == {'page': 'records'}
        h['persist_navigation_trail'].assert_called_once()

    h['restore_navigation_entry'].side_effect = restore
    await h['navigate_to_breadcrumb'](1)
    assert 'discard_navigation_guard' not in h['state']
    assert not h['controller'].restoring
    h['render_navigation_breadcrumbs'].assert_called_once()


@pytest.mark.parametrize('status', [403, 404])
@pytest.mark.parametrize('index', [0, 1])
async def test_unavailable_target_is_removed_and_uses_existing_fallback(status, index):
    h = host()
    h['restore_navigation_entry'].side_effect = [ApiError(status, 'unavailable'), None]
    await h['navigate_to_breadcrumb'](index)
    assert h['controller'].trail == ([{'page': 'dashboard'}] if index else [])
    if index:
        assert h['restore_navigation_entry'].await_count == 2
        h['restore_navigation_entry'].assert_awaited_with({'page': 'dashboard'})
        h['select_dashboard'].assert_not_awaited()
    else:
        h['select_dashboard'].assert_awaited_once()
    assert h['ui'].notify.call_args.kwargs['color'] == 'warning'
    assert not h['controller'].restoring


async def test_other_api_failure_keeps_target_and_reports_error():
    h = host(); h['restore_navigation_entry'].side_effect = ApiError(503, 'offline')
    await h['navigate_to_breadcrumb'](1)
    assert h['controller'].trail[-1] == {'page': 'records'}
    h['select_dashboard'].assert_not_awaited()
    assert h['ui'].notify.call_args.kwargs['color'] == 'negative'
    assert not h['controller'].restoring


async def test_unexpected_restore_failure_still_clears_restoring_flag():
    h = host(); h['restore_navigation_entry'].side_effect = RuntimeError('fixture')
    with pytest.raises(RuntimeError, match='fixture'):
        await h['navigate_to_breadcrumb'](1)
    assert not h['controller'].restoring
    h['render_navigation_breadcrumbs'].assert_called_once()


@pytest.mark.parametrize('allowed', [True, False])
async def test_guard_cancels_reads_only_after_permission_to_leave(allowed):
    h = host(); guard = AsyncMock(return_value=allowed); action = AsyncMock()
    h['state']['discard_navigation_guard'] = guard
    await h['guarded_page_navigation'](action)
    assert action.await_count == int(allowed)
    assert h['api'].cancel_pending_reads.call_count == int(allowed)
    assert ('discard_navigation_guard' in h['state']) is not allowed


@pytest.mark.parametrize('fallback_async', [True, False])
async def test_in_app_back_uses_existing_previous_visit_or_fallback(fallback_async):
    h = host(); fallback = AsyncMock() if fallback_async else Mock()
    await h['breadcrumb_back'](fallback)
    h['restore_navigation_entry'].assert_awaited_once_with({'page': 'records'})
    fallback.assert_not_called()
    h['controller'].trail = [{'page': 'dashboard'}]
    await h['breadcrumb_back'](fallback)
    fallback.assert_called_once()
