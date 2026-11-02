from frontend.webui.profile_privileges import closure, dependents


def test_transitive_prerequisites_and_removal_keep_unrelated_choices():
    dependencies = {3: {2}, 2: {1}, 5: {1}}
    assert closure({3, 9}, dependencies) == {1, 2, 3, 9}
    selected = {1, 2, 3, 5, 9}
    assert dependents(1, selected, dependencies) == {2, 3, 5}
    assert selected - dependents(1, selected, dependencies) - {1} == {9}
    assert dependents(2, selected, dependencies) == {3}
    assert selected == {1, 2, 3, 5, 9}  # Cancel leaves input untouched.


def test_cycles_terminate_and_unknown_dependencies_are_not_invented():
    assert closure({1}, {1: {2}, 2: {1}}) == {1, 2}
    assert closure({9}, {}) == {9}
