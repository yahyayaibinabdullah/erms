"""A verb does not waive approved terminology for subsequent document nouns."""
import pytest
from tools.generate_arabic_ui_drafts import validate


def check(source,arabic,role):
    validate([{'message_key':'example.record','default_text':source,'grammatical_role':role}],
      [{'message_key':'example.record','translated_text':arabic,'quality_flags':['needs_human_review']}])


def test_initial_record_verb_uses_action_metadata():
    check('Record external approval','تسجيل الموافقة الخارجية','action label')
    check('Record the decision for this record','سجّل القرار لهذه الوثيقة','imperative sentence')


def test_noun_still_requires_approved_terminology():
    with pytest.raises(ValueError,match='Record →'):
        check('Record title','عنوان العنصر','field label')
    with pytest.raises(ValueError,match='Record →'):
        check('Record the decision for this record','سجّل القرار لهذا العنصر','imperative sentence')
