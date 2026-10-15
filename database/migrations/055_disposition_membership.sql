BEGIN;
SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),
 set_config('app.actor_name','Database migration 055',true),set_config('app.event_source','migration',true),
 set_config('app.change_reason','Install approved disposition membership and atomic recalculation',true);

ALTER TABLE disposition_private.command_receipts DROP CONSTRAINT command_receipts_operation_check,
 ADD CONSTRAINT command_receipts_operation_check CHECK (operation IN ('job_create','job_assign','membership_add','membership_remove','eligibility_evaluate','eligibility_accelerate','job_terminate','resolve_partial','task_claim','task_release','task_reassign','task_complete','review_submit','review_decide','document_save','selective_decide','final_complete','recalculate','job_owner_change'));

ALTER TABLE disposition_job_memberships
 ADD COLUMN removal_required boolean NOT NULL DEFAULT false,
 ADD COLUMN removal_required_reason text,
 ADD CONSTRAINT disposition_removal_required_reason CHECK (
  (removal_required AND removal_required_reason IS NOT NULL AND removal_required_reason IN ('reopened','retention_rule_changed')) OR
  (NOT removal_required AND removal_required_reason IS NULL));

-- This private transaction context is created only by the policy/reopening
-- triggers. It is not a GUC authorization bypass or a public command endpoint.
CREATE TABLE disposition_private.recalculation_context (
 transaction_id bigint NOT NULL,backend_id integer NOT NULL,root_id bigint NOT NULL,
 old_evaluation jsonb NOT NULL,old_status smallint NOT NULL,cause text NOT NULL,
 applying boolean NOT NULL DEFAULT false,target_status smallint,
 PRIMARY KEY(transaction_id,backend_id,root_id));
REVOKE ALL ON disposition_private.recalculation_context FROM PUBLIC;

CREATE FUNCTION disposition_private.hook_applying(p_root bigint DEFAULT NULL) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.recalculation_context WHERE transaction_id=txid_current()
  AND backend_id=pg_backend_pid() AND applying AND (p_root IS NULL OR root_id=p_root))
$$;
CREATE OR REPLACE FUNCTION disposition_private.context_operation() RETURNS text LANGUAGE sql STABLE AS $$
 SELECT COALESCE(CASE WHEN disposition_private.hook_applying() THEN 'recalculate' END,(SELECT r.operation FROM disposition_private.command_context c
 JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid()
 AND r.actor_user_id IS NOT DISTINCT FROM current_user_id()
 AND r.actor_type=current_setting('app.actor_type',true) AND r.completed_at IS NULL))
$$;

CREATE OR REPLACE FUNCTION disposition_private.begin_command(p_id uuid,p_operation text,p_payload jsonb,p_role bigint,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE previous disposition_private.command_receipts%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 PERFORM disposition_private.require_actor(p_role);
 IF p_reason IS NULL OR p_reason ~ '^[[:space:]]*$' THEN RAISE EXCEPTION 'disposition_reason_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.command_context WHERE transaction_id=txid_current()) THEN RAISE EXCEPTION 'disposition_nested_command'; END IF;
 SELECT * INTO previous FROM disposition_private.command_receipts WHERE command_id=p_id FOR UPDATE;
 IF FOUND THEN
  IF previous.actor_type IS DISTINCT FROM 'user' OR previous.actor_user_id IS DISTINCT FROM current_user_id() OR previous.acting_role_id IS DISTINCT FROM p_role OR previous.operation<>p_operation
    OR previous.payload IS DISTINCT FROM p_payload OR previous.reason IS DISTINCT FROM p_reason THEN
    RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='disposition_command_conflict'; END IF;
  IF previous.completed_at IS NULL THEN RAISE EXCEPTION 'disposition_incomplete_command'; END IF;
  -- Returning a committed result still obeys current resource access.
  IF previous.payload ? 'job_id' THEN PERFORM disposition_private.require_job_access((previous.payload->>'job_id')::bigint);
  ELSIF p_operation='job_create' AND previous.result ? 'id' THEN PERFORM disposition_private.require_job_access((previous.result->>'id')::bigint);
  ELSIF previous.payload ? 'membership_id' THEN PERFORM disposition_private.require_job_access((SELECT job_id FROM disposition_job_memberships WHERE id=(previous.payload->>'membership_id')::bigint));
  ELSIF p_operation='eligibility_accelerate' AND previous.payload ? 'root_id' AND NOT current_user_can_view_aggregation((previous.payload->>'root_id')::bigint) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  RETURN previous.result;
 END IF;
 INSERT INTO disposition_private.command_receipts(command_id,actor_user_id,acting_role_id,operation,payload,reason)
 VALUES(p_id,current_user_id(),p_role,p_operation,p_payload,p_reason);
 INSERT INTO disposition_private.command_context VALUES(txid_current(),pg_backend_pid(),p_id);
 PERFORM set_config('app.change_reason',p_reason,true);
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.require_command() RETURNS void LANGUAGE plpgsql AS $$
DECLARE command disposition_private.command_receipts%ROWTYPE;
BEGIN
 IF disposition_private.hook_applying() THEN RETURN; END IF;
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid() AND r.completed_at IS NULL;
 IF NOT FOUND OR command.actor_user_id IS DISTINCT FROM current_user_id()
 OR command.actor_type IS DISTINCT FROM current_setting('app.actor_type',true) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 IF command.actor_type='automated_process' THEN
  IF command.operation<>'eligibility_evaluate' OR command.actor_user_id IS NOT NULL OR command.acting_role_id IS NOT NULL THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 ELSE PERFORM disposition_private.require_actor(command.acting_role_id);
 END IF;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.assert_unit(p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; member disposition_job_memberships%ROWTYPE; job disposition_jobs%ROWTYPE;
BEGIN
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 IF NOT FOUND THEN RETURN; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF EXISTS (
  SELECT 1 FROM aggregations a WHERE a.id IN (SELECT disposition_private.unit_ids(p_root)) AND
   (a.disposition_status,a.final_disposition_at,a.final_disposition_by_user_id,a.disposition_job_id,a.destruction_number,a.transfer_number,a.final_disposition_event_id)
   IS DISTINCT FROM (root.disposition_status,root.final_disposition_at,root.final_disposition_by_user_id,root.disposition_job_id,root.destruction_number,root.transfer_number,root.final_disposition_event_id)
  UNION ALL SELECT 1 FROM records r WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND
   (r.disposition_status,r.final_disposition_at,r.final_disposition_by_user_id,r.disposition_job_id,r.destruction_number,r.transfer_number,r.final_disposition_event_id)
   IS DISTINCT FROM (root.disposition_status,root.final_disposition_at,root.final_disposition_by_user_id,root.disposition_job_id,root.destruction_number,root.transfer_number,root.final_disposition_event_id)
 ) THEN RAISE EXCEPTION 'disposition_unit_inconsistent'; END IF;
 SELECT * INTO member FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active';
 IF FOUND THEN
  SELECT * INTO job FROM disposition_jobs WHERE id=member.job_id;
  IF job.lifecycle_state<>'active' OR job.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_active_membership_invalid'; END IF;
  IF root.disposition_status BETWEEN 6 AND 9 AND (root.disposition_status<>job.disposition_status OR root.disposition_status<>
   CASE job.job_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 ELSE 9 END) THEN RAISE EXCEPTION 'disposition_job_status_mismatch'; END IF;
  -- Reopened/recalculated members remain in history and block job progress
  -- until explicitly removed. They cannot acquire a free-standing pending status.
  IF root.disposition_status NOT BETWEEN 6 AND 9 AND NOT (member.removal_required AND root.disposition_status BETWEEN 1 AND 5) THEN
   RAISE EXCEPTION 'disposition_active_member_not_pending'; END IF;
 ELSIF root.disposition_status BETWEEN 6 AND 9 THEN RAISE EXCEPTION 'disposition_pending_requires_membership'; END IF;
 IF root.disposition_status IN (10,11,12) THEN
  SELECT * INTO job FROM disposition_jobs WHERE id=root.disposition_job_id;
  IF NOT FOUND OR job.lifecycle_state<>'completed' OR job.disposition_status<>root.disposition_status
    OR NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=job.id AND root_aggregation_id=p_root AND membership_state='completed_history')
    OR (root.final_disposition_at,root.final_disposition_by_user_id,root.destruction_number,root.transfer_number,root.final_disposition_event_id)
       IS DISTINCT FROM (job.completed_at,job.completed_by_user_id,job.destruction_number,job.transfer_number,job.final_event_id) THEN
   RAISE EXCEPTION 'disposition_terminal_fields_inconsistent'; END IF;
 ELSE
  IF root.final_disposition_at IS NOT NULL OR root.final_disposition_by_user_id IS NOT NULL OR root.disposition_job_id IS NOT NULL
    OR root.destruction_number IS NOT NULL OR root.transfer_number IS NOT NULL OR root.final_disposition_event_id IS NOT NULL THEN
   RAISE EXCEPTION 'disposition_premature_final_fields'; END IF;
 END IF;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.transition_unit(p_root bigint,p_version bigint,p_status integer)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; uid bigint:=current_user_id(); event_id bigint; op text;
BEGIN
 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 SELECT * INTO root FROM aggregations WHERE id=p_root FOR UPDATE;
 IF NOT FOUND OR root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF p_status NOT BETWEEN 1 AND 13 OR NOT disposition_private.allowed_transition(root.disposition_status,p_status,op) THEN RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
 IF p_status IN (10,11,12,13) THEN RAISE EXCEPTION 'disposition_action_not_implemented'; END IF;
 IF root.date_closed IS NULL AND p_status<>1 AND op<>'eligibility_accelerate' THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 IF NOT disposition_private.hook_applying(p_root) AND current_setting('app.actor_type',true)='user' AND NOT user_can_view_aggregation(uid,p_root) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.disposition_status=p_status AND (NOT disposition_private.hook_applying(p_root) OR NOT EXISTS(
  SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>p_status
  UNION ALL SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>p_status)) THEN RETURN; END IF;
 event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_STATUS_CHANGED',jsonb_build_object(
  'old_status',root.disposition_status,'new_status',p_status,'operation',op,
  'command_id',(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())));
 UPDATE aggregations SET disposition_status=p_status WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status IS DISTINCT FROM p_status;
 UPDATE records SET disposition_status=p_status WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status IS DISTINCT FROM p_status;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.evaluate_root(p_root bigint,p_command uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; evaluation record; previous disposition_private.command_receipts%ROWTYPE; result jsonb;
BEGIN
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'automated_process' OR current_user_id() IS NOT NULL THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_eligibility_worker_required'; END IF;
 PERFORM pg_advisory_xact_lock(7357,1);
 -- Freeze only the retention-policy tables during this short root transaction.
 -- Closed-root row/descendant locks protect closure and containment. These
 -- table locks also cover direct SQL policy edits and classification reparenting.
 LOCK TABLE classification_retention_rules,aggregation_retention_rules,classifications IN SHARE MODE;
 PERFORM lock_hold_policy_shared();
 SELECT * INTO previous FROM disposition_private.command_receipts WHERE command_id=p_command;
 IF FOUND THEN
  IF previous.actor_type<>'automated_process' OR previous.operation<>'eligibility_evaluate'
   OR previous.payload->>'root_id' IS DISTINCT FROM p_root::text OR previous.result IS NULL THEN
   RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='disposition_command_conflict'; END IF;
  RETURN previous.result;
 END IF;
 SELECT * INTO root FROM aggregations WHERE id=p_root FOR UPDATE;
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active' AND removal_required) THEN
 RETURN jsonb_build_object('root_id',p_root,'changed',false,'reason','removal_required'); END IF;
 IF root.id IS NULL OR root.parent_aggregation_id IS NOT NULL OR root.disposition_status<>1 OR root.date_closed IS NULL THEN
  RETURN jsonb_build_object('root_id',p_root,'changed',false,'reason','not_a_closed_not_ready_root'); END IF;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 IF NOT COALESCE(evaluation.is_due,false) OR evaluation.eligible_status IS NULL THEN
  RETURN jsonb_build_object('root_id',p_root,'changed',false,'reason','not_due_or_no_rule'); END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.command_context WHERE transaction_id=txid_current()) THEN RAISE EXCEPTION 'disposition_nested_command'; END IF;
 INSERT INTO disposition_private.command_receipts(command_id,actor_type,operation,payload,reason)
 VALUES(p_command,'automated_process','eligibility_evaluate',jsonb_build_object('root_id',p_root,'evaluation',to_jsonb(evaluation)), 'Retention period ended');
 INSERT INTO disposition_private.command_context VALUES(txid_current(),pg_backend_pid(),p_command);
 PERFORM set_config('app.actor_name','Disposition eligibility service',true);
 PERFORM set_config('app.event_source','background_service',true);
 PERFORM set_config('app.change_reason','Retention period ended',true);
 INSERT INTO event_history(entity_type,entity_id,operation,actor_type,actor_name,source,reason,metadata)
 VALUES('aggregation',p_root,'DISPOSITION_ELIGIBILITY_EVALUATED','automated_process','Disposition eligibility service','background_service','Retention period ended',to_jsonb(evaluation)||jsonb_build_object('command_id',p_command));
 PERFORM disposition_private.transition_unit(p_root,root.version,evaluation.eligible_status);
 result:=jsonb_build_object('root_id',p_root,'changed',true,'status',evaluation.eligible_status,'calculated_disposition_at',evaluation.calculated_disposition_at);
 PERFORM disposition_private.finish_command(result);
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION protect_held_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE blocked boolean;
DECLARE allowed_old jsonb;
DECLARE allowed_new jsonb;
BEGIN
    PERFORM lock_hold_policy_shared();
    -- Leaving a job/terminating it restores eligibility and preserves the hold.
    -- This is status-only bookkeeping, never destruction or a metadata override.
    IF TG_OP='UPDATE' AND disposition_private.context_operation() IN ('membership_remove','job_terminate')
      AND OLD.disposition_status BETWEEN 6 AND 9 AND NEW.disposition_status=OLD.disposition_status-4
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    IF TG_OP='UPDATE' AND disposition_private.hook_applying()
      AND OLD.disposition_status BETWEEN 1 AND 9 AND NEW.disposition_status BETWEEN 1 AND 9
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    IF TG_OP='UPDATE' AND OLD.disposition_status=1 AND NEW.disposition_status BETWEEN 2 AND 5
      AND disposition_private.context_operation()='eligibility_evaluate'
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    IF TG_OP='DELETE' THEN
        IF TG_TABLE_NAME='aggregations' THEN
            WITH RECURSIVE subtree AS (
                SELECT OLD.id AS id UNION ALL
                SELECT child.id FROM aggregations child JOIN subtree parent ON child.parent_aggregation_id=parent.id
            )
            SELECT EXISTS(
                SELECT 1 FROM subtree WHERE resource_has_effective_hold('aggregation',subtree.id)
                UNION ALL
                SELECT 1 FROM records record JOIN subtree ON subtree.id=record.aggregation_id
                WHERE resource_has_effective_hold('record',record.id)
            ) INTO blocked;
        ELSE
            blocked:=resource_has_effective_hold('record',OLD.id);
        END IF;
        IF blocked THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_deletion'; END IF;
        RETURN OLD;
    END IF;

    IF TG_TABLE_NAME='aggregations' THEN
        blocked:=resource_state_changes_blocked('aggregation',OLD.id);
        IF NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id THEN
            IF blocked OR (NEW.parent_aggregation_id IS NOT NULL AND EXISTS(
                SELECT 1 FROM effective_holds_for_aggregation(NEW.parent_aggregation_id) WHERE preserve_resource_state
            )) THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
            IF EXISTS(
                WITH old_holds AS (SELECT hold_id FROM effective_holds_for_aggregation(OLD.id)),
                     new_ancestor_holds AS (
                         SELECT hold_id FROM effective_holds_for_aggregation(NEW.parent_aggregation_id)
                         UNION SELECT hold_id FROM hold_aggregation_assignments WHERE aggregation_id=OLD.id AND hold_is_effective(hold_id)
                     ), changed AS ((SELECT * FROM old_holds EXCEPT SELECT * FROM new_ancestor_holds)
                                    UNION (SELECT * FROM new_ancestor_holds EXCEPT SELECT * FROM old_holds))
                SELECT 1 FROM changed WHERE NOT current_hold_actor_is_manager(changed.hold_id)
            ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_management_required_for_held_move'; END IF;
        END IF;
        IF blocked THEN
            allowed_old:=to_jsonb(OLD)-ARRAY['security_level_id','owning_org_unit_id','assigned_location','current_location',
                'inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','version'];
            allowed_new:=to_jsonb(NEW)-ARRAY['security_level_id','owning_org_unit_id','assigned_location','current_location',
                'inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','version'];
            IF allowed_old IS DISTINCT FROM allowed_new THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
        END IF;
    ELSE
        blocked:=resource_state_changes_blocked('record',OLD.id);
        IF NEW.aggregation_id IS DISTINCT FROM OLD.aggregation_id THEN
            IF blocked OR EXISTS(SELECT 1 FROM effective_holds_for_aggregation(NEW.aggregation_id)
                                 WHERE preserve_resource_state) THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
            IF EXISTS(
                WITH old_holds AS (SELECT hold_id FROM effective_holds_for_record(OLD.id)),
                     new_holds AS (
                         SELECT hold_id FROM effective_holds_for_aggregation(NEW.aggregation_id)
                         UNION SELECT hold_id FROM hold_record_assignments WHERE record_id=OLD.id AND hold_is_effective(hold_id)
                     ), changed AS ((SELECT * FROM old_holds EXCEPT SELECT * FROM new_holds)
                                    UNION (SELECT * FROM new_holds EXCEPT SELECT * FROM old_holds))
                SELECT 1 FROM changed WHERE NOT current_hold_actor_is_manager(changed.hold_id)
            ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_management_required_for_held_move'; END IF;
        END IF;
        IF blocked THEN
            allowed_old:=to_jsonb(OLD)-ARRAY['security_level_id','owning_org_unit_id','inherit_acl_from_parent',
                'resource_acl_version','version'];
            allowed_new:=to_jsonb(NEW)-ARRAY['security_level_id','owning_org_unit_id','inherit_acl_from_parent',
                'resource_acl_version','version'];
            IF allowed_old IS DISTINCT FROM allowed_new THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE FUNCTION protect_closed_aggregation_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE closure_source_id bigint;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.context_operation() IS NOT NULL
 AND (to_jsonb(NEW)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated'])=(to_jsonb(OLD)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated']) THEN
  PERFORM disposition_private.require_command(); RETURN NEW;
 END IF;
 IF TG_OP='INSERT' THEN
   IF NEW.parent_aggregation_id IS NOT NULL THEN
     PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id);
   END IF;
   RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN
   PERFORM assert_aggregation_effectively_open(OLD.id);
   RETURN OLD;
 END IF;
 WITH RECURSIVE ancestors AS (
   SELECT id,parent_aggregation_id,date_closed,0 depth FROM aggregations WHERE id=OLD.id
   UNION ALL
   SELECT parent.id,parent.parent_aggregation_id,parent.date_closed,child.depth+1
   FROM aggregations parent JOIN ancestors child ON parent.id=child.parent_aggregation_id
 )
 SELECT id INTO closure_source_id FROM ancestors
 WHERE date_closed IS NOT NULL ORDER BY depth LIMIT 1;
 IF closure_source_id IS NOT NULL THEN
   IF OLD.parent_aggregation_id IS NULL AND NEW.parent_aggregation_id IS NULL
      AND NEW.classification_id IS DISTINCT FROM OLD.classification_id
      AND (to_jsonb(NEW)-ARRAY['classification_id','version'])=(to_jsonb(OLD)-ARRAY['classification_id','version'])
      AND current_user_can_aggregation_operation(OLD.id,'aggregation.reclassify','aggregation.reclassify') THEN RETURN NEW; END IF;
   IF current_setting('app.vital_status_change_authorized',true)='authorized'
      AND NEW.is_vital IS DISTINCT FROM OLD.is_vital
      AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.location_change_authorized',true)='authorized'
      AND (NEW.assigned_location IS DISTINCT FROM OLD.assigned_location
           OR NEW.current_location IS DISTINCT FROM OLD.current_location)
      AND (to_jsonb(NEW)-'assigned_location'-'current_location'-'version')
          =(to_jsonb(OLD)-'assigned_location'-'current_location'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.review_date_change_authorized',true)='authorized'
      AND NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review
      AND (to_jsonb(NEW)-'date_of_next_review'-'version')=(to_jsonb(OLD)-'date_of_next_review'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.security_level_change_authorized',true)='authorized'
      AND NEW.security_level_id IS DISTINCT FROM OLD.security_level_id
      AND (to_jsonb(NEW)-'security_level_id'-'version')=(to_jsonb(OLD)-'security_level_id'-'version') THEN
     RETURN NEW;
   END IF;
   IF closure_source_id=OLD.id AND OLD.date_closed IS NOT NULL
      AND NEW.date_closed IS NULL
      AND (to_jsonb(NEW)-'date_closed'-'version')=(to_jsonb(OLD)-'date_closed'-'version') THEN
     RETURN NEW;
   END IF;
   RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='closed aggregation metadata is immutable';
 END IF;
 RETURN NEW;
END;
$$;
CREATE OR REPLACE FUNCTION disposition_private.guard_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; prior jsonb; following jsonb; op text; uid bigint:=current_user_id(); expected_status integer;
BEGIN
 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 IF NOT (CASE TG_TABLE_NAME
 WHEN 'disposition_jobs' THEN op IN ('job_create','job_assign','job_owner_change','membership_add','membership_remove','job_terminate','final_complete','review_submit','review_decide','recalculate','selective_decide')
 WHEN 'disposition_job_memberships' THEN op IN ('membership_add','membership_remove','job_terminate','final_complete','recalculate')
 WHEN 'disposition_tasks' THEN op IN ('job_create','job_assign','task_claim','task_release','task_reassign','task_complete','review_submit','review_decide','job_terminate','final_complete')
 WHEN 'disposition_review_rounds' THEN op IN ('review_submit','review_decide','membership_add','membership_remove','recalculate')
 WHEN 'disposition_review_decisions' THEN op='review_decide'
 WHEN 'disposition_job_documents' THEN op='document_save'
 ELSE false END) THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
 following:=to_jsonb(NEW);
 IF TG_OP='UPDATE' THEN
  prior:=to_jsonb(OLD);
  IF TG_TABLE_NAME='disposition_review_decisions'
    OR (TG_TABLE_NAME='disposition_jobs' AND prior->>'lifecycle_state'<>'active')
    OR (TG_TABLE_NAME='disposition_job_memberships' AND prior->>'membership_state'<>'active')
    OR (TG_TABLE_NAME='disposition_tasks' AND prior->>'task_state' IN ('completed','cancelled'))
    OR (TG_TABLE_NAME='disposition_job_documents' AND prior->>'document_state'='available')
    OR (TG_TABLE_NAME='disposition_review_rounds' AND prior->>'invalidated_at' IS NOT NULL) THEN
   RAISE EXCEPTION 'disposition_history_immutable'; END IF;
  IF (prior->>'id') IS DISTINCT FROM (following->>'id') OR
   (prior->>'job_id') IS DISTINCT FROM (following->>'job_id') THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
  IF TG_TABLE_NAME<>'disposition_review_decisions' THEN NEW.version:=OLD.version+1; NEW.date_updated:=CURRENT_TIMESTAMP; END IF;
 ELSE
  IF following ? 'version' AND (following->>'version')::integer<>1 THEN RAISE EXCEPTION 'disposition_initial_version'; END IF;
 END IF;
 IF TG_TABLE_NAME='disposition_jobs' THEN
  IF TG_OP='UPDATE' AND NOT disposition_private.hook_applying() THEN PERFORM disposition_private.require_job_access(NEW.id); END IF;
  IF TG_OP='UPDATE' AND ((NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND NEW.workflow_stage NOT IN ('officer_correction','manager_correction')) OR NEW.disposition_status<>OLD.disposition_status) AND op<>'job_terminate' THEN PERFORM disposition_private.require_progress(NEW.id); END IF;
  IF TG_OP='INSERT' THEN
   IF op<>'job_create' OR NEW.lifecycle_state<>'active' OR NEW.created_by_user_id<>uid OR (NEW.job_type='destruction' AND NEW.workflow_stage NOT IN ('officer_preparation','manager_preparation')) THEN RAISE EXCEPTION 'disposition_invalid_job_creation'; END IF;
   PERFORM disposition_private.require_job_person(uid,NEW.job_type);
   NEW.date_created:=CURRENT_TIMESTAMP;
  ELSE
   IF NEW.owning_org_unit_id IS DISTINCT FROM OLD.owning_org_unit_id THEN
    IF op<>'job_owner_change' OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active')
     OR NEW.current_review_round>0 OR EXISTS(SELECT 1 FROM disposition_review_rounds WHERE job_id=NEW.id)
     OR EXISTS(SELECT 1 FROM event_history WHERE entity_type='disposition_job' AND entity_id=NEW.id AND operation='REVIEW_SUBMIT') THEN RAISE EXCEPTION 'disposition_owning_unit_change_invalid'; END IF;
   END IF;
   IF NEW.job_number<>OLD.job_number OR NEW.job_type<>OLD.job_type OR NEW.created_by_user_id<>OLD.created_by_user_id OR NEW.date_created<>OLD.date_created THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF NEW.lifecycle_state<>OLD.lifecycle_state AND NOT ((op='job_terminate' AND NEW.lifecycle_state='terminated') OR (op='final_complete' AND NEW.lifecycle_state='completed')) THEN RAISE EXCEPTION 'disposition_invalid_lifecycle_transition'; END IF;
   IF NEW.disposition_status<>OLD.disposition_status AND NOT disposition_private.allowed_transition(OLD.disposition_status,NEW.disposition_status,op) THEN RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
   IF NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND (op NOT IN ('review_submit','review_decide','final_complete') OR NOT disposition_private.allowed_stage(OLD.workflow_stage,NEW.workflow_stage)) THEN RAISE EXCEPTION 'disposition_invalid_stage_transition'; END IF;
  END IF;
  expected_status:=CASE NEW.job_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 ELSE 9 END;
  IF NEW.lifecycle_state='active' AND NEW.disposition_status<>expected_status THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
  IF NEW.assigned_user_id IS NOT NULL AND NOT disposition_private.hook_applying() AND (TG_OP='INSERT' OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) THEN
   PERFORM disposition_private.require_job_person(NEW.assigned_user_id,NEW.job_type);
   IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active' AND NOT user_can_view_aggregation(NEW.assigned_user_id,root_aggregation_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_access_required'; END IF;
  END IF;
  IF NEW.assigned_user_id IS NOT NULL AND NOT disposition_private.hook_applying() AND (TG_OP='INSERT' OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) AND NOT EXISTS(
   SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
   JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
   WHERE u.id=NEW.assigned_user_id AND u.status='active' AND u.account_type='person' AND r.is_information_governance
    AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
    AND p.code='disposition.jobs.manage') THEN RAISE EXCEPTION 'disposition_assignee_not_authorized'; END IF;
  IF TG_OP='UPDATE' AND NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id AND op<>'job_assign' THEN RAISE EXCEPTION 'disposition_assignment_command_required'; END IF;
  NEW.updated_by_user_id:=uid;
  IF NEW.lifecycle_state='completed' THEN
   IF NEW.job_type<>'destruction' THEN RAISE EXCEPTION 'disposition_action_not_implemented'; END IF;
   -- The Phase 21 implementation replaces this fail-closed gate only when its
   -- irreversible action, approvals/evidence and recovery contract is verified.
   RAISE EXCEPTION 'disposition_final_execution_not_implemented';
  END IF;
  IF NEW.lifecycle_state='terminated' THEN
   NEW.terminated_at:=CURRENT_TIMESTAMP; NEW.terminated_by_user_id:=uid;
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=(following->>'job_id')::bigint FOR UPDATE;
 IF NOT disposition_private.hook_applying() THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') THEN PERFORM disposition_private.require_progress(job.id); END IF;
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF TG_TABLE_NAME='disposition_job_memberships' THEN
  IF (TG_OP='INSERT' AND NEW.removal_required) OR (TG_OP='UPDATE' AND (NEW.removal_required,NEW.removal_required_reason) IS DISTINCT FROM (OLD.removal_required,OLD.removal_required_reason) AND NOT disposition_private.hook_applying(NEW.root_aggregation_id)) THEN RAISE EXCEPTION 'disposition_recalculation_scope_invalid'; END IF;
  IF op IN ('membership_add','membership_remove') THEN PERFORM disposition_private.require_membership_stage(job.id); END IF;
  IF disposition_private.root_id(NEW.root_aggregation_id)<>NEW.root_aggregation_id THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
  IF TG_OP='INSERT' THEN
   IF op<>'membership_add' OR NEW.membership_state<>'active' OR NEW.added_by_user_id<>uid OR job.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_membership_add_invalid'; END IF;
   IF NOT current_user_can_view_aggregation(NEW.root_aggregation_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=NEW.root_aggregation_id AND membership_state='completed_history') THEN RAISE EXCEPTION 'disposition_already_completed'; END IF;
   PERFORM disposition_private.assert_admission(job.id,NEW.root_aggregation_id);
   NEW.added_at:=CURRENT_TIMESTAMP;
  ELSE
   IF NOT disposition_private.hook_applying(NEW.root_aggregation_id) AND NOT current_user_can_view_aggregation(NEW.root_aggregation_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF NEW.root_aggregation_id<>OLD.root_aggregation_id OR NEW.added_at<>OLD.added_at OR NEW.added_by_user_id<>OLD.added_by_user_id THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF op='recalculate' AND disposition_private.hook_applying(NEW.root_aggregation_id) THEN
    IF (to_jsonb(NEW)-ARRAY['removal_required','removal_required_reason','version','date_updated']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['removal_required','removal_required_reason','version','date_updated']) THEN RAISE EXCEPTION 'disposition_recalculation_scope_invalid'; END IF;
   ELSIF NOT ((op='membership_remove' AND NEW.membership_state='removed') OR (op='job_terminate' AND NEW.membership_state='terminated_history') OR (op='final_complete' AND NEW.membership_state='completed_history')) THEN RAISE EXCEPTION 'disposition_invalid_membership_transition'; END IF;
   IF NEW.membership_state='removed' THEN NEW.removed_at:=CURRENT_TIMESTAMP; NEW.removed_by_user_id:=uid; END IF;
  END IF;
  UPDATE disposition_jobs SET version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=job.id;
 ELSIF TG_TABLE_NAME='disposition_tasks' THEN
  IF TG_OP='INSERT' THEN NEW.date_created:=CURRENT_TIMESTAMP; END IF;
  IF NEW.workflow_stage<>job.workflow_stage THEN RAISE EXCEPTION 'disposition_task_stage_mismatch'; END IF;
  IF TG_OP='UPDATE' THEN
   IF NEW.task_type<>OLD.task_type OR NEW.workflow_stage<>OLD.workflow_stage OR NEW.review_round IS DISTINCT FROM OLD.review_round OR NEW.date_created<>OLD.date_created THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF (NEW.destination_user_id,NEW.destination_role_id) IS DISTINCT FROM (OLD.destination_user_id,OLD.destination_role_id) AND op<>'task_reassign' THEN RAISE EXCEPTION 'disposition_reassignment_command_required'; END IF;
   IF op IN ('task_release','task_complete','review_decide') AND ((OLD.claimed_by_user_id IS NOT NULL AND OLD.claimed_by_user_id<>uid) OR (OLD.destination_user_id IS NOT NULL AND OLD.destination_user_id<>uid) OR (OLD.destination_role_id IS NOT NULL AND OLD.claimed_by_user_id IS DISTINCT FROM uid)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_claim_required'; END IF;
  END IF;
  IF NEW.task_state='completed' THEN
   IF NEW.destination_role_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=NEW.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   NEW.completed_at:=CURRENT_TIMESTAMP; NEW.completed_by_user_id:=uid;
  END IF;
  IF op IN ('task_release','task_reassign') THEN
   NEW.claimed_by_user_id:=NULL; NEW.claimed_at:=NULL;
   IF op='task_release' THEN NEW.released_by_user_id:=uid; NEW.released_at:=CURRENT_TIMESTAMP;
   ELSE NEW.reassigned_by_user_id:=uid; NEW.reassigned_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
  IF TG_OP='UPDATE' AND NEW.task_state<>OLD.task_state AND NOT (
   (op='task_claim' AND OLD.task_state='open' AND NEW.task_state='claimed') OR
   (op IN ('task_release','task_reassign') AND OLD.task_state IN ('open','claimed') AND NEW.task_state='open') OR
   (op IN ('task_complete','review_decide') AND OLD.task_state IN ('open','claimed') AND NEW.task_state='completed') OR
   (op IN ('job_terminate','review_submit','review_decide') AND NEW.task_state='cancelled')) THEN RAISE EXCEPTION 'disposition_invalid_task_transition'; END IF;
  IF NEW.task_state='claimed' THEN
   IF NEW.claimed_by_user_id<>uid OR (NEW.destination_user_id IS NOT NULL AND NEW.destination_user_id<>uid) OR
     (NEW.destination_role_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.role_id=NEW.destination_role_id AND a.user_id=uid AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id))) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   NEW.claimed_at:=CURRENT_TIMESTAMP;
  END IF;
 ELSIF TG_TABLE_NAME='disposition_review_rounds' THEN
  IF TG_OP='INSERT' THEN NEW.started_at:=CURRENT_TIMESTAMP;
  ELSE
   IF OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
   IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN NEW.completed_at:=CURRENT_TIMESTAMP; END IF;
   IF OLD.invalidated_at IS NULL AND NEW.invalidated_at IS NOT NULL THEN NEW.invalidated_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
  IF TG_OP='UPDATE' AND (NEW.round_number<>OLD.round_number OR NEW.membership_snapshot<>OLD.membership_snapshot OR NEW.started_at<>OLD.started_at OR NEW.started_by_user_id<>OLD.started_by_user_id) THEN RAISE EXCEPTION 'disposition_review_snapshot_immutable'; END IF;
  IF TG_OP='INSERT' AND (NEW.started_by_user_id<>uid OR NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id)) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
  IF TG_OP='INSERT' AND NEW.round_number<>COALESCE((SELECT max(round_number)+1 FROM disposition_review_rounds WHERE job_id=job.id),1) THEN RAISE EXCEPTION 'disposition_round_out_of_order'; END IF;
  IF TG_OP='INSERT' THEN UPDATE disposition_jobs SET current_review_round=NEW.round_number,version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=job.id; END IF;
 ELSIF TG_TABLE_NAME='disposition_review_decisions' THEN
  NEW.decided_at:=CURRENT_TIMESTAMP;
  IF TG_OP<>'INSERT' OR NEW.actor_user_id<>uid OR NEW.acting_role_id<>(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()) OR NOT EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.id=NEW.task_id AND t.job_id=NEW.job_id AND t.workflow_stage=NEW.review_stage AND (t.claimed_by_user_id=uid OR (t.destination_user_id=uid AND t.task_state='open')) AND (t.destination_role_id IS NULL OR EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=t.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)))) THEN RAISE EXCEPTION 'disposition_decision_context_invalid'; END IF;
  IF NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id) THEN RAISE EXCEPTION 'disposition_review_snapshot_stale'; END IF;
  IF NEW.membership_snapshot IS DISTINCT FROM (SELECT membership_snapshot FROM disposition_review_rounds WHERE id=NEW.round_id) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
 ELSIF TG_TABLE_NAME='disposition_job_documents' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.created_by_user_id<>uid THEN RAISE EXCEPTION 'disposition_document_actor_mismatch'; END IF;
   NEW.date_created:=CURRENT_TIMESTAMP;
  END IF;
  IF TG_OP='UPDATE' AND (NEW.document_type<>OLD.document_type OR NEW.review_round IS DISTINCT FROM OLD.review_round OR NEW.created_by_user_id<>OLD.created_by_user_id OR NEW.date_created<>OLD.date_created) THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
  IF NEW.record_id IS NOT NULL AND NOT current_user_can_view_record(NEW.record_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  IF NEW.digital_component_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM digital_components c WHERE c.id=NEW.digital_component_id AND c.record_id=NEW.record_id AND (NEW.document_state<>'available' OR (c.checksum_algo=NEW.checksum_algo AND c.checksum_value=NEW.checksum))) THEN RAISE EXCEPTION 'disposition_document_component_mismatch'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.guard_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous jsonb; following jsonb; fields text[] := ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id']; operation text; inherited smallint;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.hook_applying() THEN
  IF NOT EXISTS(SELECT 1 FROM disposition_private.recalculation_context c WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid() AND c.applying
   AND c.root_id=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN NEW.id ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END) AND c.target_status=NEW.disposition_status)
   OR (to_jsonb(NEW)-ARRAY['disposition_status','version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN RAISE EXCEPTION 'disposition_recalculation_scope_invalid'; END IF;
 END IF;
 IF TG_OP='UPDATE' AND disposition_private.context_operation()='eligibility_evaluate' AND current_setting('app.actor_type',true)='automated_process' THEN
  PERFORM disposition_private.require_command();
  IF disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN NEW.id ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END)
   IS DISTINCT FROM (SELECT (r.payload->>'root_id')::bigint FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())
   OR OLD.disposition_status<>1 OR NEW.disposition_status NOT BETWEEN 2 AND 5
   OR (to_jsonb(NEW)-ARRAY['disposition_status','version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_automated_scope_invalid'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN
  IF OLD.disposition_status<>1 OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END) THEN
   RAISE EXCEPTION 'disposition_history_preserved'; END IF;
  RETURN OLD;
 END IF;
 following:=to_jsonb(NEW);
 IF TG_OP='INSERT' THEN
  IF NEW.disposition_status<>1 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
  SELECT disposition_status INTO inherited FROM aggregations WHERE id=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN (to_jsonb(NEW)->>'parent_aggregation_id')::bigint ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END);
  IF inherited BETWEEN 2 AND 5 THEN NEW.disposition_status:=inherited; END IF;
  IF (
   NEW.final_disposition_at IS NOT NULL OR NEW.final_disposition_by_user_id IS NOT NULL OR NEW.disposition_job_id IS NOT NULL
   OR NEW.destruction_number IS NOT NULL OR NEW.transfer_number IS NOT NULL OR NEW.final_disposition_event_id IS NOT NULL) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
  RETURN NEW;
 END IF;
 previous:=to_jsonb(OLD);
 IF (SELECT jsonb_object_agg(key,value) FROM jsonb_each(previous) WHERE key=ANY(fields)) IS DISTINCT FROM
    (SELECT jsonb_object_agg(key,value) FROM jsonb_each(following) WHERE key=ANY(fields)) THEN
  PERFORM disposition_private.require_command();
  operation:=disposition_private.context_operation();
  IF OLD.disposition_status IN (10,11,12) OR NOT disposition_private.allowed_transition(OLD.disposition_status,NEW.disposition_status,operation) THEN
   RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
 ELSIF OLD.disposition_status IN (10,11,12) AND following IS DISTINCT FROM previous THEN RAISE EXCEPTION 'disposition_final_resource_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.protection_blockers(p_root bigint,p_at timestamptz DEFAULT clock_timestamp())
RETURNS TABLE(resource_kind text,resource_id bigint,is_vital boolean,security_blocked boolean,hold_ids bigint[])
LANGUAGE sql STABLE AS $$
 WITH unit AS (SELECT disposition_private.unit_ids(p_root) id), resources AS (
  SELECT 'aggregation'::text kind,a.id,a.is_vital,a.security_level_id FROM aggregations a JOIN unit ON unit.id=a.id
  UNION ALL SELECT 'record',r.id,r.is_vital,r.security_level_id FROM records r JOIN unit ON unit.id=r.aggregation_id
 ), checked AS (
  SELECT r.*,s.prevents_disposition,
   CASE WHEN r.kind='aggregation' THEN ARRAY(SELECT h.hold_id FROM effective_holds_for_aggregation(r.id,p_at) h ORDER BY h.hold_id LIMIT 26)
   ELSE ARRAY(SELECT h.hold_id FROM effective_holds_for_record(r.id,p_at) h ORDER BY h.hold_id LIMIT 26) END holds
  FROM resources r JOIN security_levels s ON s.id=r.security_level_id)
 SELECT kind,id,is_vital,prevents_disposition,holds FROM checked
 WHERE is_vital OR prevents_disposition OR cardinality(holds)>0
$$;

CREATE OR REPLACE FUNCTION disposition_private.check_unit_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root bigint;
BEGIN
 IF TG_TABLE_NAME='disposition_job_memberships' THEN
  PERFORM disposition_private.assert_unit(disposition_private.root_id(NEW.root_aggregation_id));
 ELSIF TG_TABLE_NAME='disposition_jobs' THEN
  IF NEW.current_review_round>0 AND NOT EXISTS(SELECT 1 FROM disposition_review_rounds WHERE job_id=NEW.id AND round_number=NEW.current_review_round) THEN RAISE EXCEPTION 'disposition_review_round_missing'; END IF;
  FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=NEW.id LOOP
   PERFORM disposition_private.assert_unit(disposition_private.root_id(root));
  END LOOP;
 ELSE
  root:=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN NEW.id ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END);
  PERFORM disposition_private.assert_unit(root);
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER aggregations_disposition_hierarchy_consistency AFTER UPDATE ON aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.parent_aggregation_id IS DISTINCT FROM NEW.parent_aggregation_id) EXECUTE FUNCTION disposition_private.check_unit_trigger();
CREATE CONSTRAINT TRIGGER aggregations_disposition_insert_consistency AFTER INSERT ON aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();
CREATE CONSTRAINT TRIGGER records_disposition_insert_consistency AFTER INSERT ON records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE FUNCTION disposition_private.require_job_person(p_user bigint,p_type text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id
 JOIN roles r ON r.id=a.role_id JOIN profiles profile ON profile.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
 WHERE u.id=p_user AND u.status='active' AND u.account_type='person' AND r.is_information_governance
 AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND p.code='disposition.jobs.manage' AND (p_type<>'destruction' OR profile.code='INFO_GOV_OFFICER')) THEN
 RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_not_authorized'; END IF;
END $$;

CREATE FUNCTION disposition_private.require_progress(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' AND removal_required) THEN
 RAISE EXCEPTION 'disposition_removal_required'; END IF;
END $$;
CREATE FUNCTION disposition_private.require_membership_stage(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE;
BEGIN
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job;
 IF job.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF job.job_type='destruction' AND job.workflow_stage NOT IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') THEN
 RAISE EXCEPTION 'disposition_membership_stage_invalid'; END IF;
END $$;

CREATE FUNCTION disposition_private.assert_admission(p_job bigint,p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; root aggregations%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 PERFORM disposition_private.lock_current_blockers(p_root);
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 PERFORM disposition_private.require_membership_stage(p_job);
 IF NOT current_user_can_view_aggregation(p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF job.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_assignment_required'; END IF;
 PERFORM disposition_private.require_job_person(job.assigned_user_id,job.job_type);
 IF NOT user_can_view_aggregation(job.assigned_user_id,p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_access_required'; END IF;
 IF root.date_closed IS NULL THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
 IF root.disposition_status NOT BETWEEN 2 AND 5 OR root.disposition_status<>job.disposition_status-4 THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(p_root)) THEN RAISE EXCEPTION 'disposition_admission_blocked'; END IF;
 IF job.job_type='destruction' AND NOT EXISTS(WITH RECURSIVE owners AS (
 SELECT id,parent_org_unit_id FROM org_units WHERE id=root.owning_org_unit_id
 UNION ALL SELECT p.id,p.parent_org_unit_id FROM org_units p JOIN owners c ON p.id=c.parent_org_unit_id)
 SELECT 1 FROM owners WHERE id=job.owning_org_unit_id) THEN RAISE EXCEPTION 'disposition_owning_unit_mismatch'; END IF;
END $$;

-- SQL identity compares the effective rule's definition/provenance, not a
-- hierarchy depth or incidental version/timestamp. A move under the same
-- inherited rule must not undo acceleration or change membership.
CREATE FUNCTION disposition_private.rule_identity(p_evaluation jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT jsonb_build_array(p_evaluation#>'{rule_snapshot,rule_source}',p_evaluation#>'{rule_snapshot,rule_id}',
 p_evaluation#>'{rule_snapshot,defined_by_classification_id}',p_evaluation#>'{rule_snapshot,current_period_years}',
 p_evaluation#>'{rule_snapshot,intermediate_period_years}',p_evaluation#>'{rule_snapshot,final_disposition}',
 p_evaluation#>'{rule_snapshot,instructions}',p_evaluation#>'{rule_snapshot,justification}')
$$;
CREATE FUNCTION disposition_private.capture_recalculation(p_root bigint,p_cause text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE previous jsonb; status smallint;
BEGIN
 SELECT disposition_status INTO status FROM aggregations WHERE id=p_root AND parent_aggregation_id IS NULL;
 IF status NOT BETWEEN 1 AND 9 OR status IS NULL THEN RETURN; END IF;
 BEGIN
  SELECT to_jsonb(e) INTO previous FROM disposition_private.eligibility(p_root) e;
 EXCEPTION WHEN datetime_field_overflow OR numeric_value_out_of_range THEN
  -- A pre-055 policy may contain an unrepresentable due date. Preserve its
  -- rule/provenance and explicit calculation failure so an authorized repair
  -- can succeed. A new invalid result still fails the entire policy change.
  SELECT jsonb_build_object('root_id',a.id,'date_closed',a.date_closed,'database_now',CURRENT_TIMESTAMP,
   'calculated_disposition_at',NULL,'calculation_error','unrepresentable_due_timestamp',
   'rule_snapshot',to_jsonb(rule)||jsonb_build_object('definition',CASE rule.rule_source
    WHEN 'aggregation' THEN (SELECT to_jsonb(r) FROM aggregation_retention_rules r WHERE r.id=rule.rule_id)
    ELSE (SELECT to_jsonb(r) FROM classification_retention_rules r WHERE r.id=rule.rule_id) END))
  INTO previous FROM aggregations a CROSS JOIN LATERAL aggregation_effective_retention_rule(a.id) rule WHERE a.id=p_root;
 END;
 INSERT INTO disposition_private.recalculation_context(transaction_id,backend_id,root_id,old_evaluation,old_status,cause)
 VALUES(txid_current(),pg_backend_pid(),p_root,previous,status,p_cause) ON CONFLICT DO NOTHING;
END $$;
CREATE FUNCTION disposition_private.apply_recalculation(p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE context disposition_private.recalculation_context%ROWTYPE; evaluation record; root aggregations%ROWTYPE;
 member disposition_job_memberships%ROWTYPE; job disposition_jobs%ROWTYPE; target integer; required boolean:=false; why text; matched boolean; metadata jsonb;
BEGIN
 SELECT * INTO context FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT * INTO root FROM aggregations WHERE id=p_root FOR UPDATE;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 IF root.parent_aggregation_id IS NOT NULL THEN
 DELETE FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root; RETURN; END IF;
 IF context.cause<>'reopened' AND disposition_private.rule_identity(context.old_evaluation)=disposition_private.rule_identity(to_jsonb(evaluation)) THEN
 IF context.cause='hierarchy_changed' AND EXISTS(
  SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>root.disposition_status
  UNION ALL SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>root.disposition_status) THEN
  UPDATE disposition_private.recalculation_context SET applying=true,target_status=root.disposition_status WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root;
  PERFORM disposition_private.transition_unit(p_root,root.version,root.disposition_status);
  PERFORM append_domain_event('aggregation',p_root,'DISPOSITION_RECALCULATED',jsonb_build_object('old_evaluation',context.old_evaluation,'new_evaluation',to_jsonb(evaluation),'cause','hierarchy_changed','status',root.disposition_status,'effective_rule_unchanged',true));
 END IF;
 DELETE FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root; RETURN; END IF;
 IF context.cause='reopened' THEN target:=1;
 ELSE target:=CASE WHEN evaluation.is_due THEN evaluation.eligible_status ELSE 1 END; target:=COALESCE(target,1); END IF;
 SELECT * INTO member FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active' FOR UPDATE;
 IF FOUND THEN
 SELECT * INTO job FROM disposition_jobs WHERE id=member.job_id FOR UPDATE;
 matched:=target=job.disposition_status-4;
 IF context.cause='reopened' OR member.removal_required_reason='reopened' THEN required:=true;why:='reopened';target:=1;
 ELSIF matched THEN target:=job.disposition_status;
 ELSE required:=true;why:='retention_rule_changed'; END IF;
 END IF;
 UPDATE disposition_private.recalculation_context SET applying=true,target_status=target WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root;
 IF member.id IS NOT NULL THEN
 UPDATE disposition_job_memberships SET removal_required=required,removal_required_reason=why WHERE id=member.id;
 END IF;
 PERFORM disposition_private.transition_unit(p_root,root.version,target);
 metadata:=jsonb_build_object('old_evaluation',context.old_evaluation,'new_evaluation',to_jsonb(evaluation),
 'old_status',context.old_status,'new_status',target,'job_id',member.job_id,'action_matches_job',matched,
 'removal_required',required,'removal_required_reason',why,'cause',context.cause);
 PERFORM append_domain_event('aggregation',p_root,CASE WHEN context.cause='reopened' THEN 'DISPOSITION_REOPENED' ELSE 'DISPOSITION_RECALCULATED' END,metadata);
 IF member.id IS NOT NULL AND required THEN PERFORM append_domain_event('disposition_job',member.job_id,'DISPOSITION_REMOVAL_REQUIRED',jsonb_build_object('root_id',p_root,'membership_id',member.id,'reason',why,'status',target)); END IF;
 DELETE FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root;
END $$;

CREATE FUNCTION disposition_private.coordinate_policy_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock(7357,1); PERFORM lock_hold_policy_shared(); RETURN NULL; END $$;
CREATE FUNCTION disposition_private.capture_policy_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root bigint; old_root bigint; classifications_changed bigint[]; cause text:='retention_rule_changed';
BEGIN
 IF disposition_private.hook_applying() THEN RETURN COALESCE(NEW,OLD); END IF;
 IF TG_TABLE_NAME='aggregations' THEN
  IF NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id THEN
   old_root:=disposition_private.root_id(OLD.id);
   IF OLD.parent_aggregation_id IS NULL AND EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=OLD.id AND membership_state='active') THEN RAISE EXCEPTION 'disposition_active_root_move_requires_removal'; END IF;
   PERFORM disposition_private.capture_recalculation(old_root,'hierarchy_changed');
   IF NEW.parent_aggregation_id IS NULL THEN
    INSERT INTO disposition_private.recalculation_context(transaction_id,backend_id,root_id,old_evaluation,old_status,cause)
    SELECT txid_current(),pg_backend_pid(),OLD.id,to_jsonb(e),OLD.disposition_status,'hierarchy_changed' FROM disposition_private.eligibility(old_root) e ON CONFLICT DO NOTHING;
   ELSE PERFORM disposition_private.capture_recalculation(disposition_private.root_id(NEW.parent_aggregation_id),'hierarchy_changed'); END IF;
   RETURN NEW;
  END IF;
  IF OLD.date_closed IS NOT NULL AND NEW.date_closed IS NULL AND OLD.parent_aggregation_id IS NULL THEN cause:='reopened';
   IF NOT current_user_can_aggregation_operation(OLD.id,'aggregation.reopen','aggregation.reopen') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_reopen_authorization_required'; END IF;
  ELSIF NEW.classification_id IS DISTINCT FROM OLD.classification_id AND OLD.parent_aggregation_id IS NULL AND NEW.parent_aggregation_id IS NULL THEN
   IF NOT current_user_can_aggregation_operation(OLD.id,'aggregation.reclassify','aggregation.reclassify') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_reclassify_authorization_required'; END IF;
  ELSE RETURN NEW; END IF;
  PERFORM disposition_private.capture_recalculation(OLD.id,cause);
 ELSE
  IF TG_TABLE_NAME='classifications' THEN
   IF NEW.parent_classification_id IS NOT DISTINCT FROM OLD.parent_classification_id THEN RETURN NEW; END IF;
  END IF;
  IF TG_TABLE_NAME='aggregation_retention_rules' THEN
   FOR root IN SELECT DISTINCT id FROM (VALUES ((to_jsonb(NEW)->>'aggregation_id')::bigint),((to_jsonb(OLD)->>'aggregation_id')::bigint)) targets(id) WHERE id IS NOT NULL
   LOOP PERFORM disposition_private.capture_recalculation(root,cause); END LOOP;
  ELSE
   classifications_changed:=CASE WHEN TG_TABLE_NAME='classifications' THEN ARRAY[OLD.id] ELSE ARRAY[(to_jsonb(NEW)->>'classification_id')::bigint,(to_jsonb(OLD)->>'classification_id')::bigint] END;
   FOR root IN WITH RECURSIVE classes AS (SELECT id FROM classifications WHERE id=ANY(classifications_changed)
    UNION SELECT child.id FROM classifications child JOIN classes parent ON child.parent_classification_id=parent.id)
    SELECT a.id FROM aggregations a WHERE a.parent_aggregation_id IS NULL AND a.classification_id IN (SELECT id FROM classes)
    AND NOT EXISTS(SELECT 1 FROM aggregation_retention_rules WHERE aggregation_id=a.id) ORDER BY a.id
   LOOP PERFORM disposition_private.capture_recalculation(root,cause); END LOOP;
  END IF;
  IF EXISTS(SELECT 1 FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid()) THEN
   IF NOT user_has_global_privilege(current_user_id(),'classifications.administer') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_retention_authorization_required'; END IF;
  END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid()) AND NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN RAISE EXCEPTION 'disposition_reason_required'; END IF;
 RETURN COALESCE(NEW,OLD);
END $$;
CREATE FUNCTION disposition_private.finish_policy_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root bigint;
BEGIN
 IF disposition_private.hook_applying() THEN RETURN NULL; END IF;
 FOR root IN SELECT root_id FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() ORDER BY root_id
 LOOP PERFORM disposition_private.apply_recalculation(root); END LOOP;
 RETURN NULL;
END $$;
CREATE TRIGGER disposition_policy_coordination BEFORE INSERT OR UPDATE OR DELETE ON classification_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();
CREATE TRIGGER disposition_policy_coordination BEFORE INSERT OR UPDATE OR DELETE ON aggregation_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();
CREATE TRIGGER disposition_policy_coordination BEFORE UPDATE ON classifications FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();
CREATE TRIGGER disposition_policy_coordination BEFORE UPDATE OF date_closed,classification_id,parent_aggregation_id ON aggregations FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();
CREATE TRIGGER disposition_recalculation_capture BEFORE INSERT OR UPDATE OR DELETE ON classification_retention_rules FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();
CREATE TRIGGER disposition_recalculation_capture BEFORE INSERT OR UPDATE OR DELETE ON aggregation_retention_rules FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();
CREATE TRIGGER disposition_recalculation_capture BEFORE UPDATE ON classifications FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();
CREATE TRIGGER disposition_recalculation_capture BEFORE UPDATE OF date_closed,classification_id,parent_aggregation_id ON aggregations FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();
-- Statement completion sees every changed policy row, including multi-row DML.
CREATE TRIGGER disposition_recalculation_apply AFTER INSERT OR UPDATE OR DELETE ON classification_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();
CREATE TRIGGER disposition_recalculation_apply AFTER INSERT OR UPDATE OR DELETE ON aggregation_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();
CREATE TRIGGER disposition_recalculation_apply AFTER UPDATE ON classifications FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();
CREATE TRIGGER disposition_recalculation_apply AFTER UPDATE OF date_closed,classification_id,parent_aggregation_id ON aggregations FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();

CREATE FUNCTION disposition_private.create_job(p_number text,p_type text,p_owner bigint,p_assignee bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_create' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 INSERT INTO disposition_jobs(job_number,job_type,owning_org_unit_id,assigned_user_id,created_by_user_id,workflow_stage,disposition_status)
 VALUES(p_number,p_type,p_owner,p_assignee,current_user_id(),CASE WHEN p_type='destruction' THEN 'officer_preparation' END,
 CASE p_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 WHEN 'local_archives' THEN 9 END) RETURNING * INTO job;
 RETURN to_jsonb(job);
END $$;
CREATE FUNCTION disposition_private.assign_job(p_job bigint,p_version integer,p_assignee bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_assign' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 UPDATE disposition_jobs SET assigned_user_id=p_assignee WHERE id=p_job RETURNING * INTO job;
 RETURN to_jsonb(job);
END $$;
CREATE FUNCTION disposition_private.change_job_owner(p_job bigint,p_version integer,p_owner bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_owner_change' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF job.job_type<>'destruction' THEN RAISE EXCEPTION 'disposition_owning_unit_change_invalid'; END IF;
 UPDATE disposition_jobs SET owning_org_unit_id=p_owner WHERE id=p_job RETURNING * INTO job;
 RETURN to_jsonb(job);
END $$;
CREATE FUNCTION disposition_private.add_items(p_job bigint,p_version integer,p_items jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; item jsonb; root aggregations%ROWTYPE; member bigint; results jsonb:='[]'; code text;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'membership_add' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 IF jsonb_typeof(p_items)<>'array' OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'disposition_selection_bounds_invalid'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
  BEGIN
   SELECT * INTO root FROM aggregations WHERE id=(item->>'root_id')::bigint AND current_user_can_view_aggregation(id) FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF root.version<>(item->>'expected_version')::bigint THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
   INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id) VALUES(p_job,root.id,current_user_id()) RETURNING id INTO member;
   PERFORM disposition_private.transition_unit(root.id,root.version,job.disposition_status);
   PERFORM disposition_private.assert_unit(root.id);
   results:=results||jsonb_build_array(jsonb_build_object('root_id',root.id,'success',true,'membership_id',member));
  EXCEPTION WHEN SQLSTATE 'P0001' OR SQLSTATE '42501' OR unique_violation OR SQLSTATE '40001' THEN
   GET STACKED DIAGNOSTICS code=MESSAGE_TEXT;
   IF code NOT IN ('disposition_resource_access_required','disposition_stale_version','disposition_assignment_required','disposition_assignee_not_authorized','disposition_assignee_access_required','disposition_root_not_closed','disposition_job_type_status_mismatch','disposition_admission_blocked','disposition_owning_unit_mismatch','disposition_requires_governing_root','disposition_membership_stage_invalid','disposition_already_completed','disposition_inactive_job') THEN code:='disposition_item_not_added'; END IF;
   results:=results||jsonb_build_array(jsonb_build_object('root_id',item->'root_id','success',false,'code',code));
  END;
 END LOOP;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job;
 RETURN jsonb_build_object('items',results,'job_version',job.version);
END $$;
CREATE FUNCTION disposition_private.remove_member(p_member bigint,p_version integer,p_root_version bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE member disposition_job_memberships%ROWTYPE; job disposition_jobs%ROWTYPE; root aggregations%ROWTYPE; target integer;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'membership_remove' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO member FROM disposition_job_memberships WHERE id=p_member FOR UPDATE;
 IF NOT FOUND OR member.version<>p_version OR member.membership_state<>'active' THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=member.job_id FOR UPDATE;
 SELECT * INTO root FROM aggregations WHERE id=member.root_aggregation_id FOR UPDATE;
 IF root.version<>p_root_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 target:=CASE WHEN member.removal_required THEN root.disposition_status ELSE job.disposition_status-4 END;
 PERFORM disposition_private.transition_unit(root.id,root.version,target);
 UPDATE disposition_job_memberships SET membership_state='removed',removal_reason=current_setting('app.change_reason',true) WHERE id=member.id;
 PERFORM disposition_private.assert_unit(root.id);
 RETURN jsonb_build_object('membership_id',member.id,'root_id',root.id,'status',target);
END $$;
CREATE FUNCTION disposition_private.accelerate(p_root bigint,p_version bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; evaluation record;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'eligibility_accelerate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 PERFORM disposition_private.lock_current_blockers(p_root);
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 IF root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF NOT current_user_can_view_aggregation(p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.disposition_status<>1 OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active') THEN RAISE EXCEPTION 'disposition_acceleration_state_invalid'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(p_root)) THEN RAISE EXCEPTION 'disposition_admission_blocked'; END IF;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 IF evaluation.eligible_status IS NULL THEN RAISE EXCEPTION 'disposition_retention_rule_required'; END IF;
 PERFORM disposition_private.transition_unit(p_root,root.version,evaluation.eligible_status);
 PERFORM append_domain_event('aggregation',p_root,'DISPOSITION_ACCELERATED',to_jsonb(evaluation));
 RETURN jsonb_build_object('root_id',p_root,'status',evaluation.eligible_status);
END $$;
CREATE FUNCTION disposition_private.terminate_job(p_job bigint,p_version integer,p_confirm boolean) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; member record; root aggregations%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_terminate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 IF p_confirm IS DISTINCT FROM true THEN RAISE EXCEPTION 'disposition_confirmation_required'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF job.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF job.workflow_stage IN ('digital_destruction','certificate_generation') THEN RAISE EXCEPTION 'disposition_irreversible_termination_not_implemented'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 FOR member IN SELECT * FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' ORDER BY root_aggregation_id FOR UPDATE LOOP
 SELECT * INTO root FROM aggregations WHERE id=member.root_aggregation_id FOR UPDATE;
 IF root.disposition_status NOT BETWEEN 1 AND 9 THEN RAISE EXCEPTION 'disposition_irreversible_termination_not_implemented'; END IF;
 IF NOT member.removal_required THEN PERFORM disposition_private.transition_unit(root.id,root.version,job.disposition_status-4); END IF;
 UPDATE disposition_job_memberships SET membership_state='terminated_history' WHERE id=member.id;
 END LOOP;
 UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_state IN ('open','claimed');
 UPDATE disposition_jobs SET lifecycle_state='terminated',disposition_status=job.disposition_status-4,termination_reason=current_setting('app.change_reason',true) WHERE id=p_job RETURNING * INTO job;
 RETURN to_jsonb(job);
END $$;
CREATE OR REPLACE FUNCTION disposition_private.audit_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE before_state jsonb; after_state jsonb; command disposition_private.command_receipts%ROWTYPE;
BEGIN
 before_state:=CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) END;
 after_state:=to_jsonb(NEW);
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM append_domain_event(CASE TG_TABLE_NAME WHEN 'disposition_jobs' THEN 'disposition_job' WHEN 'disposition_job_memberships' THEN 'disposition_job_membership' WHEN 'disposition_tasks' THEN 'disposition_task' WHEN 'disposition_review_rounds' THEN 'disposition_review_round' WHEN 'disposition_review_decisions' THEN 'disposition_review_decision' ELSE 'disposition_job_document' END,
 NEW.id, CASE WHEN disposition_private.hook_applying() THEN 'DISPOSITION_RECALCULATED' ELSE upper(command.operation) END, jsonb_build_object('command_id',command.command_id,'acting_role_id',command.acting_role_id,'before',before_state,'after',after_state),command.reason);
 RETURN NULL;
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('055_disposition_membership');
COMMIT;
