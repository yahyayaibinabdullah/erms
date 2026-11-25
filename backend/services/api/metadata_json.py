from decimal import Decimal, InvalidOperation
import json
from json import detect_encoding
from typing import Annotated

from fastapi import Depends, HTTPException, Request


async def json_source(request: Request) -> str:
    # PostgreSQL's JSON decoder retains the original digits of decimal literals.
    raw = await request.body()
    return raw.decode(detect_encoding(raw)) if raw else "{}"


JsonSource = Annotated[str, Depends(json_source)]


async def preserve_search_numbers(request: Request, search, *, saved=False):
    """Copy exact JSON numeric literals into typed criteria before canonicalization.

    FastAPI already validated the shape. Revisit the wire body only when a typed
    operand passed through Python's binary float decoder.
    """

    def has_float(node):
        if node is None:
            return False
        if node.field and node.field.startswith("type."):
            values = node.value if isinstance(node.value, list) else [node.value]
            return any(isinstance(value, float) for value in values)
        return has_float(node.not_) or any(
            has_float(child) for child in (node.and_ or node.or_ or [])
        )

    if not has_float(search.where):
        return
    try:
        body = json.loads(await request.body(), parse_float=Decimal)
    except (InvalidOperation, ValueError) as error:
        raise HTTPException(422, detail="Invalid numeric search value") from error
    if saved:
        body = body["definition"]["request"]

    def restore(node, raw):
        if node.field and node.field.startswith("type.") and "value" in raw:
            node.value = raw["value"]
        elif node.not_ is not None:
            restore(node.not_, raw["not"])
        else:
            for child, value in zip(
                node.and_ or node.or_ or [], raw.get("and") or raw.get("or") or []
            ):
                restore(child, value)

    restore(search.where, body["where"])
