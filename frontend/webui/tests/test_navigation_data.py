"""Existing trail semantics, independent of UI rendering and persistence."""
from copy import deepcopy

import pytest

from frontend.webui.navigation_data import (
    NAVIGATION_TRAIL_LIMIT, NAVIGATION_VISIBLE_LIMIT,
    append_navigation_entry, navigation_entry_identity, visible_navigation_indices,
)


def test_identity_uses_page_and_optional_entity_not_label_or_snapshot():
    assert navigation_entry_identity({'page': 'dashboard'}) == ('dashboard', None)
    assert navigation_entry_identity({'page': 'record-details', 'entity_id': 7,
                                      'label': 'Old', 'state': {'searched': True}}) == ('record-details', 7)
    assert navigation_entry_identity({'page': 'disposition-job', 'entity_id': 7}) != navigation_entry_identity(
        {'page': 'disposition-task', 'entity_id': 7})


def test_duplicate_updates_supplied_fields_and_retains_unsupplied_metadata():
    trail = [{'page': 'record-details', 'entity_id': 7, 'label': 'Old',
              'accessible_label': 'Record seven', 'state': {'searched': True}}]
    before = deepcopy(trail)
    entry = {'page': 'record-details', 'entity_id': 7, 'label': 'Current', 'state': {'searched': False}}
    result = append_navigation_entry(trail, entry)
    assert result == [{**before[0], **entry}]
    assert trail == before
    assert result is not trail and result[0] is not trail[0] and result[0] is not entry


def test_returning_to_an_earlier_destination_appends_a_new_visit():
    trail = [{'page': 'dashboard'}, {'page': 'application-settings'}]
    assert append_navigation_entry(trail, {'page': 'dashboard'}) == [*trail, {'page': 'dashboard'}]


def test_different_entity_ids_remain_distinct_visits():
    trail = [{'page': 'record-details', 'entity_id': 7}]
    assert len(append_navigation_entry(trail, {'page': 'record-details', 'entity_id': 8})) == 2


def test_trail_limits_keep_latest_visits_without_modifying_input():
    trail = [{'page': 'record-details', 'entity_id': n} for n in range(23)]
    result = append_navigation_entry(trail, {'page': 'dashboard'})
    assert NAVIGATION_TRAIL_LIMIT == 20
    assert len(result) == 20 and result[0]['entity_id'] == 4 and result[-1]['page'] == 'dashboard'
    assert len(trail) == 23
    assert append_navigation_entry(trail, {'page': 'dashboard'}, limit=1) == [{'page': 'dashboard'}]


@pytest.mark.parametrize('length,visible,hidden', [
    (0, [], []), (1, [0], []), (5, [0, 1, 2, 3, 4], []),
    (6, [0, 2, 3, 4, 5], [1]), (9, [0, 5, 6, 7, 8], [1, 2, 3, 4]),
    (20, [0, 16, 17, 18, 19], list(range(1, 16))),
])
def test_visible_indices_cover_empty_boundary_and_overflow(length, visible, hidden):
    assert NAVIGATION_VISIBLE_LIMIT == 5
    assert visible_navigation_indices(length) == (visible, hidden)
    assert sorted(visible + hidden) == list(range(length))


def test_custom_visible_limit_preserves_first_and_recent_visits():
    assert visible_navigation_indices(9, limit=4) == ([0, 6, 7, 8], [1, 2, 3, 4, 5])
