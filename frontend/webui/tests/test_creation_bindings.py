"""Creation hints remain bounded, fresh and limited to blank Text inputs."""
import asyncio
from types import SimpleNamespace

import pytest

from frontend.webui.creation_bindings import CreationBindings
from frontend.webui.entity_editor_controls import form_payload
from frontend.webui.entities import ENTITIES
from frontend.webui.resource_number_controls import NumberState
from frontend.webui.type_controls import MetadataForm


def controls():
    return {key:SimpleNamespace(value=value,on_value_change=lambda callback:None)
            for key,value in {'record_number':'','title':'Manual title','aggregation_id':7,'security_level_id':1}.items()}


@pytest.mark.asyncio
async def test_save_reads_visited_fields_in_bounded_batches_and_only_text_may_be_generated():
    calls=[]
    async def hints(kind,**params):
        calls.append((kind,params))
        rows=[{'generator_id':1,'primary_field':'record_number','field_id':None}]
        rows += [{'generator_id':fid+1000,'primary_field':None,'field_id':fid} for fid in params['field_ids']]
        return {'items':rows,'total':len(rows)}
    api=SimpleNamespace(code_generation_bindings=hints)
    typed=MetadataForm(api,'record',initial_type=5)
    typed.definitions={str(fid):{'id':fid,'name':f'Reference {fid}','required':True,
        'data_type':'text','max_length':100,'default':None} for fid in range(1,206)}
    typed.page_field_ids=list(typed.definitions)[:25]
    fields=controls()
    bindings=CreationBindings(api,'record',fields,typed,active=lambda:True,show_error=lambda error:None)
    assert await bindings.refresh(for_save=True)
    assert [len(params['field_ids']) for _,params in calls]==[90,90,25]
    assert all(params['limit']==100 and params['parent_aggregation_id']==7 and params['type_id']==5 for _,params in calls)
    assert form_payload(ENTITIES['records'],fields,creating=True)['record_number'] is None
    assert typed.payload()=={'type_id':5,'field_values':{}}
    assert fields['title'].value=='Manual title'
    typed.definitions['999']={'id':999,'name':'Required count','required':True,
        'data_type':'integer','max_length':None,'default':None}
    typed.generated_fields.add('999')
    with pytest.raises(ValueError):
        typed.payload()
    # Ordinary metadata editing retains required-value checks.
    with pytest.raises(ValueError):
        form_payload(ENTITIES['records'],fields,creating=False)


@pytest.mark.asyncio
async def test_late_hint_cannot_apply_after_context_edit_and_revert_or_clear_a_chosen_code():
    started,release=asyncio.Event(),asyncio.Event()
    async def hints(*args,**kwargs):
        started.set()
        await release.wait()
        return {'total':1,'items':[{'generator_id':1,'primary_field':'record_number','field_id':None}]}
    api=SimpleNamespace(code_generation_bindings=hints)
    typed=MetadataForm(api,'record')
    fields=controls()
    state=NumberState(origin={'source':'generator','generator_id':1})
    fields['record_number'].value='R10'
    fields['record_number']._creation_number_state=state
    bindings=CreationBindings(api,'record',fields,typed,active=lambda:True,show_error=lambda error:None)
    pending=asyncio.create_task(bindings.refresh())
    await started.wait()
    fields['aggregation_id'].value=8
    bindings.invalidate(schedule=False)
    fields['aggregation_id'].value=7
    bindings.invalidate(schedule=False)
    release.set()
    assert not await pending
    assert not fields['record_number']._generator_eligible
    assert fields['record_number'].value=='R10' and state.origin=={'source':'generator','generator_id':1}
    assert state.revision==2
