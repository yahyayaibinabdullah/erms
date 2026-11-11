"""Organization list projections reuse bounded shared relationship hydration."""
from __future__ import annotations
import asyncio
from .identity_presentation import user_avatar
from .organization_editor import inactive_org_unit_source
from .security_administration import localized_profile_value


async def decorate_organization_rows(spec, rows, *, org_unit_context, rows_by_id,
                                     decorate_relationship_rows, relationship_cell):
    if spec.key == "org-units":
        parents = await org_unit_context(
            {item.get("parent_org_unit_id") for item in rows},
        )
        decorated = decorate_relationship_rows(spec.key, rows, list(parents.values()))
        result = []
        for item in decorated:
            source = inactive_org_unit_source(item, {**parents, int(item["id"]): item})
            result.append({
                **item,
                "effective_status": "inactive" if source else "active",
                "_inactive_reason": (
                    "Directly inactive" if source and source["id"] == item["id"]
                    else f"Inherited from {source['code']} — {source['name']}" if source
                    else "Active"
                ),
            })
        return result
    if spec.key == "roles":
        units_by_id, profiles_by_id, security_levels_by_id = await asyncio.gather(
            org_unit_context({item.get("org_unit_id") for item in rows}),
            rows_by_id("profiles", {item.get("profile_id") for item in rows}),
            rows_by_id("security-levels", {item.get("security_level_id") for item in rows}),
        )
        decorated = decorate_relationship_rows(spec.key, rows, list(units_by_id.values()))
        result = []
        for item in decorated:
            unit = units_by_id.get(item.get("org_unit_id"))
            source = inactive_org_unit_source(unit, units_by_id)
            effective = item.get("status") == "active" and source is None
            result.append({
                **item,
                "profile_display": relationship_cell({
                    **profiles_by_id[item["profile_id"]],
                    "name": localized_profile_value(
                        profiles_by_id[item["profile_id"]], "name",
                    ),
                }) if item.get("profile_id") in profiles_by_id else None,
                "security_level_display": relationship_cell(
                    security_levels_by_id.get(item.get("security_level_id"))
                ),
                "effective_status": "active" if effective else "inactive",
                "_inactive_reason": (
                    "Role is directly inactive" if item.get("status") == "inactive"
                    else f"Organization inactive: {source['code']} — {source['name']}" if source
                    else "Active"
                ),
            })
        return result
    if spec.key == "users":
        return [
            {
                **item,
                "_avatar": user_avatar(item),
                "_inactive_reason": item.get("status", "active").title(),
            }
            for item in rows
        ]

