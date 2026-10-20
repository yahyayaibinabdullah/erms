"""Native visibility events keep the outside toggle's accessible state current."""
import pytest
from nicegui import ui
from frontend.webui.navigation_drawer import navigation_menu


@pytest.mark.parametrize('direction,expand,collapse', [
    ('ltr', 'Expand navigation', 'Collapse navigation'),
    ('rtl', 'توسيع التنقل', 'طي التنقل'),
])
def test_mobile_control_tracks_native_drawer_visibility(direction, expand, collapse):
    drawer = (ui.right_drawer if direction == 'rtl' else ui.left_drawer)(value=False)
    button = navigation_menu(drawer, expand_label=expand, collapse_label=collapse)
    assert not button.visible
    assert 'lg:hidden' in button._classes
    assert button._props['aria-label'] == expand
    assert button._props['aria-expanded'] == 'false'
    drawer.toggle()
    assert drawer.value is True
    assert button._props['aria-label'] == collapse
    assert button._props['aria-expanded'] == 'true'
    drawer.hide()
    assert button._props['aria-label'] == expand
    button.delete()
    drawer.delete()
