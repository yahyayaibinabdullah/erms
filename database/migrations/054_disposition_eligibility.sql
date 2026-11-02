BEGIN;
SELECT set_config('app.user_id','',true),
       set_config('app.actor_type','automated_process',true),
       set_config('app.actor_name','Database migration 054',true),
       set_config('app.event_source','migration',true),
       set_config('app.change_reason','Install approved disposition eligibility and current blocker queries',true);

-- Existing human command receipts retain their identity. Automation is limited
-- to the scheduled eligibility operation, with no fabricated user or role.
ALTER TABLE disposition_private.command_receipts
 ALTER COLUMN actor_user_id DROP NOT NULL,
 ALTER COLUMN acting_role_id DROP NOT NULL,
 ADD COLUMN actor_type text NOT NULL DEFAULT 'user',
 ADD CONSTRAINT disposition_command_actor CHECK (
  (actor_type='user' AND actor_user_id IS NOT NULL AND acting_role_id IS NOT NULL)
  OR (actor_type='automated_process' AND actor_user_id IS NULL AND acting_role_id IS NULL AND operation='eligibility_evaluate'));

CREATE OR REPLACE FUNCTION disposition_private.context_operation() RETURNS text LANGUAGE sql STABLE AS $$
 SELECT r.operation FROM disposition_private.command_context c
 JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid()
   AND r.actor_user_id IS NOT DISTINCT FROM current_user_id()
   AND r.actor_type=current_setting('app.actor_type',true) AND r.completed_at IS NULL
$$;
CREATE OR REPLACE FUNCTION disposition_private.require_command() RETURNS void LANGUAGE plpgsql AS $$
DECLARE command disposition_private.command_receipts%ROWTYPE;
BEGIN
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

CREATE FUNCTION disposition_private.can_manage() RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id
  JOIN roles r ON r.id=a.role_id JOIN profile_privileges pp ON pp.profile_id=r.profile_id
  JOIN privileges p ON p.id=pp.privilege_id AND p.code='disposition.jobs.manage'
  WHERE u.id=current_user_id() AND u.account_type='person' AND u.status='active'
   AND r.is_information_governance AND role_effectively_active(r.id)
   AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))
$$;

CREATE FUNCTION disposition_private.eligibility(p_root bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS TABLE(root_id bigint,date_closed timestamptz,rule_snapshot jsonb,calculated_disposition_at timestamptz,
 database_now timestamptz,eligible_status smallint,is_due boolean)
LANGUAGE sql STABLE AS $$
 SELECT a.id,a.date_closed,
  to_jsonb(rule)||jsonb_build_object('definition',CASE rule.rule_source
   WHEN 'aggregation' THEN (SELECT to_jsonb(r) FROM aggregation_retention_rules r WHERE r.id=rule.rule_id)
   ELSE (SELECT to_jsonb(r) FROM classification_retention_rules r WHERE r.id=rule.rule_id) END),
  due.at_time,p_at,
  CASE rule.final_disposition WHEN 'destruction' THEN 2 WHEN 'transfer_to_external_archive' THEN 3
   WHEN 'selective_preservation' THEN 4 WHEN 'retain_as_local_archives' THEN 5 END::smallint,
  COALESCE(a.date_closed IS NOT NULL AND p_at>due.at_time,false)
 FROM aggregations a LEFT JOIN LATERAL aggregation_effective_retention_rule(a.id) rule ON true
 LEFT JOIN LATERAL (SELECT ((a.date_closed AT TIME ZONE 'UTC')+
  make_interval(years=>(rule.current_period_years::bigint+rule.intermediate_period_years)::integer)) AT TIME ZONE 'UTC' AS at_time) due ON true
 WHERE a.id=p_root AND a.parent_aggregation_id IS NULL
$$;
CREATE INDEX disposition_eligibility_scan ON aggregations(id) WHERE parent_aggregation_id IS NULL AND disposition_status=1 AND date_closed IS NOT NULL;

-- Raw server-only rows. Authorization/redaction/pagination are applied by the
-- common blocker service before any row can be returned to a person. Hold IDs
-- are a bounded preview (25 plus a continuation sentinel), never an exhaustive
-- authority to remove holds. Any nonempty preview is a full blocker fact.
CREATE FUNCTION disposition_private.protection_blockers(p_root bigint,p_at timestamptz DEFAULT statement_timestamp())
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

CREATE FUNCTION disposition_private.relationship_scope(p_root bigint)
RETURNS TABLE(resource_kind text,relationship_id bigint,relationship_type_id bigint,source_id bigint,target_id bigint,
 source_root_id bigint,target_root_id bigint,is_internal boolean,is_same_job boolean,blocks_final boolean)
LANGUAGE sql STABLE AS $$
 WITH unit AS (SELECT disposition_private.unit_ids(p_root) id), links AS (
  SELECT 'aggregation'::text kind,l.id,l.relationship_type_id,l.source_id,l.target_id,
   disposition_private.root_id(l.source_id) source_root,disposition_private.root_id(l.target_id) target_root
  FROM aggregation_relationships l WHERE l.source_id IN (SELECT id FROM unit) OR l.target_id IN (SELECT id FROM unit)
  UNION ALL
  SELECT 'record',l.id,l.relationship_type_id,l.source_id,l.target_id,
   disposition_private.root_id(s.aggregation_id),disposition_private.root_id(t.aggregation_id)
  FROM record_relationships l JOIN records s ON s.id=l.source_id JOIN records t ON t.id=l.target_id
  WHERE s.aggregation_id IN (SELECT id FROM unit) OR t.aggregation_id IN (SELECT id FROM unit)
 ), scoped AS (
  SELECT l.*,l.source_root=l.target_root internal,
   EXISTS(SELECT 1 FROM disposition_job_memberships a JOIN disposition_job_memberships b ON b.job_id=a.job_id
    JOIN disposition_jobs j ON j.id=a.job_id AND j.lifecycle_state='active'
    WHERE a.root_aggregation_id=l.source_root AND b.root_aggregation_id=l.target_root
     AND a.membership_state='active' AND b.membership_state='active') same_job FROM links l)
 SELECT kind,id,relationship_type_id,source_id,target_id,source_root,target_root,internal,same_job,NOT(internal OR same_job) FROM scoped
$$;

CREATE OR REPLACE FUNCTION disposition_private.guard_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous jsonb; following jsonb; fields text[] := ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id']; operation text;
BEGIN
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
  IF NEW.disposition_status<>1 OR (
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

DROP FUNCTION disposition_private.transition_unit(bigint,integer,integer);
CREATE FUNCTION disposition_private.transition_unit(p_root bigint,p_version bigint,p_status integer)
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
 IF root.date_closed IS NULL AND p_status<>1 THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 IF current_setting('app.actor_type',true)='user' AND NOT user_can_view_aggregation(uid,p_root) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.disposition_status=p_status THEN RETURN; END IF;
 event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_STATUS_CHANGED',jsonb_build_object(
  'old_status',root.disposition_status,'new_status',p_status,'operation',op,
  'command_id',(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())));
 UPDATE aggregations SET disposition_status=p_status WHERE id IN (SELECT disposition_private.unit_ids(p_root));
 UPDATE records SET disposition_status=p_status WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
END $$;

CREATE OR REPLACE FUNCTION protect_held_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE blocked boolean;
DECLARE allowed_old jsonb;
DECLARE allowed_new jsonb;
BEGIN
    PERFORM lock_hold_policy_shared();
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

-- The same job/membership coordination lock is used by relationship writers
-- before endpoint locks. It covers both directions/types and direct SQL writes.
CREATE FUNCTION disposition_private.coordinate_relationship_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock(7357,1); RETURN NULL; END $$;
CREATE TRIGGER disposition_relationship_coordination BEFORE INSERT OR UPDATE OR DELETE ON aggregation_relationships FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_relationship_change();
CREATE TRIGGER disposition_relationship_coordination BEFORE INSERT OR UPDATE OR DELETE ON record_relationships FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_relationship_change();

CREATE FUNCTION disposition_private.lock_current_blockers(p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 PERFORM lock_hold_policy_shared();
 PERFORM 1 FROM aggregations WHERE id=p_root AND parent_aggregation_id IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM security_levels WHERE id IN (
  SELECT security_level_id FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root))
  UNION SELECT security_level_id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))) ORDER BY id FOR SHARE;
END $$;

-- There is deliberately no caller-supplied clock or status in this mutation.
CREATE FUNCTION disposition_private.evaluate_root(p_root bigint,p_command uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
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
 IF NOT FOUND OR root.parent_aggregation_id IS NOT NULL OR root.disposition_status<>1 OR root.date_closed IS NULL THEN
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

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('054_disposition_eligibility');
COMMIT;
