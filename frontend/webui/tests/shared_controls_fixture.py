"""Small adapters for exercising the real shared controls without a server."""
from unittest.mock import Mock
from frontend.webui.entity_selectors import build_relationship_selector
from frontend.webui.personal_resources import PersonalResourceState, build_personal_resources
from frontend.webui.collection_controls import build_collection_loader


def selector(api):
    return build_relationship_selector(api,error_message=lambda error:str(error))


def personal(api,data,principal,resource,decorate):
    return build_personal_resources(api,data,get_principal=lambda:principal['principal'],
        get_resource=resource,accept_application_configuration=Mock(),
        decorate_for_spec=decorate,error_message=lambda error:str(error))


def collection_loader(scope):
    """Use the host's same narrow view adapters with a test-owned view state."""
    state=scope['state']
    return build_collection_loader(scope['api'],
        get_resource=lambda:state['resource'],
        get_query=lambda:getattr(scope.get('search_input'),'value',''),
        pages=state.setdefault('collection_pages',{}),
        accept_results=lambda rows,searched:state.update(rows=rows,searched=searched),
        clear_result_state=lambda resource:state.setdefault('entity_result_states',{}).pop(resource,None),
        decorate_for_spec=scope['decorate_for_spec'],
        decorate_record_search_components=scope.get('decorate_record_search_components'),
        page_client=scope.get('page_client'),set_connection_status=scope['set_connection_status'],
        render_table=scope['render_table'],error_message=lambda error:str(error))
