"""Creation-authorized field hints; never administrator settings or counters."""

from typing import Annotated,Literal

from fastapi import APIRouter,Depends,Query
from psycopg import Connection

from . import typed_metadata
from .code_generation import CodeGenerationError
from .creation_roles import creation_role_options
from .database import get_connection
from .operation_policy import operation_policy
from .resource_authorization import require_clearance_for_level,require_global,require_resource_operation


router=APIRouter(prefix="/api/v1/code-generation",tags=["code generation"])


@router.get("/bindings")
@operation_policy("relationship_scoped",conditional_global_privileges={
    "query_parameter":"kind","match":"any","when_omitted":[],
    "by_value":{"record":["record.create"],"aggregation":["aggregation.create_root","aggregation.create_child"]}},
    conditional_resource_authorization={"parent":"Existing view and add-record/add-child authority; root requires aggregation.create_root, parent requires aggregation.create_child", "type":"Use selected type"})
def bindings(kind:Literal["record","aggregation"],
             c:Annotated[Connection,Depends(get_connection,scope="function")],
             parent_aggregation_id:int|None=None,type_id:int|None=None,security_level_id:int|None=None,
             field_ids:Annotated[list[int]|None,Query(max_length=100)]=None,
             limit:Annotated[int,Query(ge=1,le=100)]=25,offset:Annotated[int,Query(ge=0)]=0):
    privilege="record.create" if kind=="record" else "aggregation.create_child" if parent_aggregation_id is not None else "aggregation.create_root"
    require_global(c,privilege)
    if kind=="record" and parent_aggregation_id is None:
        return {"items":[],"total":0}
    parent=None
    if parent_aggregation_id is not None:
        parent=require_resource_operation(c,"aggregation",parent_aggregation_id,privilege,
            "aggregation.add_record" if kind=="record" else "aggregation.add_child",lock=False)
    if not creation_role_options(c,parent_aggregation_id):
        raise CodeGenerationError("code_generator_access_denied")
    level=security_level_id or (parent["security_level_id"] if kind=="aggregation" and parent else
        c.execute("SELECT lowest_security_level_id() AS id").fetchone()["id"])
    require_clearance_for_level(c,level)
    typed_metadata.authorize_creation(c,kind,type_id,level)
    rows=c.execute("""WITH matching AS MATERIALIZED (
        SELECT id AS generator_id,primary_field,field_id FROM code_generators
        WHERE enabled AND kind=%s AND type_population @> coalesce(%s::bigint,0)
          AND (primary_field IS NOT NULL OR field_id=ANY(%s))
        ), total AS(SELECT count(*) AS total FROM matching),page AS(
        SELECT * FROM matching ORDER BY generator_id LIMIT %s OFFSET %s)
        SELECT total.total,to_jsonb(page) AS item FROM total LEFT JOIN page ON true ORDER BY page.generator_id""",
        (kind,type_id,field_ids or [],limit,offset)).fetchall()
    return {"items":[row["item"] for row in rows if row["item"] is not None and row["item"]["generator_id"] is not None],
            "total":rows[0]["total"]}
