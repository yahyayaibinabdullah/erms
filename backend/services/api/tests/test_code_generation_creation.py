"""Final-creation batch primitives; real adapters add their own path coverage."""

import json

import pytest
import psycopg
from psycopg.types.json import Jsonb

from backend.services.api import typed_metadata
from backend.services.api.code_generation import CodeGenerationError
from backend.services.api.code_generation_creation import CreationBatch, generation_context

from .test_code_generator_database import c, generator, resource_type
from .test_code_generation_store import context


def field(c,type_id,name,order,kind="text",default=None,required=False):
    return c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length,required,default_value)
        VALUES('record',%s,%s,%s,%s,%s,%s,resource_field_decode(%s,%s)) RETURNING id""",
        (type_id,name,order,kind,100 if kind=="text" else None,required,kind,Jsonb(default))).fetchone()["id"]


def values(aggregation,**changes):
    return {"record_number":None,"title":"Manual title","aggregation_id":aggregation["id"],"medium":aggregation["medium"],**changes}


def batch(c,aggregation,type_id=None):
    typed_metadata.authorize_creation(c,"record",type_id,aggregation["security_level_id"])
    return CreationBatch(c,"record",type_id,lambda:context(aggregation))


def test_batch_fills_required_text_after_defaults_and_preserves_exact_decimal(c,aggregation):
    type_id=resource_type(c)
    text=field(c,type_id,"Contract number",1,required=True)
    precise=field(c,type_id,"Exact amount",2,kind="decimal")
    generator(c,pattern="R{SERIAL}")
    generator(c,primary_field=None,type_id=type_id,field_id=text,pattern="C{SERIAL}")
    current=batch(c,aggregation,type_id)
    raw='{"field_values":{"%s":12345678901234567890.123456789012345678901}}'%precise
    item=current.add(values(aggregation),typed_metadata.creation_defaults(c,"record",type_id,raw))
    current.apply()
    current.validate_primary()
    prepared=typed_metadata.validate_creation(c,"record",type_id,item.raw)
    assert item.values["record_number"]=="R10"
    assert prepared[2][str(text)]=="C10"
    assert prepared[2][str(precise)]=="12345678901234567890.123456789012345678901"
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters WHERE last_serial=10").fetchone()["n"]==2


def test_nonblank_static_default_and_manual_values_never_allocate(c,aggregation):
    type_id=resource_type(c)
    text=field(c,type_id,"Contract number",1,default="STATIC",required=True)
    generator(c,pattern="R{SERIAL}")
    generator(c,primary_field=None,type_id=type_id,field_id=text,pattern="C{SERIAL}")
    current=batch(c,aggregation,type_id)
    current._context=lambda:pytest.fail("A manual/default-only item should not need generation context")
    item=current.add(values(aggregation,record_number=" MANUAL "),typed_metadata.creation_defaults(c,"record",type_id,"{}"))
    current.apply()
    current.validate_primary()
    assert item.values["record_number"]==" MANUAL "
    assert typed_metadata.validate_creation(c,"record",type_id,item.raw)[2][str(text)]=="STATIC"
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_explicit_null_suppresses_default_then_generator_fills_it(c,aggregation):
    type_id=resource_type(c)
    text=field(c,type_id,"Contract number",1,default="STATIC",required=True)
    generator(c,primary_field=None,type_id=type_id,field_id=text,pattern="C{SERIAL}")
    current=batch(c,aggregation,type_id)
    raw=json.dumps({"field_values":{str(text):None}})
    item=current.add(values(aggregation,record_number="MANUAL"),typed_metadata.creation_defaults(c,"record",type_id,raw))
    current.apply()
    assert typed_metadata.validate_creation(c,"record",type_id,item.raw)[2][str(text)]=="C10"


def test_batch_preview_consumes_nothing_and_final_values_follow_one_sequence(c,aggregation):
    generator(c,pattern="R{SERIAL}")
    current=batch(c,aggregation)
    items=[current.add(values(aggregation),"{}") for _ in range(3)]
    assert current.preview()==[{"record_number":"R10"},{"record_number":"R20"},{"record_number":"R30"}]
    assert all(item.values["record_number"] is None for item in items)
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0
    current.apply()
    assert [item.values["record_number"] for item in items]==["R10","R20","R30"]


def test_stale_automatic_origin_is_never_silently_treated_as_manual(c,aggregation):
    row=generator(c,pattern="R{SERIAL}")
    current=batch(c,aggregation)
    with pytest.raises(CodeGenerationError,match="code_generator_recommendation_conflict"):
        current.add(values(aggregation,record_number="R10"),"{}",intent={"record_number":{"source":"generator","generator_id":row["id"]+1}})
    with pytest.raises(CodeGenerationError,match="code_generator_recommendation_conflict"):
        current.add(values(aggregation,record_number="R10"),"{}",intent={"record_number":{"source":"legacy"}})
    item=current.add(values(aggregation,record_number="R10"),"{}",intent={"record_number":{"source":"generator","generator_id":row["id"]}})
    current.apply()
    assert item.values["record_number"]=="R10"


def test_missing_required_field_after_generation_rolls_back_the_entire_batch(c,aggregation):
    type_id=resource_type(c)
    field(c,type_id,"Required manual note",1,required=True)
    generator(c,pattern="R{SERIAL}")
    with pytest.raises(psycopg.errors.CheckViolation,match="Invalid value for field"),c.transaction():
        current=batch(c,aggregation,type_id)
        item=current.add(values(aggregation),typed_metadata.creation_defaults(c,"record",type_id,"{}"))
        current.apply()
        typed_metadata.validate_creation(c,"record",type_id,item.raw)
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_context_uses_actual_parent_root_owner_and_selected_creator_role(c,aggregation):
    current=generation_context(c,parent_id=aggregation["id"],classification_id=None,
                               owner_org_unit_id=999,role_id=1)
    assert current.parent_aggregation_number==aggregation["aggregation_number"]
    assert current.classification_id==1 and current.classification_code=="TEST-01"
    assert current.classification_scheme_code=="TEST"
    assert current.org_unit_id==aggregation["owning_org_unit_id"] and current.org_unit_code=="test-root"
    assert current.role_code=="system-administrator" and current.working_timezone=="Asia/Dubai"
    assert current.instant.tzinfo is not None
