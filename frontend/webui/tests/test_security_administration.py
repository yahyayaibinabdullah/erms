"""Protected profiles and existing metadata update rules remain unchanged."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from frontend.webui.security_administration import (
    profile_translation_only,configure_profile_field,prepare_profile_update,profile_change_reason,
)

@pytest.mark.parametrize('resource,code,expected',[
    ('profiles','TEXT_INDEXER_SERVICE',True),('profiles','ALL_PRIVS',False),
    ('roles','TEXT_INDEXER_SERVICE',False),('profiles','CUSTOM',False),
])
def test_protected_profile_rule(resource,code,expected):
    assert profile_translation_only(resource,{'code':code}) is expected
    assert not profile_translation_only(resource,None)

@pytest.mark.parametrize('name,creating,disabled', [('code',True,False),('code',False,True),('name',False,False)])
def test_only_existing_code_is_disabled(name,creating,disabled):
    control=Mock();configure_profile_field(SimpleNamespace(name=name),control,creating=creating)
    assert control.disable.call_count==int(disabled)

@pytest.mark.parametrize('value',[None,'','   '])
def test_blank_reason_cannot_authorize_update(value):
    with pytest.raises(ValueError,match='A reason is required when changing a profile'):
        profile_change_reason(SimpleNamespace(value=value))

def test_update_keeps_metadata_and_strips_reason():
    payload={'code':'UNCHANGED','name':'Name','description':'Description'}
    prepare_profile_update(payload)
    assert payload=={'name':'Name','description':'Description'}
    assert profile_change_reason(SimpleNamespace(value='  Review  '))=='Review'
