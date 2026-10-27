-- Retain identifying titles/numbers prospectively; no erased values are invented.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.retain_unit(p_job bigint,p_root bigint,p_run bigint,p_event bigint,p_at timestamptz,p_executor bigint,p_name text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE physical_id bigint;rule jsonb;due timestamptz;acceleration jsonb;item record;
BEGIN
 IF NOT disposition_private.destruction_active('finalize',p_root) THEN RAISE EXCEPTION 'disposition_destruction_command_required'; END IF;
 PERFORM disposition_private.capture_retiring_identities(p_root);
 SELECT id INTO physical_id FROM disposition_physical_confirmations WHERE job_id=p_job;
 SELECT e.rule_snapshot,e.calculated_disposition_at INTO rule,due FROM disposition_private.eligibility(p_root) e;
 SELECT coalesce(jsonb_agg(disposition_private.retained_json(metadata) ORDER BY id),'[]') INTO acceleration FROM event_history WHERE entity_type='aggregation' AND entity_id=p_root AND operation IN ('DISPOSITION_ACCELERATED','DISPOSITION_RECALCULATED');
 INSERT INTO disposition_retained_records(resource_kind,resource_id,root_id,job_id,run_id,parent_resource_id,classification_id,owning_org_unit_id,date_closed,calculated_disposition_at,rule_snapshot,acceleration,security_level_id,access_snapshot,medium,destruction_number,executor_user_id,executor_name,destroyed_at,physical_confirmation_id,digital_confirmation_event_id,final_event_id,method)
 SELECT 'aggregation',a.id,p_root,p_job,p_run,a.parent_aggregation_id,root.classification_id,a.owning_org_unit_id,root.date_closed,due,rule,acceleration,a.security_level_id,
 jsonb_build_object('inherit_acl_from_parent',a.inherit_acl_from_parent,'resource_acl_version',a.resource_acl_version,'grants',(SELECT coalesce(jsonb_agg(to_jsonb(g)-'id'),'[]') FROM aggregation_acl_grants g WHERE g.aggregation_id=a.id)),a.medium,j.destruction_number,p_executor,p_name,p_at,physical_id,CASE WHEN p_run IS NOT NULL THEN p_event END,p_event,CASE WHEN p_run IS NULL THEN 'confirmed_physical' ELSE 'postgresql_transactional_erasure' END
 FROM aggregations a JOIN aggregations root ON root.id=p_root JOIN disposition_jobs j ON j.id=p_job WHERE a.id IN (SELECT disposition_private.unit_ids(p_root));
 INSERT INTO disposition_retained_records(resource_kind,resource_id,root_id,job_id,run_id,parent_resource_id,classification_id,owning_org_unit_id,date_closed,calculated_disposition_at,rule_snapshot,acceleration,security_level_id,access_snapshot,medium,destruction_number,executor_user_id,executor_name,destroyed_at,physical_confirmation_id,digital_confirmation_event_id,final_event_id,method)
 SELECT 'record',r.id,p_root,p_job,p_run,r.aggregation_id,root.classification_id,r.owning_org_unit_id,root.date_closed,due,rule,acceleration,r.security_level_id,
 jsonb_build_object('inherit_acl_from_parent',r.inherit_acl_from_parent,'resource_acl_version',r.resource_acl_version,'grants',(SELECT coalesce(jsonb_agg(to_jsonb(g)-'id'),'[]') FROM record_acl_grants g WHERE g.record_id=r.id)),r.medium,j.destruction_number,p_executor,p_name,p_at,physical_id,CASE WHEN p_run IS NOT NULL THEN p_event END,p_event,CASE WHEN p_run IS NULL THEN 'confirmed_physical' ELSE 'postgresql_transactional_erasure' END
 FROM records r JOIN aggregations root ON root.id=p_root JOIN disposition_jobs j ON j.id=p_job WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
 DELETE FROM user_favourite_aggregations WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
 DELETE FROM user_favourite_records WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 UPDATE aggregations SET disposition_status=10,description=NULL,date_opened=NULL,date_created=p_at,date_of_next_review=NULL,assigned_location=NULL,current_location=NULL,
 final_disposition_at=p_at,final_disposition_by_user_id=p_executor,disposition_job_id=p_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=p_job),final_disposition_event_id=p_event
 WHERE id IN (SELECT disposition_private.unit_ids(p_root));
 UPDATE records SET disposition_status=10,description=NULL,date_originated=NULL,date_created=p_at,date_of_next_review=NULL,
 final_disposition_at=p_at,final_disposition_by_user_id=p_executor,disposition_job_id=p_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=p_job),final_disposition_event_id=p_event
 WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
END $$;

CREATE OR REPLACE VIEW authorized_aggregations_for_search AS
SELECT resource.id,
       -- Search predicates must use the true relationship. The API redacts an
       -- inaccessible parent only after filtering and adds parent_aggregation_state.
       resource.parent_aggregation_id,
       resource.classification_id,resource.aggregation_number,resource.title,resource.description,
       resource.date_created,resource.date_opened,resource.date_closed,resource.security_level_id,
       resource.inherit_acl_from_parent,resource.default_child_aggregation_acl_mode,
       resource.resource_acl_version,resource.child_aggregation_acl_version,resource.child_record_acl_version,
       resource.version,resource.owning_org_unit_id,resource.medium,resource.is_vital,
       resource.date_of_next_review,resource.assigned_location,resource.current_location,
       CASE WHEN resource.disposition_status<>10 THEN aggregation_effective_assigned_location(resource.id) END AS effective_assigned_location,
       CASE WHEN resource.disposition_status<>10 THEN aggregation_effective_current_location(resource.id) END AS effective_current_location,
       CASE WHEN resource.disposition_status<>10 AND current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.id))
            THEN aggregation_effective_assigned_location_source_id(resource.id) END AS effective_assigned_location_source_aggregation_id,
       CASE WHEN resource.disposition_status<>10 AND current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.id))
            THEN aggregation_effective_current_location_source_id(resource.id) END AS effective_current_location_source_aggregation_id,
       hold_state.effective_hold_count > 0 AS on_effective_hold,
       hold_state.resource_state_changes_blocked,
       hold_state.effective_hold_ids,
       resource.disposition_status,resource.final_disposition_at,resource.final_disposition_by_user_id,
       resource.disposition_job_id,resource.destruction_number,resource.transfer_number,resource.final_disposition_event_id
FROM aggregations resource
CROSS JOIN LATERAL (
    SELECT count(*)::integer effective_hold_count,
           COALESCE(bool_or(effective.preserve_resource_state),false) resource_state_changes_blocked,
           COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id),'{}'::bigint[]) effective_hold_ids
    FROM effective_holds_for_aggregation(resource.id) effective
) hold_state
WHERE resource.disposition_status NOT IN (10,11,12) OR (disposition_private.can_manage() AND (resource.disposition_status<>10 OR disposition_private.retained_access('aggregation',resource.id,false)));

CREATE OR REPLACE VIEW authorized_records_for_search AS
SELECT resource.id,
       -- Keep the true container for filtering; API serialization performs
       -- output redaction and adds aggregation_state.
       resource.aggregation_id,
       resource.record_number,resource.title,resource.description,resource.date_created,resource.date_originated,
       resource.security_level_id,resource.inherit_acl_from_parent,resource.resource_acl_version,resource.version,
       resource.owning_org_unit_id,resource.medium,resource.is_vital,resource.date_of_next_review,
       aggregation_effective_assigned_location(resource.aggregation_id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.aggregation_id) AS effective_current_location,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.aggregation_id))
            THEN aggregation_effective_assigned_location_source_id(resource.aggregation_id) END AS effective_assigned_location_source_aggregation_id,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.aggregation_id))
            THEN aggregation_effective_current_location_source_id(resource.aggregation_id) END AS effective_current_location_source_aggregation_id,
       hold_state.effective_hold_count > 0 AS on_effective_hold,
       hold_state.resource_state_changes_blocked,
       hold_state.effective_hold_ids,
       resource.disposition_status,resource.final_disposition_at,resource.final_disposition_by_user_id,
       resource.disposition_job_id,resource.destruction_number,resource.transfer_number,resource.final_disposition_event_id
FROM records resource
CROSS JOIN LATERAL (
    SELECT count(*)::integer effective_hold_count,
           COALESCE(bool_or(effective.preserve_resource_state),false) resource_state_changes_blocked,
           COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id),'{}'::bigint[]) effective_hold_ids
    FROM effective_holds_for_record(resource.id) effective
) hold_state
WHERE resource.disposition_status NOT IN (10,11,12) OR (disposition_private.can_manage() AND (resource.disposition_status<>10 OR disposition_private.retained_access('record',resource.id,false)));
INSERT INTO schema_migrations(version) VALUES('089_governance_terminal_search') ON CONFLICT DO NOTHING;
COMMIT;
