"""Current field hints for one creation form, never a configuration cache."""
import asyncio

from nicegui import background_tasks

from .api_client import ApiError


class CreationBindings:
    def __init__(self, api, kind, controls, typed, *, active, show_error):
        self.api, self.kind, self.controls, self.typed = api, kind, controls, typed
        self.active, self.show_error = active, show_error
        self.revision = 0
        typed.creation_bindings = self
        for name in ("aggregation_id", "parent_aggregation_id", "classification_id",
                     "creator_acl_role_id", "security_level_id"):
            if name in controls:
                controls[name].on_value_change(lambda _: self.invalidate())

    def context(self):
        parent = self.controls.get("aggregation_id" if self.kind == "record" else "parent_aggregation_id")
        level = self.controls.get("security_level_id")
        return {"parent_aggregation_id": parent.value if parent is not None else None,
                "type_id": self.typed.selected,
                "security_level_id": level.value if level is not None else None}

    def invalidate(self, *, schedule=True):
        self.revision += 1
        self.typed.generated_fields.clear()
        for control in self.controls.values():
            control._generator_eligible = False
            state = getattr(control, "_creation_number_state", None)
            if state is not None:
                state.revision += 1
        if schedule:
            async def update():
                if not self.active() or self.typed.host.is_deleted:
                    return
                with self.typed.host:
                    try:
                        await self.refresh()
                    except ApiError as error:
                        if self.active():
                            self.show_error(error)
            background_tasks.create(update())

    async def refresh(self, *, for_save=False):
        # Read again on Save. Page refreshes request only the visible field IDs;
        # Save checks visited definitions in bounded batches, never a catalogue.
        self.revision += 1
        revision, context = self.revision, self.context()
        fields = list(self.typed.definitions if for_save else self.typed.page_field_ids)
        chunks = [fields[i:i + 90] for i in range(0, len(fields), 90)] or [[]]
        pages = await asyncio.gather(*(self.api.code_generation_bindings(
            self.kind, **context, field_ids=[int(fid) for fid in chunk], limit=100,
        ) for chunk in chunks))
        if not self.active() or revision != self.revision or context != self.context():
            return False
        rows = [item for page in pages for item in page["items"]]
        primary = {item["primary_field"] for item in rows if item["primary_field"]}
        generated = {str(item["field_id"]) for item in rows if item["field_id"] is not None}
        self.typed.generated_fields.difference_update(fields)
        self.typed.generated_fields.update(generated)
        for name, control in self.controls.items():
            control._generator_eligible = name in primary
        return True


def suggestion_context(controls, typed):
    result = {"type_id": typed.selected}
    for name in ("creator_acl_role_id", "security_level_id"):
        if name in controls:
            result[name] = controls[name].value
    return result
