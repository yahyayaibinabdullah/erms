import pytest
from frontend.webui.scripts.check_approved_arabic_terminology import is_record_verb


@pytest.mark.parametrize('text', [
    'Record external approval', 'Record external rejection',
    'Record external destruction approval',
    'Record the required physical-destruction confirmation before proceeding.',
    'Record the received decision against this request.',
])
def test_imperative_record_is_not_the_glossary_noun(text):
    assert is_record_verb(text)


@pytest.mark.parametrize('text', ['Record', 'Record number', 'Record external identifier', 'Records', 'Create record'])
def test_record_noun_stays_subject_to_approved_terminology(text):
    assert not is_record_verb(text)
