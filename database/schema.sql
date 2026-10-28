-- Wathiq: canonical current PostgreSQL schema.
-- Final object definitions only. Historical upgrades belong in migrations/.
-- Required reference data: seeds/000_required_reference_data.sql (run separately).
-- Fresh-install version bookkeeping: baseline.sql (run separately).
-- PostgreSQL 18 or later is required (including the Arabic text-search config).
BEGIN;
DO $$ BEGIN
    IF current_setting('server_version_num')::integer < 180000
       OR EXISTS(SELECT 1 FROM (VALUES ('simple'),('english'),('arabic')) required(name)
                 WHERE NOT EXISTS(SELECT 1 FROM pg_catalog.pg_ts_config c
                     JOIN pg_catalog.pg_namespace n ON n.oid=c.cfgnamespace
                     WHERE n.nspname='pg_catalog' AND c.cfgname=required.name)) THEN
        RAISE EXCEPTION 'Wathiq requires PostgreSQL 18 or later with Arabic text search';
    END IF;
END $$;
SET LOCAL check_function_bodies = false;
SET LOCAL search_path = public, pg_catalog;

CREATE SCHEMA disposition_private;

CREATE COLLATION public.erms_code_natural (provider = icu, locale = 'und-u-kn');

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';

CREATE FUNCTION disposition_private.accelerate(p_root bigint, p_version bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE root aggregations%ROWTYPE; evaluation record;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'eligibility_accelerate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 PERFORM disposition_private.lock_current_blockers(p_root);
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 IF NOT FOUND OR root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF NOT current_user_can_view_aggregation(p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF root.disposition_status<>1 OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active') THEN RAISE EXCEPTION 'disposition_acceleration_state_invalid'; END IF;
 IF root.date_closed IS NULL THEN
  IF NOT current_user_can_aggregation_operation(p_root,'aggregation.close','aggregation.close') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='insufficient_privilege'; END IF;
  UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=p_root RETURNING * INTO root;
 END IF;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 IF evaluation.eligible_status IS NULL THEN RAISE EXCEPTION 'disposition_retention_rule_required'; END IF;
 PERFORM disposition_private.transition_unit(p_root,root.version,evaluation.eligible_status);
 PERFORM append_domain_event('aggregation',p_root,'DISPOSITION_ACCELERATED',to_jsonb(evaluation));
 RETURN jsonb_build_object('root_id',p_root,'status',evaluation.eligible_status);
END $$;

CREATE FUNCTION disposition_private.activate_certificate(p_job bigint, p_request uuid, p_token uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE w disposition_private.completion_work%ROWTYPE;acting bigint;key uuid;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT * INTO w FROM disposition_private.completion_work WHERE job_id=p_job FOR UPDATE;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF disposition_private.context_operation()<>'document_save' OR w.request_id IS DISTINCT FROM p_request OR w.claim_token IS DISTINCT FROM p_token OR w.state IS DISTINCT FROM 'running' OR w.requested_by_user_id IS DISTINCT FROM current_user_id() OR w.acting_role_id IS DISTINCT FROM acting THEN RAISE EXCEPTION 'disposition_certificate_claim_lost'; END IF;
 PERFORM disposition_private.check_completion(p_job,w.task_id,acting);
 INSERT INTO disposition_private.completion_context VALUES(txid_current(),pg_backend_pid(),key,p_job);
END $$;

CREATE FUNCTION disposition_private.activate_request(p_job bigint, p_round bigint, p_document bigint, p_version integer) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;r disposition_review_rounds%ROWTYPE;acting bigint;key uuid;task_id bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.lock_request_facts(p_job);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job;
 SELECT * INTO r FROM disposition_review_rounds WHERE id=p_round AND job_id=p_job;
 IF j.version IS DISTINCT FROM p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF j.lifecycle_state<>'active' OR j.workflow_stage NOT IN ('records_manager_review','manager_preparation','manager_correction') OR r.round_number<>j.current_review_round THEN RAISE EXCEPTION 'disposition_request_stage_invalid'; END IF;
 IF NOT disposition_private.person_role(current_user_id(),acting) OR NOT disposition_private.review_role(j.id,'records_manager_review',acting) OR NOT disposition_private.can_review_content(current_user_id(),j.id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 IF NOT disposition_private.request_approval_current(j.id,r.id) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=p_document AND d.job_id=j.id AND d.document_type='destruction_request' AND d.document_state='available' AND d.review_round=r.round_number AND d.provenance->>'approval_round_id'=r.id::text AND disposition_private.review_fingerprint(d.provenance#>'{snapshot,source,approved_facts}')=disposition_private.review_fingerprint(disposition_private.request_facts(j.id))) THEN RAISE EXCEPTION 'disposition_request_snapshot_invalid'; END IF;
 PERFORM disposition_private.require_preparer(j.assigned_user_id,j.review_route);
 IF NOT disposition_private.can_review_content(j.assigned_user_id,j.id) THEN RAISE EXCEPTION 'disposition_assignee_access_required'; END IF;
 INSERT INTO disposition_private.external_context VALUES(txid_current(),pg_backend_pid(),key,j.id,'request');
 UPDATE disposition_jobs SET workflow_stage='external_approval_pending' WHERE id=j.id;
 INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id,request_document_id)
 VALUES(j.id,'external_approval','external_approval_pending',r.round_number,j.assigned_user_id,p_document) RETURNING id INTO task_id;
 PERFORM append_domain_event('disposition_job',j.id,'DESTRUCTION_REQUEST_GENERATED',jsonb_build_object('after',jsonb_build_object('request_document_id',p_document,'round_id',r.id,'review_round',r.round_number,'task_id',task_id),'acting_role_id',acting));
 DELETE FROM disposition_private.external_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',j.id,'round_id',r.id,'request_document_id',p_document,'task_id',task_id,'request_status','available','workflow_stage','external_approval_pending','job_version',(SELECT version FROM disposition_jobs WHERE id=j.id));
END $$;

CREATE FUNCTION disposition_private.add_items(p_job bigint, p_version integer, p_items jsonb) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
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
   IF code NOT IN ('disposition_assigned_preparer_required','disposition_resource_access_required','disposition_stale_version','disposition_assignment_required','disposition_assignee_not_authorized','disposition_assignee_access_required','disposition_root_not_closed','disposition_job_type_status_mismatch','disposition_admission_blocked','disposition_owning_unit_mismatch','disposition_requires_governing_root','disposition_membership_stage_invalid','disposition_already_completed','disposition_inactive_job') THEN code:='disposition_item_not_added'; END IF;
   results:=results||jsonb_build_array(jsonb_build_object('root_id',item->'root_id','success',false,'code',code));
  END;
 END LOOP;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job;
 RETURN jsonb_build_object('items',results,'job_version',job.version);
END $$;

CREATE FUNCTION disposition_private.allowed_stage(old_stage text, new_stage text) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$
 SELECT old_stage=new_stage OR CASE old_stage
 WHEN 'officer_preparation' THEN new_stage IN ('file_administrator_review','unit_manager_review','records_manager_review')
 WHEN 'officer_correction' THEN new_stage IN ('file_administrator_review','unit_manager_review','records_manager_review')
 WHEN 'file_administrator_review' THEN new_stage='unit_manager_review'
 WHEN 'unit_manager_review' THEN new_stage IN ('officer_correction','records_manager_review')
 WHEN 'records_manager_review' THEN new_stage IN ('officer_correction','external_approval_pending')
 WHEN 'manager_preparation' THEN new_stage='external_approval_pending'
 WHEN 'manager_correction' THEN new_stage='external_approval_pending'
 WHEN 'external_approval_pending' THEN new_stage IN ('officer_correction','manager_correction','physical_destruction','digital_destruction')
 WHEN 'physical_destruction' THEN new_stage IN ('digital_destruction','certificate_generation')
 WHEN 'digital_destruction' THEN new_stage='certificate_generation'
 ELSE false END
$$;

CREATE FUNCTION disposition_private.allowed_transition(old_status integer, new_status integer, cause text) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$
 SELECT old_status=new_status OR CASE cause
 WHEN 'eligibility_evaluate' THEN old_status=1 AND new_status BETWEEN 2 AND 5
 WHEN 'eligibility_accelerate' THEN old_status=1 AND new_status BETWEEN 2 AND 5
 WHEN 'membership_add' THEN (old_status,new_status) IN ((2,6),(3,7),(4,8),(5,9))
 WHEN 'membership_remove' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5))
 WHEN 'job_terminate' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5),(6,13),(6,10))
 WHEN 'resolve_partial' THEN old_status=13 AND new_status BETWEEN 2 AND 5
 WHEN 'selective_decide' THEN old_status=8 AND new_status IN (2,3,5)
 WHEN 'final_complete' THEN (old_status,new_status) IN ((6,10),(7,11),(9,12))
 WHEN 'recalculate' THEN old_status NOT IN (10,11,12,13) AND new_status BETWEEN 1 AND 9
 ELSE false END
$$;

CREATE FUNCTION disposition_private.apply_recalculation(p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.approval_active(p_job bigint DEFAULT NULL::bigint, p_root bigint DEFAULT NULL::bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.approval_context a JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 JOIN disposition_private.command_receipts r USING(command_id) WHERE a.transaction_id=txid_current() AND a.backend_id=pg_backend_pid()
 AND r.operation='review_decide' AND r.completed_at IS NULL AND r.actor_type='user' AND r.actor_user_id=current_user_id()
 AND a.acting_role_id=r.acting_role_id AND (p_job IS NULL OR a.job_id=p_job)
 AND (p_root IS NULL OR EXISTS(SELECT 1 FROM jsonb_array_elements(a.membership_snapshot) s WHERE (s->>'root_id')::bigint=p_root)))
$$;

CREATE FUNCTION disposition_private.approval_event_metadata() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE a disposition_private.approval_context%ROWTYPE;
BEGIN
 IF disposition_private.approval_active() THEN
  SELECT * INTO a FROM disposition_private.approval_context WHERE transaction_id=txid_current();
  NEW.metadata:=COALESCE(NEW.metadata,'{}')||jsonb_build_object('approval_command_id',a.command_id,'job_id',a.job_id,'acting_role_id',a.acting_role_id,
   'proposal_id',a.current_proposal_id,'reason_used',a.reason_used,'reason_source',a.reason_source);
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.approval_preview(p_task bigint, p_role bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE;j disposition_jobs%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_task_actor(p_task,p_role,true);
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task;SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id;
 IF NOT disposition_private.review_role(j.id,'records_manager_review',p_role) OR t.workflow_stage NOT IN ('records_manager_review','manager_preparation','manager_correction') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 RETURN jsonb_build_object('job_id',j.id,'job_version',j.version,'task_version',t.version,
 'membership_token',disposition_private.review_fingerprint(disposition_private.membership_snapshot(j.id)),
 'proposals_token',disposition_private.review_fingerprint(disposition_private.proposal_snapshot(j.id)));
END $$;

CREATE FUNCTION disposition_private.approve_proposals(p_task bigint, p_job_version integer, p_task_version integer, p_membership_token text, p_proposals_token text, p_overall_reason text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE t disposition_tasks%ROWTYPE;j disposition_jobs%ROWTYPE;p disposition_review_proposals%ROWTYPE;other disposition_review_proposals%ROWTYPE;
 rr disposition_review_rounds%ROWTYPE;acting bigint;key uuid;before_members jsonb;before_proposals jsonb;facts jsonb;invalid_ids jsonb:='[]';
 root bigint;selected bigint;created bigint;decision_id bigint;next_round integer;carried bigint;current_reason text;source text;total_reason text;
 baseline_links jsonb:='{}';new_links jsonb:='{}';removed jsonb:='{}';causes jsonb;link record;m record;effect_root text;
 previous_status integer;result_status integer;changed boolean;material_changed boolean;prior_level bigint;changed_holds bigint[];results jsonb:='[]';effect jsonb;execution jsonb;old_metadata text;
BEGIN
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_context(p_task,p_job_version,p_task_version);SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id;
 SELECT r.acting_role_id,r.command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF NOT disposition_private.review_role(j.id,'records_manager_review',acting) OR t.workflow_stage NOT IN ('records_manager_review','manager_preparation','manager_correction') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 PERFORM disposition_private.require_progress(j.id);
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active') THEN RAISE EXCEPTION 'disposition_empty_job'; END IF;
 PERFORM lock_hold_policy_exclusive();
 LOCK TABLE classifications,classification_retention_rules,aggregation_retention_rules,relationship_types,security_levels IN SHARE MODE;
 PERFORM 1 FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active' ORDER BY id FOR UPDATE;
 PERFORM 1 FROM disposition_review_proposals WHERE job_id=j.id ORDER BY id FOR UPDATE;
 -- Freeze full units and all selected relationship endpoints in stable order.
 PERFORM 1 FROM aggregations a WHERE a.id IN (SELECT disposition_private.unit_ids(root_aggregation_id) FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active')
 OR a.id IN (SELECT (v->>'source_id')::bigint FROM disposition_review_proposals p1 CROSS JOIN LATERAL (SELECT p1.current_values->'relationship' v) x WHERE p1.job_id=j.id AND v->>'resource_kind'='aggregation'
 UNION SELECT (v->>'target_id')::bigint FROM disposition_review_proposals p1 CROSS JOIN LATERAL (SELECT p1.current_values->'relationship' v) x WHERE p1.job_id=j.id AND v->>'resource_kind'='aggregation') ORDER BY a.id FOR UPDATE;
 PERFORM 1 FROM records r WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(root_aggregation_id) FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active')
 OR r.id IN (SELECT (v->>'source_id')::bigint FROM disposition_review_proposals p1 CROSS JOIN LATERAL (SELECT p1.current_values->'relationship' v) x WHERE p1.job_id=j.id AND v->>'resource_kind'='record'
 UNION SELECT (v->>'target_id')::bigint FROM disposition_review_proposals p1 CROSS JOIN LATERAL (SELECT p1.current_values->'relationship' v) x WHERE p1.job_id=j.id AND v->>'resource_kind'='record') ORDER BY r.id FOR UPDATE;
 before_members:=disposition_private.membership_snapshot(j.id);before_proposals:=disposition_private.proposal_snapshot(j.id);
 IF p_membership_token IS DISTINCT FROM disposition_private.review_fingerprint(before_members) OR p_proposals_token IS DISTINCT FROM disposition_private.review_fingerprint(before_proposals) THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_approval_stale'; END IF;
 IF j.review_route='records_manager_only' THEN total_reason:=p_overall_reason;
 ELSE
  SELECT * INTO rr FROM disposition_review_rounds WHERE job_id=j.id AND round_number=j.current_review_round FOR UPDATE;
  IF NOT FOUND OR rr.completed_at IS NOT NULL OR rr.invalidated_at IS NOT NULL OR rr.membership_snapshot IS DISTINCT FROM before_members THEN RAISE EXCEPTION 'disposition_review_snapshot_stale'; END IF;
  total_reason:=rr.submission_reason;
 END IF;
 IF total_reason IS NULL OR total_reason ~ '^[[:space:]]*$' THEN RAISE EXCEPTION 'disposition_submission_reason_required'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(before_proposals) v WHERE v->>'proposal_type'='remove_from_job') THEN
  IF j.review_route='records_manager_only' THEN RAISE EXCEPTION 'disposition_marked_removals_require_correction'; ELSE RAISE EXCEPTION 'disposition_marked_removals_require_rejection'; END IF;
 END IF;
 -- Validate every operation before applying any of them, using the approving
 -- person's effective underlying authority, never the proposer's privileges.
 FOR p IN SELECT p1.* FROM disposition_review_proposals p1 WHERE p1.id IN (SELECT (v->>'id')::bigint FROM jsonb_array_elements(before_proposals) v) ORDER BY p1.id LOOP
  BEGIN
   facts:=disposition_private.proposal_facts(j.id,p.governing_root_id,p.target_aggregation_id,p.target_record_id,p.proposal_type,p.proposed_values,p.reason);
   IF disposition_private.canonical_review_json(facts) IS DISTINCT FROM disposition_private.canonical_review_json(p.current_values) THEN RAISE EXCEPTION 'disposition_proposal_stale'; END IF;
   IF p.proposal_type='make_vital' AND NOT current_user_can_aggregation_operation(p.target_aggregation_id,'aggregation.vital_status.change','aggregation.vital_status.change') THEN RAISE EXCEPTION 'disposition_execution_authority_required'; END IF;
   IF p.proposal_type='blocking_security' THEN
    IF NOT current_user_can_aggregation_operation(p.target_aggregation_id,'aggregation.security_level.change','aggregation.security_level.change') OR NOT user_has_governance_clearance(current_user_id(),(p.proposed_values->>'security_level_id')::bigint) AND NOT EXISTS(SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id JOIN security_levels sl ON sl.id=r.security_level_id JOIN security_levels wanted ON wanted.id=(p.proposed_values->>'security_level_id')::bigint WHERE a.user_id=current_user_id() AND disposition_private.person_role(current_user_id(),r.id) AND sl.level_number>=wanted.level_number) THEN RAISE EXCEPTION 'disposition_execution_authority_required'; END IF;
   END IF;
   IF p.proposal_type='blocking_security' AND EXISTS(SELECT 1 FROM aggregations a JOIN aggregations parent ON parent.id=a.parent_aggregation_id JOIN security_levels old_level ON old_level.id=parent.security_level_id JOIN security_levels wanted ON wanted.id=(p.proposed_values->>'security_level_id')::bigint WHERE a.id=p.target_aggregation_id AND old_level.level_number<wanted.level_number AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(before_proposals) proposed JOIN security_levels planned ON planned.id=(proposed#>>'{proposed_values,security_level_id}')::bigint WHERE proposed->>'proposal_type'='blocking_security' AND (proposed->>'target_aggregation_id')::bigint=parent.id AND planned.level_number>=wanted.level_number)) THEN RAISE EXCEPTION 'disposition_security_hierarchy_invalid'; END IF;
   IF p.proposal_type='add_to_holds' THEN
    PERFORM 1 FROM holds WHERE id IN (SELECT v::text::bigint FROM jsonb_array_elements(p.proposed_values->'hold_ids') v) ORDER BY id FOR UPDATE;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(p.proposed_values->'hold_ids') v WHERE NOT current_hold_actor_is_manager(v::text::bigint)) THEN RAISE EXCEPTION 'disposition_execution_authority_required'; END IF;
   END IF;
   IF p.proposal_type IN ('create_aggregation_relationship','remove_aggregation_relationship','remove_record_relationship') AND NOT user_has_global_privilege(current_user_id(),'relationships.link') THEN RAISE EXCEPTION 'disposition_execution_authority_required'; END IF;
   IF p.proposal_type='create_aggregation_relationship' AND EXISTS(SELECT 1 FROM aggregation_relationships r WHERE disposition_private.proposal_relationship_key(to_jsonb(r)||jsonb_build_object('resource_kind','aggregation'))=disposition_private.proposal_relationship_key(p.current_values->'relationship')) THEN RAISE EXCEPTION 'disposition_proposal_conflict'; END IF;
   IF p.proposal_type='remove_aggregation_relationship' THEN PERFORM 1 FROM aggregation_relationships WHERE id=(p.proposed_values->>'relationship_id')::bigint FOR UPDATE; END IF;
   IF p.proposal_type='remove_record_relationship' THEN PERFORM 1 FROM record_relationships WHERE id=(p.proposed_values->>'relationship_id')::bigint FOR UPDATE; END IF;
   IF p.proposal_type='local_retention_override' AND NOT user_has_global_privilege(current_user_id(),'classifications.administer') THEN RAISE EXCEPTION 'disposition_execution_authority_required'; END IF;
  EXCEPTION WHEN OTHERS THEN invalid_ids:=invalid_ids||to_jsonb(p.id); END;
 END LOOP;
 IF jsonb_array_length(invalid_ids)>0 THEN RAISE EXCEPTION USING MESSAGE='disposition_proposal_requires_correction',DETAIL=jsonb_build_object('proposal_ids',invalid_ids)::text; END IF;
 -- Incompatible desired values, duplicate exact removals/creations and creating
 -- and removing the same named link are unresolved conflicts, never skipped.
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(before_proposals) a JOIN jsonb_array_elements(before_proposals) b ON (a->>'id')::bigint<(b->>'id')::bigint WHERE
  (a->>'target_aggregation_id'=b->>'target_aggregation_id' AND a->>'proposal_type'=b->>'proposal_type' AND a->>'proposal_type' IN ('blocking_security','local_retention_override') AND a->'proposed_values'<>b->'proposed_values')
  OR (a->>'proposal_type'=b->>'proposal_type' AND a->>'proposal_type' IN ('remove_aggregation_relationship','remove_record_relationship') AND a#>'{proposed_values,relationship_id}'=b#>'{proposed_values,relationship_id}')
  OR (a#>'{current_values,relationship}' IS NOT NULL AND b#>'{current_values,relationship}' IS NOT NULL AND
    disposition_private.proposal_relationship_key(a#>'{current_values,relationship}')=disposition_private.proposal_relationship_key(b#>'{current_values,relationship}') AND (a->>'proposal_type'='create_aggregation_relationship' OR b->>'proposal_type'='create_aggregation_relationship')))
 THEN RAISE EXCEPTION 'disposition_proposal_conflict'; END IF;
 INSERT INTO disposition_private.approval_context VALUES(txid_current(),pg_backend_pid(),key,j.id,t.id,acting,before_members,before_proposals,'preparing',NULL,total_reason,'submission');
 IF j.review_route='records_manager_only' THEN
  next_round:=j.current_review_round+1;
  IF next_round>1 THEN
   FOR p IN SELECT p1.* FROM disposition_review_proposals p1 WHERE p1.id IN (SELECT (v->>'id')::bigint FROM jsonb_array_elements(before_proposals) v) ORDER BY p1.id LOOP
    INSERT INTO disposition_review_proposals(job_id,review_round,governing_root_id,target_aggregation_id,target_record_id,proposal_type,proposed_values,current_values,reason,proposer_user_id,proposer_role_id,proposer_stage,proposed_at,original_review_round,carried_from_proposal_id,last_revised_by_user_id,last_revised_role_id,last_revised_stage,last_revised_round,last_revised_at)
    VALUES(j.id,next_round,p.governing_root_id,p.target_aggregation_id,p.target_record_id,p.proposal_type,p.proposed_values,p.current_values,p.reason,p.proposer_user_id,p.proposer_role_id,p.proposer_stage,p.proposed_at,p.original_review_round,p.id,p.last_revised_by_user_id,p.last_revised_role_id,p.last_revised_stage,p.last_revised_round,p.last_revised_at) RETURNING id INTO carried;
    INSERT INTO disposition_proposal_holds(proposal_id,hold_id,hold_snapshot) SELECT carried,hold_id,hold_snapshot FROM disposition_proposal_holds WHERE proposal_id=p.id;
   END LOOP;
  END IF;
  INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot,submission_reason) VALUES(j.id,next_round,current_user_id(),before_members,total_reason) RETURNING * INTO rr;
  before_proposals:=disposition_private.proposal_snapshot(j.id);
  UPDATE disposition_private.approval_context SET proposal_snapshot=before_proposals WHERE transaction_id=txid_current();
 END IF;
 UPDATE disposition_private.approval_context SET phase='applying' WHERE transaction_id=txid_current();
 INSERT INTO disposition_review_decisions(job_id,round_id,review_stage,decision,task_id,actor_user_id,acting_role_id,reason,membership_snapshot)
 VALUES(j.id,rr.id,t.workflow_stage,'approved',t.id,current_user_id(),acting,total_reason,before_members) RETURNING id INTO decision_id;
 FOR m IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active' LOOP
  baseline_links:=baseline_links||jsonb_build_object(m.root_aggregation_id::text,(SELECT COALESCE(jsonb_agg(resource_kind||':'||relationship_id),'[]') FROM disposition_private.relationship_scope(m.root_aggregation_id) WHERE blocks_final));
 END LOOP;
 FOR p IN SELECT p1.* FROM disposition_review_proposals p1 WHERE p1.id IN (SELECT (v->>'id')::bigint FROM jsonb_array_elements(before_proposals) v)
 ORDER BY CASE p1.proposal_type WHEN 'local_retention_override' THEN 1 WHEN 'blocking_security' THEN 2 WHEN 'make_vital' THEN 3 WHEN 'add_to_holds' THEN 5 ELSE 4 END,CASE WHEN p1.proposal_type='blocking_security' THEN (WITH RECURSIVE parents AS (SELECT id,parent_aggregation_id FROM aggregations WHERE id=p1.target_aggregation_id UNION ALL SELECT a.id,a.parent_aggregation_id FROM aggregations a JOIN parents b ON a.id=b.parent_aggregation_id) SELECT count(*) FROM parents) ELSE 0 END,p1.id LOOP
  current_reason:=COALESCE(NULLIF(btrim(p.reason),''),total_reason);source:=CASE WHEN p.reason IS NULL OR p.reason ~ '^[[:space:]]*$' THEN 'submission' ELSE 'proposal' END;
  UPDATE disposition_private.approval_context SET current_proposal_id=p.id,reason_used=current_reason,reason_source=source WHERE transaction_id=txid_current();
  PERFORM set_config('app.change_reason',current_reason,true);
  created:=NULL;material_changed:=true;changed_holds:=ARRAY[]::bigint[];
  SELECT disposition_status INTO previous_status FROM aggregations WHERE id=p.governing_root_id;
  CASE p.proposal_type
  WHEN 'make_vital' THEN
   PERFORM set_config('app.vital_status_change_authorized','authorized',true);
   UPDATE aggregations SET is_vital=true WHERE id=p.target_aggregation_id AND NOT is_vital;
   material_changed:=FOUND;
   IF material_changed THEN PERFORM append_domain_event('aggregation',p.target_aggregation_id,'VITAL_STATUS_CHANGED',jsonb_build_object('old_is_vital',false,'new_is_vital',true)); END IF;
   PERFORM set_config('app.vital_status_change_authorized','',true);
  WHEN 'blocking_security' THEN
   PERFORM set_config('app.security_level_change_authorized','authorized',true);
   SELECT security_level_id INTO prior_level FROM aggregations WHERE id=p.target_aggregation_id;
   UPDATE aggregations SET security_level_id=(p.proposed_values->>'security_level_id')::bigint WHERE id=p.target_aggregation_id AND security_level_id<>(p.proposed_values->>'security_level_id')::bigint;
   material_changed:=FOUND;
   IF material_changed THEN PERFORM append_domain_event('aggregation',p.target_aggregation_id,'SECURITY_LEVEL_UPGRADED',jsonb_build_object('old_security_level_id',prior_level,'new_security_level_id',p.proposed_values->'security_level_id')); END IF;
   PERFORM set_config('app.security_level_change_authorized','',true);
  WHEN 'add_to_holds' THEN
   material_changed:=false;
   FOR selected IN SELECT v::text::bigint FROM jsonb_array_elements(p.proposed_values->'hold_ids') v LOOP
    INSERT INTO hold_aggregation_assignments(hold_id,aggregation_id) VALUES(selected,p.target_aggregation_id) ON CONFLICT(hold_id,aggregation_id) DO NOTHING;
    IF FOUND THEN material_changed:=true;changed_holds:=array_append(changed_holds,selected); END IF;
   END LOOP;
  WHEN 'create_aggregation_relationship' THEN
   INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES((p.current_values#>>'{relationship,relationship_type_id}')::bigint,(p.current_values#>>'{relationship,source_id}')::bigint,(p.current_values#>>'{relationship,target_id}')::bigint) RETURNING id INTO created;
   new_links:=new_links||jsonb_build_object('aggregation:'||created,jsonb_build_array(p.id));
  WHEN 'remove_aggregation_relationship' THEN DELETE FROM aggregation_relationships WHERE id=(p.proposed_values->>'relationship_id')::bigint;
  WHEN 'remove_record_relationship' THEN DELETE FROM record_relationships WHERE id=(p.proposed_values->>'relationship_id')::bigint;
  WHEN 'local_retention_override' THEN
   INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,instructions,justification)
   VALUES(p.governing_root_id,(p.proposed_values->>'current_period_years')::integer,(p.proposed_values->>'intermediate_period_years')::integer,p.proposed_values->>'final_disposition',p.proposed_values->>'instructions',current_reason)
   ON CONFLICT(aggregation_id) DO UPDATE SET current_period_years=EXCLUDED.current_period_years,intermediate_period_years=EXCLUDED.intermediate_period_years,final_disposition=EXCLUDED.final_disposition,instructions=EXCLUDED.instructions,justification=EXCLUDED.justification;
  ELSE RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END CASE;
  SELECT disposition_status INTO result_status FROM aggregations WHERE id=p.governing_root_id;
  IF material_changed THEN
  INSERT INTO disposition_proposal_effects(proposal_id,governing_root_id,effect_type,previous_status,resulting_status,actor_user_id,acting_role_id,details)
  VALUES(p.id,p.governing_root_id,'resource_changed',previous_status,result_status,current_user_id(),acting,jsonb_build_object('proposal_type',p.proposal_type,'target_aggregation_id',p.target_aggregation_id,'target_record_id',p.target_record_id,'reason_used',current_reason,'reason_source',source,'relationship_id',COALESCE(created,(p.proposed_values->>'relationship_id')::bigint)));
  END IF;
  IF p.proposal_type='local_retention_override' THEN
   INSERT INTO disposition_proposal_effects(proposal_id,governing_root_id,effect_type,previous_status,resulting_status,actor_user_id,acting_role_id,details) VALUES(p.id,p.governing_root_id,'status_recalculated',previous_status,result_status,current_user_id(),acting,'{}');
  END IF;
  IF (material_changed AND (p.proposal_type IN ('make_vital','blocking_security') OR (p.proposal_type='add_to_holds' AND EXISTS(SELECT 1 FROM disposition_private.protection_blockers(p.governing_root_id) WHERE hold_ids && changed_holds))))
    OR (p.proposal_type='local_retention_override' AND EXISTS(SELECT 1 FROM disposition_private.eligibility(p.governing_root_id) e WHERE NOT e.is_due OR e.eligible_status IS DISTINCT FROM 2)) THEN
   IF p.proposal_type IN ('make_vital','blocking_security','add_to_holds') THEN
    INSERT INTO disposition_proposal_effects(proposal_id,governing_root_id,effect_type,previous_status,resulting_status,actor_user_id,acting_role_id,details) VALUES(p.id,p.governing_root_id,'unit_blocked',previous_status,result_status,current_user_id(),acting,'{}');
   END IF;
   removed:=jsonb_set(removed,ARRAY[p.governing_root_id::text],COALESCE(removed->p.governing_root_id::text,'[]')||jsonb_build_array(p.id));
  END IF;
 END LOOP;
 UPDATE disposition_private.approval_context SET current_proposal_id=NULL,reason_used=total_reason,reason_source='submission',phase='removing' WHERE transaction_id=txid_current();
 PERFORM set_config('app.change_reason',total_reason,true);
 -- Repeat against actual remaining membership until no newly outside link or
 -- proposal-invalidated unit remains. Independently arising baseline blockers
 -- retain their existing membership and cannot cause automatic removals.
 LOOP
  changed:=false;
  FOR m IN SELECT * FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active' ORDER BY id LOOP
   causes:=COALESCE(removed->m.root_aggregation_id::text,'[]');
   effect_root:=CASE WHEN removed ? m.root_aggregation_id::text THEN 'unit_removed' ELSE 'cascading_unit_removed' END;
   IF jsonb_array_length(causes)=0 THEN
    FOR link IN SELECT * FROM disposition_private.relationship_scope(m.root_aggregation_id) WHERE blocks_final LOOP
     IF NOT (baseline_links->m.root_aggregation_id::text @> jsonb_build_array(link.resource_kind||':'||link.relationship_id)) THEN
      IF new_links ? (link.resource_kind||':'||link.relationship_id) AND NOT (removed ? link.source_root_id::text OR removed ? link.target_root_id::text) THEN effect_root:='unit_removed'; END IF;
      causes:=causes||COALESCE(new_links->(link.resource_kind||':'||link.relationship_id),'[]')||COALESCE(removed->link.source_root_id::text,'[]')||COALESCE(removed->link.target_root_id::text,'[]');
     END IF;
    END LOOP;
   END IF;
   IF jsonb_array_length(causes)>0 THEN
    SELECT COALESCE(jsonb_agg(DISTINCT v),'[]') INTO causes FROM jsonb_array_elements(causes) v;
    removed:=jsonb_set(removed,ARRAY[m.root_aggregation_id::text],causes);
    SELECT disposition_status INTO previous_status FROM aggregations WHERE id=m.root_aggregation_id;
    PERFORM disposition_private.remove_member(m.id,m.version,(SELECT version FROM aggregations WHERE id=m.root_aggregation_id));
    SELECT disposition_status INTO result_status FROM aggregations WHERE id=m.root_aggregation_id;
    FOR selected IN SELECT v::text::bigint FROM jsonb_array_elements(causes) v LOOP
     INSERT INTO disposition_proposal_effects(proposal_id,governing_root_id,effect_type,previous_status,resulting_status,membership_id,actor_user_id,acting_role_id,details)
     VALUES(selected,m.root_aggregation_id,effect_root,previous_status,result_status,m.id,current_user_id(),acting,jsonb_build_object('cause_proposals',causes));
    END LOOP;
    changed:=true;
   END IF;
  END LOOP;
  EXIT WHEN NOT changed;
 END LOOP;
 UPDATE disposition_private.approval_context SET phase='finalizing' WHERE transaction_id=txid_current();
 FOR p IN SELECT p1.* FROM disposition_review_proposals p1 WHERE p1.id IN (SELECT (v->>'id')::bigint FROM jsonb_array_elements(before_proposals) v) ORDER BY p1.id LOOP
  SELECT jsonb_build_object('approving_user_id',current_user_id(),'acting_role_id',acting,'decision_id',decision_id,'reason_used',COALESCE(NULLIF(btrim(p.reason),''),total_reason),'reason_source',CASE WHEN p.reason IS NULL OR p.reason ~ '^[[:space:]]*$' THEN 'submission' ELSE 'proposal' END,
   'resource_changed',COALESCE(bool_or(e.effect_type='resource_changed'),false),'effects',COALESCE(jsonb_agg(to_jsonb(e) ORDER BY e.id),'[]')) INTO effect FROM disposition_proposal_effects e WHERE e.proposal_id=p.id;
  -- The join is active work only; immutable proposal/round snapshots retain
  -- every selected hold and its metadata after execution.
  DELETE FROM disposition_proposal_holds WHERE proposal_id=p.id;
  UPDATE disposition_review_proposals SET proposal_state='executed',execution_message=effect WHERE id=p.id;
  SELECT to_jsonb(p1)||jsonb_build_object('proposer_name',u.name,'proposer_role',r.name,'effect',effect) INTO facts FROM disposition_review_proposals p1 JOIN users u ON u.id=p1.proposer_user_id JOIN roles r ON r.id=p1.proposer_role_id WHERE p1.id=p.id;
  results:=results||jsonb_build_array(facts);
 END LOOP;
 execution:=jsonb_build_object('command_id',key,'decision_id',decision_id,'approving_user_id',current_user_id(),'approving_user_name',(SELECT name FROM users WHERE id=current_user_id()),'acting_role_id',acting,'acting_role_name',(SELECT name FROM roles WHERE id=acting),'executed_at',CURRENT_TIMESTAMP,
 'reviewed_membership',before_members,'reviewed_proposals',before_proposals,'post_membership',disposition_private.membership_snapshot(j.id),'results',results,'removed_units',removed,'overall_reason',total_reason,
 'job_snapshot',to_jsonb(j)||jsonb_build_object('owner_name',(SELECT name FROM org_units WHERE id=j.owning_org_unit_id),'assignee_name',(SELECT name FROM users WHERE id=j.assigned_user_id)),
 'post_rules',(SELECT COALESCE(jsonb_agg(jsonb_build_object('root_id',member_row.root_aggregation_id,'rule',e.rule_snapshot)),'[]') FROM disposition_job_memberships member_row CROSS JOIN LATERAL disposition_private.eligibility(member_row.root_aggregation_id) e WHERE member_row.job_id=j.id AND member_row.membership_state='active'));
 UPDATE disposition_tasks SET task_state=CASE WHEN id=t.id THEN 'completed' ELSE 'cancelled' END WHERE job_id=j.id AND task_state IN ('open','claimed');
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active') THEN
  IF j.review_route='records_manager_only' THEN
   INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id) VALUES(j.id,CASE WHEN j.workflow_stage='manager_preparation' THEN 'preparation' ELSE 'correction' END,j.workflow_stage,rr.round_number,j.assigned_user_id);
  ELSE PERFORM disposition_private.route_correction(j.id); END IF;
 END IF;
 UPDATE disposition_jobs SET date_updated=CURRENT_TIMESTAMP WHERE id=j.id;
 execution:=execution||jsonb_build_object('approved_job_version',(SELECT version FROM disposition_jobs WHERE id=j.id),'request_facts',disposition_private.request_facts(j.id));
 UPDATE disposition_review_rounds SET approval_execution=execution,completed_at=CURRENT_TIMESTAMP WHERE id=rr.id;
 PERFORM append_domain_event('disposition_job',j.id,'REVIEW_PROPOSALS_APPROVED',jsonb_build_object('round_id',rr.id,'review_round',rr.round_number,'decision_id',decision_id,'approval_execution',execution));
 DELETE FROM disposition_private.approval_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',j.id,'round_id',rr.id,'review_round',rr.round_number,'decision_id',decision_id,'job_version',(SELECT version FROM disposition_jobs WHERE id=j.id),'remaining_units',jsonb_array_length(execution->'post_membership'),'removed_units',removed,'report_status','pending');
END $_$;

CREATE FUNCTION disposition_private.artifact_destination(p_type text) RETURNS TABLE(scheme_id bigint, classification_id bigint, aggregation_id bigint)
    LANGUAGE plpgsql
    AS $$
DECLARE scheme bigint; dest bigint; root bigint; setting_name text;
BEGIN
 IF p_type NOT IN ('destruction_request','external_rejection_letter','external_approval_letter','physical_destruction_certificate','digital_destruction_certificate','proposal_execution_report','physical_preparation_report') THEN RAISE EXCEPTION 'disposition_document_type_invalid'; END IF;
 setting_name:=CASE WHEN p_type IN ('destruction_request','proposal_execution_report','physical_preparation_report') THEN 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID' ELSE 'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID' END;
 PERFORM 1 FROM application_settings WHERE key IN ('DISPOSITION_CLASSIFICATION_SCHEME_ID','DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID') ORDER BY key FOR SHARE;
 SELECT (value#>>'{}')::bigint INTO scheme FROM application_settings WHERE key='DISPOSITION_CLASSIFICATION_SCHEME_ID';
 SELECT (value#>>'{}')::bigint INTO dest FROM application_settings WHERE key=setting_name;
 IF scheme IS NULL OR dest IS NULL THEN RAISE EXCEPTION 'disposition_destination_unset'; END IF;
 PERFORM 1 FROM classifications c WHERE c.id=dest AND c.classification_scheme_id=scheme AND c.is_terminal FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'disposition_destination_invalid'; END IF;
 SELECT a.id INTO root FROM aggregations a WHERE a.parent_aggregation_id IS NULL
 AND a.date_closed IS NULL AND a.classification_id=dest ORDER BY a.date_opened DESC,a.id DESC LIMIT 1 FOR SHARE;
 IF root IS NULL THEN RAISE EXCEPTION 'disposition_destination_open_root_missing'; END IF;
 RETURN QUERY SELECT scheme,dest,root;
END $$;

CREATE FUNCTION disposition_private.artifact_outside_job() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_documents d JOIN records r ON r.id=d.record_id
 JOIN disposition_job_memberships m ON m.job_id=d.job_id AND m.membership_state IN ('active','completed_history')
 WHERE disposition_private.root_id(r.aggregation_id)=m.root_aggregation_id) THEN
  RAISE EXCEPTION 'disposition_evidence_inside_job'; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.assert_admission(p_job bigint, p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
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
 IF job.job_type='destruction' THEN PERFORM disposition_private.require_preparer(job.assigned_user_id,job.review_route); ELSE PERFORM disposition_private.require_job_person(job.assigned_user_id,job.job_type); END IF;
 IF NOT user_can_view_aggregation(job.assigned_user_id,p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_access_required'; END IF;
 IF root.date_closed IS NULL THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
 IF root.disposition_status NOT BETWEEN 2 AND 5 OR root.disposition_status<>job.disposition_status-4 THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(p_root)) THEN RAISE EXCEPTION 'disposition_admission_blocked'; END IF;
 IF job.job_type='destruction' AND NOT EXISTS(WITH RECURSIVE owners AS (
 SELECT id,parent_org_unit_id FROM org_units WHERE id=root.owning_org_unit_id
 UNION ALL SELECT p.id,p.parent_org_unit_id FROM org_units p JOIN owners c ON p.id=c.parent_org_unit_id)
 SELECT 1 FROM owners WHERE id=job.owning_org_unit_id) THEN RAISE EXCEPTION 'disposition_owning_unit_mismatch'; END IF;
END $$;

CREATE FUNCTION disposition_private.assert_unit(p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
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
  IF root.disposition_status NOT BETWEEN 6 AND 9 AND NOT (root.disposition_status=10 AND root.disposition_job_id=member.job_id) AND NOT (member.removal_required AND root.disposition_status BETWEEN 1 AND 5) THEN
   RAISE EXCEPTION 'disposition_active_member_not_pending'; END IF;
 ELSIF root.disposition_status BETWEEN 6 AND 9 THEN RAISE EXCEPTION 'disposition_pending_requires_membership'; END IF;
 IF root.disposition_status=13 AND NOT EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN disposition_jobs j ON j.id=m.job_id WHERE m.root_aggregation_id=p_root AND m.membership_state='terminated_history' AND j.lifecycle_state='terminated' AND disposition_private.physical_covered(j.id,p_root)) THEN RAISE EXCEPTION 'disposition_partial_history_required'; END IF;
 IF root.disposition_status IN (10,11,12) THEN
  SELECT * INTO job FROM disposition_jobs WHERE id=root.disposition_job_id;
  IF root.disposition_status=10 AND job.lifecycle_state IN ('active','terminated','completed') AND EXISTS(SELECT 1 FROM disposition_retained_records p WHERE p.resource_kind='aggregation' AND p.resource_id=p_root AND p.job_id=job.id AND p.final_event_id=root.final_disposition_event_id AND p.executor_user_id=root.final_disposition_by_user_id AND p.destroyed_at=root.final_disposition_at) AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=job.id AND m.root_aggregation_id=p_root AND m.membership_state IN ('active','completed_history','terminated_history')) THEN RETURN; END IF;
  IF root.disposition_status=10 AND job.lifecycle_state IN ('active','terminated') AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=job.id AND m.root_aggregation_id=p_root AND m.membership_state IN ('active','terminated_history','completed_history')) AND EXISTS(SELECT 1 FROM event_history e WHERE e.id=root.final_disposition_event_id AND e.entity_type='aggregation' AND e.entity_id=p_root AND e.operation='DISPOSITION_UNIT_DESTROYED' AND (e.metadata->>'recovery_job_id')::bigint=job.id AND (e.metadata->>'executor_user_id')::bigint=root.final_disposition_by_user_id AND (e.metadata->>'completed_at')::timestamptz=root.final_disposition_at) AND root.destruction_number=job.destruction_number THEN RETURN; END IF;
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

CREATE FUNCTION disposition_private.assign_job(p_job bigint, p_version integer, p_assignee bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE job disposition_jobs%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_assign' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 UPDATE disposition_jobs SET assigned_user_id=p_assignee WHERE id=p_job RETURNING * INTO job;
 RETURN to_jsonb(job);
END $$;

CREATE FUNCTION disposition_private.assign_single_reviewer() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE candidates bigint[];
BEGIN
 IF NEW.destination_role_id IS NULL OR NEW.task_state<>'open'
    OR NEW.task_type NOT IN ('file_administrator_review','unit_manager_review','records_manager_review')
    OR disposition_private.context_operation() NOT IN ('review_submit','review_decide')
    OR EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.job_id=NEW.job_id
      AND t.workflow_stage=NEW.workflow_stage AND t.task_state='claimed') THEN
  RETURN NEW;
 END IF;
 PERFORM disposition_private.require_command();
 -- These are the same role-queue gates used by task_eligible. The new task is
 -- not visible to that function until INSERT finishes, so evaluate its fields.
 SELECT array_agg(candidate.id) INTO candidates FROM (
  SELECT DISTINCT a.user_id AS id FROM user_role_assignments a
  JOIN disposition_jobs j ON j.id=NEW.job_id
  WHERE (a.role_id=NEW.destination_role_id OR NEW.workflow_stage='records_manager_review') AND j.lifecycle_state='active'
   AND j.workflow_stage=NEW.workflow_stage
   AND disposition_private.person_role(a.user_id,a.role_id)
   AND disposition_private.review_role(j.id,NEW.workflow_stage,a.role_id)
   AND disposition_private.can_review_content(a.user_id,j.id)
  ORDER BY a.user_id LIMIT 2
 ) candidate;
 IF cardinality(candidates)=1 AND disposition_private.person_role(candidates[1],NEW.destination_role_id) THEN
  NEW.task_state:='claimed';
  NEW.claimed_by_user_id:=candidates[1];
  NEW.claimed_at:=CURRENT_TIMESTAMP;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.audit_review_work() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE operation text;
BEGIN
 operation:=CASE WHEN TG_TABLE_NAME='disposition_review_notes' THEN 'REVIEW_NOTES_SAVED'
 WHEN TG_OP='INSERT' AND to_jsonb(NEW)->>'carried_from_proposal_id' IS NOT NULL THEN 'REVIEW_PROPOSAL_CARRIED'
 WHEN TG_OP='INSERT' THEN 'REVIEW_PROPOSAL_CREATED'
 WHEN to_jsonb(NEW)->>'proposal_state'='executed' THEN 'REVIEW_PROPOSAL_EXECUTED'
 WHEN to_jsonb(NEW)->>'proposal_state'='withdrawn' THEN 'REVIEW_PROPOSAL_WITHDRAWN' ELSE 'REVIEW_PROPOSAL_REVISED' END;
 PERFORM append_domain_event(CASE WHEN TG_TABLE_NAME='disposition_review_notes' THEN 'disposition_review_note' ELSE 'disposition_review_proposal' END,NEW.id,operation,
 jsonb_build_object('before',CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) END,'after',to_jsonb(NEW),
 'acting_role_id',(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())));
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.audit_template_revision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 PERFORM append_domain_event(CASE WHEN NEW.uploaded_from_job_id IS NULL THEN 'disposition_template_revision' ELSE 'disposition_job' END,COALESCE(NEW.uploaded_from_job_id,NEW.id),'TEMPLATE_REVISED',
 jsonb_build_object('template_type',NEW.document_type,'template_revision_id',NEW.id,
 'template_revision',NEW.revision_number,'original_filename',NEW.original_filename,
 'checksum_algo','sha256','checksum',NEW.checksum,'uploaded_by_user_id',NEW.uploaded_by_user_id,
 'acting_role_id',NEW.acting_role_id,'actor_type',NEW.actor_type,'uploaded_at',NEW.uploaded_at));
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.audit_workflow() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE before_state jsonb; after_state jsonb; command disposition_private.command_receipts%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') THEN RETURN NEW; END IF;

 before_state:=CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) END;
 after_state:=to_jsonb(NEW);
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM append_domain_event(CASE TG_TABLE_NAME WHEN 'disposition_jobs' THEN 'disposition_job' WHEN 'disposition_job_memberships' THEN 'disposition_job_membership' WHEN 'disposition_tasks' THEN 'disposition_task' WHEN 'disposition_review_rounds' THEN 'disposition_review_round' WHEN 'disposition_review_decisions' THEN 'disposition_review_decision' ELSE 'disposition_job_document' END,
 NEW.id, CASE WHEN disposition_private.hook_applying() THEN 'DISPOSITION_RECALCULATED' ELSE upper(command.operation) END, jsonb_build_object('command_id',command.command_id,'acting_role_id',command.acting_role_id,'before',before_state,'after',after_state),command.reason);
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.begin_command(p_id uuid, p_operation text, p_payload jsonb, p_role bigint, p_reason text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE previous disposition_private.command_receipts%ROWTYPE;
BEGIN
 p_reason:=COALESCE(p_reason,'');
 PERFORM pg_advisory_xact_lock(7357,1);
 IF p_operation IN ('task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide') AND p_payload ? 'task_id' AND NOT (p_operation='review_decide' AND disposition_private.physical_confirmation_retry(p_id,p_role)) THEN
  PERFORM disposition_private.require_task_command((p_payload->>'task_id')::bigint,p_role,p_operation);
 ELSE PERFORM disposition_private.require_actor(p_role); END IF;
 IF p_operation NOT IN ('job_create','membership_add','task_claim') AND (p_reason IS NULL OR p_reason ~ '^[[:space:]]*$') THEN RAISE EXCEPTION 'disposition_reason_required'; END IF;
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
END $_$;

CREATE FUNCTION disposition_private.can_correct_evidence(p_job bigint, p_role bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_jobs j JOIN users u ON u.id=current_user_id()
 JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
 JOIN profiles profile ON profile.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
 WHERE j.id=p_job AND j.job_type='destruction' AND j.lifecycle_state='active'
 AND u.status='active' AND u.account_type='person' AND r.id=p_role
 AND r.is_information_governance AND role_effectively_active(r.id)
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND p.code='disposition.jobs.manage' AND (profile.code='INFO_GOV_MGR'
 OR (profile.code='INFO_GOV_OFFICER' AND j.assigned_user_id=u.id)))
$$;

CREATE FUNCTION disposition_private.can_email(p_user bigint, p_job bigint, p_document bigint, p_role bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_jobs j JOIN disposition_job_documents d ON d.job_id=j.id
 JOIN digital_components dc ON dc.id=d.digital_component_id
 WHERE j.id=p_job AND d.id=p_document AND d.document_state='available'
 AND disposition_private.person_role(p_user,p_role)
 AND user_can_view_record(p_user,d.record_id) AND user_can_record_operation(p_user,d.record_id,'record.component.download','record.component.download')
 AND disposition_private.can_review_content(p_user,j.id)
 AND CASE WHEN d.document_type='digital_destruction_certificate' THEN
   j.lifecycle_state IN ('active','completed') AND disposition_private.review_role(j.id,'records_manager_review',p_role)
 WHEN d.document_type='destruction_request' THEN
   j.lifecycle_state='active' AND j.workflow_stage='external_approval_pending'
   AND EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.job_id=j.id AND t.task_type='external_approval'
      AND t.request_document_id=d.id AND j.current_review_round=d.review_round
      AND disposition_private.request_approval_current(j.id,(d.provenance->>'approval_round_id')::bigint) AND t.task_state IN ('open','claimed')
      AND (disposition_private.review_role(j.id,'records_manager_review',p_role)
        OR (j.assigned_user_id=p_user AND disposition_private.task_eligible(p_user,t.id,p_role))))
 ELSE false END)
$$;

CREATE FUNCTION disposition_private.can_manage() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id
  JOIN roles r ON r.id=a.role_id JOIN profile_privileges pp ON pp.profile_id=r.profile_id
  JOIN privileges p ON p.id=pp.privilege_id AND p.code='disposition.jobs.manage'
  WHERE u.id=current_user_id() AND u.account_type='person' AND u.status='active'
   AND r.is_information_governance AND role_effectively_active(r.id)
   AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))
$$;

CREATE FUNCTION disposition_private.can_review_content(p_user bigint, p_job bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT NOT EXISTS(SELECT 1 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
 WHERE m.job_id=p_job AND m.membership_state='active' AND
 (NOT disposition_private.history_resource_access(p_user,'aggregation',unit.id) OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=unit.id AND NOT disposition_private.history_resource_access(p_user,'record',r.id))))
$$;

CREATE FUNCTION disposition_private.can_revise_template(p_role bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id
 JOIN roles r ON r.id=a.role_id JOIN profiles profile ON profile.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
 WHERE u.id=current_user_id() AND u.status='active' AND u.account_type='person'
 AND r.id=p_role AND r.is_information_governance AND role_effectively_active(r.id)
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND profile.code IN ('INFO_GOV_OFFICER','INFO_GOV_MGR') AND p.code='disposition.jobs.manage')
$$;

CREATE FUNCTION disposition_private.canonical_review_json(p_value jsonb) RETURNS jsonb
    LANGUAGE plpgsql IMMUTABLE
    SET "TimeZone" TO 'UTC'
    AS $$
DECLARE result jsonb;item record;v jsonb;
BEGIN
 IF jsonb_typeof(p_value)='object' THEN
  result:='{}';
  FOR item IN SELECT * FROM jsonb_each(p_value) LOOP
   v:=disposition_private.canonical_review_json(item.value);
   IF item.key IN ('date_created','date_updated','date_closed','valid_from','valid_to','proposed_at','last_revised_at','withdrawn_at','executed_at','started_at','completed_at') AND jsonb_typeof(v)='string' AND v#>>'{}' ~ '^\d{4}-\d\d-\d\dT\d\d:' THEN
    v:=to_jsonb(to_char((v#>>'{}')::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'));
   END IF;
   result:=result||jsonb_build_object(item.key,v);
  END LOOP;RETURN result;
 ELSIF jsonb_typeof(p_value)='array' THEN SELECT COALESCE(jsonb_agg(disposition_private.canonical_review_json(value) ORDER BY ordinality),'[]') INTO result FROM jsonb_array_elements(p_value) WITH ORDINALITY;RETURN result;
 ELSE RETURN p_value;END IF;
END $$;

CREATE FUNCTION disposition_private.capture_policy_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.capture_recalculation(p_root bigint, p_cause text) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE previous jsonb; status smallint;
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN disposition_jobs j ON j.id=m.job_id WHERE m.root_aggregation_id=p_root AND m.membership_state='active' AND j.lifecycle_state='active' AND disposition_private.physical_covered(j.id,p_root)) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
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

CREATE FUNCTION disposition_private.capture_retiring_identities(p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 INSERT INTO disposition_private.destruction_identities SELECT txid_current(),pg_backend_pid(),p_root,jsonb_build_object(
 'aggregation_ids',(SELECT coalesce(jsonb_agg(id),'[]') FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root))),
 'record_ids',(SELECT coalesce(jsonb_agg(id),'[]') FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),
 'component_ids',(SELECT coalesce(jsonb_agg(DISTINCT identity),'[]') FROM (SELECT source_component_id AS identity FROM disposition_destruction_manifest_items WHERE root_id=p_root AND source_component_id IS NOT NULL UNION SELECT e.entity_id FROM event_history e WHERE e.entity_type IN ('digital_component','record_component') AND ((e.before_state->>'record_id') IN (SELECT id::text FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))) OR (e.after_state->>'record_id') IN (SELECT id::text FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)))) AND NOT EXISTS(SELECT 1 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE d.id=e.entity_id AND r.aggregation_id NOT IN (SELECT disposition_private.unit_ids(p_root)))) identities),
 'aggregation_numbers',(SELECT coalesce(jsonb_agg(DISTINCT number),'[]') FROM (SELECT aggregation_number AS number FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) UNION ALL SELECT before_state->>'aggregation_number' FROM event_history WHERE entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root)) UNION ALL SELECT after_state->>'aggregation_number' FROM event_history WHERE entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root))) names WHERE number IS NOT NULL),
 'record_numbers',(SELECT coalesce(jsonb_agg(record_number),'[]') FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))))
 ON CONFLICT(transaction_id,root_id) DO NOTHING;
END $$;

CREATE FUNCTION disposition_private.change_job_owner(p_job bigint, p_version integer, p_owner bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.check_completion(p_job bigint, p_task bigint, p_role bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 PERFORM disposition_private.require_actor(p_role);
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT disposition_private.person_role(current_user_id(),p_role) OR NOT disposition_private.review_role(p_job,'records_manager_review',p_role) OR NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 IF j.job_type IS DISTINCT FROM 'destruction' OR j.lifecycle_state IS DISTINCT FROM 'active' OR j.workflow_stage IS DISTINCT FROM 'digital_destruction' THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
 PERFORM disposition_private.require_task_actor(p_task,p_role,true);
 IF NOT EXISTS(SELECT 1 FROM disposition_tasks WHERE id=p_task AND job_id=p_job AND task_type='digital_destruction') THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='completed_history') OR EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id WHERE m.job_id=p_job AND (m.membership_state='active' OR m.membership_state='completed_history' AND (a.disposition_status<>10 OR a.disposition_job_id IS DISTINCT FROM p_job OR NOT EXISTS(SELECT 1 FROM disposition_retained_records p WHERE p.resource_kind='aggregation' AND p.resource_id=a.id AND p.job_id=p_job)))) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_destruction_runs WHERE job_id=p_job AND state IN ('queued','running')) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=p_job AND method='postgresql_transactional_erasure') THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
END $$;

CREATE FUNCTION disposition_private.check_digital_job(p_job bigint, p_role bigint, p_initial boolean DEFAULT false) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;root bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 PERFORM disposition_private.lock_request_facts(p_job);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 PERFORM disposition_private.require_actor(p_role);
 IF NOT disposition_private.review_role(p_job,'records_manager_review',p_role) OR NOT disposition_private.person_role(current_user_id(),p_role) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 IF j.lifecycle_state IS DISTINCT FROM 'active' OR j.job_type<>'destruction' OR j.workflow_stage<>'digital_destruction' THEN RAISE EXCEPTION 'disposition_digital_stage_invalid'; END IF;
 PERFORM disposition_private.require_preparer(j.assigned_user_id,j.review_route);
 IF NOT EXISTS(SELECT 1 FROM disposition_external_approvals a JOIN disposition_review_rounds rr ON rr.id=a.round_id JOIN disposition_job_documents doc ON doc.id=a.approval_letter_document_id
 WHERE a.job_id=j.id AND a.decision='approved' AND rr.round_number=j.current_review_round AND rr.approval_execution IS NOT NULL AND rr.invalidated_at IS NULL
 AND a.destruction_number=j.destruction_number AND doc.document_state='available' AND current_user_can_view_record(doc.record_id) AND current_user_can_list_record_components(doc.record_id)) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 IF p_initial AND NOT EXISTS(SELECT 1 FROM disposition_external_approvals a JOIN disposition_review_rounds rr ON rr.id=a.round_id WHERE a.job_id=j.id AND rr.round_number=j.current_review_round AND disposition_private.request_approval_current(j.id,rr.id)) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' AND removal_required) THEN RAISE EXCEPTION 'disposition_removal_required'; END IF;
 FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' ORDER BY root_aggregation_id LOOP
  PERFORM disposition_private.lock_current_blockers(root);
  IF NOT disposition_private.recovery_unit_visible(root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  IF EXISTS(SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(root)) AND (date_closed IS NULL AND id=root OR disposition_status<>6)) OR EXISTS(SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(root)) AND disposition_status<>6) THEN RAISE EXCEPTION 'disposition_digital_scope_changed'; END IF;
  IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(root)) OR EXISTS(SELECT 1 FROM disposition_private.relationship_scope(root) WHERE blocks_final) THEN
   IF disposition_private.physical_covered(p_job,root) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
   RAISE EXCEPTION 'disposition_digital_blocked';
  END IF;
  IF EXISTS(SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(root)) AND medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('aggregations',id)) OR EXISTS(SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(root)) AND medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('records',id)) THEN RAISE EXCEPTION 'disposition_physical_confirmation_required'; END IF;
 END LOOP;
END $$;

CREATE FUNCTION disposition_private.check_physical_work(p_task bigint, p_job_version integer, p_task_version integer, p_role bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;t disposition_tasks%ROWTYPE;root bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task;
 PERFORM disposition_private.lock_request_facts(t.job_id);
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id;
 PERFORM disposition_private.require_task_actor(t.id,p_role,true);
 IF NOT disposition_private.person_role(current_user_id(),p_role) OR NOT disposition_private.review_role(j.id,'records_manager_review',p_role) THEN RAISE EXCEPTION 'disposition_manager_role_required'; END IF;
 IF t.version IS DISTINCT FROM p_task_version OR j.version IS DISTINCT FROM p_job_version THEN RAISE EXCEPTION 'disposition_stale_task'; END IF;
 IF j.lifecycle_state<>'active' OR j.workflow_stage<>'physical_destruction' OR t.task_type<>'physical_destruction' OR EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE job_id=j.id) THEN RAISE EXCEPTION 'disposition_physical_stage_invalid'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_external_approvals a JOIN disposition_review_rounds r ON r.id=a.round_id WHERE a.job_id=j.id AND a.decision='approved' AND r.round_number=j.current_review_round AND disposition_private.request_approval_current(j.id,r.id)) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 PERFORM disposition_private.require_progress(j.id);
 FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active' ORDER BY root_aggregation_id LOOP
  PERFORM disposition_private.lock_current_blockers(root);
  IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(root)) OR EXISTS(SELECT 1 FROM disposition_private.relationship_scope(root) WHERE blocks_final) THEN RAISE EXCEPTION 'disposition_physical_blocked'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.job_id=j.id AND d.document_type='physical_preparation_report' AND d.document_state='available') THEN RAISE EXCEPTION 'disposition_physical_report_required'; END IF;
 RETURN disposition_private.physical_scope(j.id);
END $$;

CREATE FUNCTION disposition_private.check_proposal_holds() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE p disposition_review_proposals%ROWTYPE; identity bigint;
BEGIN
 identity:=CASE WHEN TG_TABLE_NAME='disposition_review_proposals' THEN (to_jsonb(NEW)->>'id')::bigint WHEN TG_OP='DELETE' THEN (to_jsonb(OLD)->>'proposal_id')::bigint ELSE (to_jsonb(NEW)->>'proposal_id')::bigint END;
 SELECT * INTO p FROM disposition_review_proposals WHERE id=identity;
 IF p.proposal_type='add_to_holds' AND p.proposal_state='active' THEN
  IF (SELECT COALESCE(jsonb_agg(hold_id ORDER BY hold_id),'[]') FROM disposition_proposal_holds WHERE proposal_id=p.id)
   IS DISTINCT FROM (SELECT jsonb_agg(v::text::bigint ORDER BY v::text::bigint) FROM jsonb_array_elements(p.proposed_values->'hold_ids') v) THEN RAISE EXCEPTION 'disposition_proposal_holds_inconsistent'; END IF;
 ELSIF EXISTS(SELECT 1 FROM disposition_proposal_holds WHERE proposal_id=p.id) THEN RAISE EXCEPTION 'disposition_proposal_holds_inconsistent'; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.check_unit_trigger() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.claim_email(p_token uuid) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE selected bigint;
BEGIN
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'automated_process' OR current_user_id() IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_worker_required'; END IF;
 INSERT INTO disposition_private.communication_context VALUES(txid_current());
 -- A lost process never resends an uncertain SMTP transaction.
 FOR selected IN SELECT a.id FROM disposition_email_attempts a JOIN disposition_private.email_payloads p ON p.attempt_id=a.id WHERE a.status='sending' AND p.worker_token IS NOT NULL AND p.lease_expires_at<clock_timestamp() ORDER BY a.id LIMIT 100 FOR UPDATE OF a SKIP LOCKED LOOP
  UPDATE disposition_email_attempts SET status='unknown',outcome_at=clock_timestamp(),error_code='disposition_email_unknown' WHERE id=selected;
  UPDATE disposition_private.email_payloads SET encrypted_password=NULL WHERE attempt_id=selected;
  PERFORM disposition_private.email_event(selected,'DISPOSITION_EMAIL_OUTCOME');
 END LOOP;
 SELECT a.id INTO selected FROM disposition_email_attempts a JOIN disposition_private.email_payloads p ON p.attempt_id=a.id WHERE a.status='sending' AND p.worker_token IS NULL ORDER BY a.id LIMIT 1 FOR UPDATE OF a SKIP LOCKED;
 IF selected IS NOT NULL THEN
  UPDATE disposition_private.email_payloads p SET worker_token=p_token,lease_expires_at=clock_timestamp()+make_interval(secs=>((a.configuration->>'timeout_seconds')::int*10+30)) FROM disposition_email_attempts a WHERE p.attempt_id=selected AND a.id=selected;
 END IF;
 DELETE FROM disposition_private.communication_context WHERE transaction_id=txid_current();
 RETURN selected;
END $$;

CREATE FUNCTION disposition_private.claim_task(p_task bigint, p_version integer) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; next_version integer; acting_role bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_claim' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.version<>p_version OR t.task_state<>'open' THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 IF t.destination_role_id IS NULL THEN RAISE EXCEPTION 'disposition_role_queue_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_tasks other WHERE other.job_id=t.job_id AND other.workflow_stage=t.workflow_stage AND other.task_state='claimed' AND other.id<>t.id) THEN RAISE EXCEPTION 'disposition_task_already_claimed'; END IF;
 SELECT r.acting_role_id INTO acting_role FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_task_actor(p_task,acting_role,false);
 UPDATE disposition_tasks SET task_state='claimed',claimed_by_user_id=current_user_id() WHERE id=p_task RETURNING version INTO next_version;
 RETURN next_version;
END $$;

CREATE FUNCTION disposition_private.command_complete_check() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_private.command_receipts WHERE command_id=NEW.command_id AND completed_at IS NULL)
 OR EXISTS(SELECT 1 FROM disposition_private.command_context WHERE command_id=NEW.command_id) THEN RAISE EXCEPTION 'disposition_command_not_finished'; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.command_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND OLD.completed_at IS NOT NULL AND NEW.payload=disposition_private.retained_command_payload(OLD.payload) AND NEW.result=disposition_private.retained_history_json(OLD.result) AND (to_jsonb(NEW)-ARRAY['payload','result'])=(to_jsonb(OLD)-ARRAY['payload','result']) THEN RETURN NEW; END IF;

 IF TG_OP='DELETE' OR OLD.completed_at IS NOT NULL OR (to_jsonb(NEW)-ARRAY['result','completed_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['result','completed_at']) THEN RAISE EXCEPTION 'disposition_command_history_immutable'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.communication_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM disposition_private.communication_context WHERE transaction_id=txid_current()) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_communication_protected';
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE FUNCTION disposition_private.complete_certificate_task(p_job bigint, p_task bigint, p_version bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE;j disposition_jobs%ROWTYPE;acting bigint;doc bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'final_complete' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task AND job_id=p_job AND task_type='certificate_download' FOR UPDATE;
 IF t.id IS NULL OR t.task_state NOT IN ('open','claimed') THEN RAISE EXCEPTION 'disposition_certificate_task_unavailable'; END IF;
 IF t.version<>p_version THEN RAISE EXCEPTION 'disposition_stale_task'; END IF;
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 SELECT id INTO doc FROM disposition_job_documents WHERE job_id=p_job AND document_type='digital_destruction_certificate' AND document_state='available';
 IF doc IS NULL THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
 IF j.lifecycle_state='completed' THEN
  INSERT INTO disposition_private.completion_context VALUES(txid_current(),pg_backend_pid(),(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current()),p_job);
  PERFORM append_domain_event('disposition_job',p_job,'CERTIFICATE_TASK_COMPLETED',jsonb_build_object('task_id',t.id,'certificate_document_id',doc));
  UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
  DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current();
  RETURN jsonb_build_object('job_id',p_job,'task_id',t.id,'lifecycle_state','completed');
 END IF;
 RETURN disposition_private.finish_destruction_job(p_job,doc);
END $$;

CREATE FUNCTION disposition_private.completion_active(p_job bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.completion_context x JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE x.transaction_id=txid_current() AND x.backend_id=pg_backend_pid() AND x.job_id=p_job)
$$;

CREATE FUNCTION disposition_private.confirm_physical(p_task bigint, p_job_version integer, p_task_version integer, p_success boolean, p_reference text, p_document bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE scope jsonb;j bigint;acting bigint;key uuid;result_id bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 scope:=disposition_private.check_physical_work(p_task,p_job_version,p_task_version,acting);
 IF p_success IS DISTINCT FROM true OR p_reference IS NULL OR btrim(p_reference)='' THEN RAISE EXCEPTION 'disposition_physical_required'; END IF;
 SELECT job_id INTO j FROM disposition_tasks WHERE id=p_task;
 IF EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE certificate_reference=p_reference) THEN RAISE EXCEPTION 'disposition_physical_reference_used'; END IF;
 INSERT INTO disposition_private.physical_context VALUES(txid_current(),pg_backend_pid(),key,j);
 INSERT INTO disposition_physical_confirmations(job_id,task_id,successful,certificate_reference,certificate_document_id,confirmed_by_user_id,acting_role_id,confirmation_text,confirmation_version,physical_scope)
 VALUES(j,p_task,true,p_reference,p_document,current_user_id(),acting,'server supplied',1,scope) RETURNING id INTO result_id;
 UPDATE disposition_tasks SET task_state=CASE WHEN id=p_task THEN 'completed' ELSE 'cancelled' END WHERE job_id=j AND task_type='physical_destruction' AND task_state IN ('open','claimed');
 IF disposition_private.has_digital_material(j) THEN
  UPDATE disposition_jobs SET workflow_stage='digital_destruction' WHERE id=j;
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_role_id) SELECT j,'digital_destruction','digital_destruction',current_review_round,acting FROM disposition_jobs WHERE id=j;
 END IF;
 -- Physical-only finalization remains at the existing final_complete gate.
 PERFORM append_domain_event('disposition_job',j,'PHYSICAL_DESTRUCTION_CONFIRMED',jsonb_build_object('after',(SELECT to_jsonb(p) FROM disposition_physical_confirmations p WHERE id=result_id),'acting_role_id',acting));
 DELETE FROM disposition_private.physical_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('id',result_id,'job_id',j,'certificate_document_id',p_document,'workflow_stage',(SELECT workflow_stage FROM disposition_jobs WHERE id=j),'job_version',(SELECT version FROM disposition_jobs WHERE id=j));
END $$;

CREATE FUNCTION disposition_private.content_reserved(p_record bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM records r JOIN disposition_job_memberships m ON m.root_aggregation_id=disposition_private.root_id(r.aggregation_id)
 JOIN disposition_destruction_runs run ON run.job_id=m.job_id WHERE r.id=p_record AND run.state IN ('queued','running'))
$$;

CREATE FUNCTION disposition_private.context_operation() RETURNS text
    LANGUAGE sql STABLE
    AS $$
 SELECT COALESCE(CASE WHEN disposition_private.hook_applying() THEN 'recalculate'
 WHEN disposition_private.approval_active() AND (SELECT phase FROM disposition_private.approval_context WHERE transaction_id=txid_current())='removing' THEN 'membership_remove' END,
 (SELECT r.operation FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid() AND r.actor_user_id IS NOT DISTINCT FROM current_user_id()
 AND r.actor_type=current_setting('app.actor_type',true) AND r.completed_at IS NULL))
$$;

CREATE FUNCTION disposition_private.coordinate_policy_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN PERFORM pg_advisory_xact_lock(7357,1); PERFORM lock_hold_policy_shared(); RETURN NULL; END $$;

CREATE FUNCTION disposition_private.coordinate_relationship_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN PERFORM pg_advisory_xact_lock(7357,1); RETURN NULL; END $$;

CREATE FUNCTION disposition_private.create_email_attempt(p_command uuid, p_job bigint, p_document bigint, p_role bigint, p_config jsonb, p_database text, p_secret bytea, p_message text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE a disposition_email_attempts%ROWTYPE; d disposition_job_documents%ROWTYPE; content_id bigint; new_id bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(7361,hashtext(p_command::text));
 SELECT * INTO a FROM disposition_email_attempts WHERE command_id=p_command;
 IF FOUND THEN
  IF (a.job_id,a.document_id,a.actor_user_id,a.acting_role_id) IS DISTINCT FROM (p_job,p_document,current_user_id(),p_role) THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_command_conflict'; END IF;
  -- Exact committed retries return the captured attempt, even after its task closes.
  IF NOT disposition_private.person_role(current_user_id(),p_role) OR NOT user_can_view_record(current_user_id(),(SELECT record_id FROM disposition_job_documents WHERE id=p_document)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_email_not_authorized'; END IF;
  RETURN a.id;
 END IF;
 IF NOT disposition_private.can_email(current_user_id(),p_job,p_document,p_role) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_email_not_authorized'; END IF;
 SELECT * INTO STRICT d FROM disposition_job_documents WHERE id=p_document;
 SELECT active_content_set_id INTO STRICT content_id FROM digital_components WHERE id=d.digital_component_id;
 IF content_id IS NULL OR p_config->>'recipient' IS NULL OR p_config->>'sender_email' IS NULL OR p_config ? 'password' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='disposition_email_configuration'; END IF;
 INSERT INTO disposition_private.communication_context VALUES(txid_current());
 INSERT INTO disposition_email_attempts(command_id,job_id,document_id,review_round,actor_user_id,acting_role_id,recipient,sender,configuration,message_id)
 VALUES(p_command,p_job,p_document,d.review_round,current_user_id(),p_role,p_config->>'recipient',p_config->>'sender_email',p_config,p_message) RETURNING id INTO new_id;
 INSERT INTO disposition_private.email_payloads(attempt_id,content_set_id,checksum,database_id,encrypted_password) VALUES(new_id,content_id,d.checksum,p_database,p_secret);
 PERFORM disposition_private.email_event(new_id,'DISPOSITION_EMAIL_REQUESTED');
 DELETE FROM disposition_private.communication_context WHERE transaction_id=txid_current();
 RETURN new_id;
END $$;

CREATE FUNCTION disposition_private.create_job(p_number text, p_type text, p_owner bigint, p_assignee bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE job disposition_jobs%ROWTYPE; prefix text; job_year integer; serial bigint; zone text;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_create' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 IF p_number IS NULL THEN
  prefix:=CASE p_type WHEN 'destruction' THEN 'DT' WHEN 'permanent_transfer' THEN 'PT' WHEN 'selective_transfer' THEN 'ST' WHEN 'local_archives' THEN 'LA' END;
  IF prefix IS NULL THEN RAISE EXCEPTION 'disposition_job_type_invalid'; END IF;
  SELECT value#>>'{}' INTO zone FROM application_settings WHERE key='DEFAULT_WORKING_TIMEZONE';
  job_year:=extract(year FROM CURRENT_TIMESTAMP AT TIME ZONE COALESCE(zone,'UTC'))::integer;
  INSERT INTO disposition_private.job_number_counters(job_type,number_year,last_number)
  SELECT p_type,job_year,COALESCE(max(substring(job_number FROM '[0-9]+$')::bigint),0)+1
  FROM disposition_jobs WHERE job_number ~ ('^'||prefix||'-'||job_year||'-[0-9]+$')
  ON CONFLICT(job_type,number_year) DO UPDATE
  SET last_number=greatest(disposition_private.job_number_counters.last_number+1,excluded.last_number)
  RETURNING last_number INTO serial;
  p_number:=prefix||'-'||job_year||'-'||serial;
 END IF;
 INSERT INTO disposition_jobs(job_number,job_type,owning_org_unit_id,assigned_user_id,created_by_user_id,workflow_stage,disposition_status)
 VALUES(p_number,p_type,p_owner,p_assignee,current_user_id(),CASE WHEN p_type='destruction' THEN 'officer_preparation' END,
 CASE p_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 WHEN 'local_archives' THEN 9 END) RETURNING * INTO job;
 RETURN to_jsonb(job);
END $_$;

CREATE FUNCTION disposition_private.decide_review_work(p_task bigint, p_job_version integer, p_task_version integer, p_decision text, p_reason text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE t disposition_tasks%ROWTYPE; j disposition_jobs%ROWTYPE; round_id bigint; acting bigint; identity bigint; reason text;
BEGIN
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_context(p_task,p_job_version,p_task_version);
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id;
 IF t.workflow_stage NOT IN ('file_administrator_review','unit_manager_review','records_manager_review') OR p_decision NOT IN ('approved','rejected') OR (t.workflow_stage='file_administrator_review' AND p_decision<>'approved') THEN RAISE EXCEPTION 'disposition_review_decision_invalid'; END IF;
 IF t.workflow_stage='records_manager_review' AND p_decision='approved' THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
 IF p_decision='rejected' AND (p_reason IS NULL OR p_reason ~ '^[[:space:]]*$') THEN RAISE EXCEPTION 'disposition_decision_reason_required'; END IF;
 -- Intermediate completion records the review; it does not authorize proposal execution.
 -- Proposal writes and final Records Manager approval retain their full access checks.
 reason:=COALESCE(NULLIF(btrim(p_reason),''),CASE WHEN p_decision='rejected' THEN 'Return marked aggregations for correction' ELSE 'Complete authorized review' END);
 SELECT id INTO round_id FROM disposition_review_rounds WHERE job_id=j.id AND round_number=j.current_review_round;
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 INSERT INTO disposition_review_decisions(job_id,round_id,review_stage,decision,task_id,actor_user_id,acting_role_id,reason,membership_snapshot)
 VALUES(j.id,round_id,t.workflow_stage,p_decision,t.id,current_user_id(),acting,reason,disposition_private.membership_snapshot(j.id)) RETURNING id INTO identity;
 UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
 IF p_decision='rejected' THEN PERFORM disposition_private.route_correction(j.id);
 ELSE PERFORM disposition_private.route_review(j.id,CASE WHEN t.workflow_stage='file_administrator_review' THEN 'unit_manager_review' ELSE 'records_manager_review' END); END IF;
 RETURN jsonb_build_object('decision_id',identity,'job_id',j.id,'workflow_stage',(SELECT workflow_stage FROM disposition_jobs WHERE id=j.id),'job_version',(SELECT version FROM disposition_jobs WHERE id=j.id));
END $_$;

CREATE FUNCTION disposition_private.destruction_active(p_mode text DEFAULT NULL::text, p_root bigint DEFAULT NULL::bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.destruction_context d WHERE d.transaction_id=txid_current() AND d.backend_id=pg_backend_pid()
 AND (p_mode IS NULL OR d.mode=p_mode) AND (p_root IS NULL OR d.root_id=p_root)
 AND (d.command_id IS NULL OR EXISTS(SELECT 1 FROM disposition_private.command_context c WHERE c.transaction_id=d.transaction_id AND c.backend_id=d.backend_id AND c.command_id=d.command_id)))
$$;

CREATE FUNCTION disposition_private.destruction_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP='DELETE' OR NOT disposition_private.destruction_active() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_destruction_command_required'; END IF;
 IF TG_OP='UPDATE' AND ((TG_TABLE_NAME IN ('disposition_destruction_runs','disposition_destruction_run_units') AND (to_jsonb(OLD)->>'state') IN ('succeeded','failed')) OR (TG_TABLE_NAME='disposition_destruction_manifest_items' AND (to_jsonb(OLD)->>'destruction_state')='succeeded')) THEN RAISE EXCEPTION 'disposition_destruction_history_immutable'; END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('disposition_destruction_runs','disposition_destruction_run_units') THEN NEW.version:=OLD.version+1; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.destruction_scope(p_root bigint) RETURNS jsonb
    LANGUAGE sql STABLE
    SET "TimeZone" TO 'UTC'
    AS $$
 SELECT jsonb_build_object(
 'aggregations',(SELECT coalesce(jsonb_agg(jsonb_build_array(a.id,a.version,a.parent_aggregation_id,a.classification_id,a.owning_org_unit_id,a.security_level_id,a.medium,a.date_closed,a.disposition_status) ORDER BY a.id),'[]') FROM aggregations a WHERE a.id IN (SELECT disposition_private.unit_ids(p_root))),
 'records',(SELECT coalesce(jsonb_agg(jsonb_build_array(r.id,r.version,r.aggregation_id,r.owning_org_unit_id,r.security_level_id,r.medium,r.disposition_status) ORDER BY r.id),'[]') FROM records r WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),
 'components',(SELECT coalesce(jsonb_agg(jsonb_build_array(d.id,d.version,d.record_id,d.active_content_set_id,d.checksum_algo,d.checksum_value,d.size_in_bytes,d.storage_backend) ORDER BY d.id),'[]') FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),
 'rule',(SELECT jsonb_build_object('due',e.calculated_disposition_at,'rule',e.rule_snapshot) FROM disposition_private.eligibility(p_root) e))
$$;

CREATE FUNCTION disposition_private.eligibility(p_root bigint, p_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP) RETURNS TABLE(root_id bigint, date_closed timestamp with time zone, rule_snapshot jsonb, calculated_disposition_at timestamp with time zone, database_now timestamp with time zone, eligible_status smallint, is_due boolean)
    LANGUAGE sql STABLE
    AS $$
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

CREATE FUNCTION disposition_private.email_event(p_id bigint, p_operation text) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE a disposition_email_attempts%ROWTYPE;
BEGIN
 SELECT * INTO STRICT a FROM disposition_email_attempts WHERE id=p_id;
 PERFORM append_domain_event('disposition_job',a.job_id,p_operation,
  jsonb_build_object('email_attempt_id',a.id,'request_document_id',a.document_id,'review_round',a.review_round,
   'initiating_user_id',a.actor_user_id,'initiating_actor_type',a.actor_type,'acting_role_id',a.acting_role_id,
   'recipient',a.recipient,'sender',a.sender,'requested_at',a.requested_at,'outcome_at',a.outcome_at,
   'status',a.status,'message_id',a.message_id,'server_message_id',a.server_message_id,'error_code',a.error_code,'smtp_code',a.smtp_code),
   'External document email attempt');
END $$;

CREATE FUNCTION disposition_private.erase_unit_content(p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT disposition_private.destruction_active('delete',p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_destruction_command_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.processing_copies p JOIN digital_components d ON d.id=p.component_id JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))) THEN RAISE EXCEPTION 'disposition_processing_cleanup_required'; END IF;
 IF EXISTS(SELECT 1 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND d.storage_backend<>'postgresql') THEN RAISE EXCEPTION 'disposition_storage_backend_unsupported'; END IF;
 -- Remove attempt/error/operation fields too: none is permanent disposition proof.
 DELETE FROM content_indexing_batch_items WHERE component_identifier IN (SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM content_indexing_attempts WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM content_indexing_jobs WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_component_search_documents WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_component_blobs WHERE content_set_id IN (SELECT s.id FROM digital_component_content_sets s JOIN digital_components d ON d.id=s.digital_component_id JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_component_content_sets WHERE digital_component_id IN (SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_components WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
END $$;

CREATE FUNCTION disposition_private.evaluate_root(p_root bigint, p_command uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.external_active(p_job bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.external_context x JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE x.transaction_id=txid_current() AND x.backend_id=pg_backend_pid() AND x.job_id=p_job)
$$;

CREATE FUNCTION disposition_private.finish_command(p_result jsonb) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE command uuid;
BEGIN
 SELECT command_id INTO command FROM disposition_private.command_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid();
 IF command IS NULL OR p_result IS NULL THEN RAISE EXCEPTION 'disposition_command_required'; END IF;
 UPDATE disposition_private.command_receipts SET result=p_result,completed_at=CURRENT_TIMESTAMP WHERE command_id=command;
 DELETE FROM disposition_private.command_context WHERE transaction_id=txid_current();
END $$;

CREATE FUNCTION disposition_private.finish_destruction_job(p_job bigint, p_document bigint DEFAULT NULL::bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;acting bigint;key uuid;t record;physical disposition_physical_confirmations%ROWTYPE;root record;eid bigint;at_time timestamptz;executor bigint;executor_name text;download_id bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'final_complete' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF j.lifecycle_state IS DISTINCT FROM 'active' OR j.job_type IS DISTINCT FROM 'destruction' THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
 PERFORM disposition_private.require_actor(acting);
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT disposition_private.review_role(p_job,'records_manager_review',acting) OR NOT disposition_private.person_role(current_user_id(),acting) OR NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 IF p_document IS NOT NULL THEN
  IF EXISTS(SELECT 1 FROM disposition_private.completion_work WHERE job_id=p_job AND state='running') THEN
   SELECT task_id INTO download_id FROM disposition_private.completion_work WHERE job_id=p_job AND state='running' AND requested_by_user_id=current_user_id() AND acting_role_id=acting;
   PERFORM disposition_private.check_completion(p_job,download_id,acting);
  ELSE
   SELECT id INTO download_id FROM disposition_tasks WHERE job_id=p_job AND task_type='certificate_download' AND task_state IN ('open','claimed') FOR UPDATE;
   IF j.workflow_stage<>'certificate_generation' OR download_id IS NULL OR NOT EXISTS(SELECT 1 FROM disposition_private.completion_work WHERE job_id=p_job AND state='succeeded' AND document_id=p_document) THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
   PERFORM disposition_private.require_task_actor(download_id,acting,true);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=p_document AND d.job_id=p_job AND d.document_type='digital_destruction_certificate' AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id) AND d.provenance->>'completion_request_id'=(SELECT request_id::text FROM disposition_private.completion_work WHERE job_id=p_job)) THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
 ELSE
  SELECT * INTO physical FROM disposition_physical_confirmations WHERE job_id=p_job;
  IF j.workflow_stage<>'physical_destruction' OR physical.id IS NULL OR physical.confirmed_by_user_id<>current_user_id() OR disposition_private.has_digital_material(p_job) OR NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=physical.certificate_document_id AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)) THEN RAISE EXCEPTION 'disposition_physical_certificate_required'; END IF;
 END IF;
 INSERT INTO disposition_private.completion_context VALUES(txid_current(),pg_backend_pid(),key,p_job);
 -- Saving the certificate prepares the last human task; it does not finish the job.
 IF p_document IS NOT NULL AND EXISTS(SELECT 1 FROM disposition_private.completion_work WHERE job_id=p_job AND state='running') THEN
  UPDATE disposition_tasks SET task_state='completed' WHERE id=download_id;
  UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_type='digital_destruction' AND task_state IN ('open','claimed');
  UPDATE disposition_jobs SET workflow_stage='certificate_generation' WHERE id=p_job;
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id) VALUES(p_job,'certificate_download','certificate_generation',j.current_review_round,current_user_id()) RETURNING id INTO download_id;
  UPDATE disposition_private.completion_work SET state='succeeded',finished_at=clock_timestamp(),last_error_code=NULL,document_id=p_document WHERE job_id=p_job;
  PERFORM append_domain_event('disposition_job',p_job,'DIGITAL_CERTIFICATE_SAVED',jsonb_build_object('certificate_document_id',p_document,'task_id',download_id));
  DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current();
  RETURN jsonb_build_object('job_id',p_job,'lifecycle_state','active','certificate_document_id',p_document,'download_task_id',download_id);
 END IF;

 IF p_document IS NULL THEN
  -- Confirmation and completion share the caller's transaction. Reuse the
  -- verified physical-proof/minimization primitive, never digital deletion.
  FOR root IN SELECT a.id,a.version FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id WHERE m.job_id=p_job AND m.membership_state='active' ORDER BY a.id LOOP
   IF NOT disposition_private.physical_covered(p_job,root.id) OR disposition_private.unit_has_digital(root.id) THEN RAISE EXCEPTION 'disposition_recovery_scope_invalid'; END IF;
   INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,root.id,10);
   PERFORM disposition_private.transition_unit(root.id,root.version,10);
   UPDATE disposition_job_memberships SET membership_state='completed_history' WHERE job_id=p_job AND root_aggregation_id=root.id AND membership_state='active';
  END LOOP;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='completed_history') OR EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id WHERE m.job_id=p_job AND (m.membership_state='active' OR m.membership_state='completed_history' AND (a.disposition_status<>10 OR a.disposition_job_id IS DISTINCT FROM p_job))) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 SELECT destroyed_at,executor_user_id,p.executor_name INTO at_time,executor,executor_name FROM disposition_retained_records p WHERE p.job_id=p_job ORDER BY destroyed_at DESC,resource_kind,resource_id LIMIT 1;
 IF at_time IS NULL THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 eid:=append_domain_event('disposition_job',p_job,'DESTRUCTION_JOB_COMPLETED',jsonb_build_object('job_id',p_job,'certificate_document_id',coalesce(p_document,physical.certificate_document_id),'digital_certificate',p_document IS NOT NULL,'executor_user_id',executor,'executor_name',executor_name,'completed_at',at_time));
 -- Close current digital queues while their task eligibility is still active.
 IF p_document IS NOT NULL THEN
  UPDATE disposition_tasks SET task_state='completed' WHERE id=download_id;
  UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_type='digital_destruction' AND task_state IN ('open','claimed');
 END IF;
 UPDATE disposition_jobs SET workflow_stage='certificate_generation',lifecycle_state='completed',disposition_status=10,completed_at=at_time,completed_by_user_id=executor,completed_by_name=executor_name,final_event_id=eid WHERE id=p_job;

 DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',p_job,'lifecycle_state','completed','certificate_document_id',coalesce(p_document,physical.certificate_document_id),'task_id',CASE WHEN p_document IS NOT NULL THEN download_id END);
END $$;

CREATE FUNCTION disposition_private.finish_digital_unit(p_run bigint, p_root bigint, p_token uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE run disposition_destruction_runs%ROWTYPE;at_time timestamptz:=clock_timestamp();key uuid;event_id bigint;name text;finished boolean;physical disposition_physical_confirmations%ROWTYPE;proof_at timestamptz;proof_user bigint;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT * INTO run FROM disposition_destruction_runs WHERE id=p_run FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM disposition_destruction_run_units WHERE run_id=p_run AND root_id=p_root AND state='running' AND claim_token=p_token) THEN RAISE EXCEPTION 'disposition_digital_claim_lost'; END IF;
 IF run.requested_by_user_id IS DISTINCT FROM current_user_id() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_authorization_required'; END IF;
 PERFORM disposition_private.require_task_actor(run.task_id,run.acting_role_id,true);
 PERFORM disposition_private.check_digital_job(run.job_id,run.acting_role_id,false);
 IF NOT EXISTS(SELECT 1 FROM disposition_private.destruction_scopes WHERE run_id=p_run AND root_id=p_root AND scope=disposition_private.destruction_scope(p_root)) THEN
  IF disposition_private.physical_covered(run.job_id,p_root) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
  RAISE EXCEPTION 'disposition_digital_scope_changed'; END IF;
 SELECT command_id INTO key FROM disposition_private.command_context WHERE transaction_id=txid_current();
 INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),key,p_run,p_root,p_token,'delete');
 IF NOT disposition_private.unit_has_digital(p_root) THEN
  SELECT * INTO physical FROM disposition_physical_confirmations WHERE job_id=run.job_id;
  IF physical.id IS NULL OR NOT disposition_private.physical_covered(run.job_id,p_root) THEN RAISE EXCEPTION 'disposition_physical_confirmation_required'; END IF;
  UPDATE disposition_private.destruction_context SET mode='finalize' WHERE transaction_id=txid_current();
  SELECT e.actor_name INTO name FROM event_history e WHERE e.entity_type='disposition_job' AND e.entity_id=run.job_id AND e.operation='PHYSICAL_DESTRUCTION_CONFIRMED' ORDER BY e.id LIMIT 1;
  event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_UNIT_DESTROYED',jsonb_build_object('recovery_job_id',run.job_id,'root_id',p_root,'physical_confirmation_id',physical.id,'certificate_document_id',physical.certificate_document_id,'executor_user_id',physical.confirmed_by_user_id,'executor_name',name,'completed_at',physical.confirmed_at));
  PERFORM disposition_private.retain_unit(run.job_id,p_root,NULL,event_id,physical.confirmed_at,physical.confirmed_by_user_id,name);
 ELSE
 PERFORM disposition_private.erase_unit_content(p_root);
 UPDATE disposition_private.destruction_context SET mode='finalize' WHERE transaction_id=txid_current();
 SELECT u.name INTO name FROM users u WHERE u.id=current_user_id();
 event_id:=append_domain_event('aggregation',p_root,'DIGITAL_DESTRUCTION_UNIT_COMPLETED',jsonb_build_object('job_id',run.job_id,'run_id',p_run,'root_id',p_root,'executor_user_id',current_user_id(),'executor_name',name,'completed_at',at_time,'method','postgresql_transactional_erasure','command_id',key));
 PERFORM disposition_private.retain_unit(run.job_id,p_root,p_run,event_id,at_time,current_user_id(),name);
 END IF;
 UPDATE disposition_job_memberships SET membership_state='completed_history' WHERE job_id=run.job_id AND root_aggregation_id=p_root AND membership_state='active';
 UPDATE disposition_destruction_manifest_items SET destruction_state='succeeded',destroyed_at=at_time,run_id=p_run WHERE job_id=run.job_id AND root_id=p_root AND destruction_state='queued';
 UPDATE disposition_destruction_run_units SET state='succeeded',finished_at=at_time WHERE run_id=p_run AND root_id=p_root;
 SELECT NOT EXISTS(SELECT 1 FROM disposition_destruction_run_units WHERE run_id=p_run AND state<>'succeeded') INTO finished;
 UPDATE disposition_destruction_runs SET completed_units=completed_units+1,state=CASE WHEN finished THEN 'succeeded' ELSE 'running' END,finished_at=CASE WHEN finished THEN at_time END WHERE id=p_run;
 PERFORM disposition_private.minimize_unit_history(run.job_id,p_root);
 PERFORM append_domain_event('disposition_job',run.job_id,CASE WHEN finished THEN 'DIGITAL_DESTRUCTION_SUCCEEDED' ELSE 'DIGITAL_DESTRUCTION_PROGRESS' END,jsonb_build_object('run_id',p_run,'root_id',p_root,'completed_units',(SELECT completed_units FROM disposition_destruction_runs WHERE id=p_run),'job_completed',false));
 IF finished AND NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=run.job_id AND membership_state='active') THEN
  INSERT INTO disposition_private.completion_work(job_id,request_id,task_id,requested_by_user_id,acting_role_id,state) VALUES(run.job_id,key,run.task_id,run.requested_by_user_id,run.acting_role_id,'queued') ON CONFLICT(job_id) DO NOTHING;
 END IF;
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('run_id',p_run,'root_id',p_root,'state','succeeded','run_finished',finished);
END $$;

CREATE FUNCTION disposition_private.finish_email(p_id bigint, p_token uuid, p_status text, p_error text, p_code integer, p_server_id text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'automated_process' OR current_user_id() IS NOT NULL OR p_status NOT IN ('smtp_accepted','failed','unknown')
 OR p_error IS NOT NULL AND p_error NOT IN ('disposition_email_failed','disposition_email_unknown','disposition_email_configuration','disposition_email_not_authorized','disposition_document_unavailable')
 OR length(COALESCE(p_server_id,''))>120 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_communication_protected'; END IF;
 PERFORM 1 FROM disposition_email_attempts a JOIN disposition_private.email_payloads p ON p.attempt_id=a.id WHERE a.id=p_id AND a.status='sending' AND p.worker_token=p_token FOR UPDATE OF a;
 IF NOT FOUND THEN RETURN; END IF;
 INSERT INTO disposition_private.communication_context VALUES(txid_current());
 UPDATE disposition_email_attempts SET status=p_status,outcome_at=clock_timestamp(),error_code=p_error,smtp_code=p_code,server_message_id=p_server_id WHERE id=p_id;
 UPDATE disposition_private.email_payloads SET encrypted_password=NULL WHERE attempt_id=p_id;
 PERFORM disposition_private.email_event(p_id,'DISPOSITION_EMAIL_OUTCOME');
 DELETE FROM disposition_private.communication_context WHERE transaction_id=txid_current();
END $$;

CREATE FUNCTION disposition_private.finish_policy_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE root bigint;
BEGIN
 IF disposition_private.hook_applying() THEN RETURN NULL; END IF;
 FOR root IN SELECT root_id FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() ORDER BY root_id
 LOOP PERFORM disposition_private.apply_recalculation(root); END LOOP;
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.governance_person(p_user bigint, p_profile text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE p.code=p_profile AND r.is_information_governance AND v.code='disposition.jobs.manage'
 AND disposition_private.person_role(p_user,r.id))
$$;

CREATE FUNCTION disposition_private.guard_artifact() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE target record; previous disposition_job_documents%ROWTYPE; role_id bigint;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND NEW.provenance=disposition_private.retained_history_json(OLD.provenance) AND (to_jsonb(NEW)-'provenance')=(to_jsonb(OLD)-'provenance') THEN RETURN NEW; END IF;

 PERFORM disposition_private.require_command();
 IF NEW.document_type='digital_destruction_certificate' AND NOT disposition_private.completion_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_completion_command_required'; END IF;
 SELECT r.acting_role_id INTO role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF NEW.acting_role_id IS DISTINCT FROM role_id THEN RAISE EXCEPTION 'disposition_document_actor_mismatch'; END IF;
 IF NEW.origin IS DISTINCT FROM (CASE WHEN NEW.document_type IN ('external_rejection_letter','external_approval_letter','physical_destruction_certificate') THEN 'uploaded' ELSE 'generated' END) THEN RAISE EXCEPTION 'disposition_document_origin_invalid'; END IF;
 IF NEW.supersedes_document_id IS NOT NULL THEN
  SELECT * INTO previous FROM disposition_job_documents WHERE id=NEW.supersedes_document_id FOR UPDATE;
  IF previous.id IS NULL OR previous.origin<>'uploaded' OR NEW.origin<>'uploaded'
   OR previous.job_id<>NEW.job_id OR previous.document_type<>NEW.document_type
   OR previous.document_state<>'available' OR NEW.evidence_version<>previous.evidence_version+1
   OR NEW.review_round IS DISTINCT FROM previous.review_round
   OR EXISTS(SELECT 1 FROM disposition_job_documents WHERE supersedes_document_id=previous.id)
  THEN RAISE EXCEPTION 'disposition_evidence_version_invalid'; END IF;
  IF NOT disposition_private.can_correct_evidence(NEW.job_id,role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_evidence_correction_forbidden'; END IF;
 ELSIF NEW.evidence_version<>1 THEN RAISE EXCEPTION 'disposition_evidence_version_invalid'; END IF;
 IF NEW.document_state='available' THEN
  SELECT * INTO target FROM disposition_private.artifact_destination(NEW.document_type);
  IF (NEW.classification_scheme_id,NEW.classification_id,NEW.aggregation_id) IS DISTINCT FROM (target.scheme_id,target.classification_id,target.aggregation_id)
  OR NOT EXISTS(SELECT 1 FROM records r WHERE r.id=NEW.record_id AND r.aggregation_id=target.aggregation_id)
  OR EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=NEW.job_id AND m.membership_state IN ('active','completed_history') AND m.root_aggregation_id=target.aggregation_id)
  THEN RAISE EXCEPTION 'disposition_document_destination_invalid'; END IF;
  IF NOT EXISTS(SELECT 1 FROM digital_components c JOIN digital_component_content_sets s ON s.id=c.active_content_set_id AND s.digital_component_id=c.id
   WHERE c.id=NEW.digital_component_id AND c.record_id=NEW.record_id AND c.content_status='available' AND s.status='active'
   AND c.checksum_algo=NEW.checksum_algo AND c.checksum_value=NEW.checksum AND s.checksum_value=NEW.checksum)
  THEN RAISE EXCEPTION 'disposition_document_content_unavailable'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_destruction_number() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 PERFORM disposition_private.require_command();
 IF TG_OP<>'INSERT' OR NOT disposition_private.external_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_number_immutable'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_external_approval() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE;j disposition_jobs%ROWTYPE;letter disposition_job_documents%ROWTYPE;req disposition_job_documents%ROWTYPE;acting bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF TG_OP<>'INSERT' OR NOT disposition_private.external_active(NEW.job_id) OR disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_external_immutable'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=NEW.task_id;
 SELECT * INTO j FROM disposition_jobs WHERE id=NEW.job_id;
 SELECT acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 SELECT * INTO req FROM disposition_job_documents WHERE id=NEW.request_document_id;
 SELECT * INTO letter FROM disposition_job_documents WHERE id=COALESCE(NEW.approval_letter_document_id,NEW.rejection_letter_document_id);
 IF t.job_id<>j.id OR t.task_type<>'external_approval' OR t.request_document_id<>req.id OR j.workflow_stage<>'external_approval_pending' OR j.lifecycle_state<>'active' OR NEW.round_id::text IS DISTINCT FROM req.provenance->>'approval_round_id' OR req.review_round<>j.current_review_round THEN RAISE EXCEPTION 'disposition_external_request_mismatch'; END IF;
 IF NEW.recorded_by_user_id IS DISTINCT FROM current_user_id() OR NEW.acting_role_id IS DISTINCT FROM acting THEN RAISE EXCEPTION 'disposition_document_actor_mismatch'; END IF;
 IF letter.id IS NULL OR letter.job_id<>j.id OR letter.document_type IS DISTINCT FROM (CASE NEW.decision WHEN 'approved' THEN 'external_approval_letter' ELSE 'external_rejection_letter' END) OR letter.document_state<>'available' OR letter.created_by_user_id<>current_user_id() OR letter.review_round<>j.current_review_round OR letter.provenance->>'request_document_id' IS DISTINCT FROM req.id::text OR letter.provenance->>'external_command_id' IS DISTINCT FROM (SELECT command_id::text FROM disposition_private.command_context WHERE transaction_id=txid_current()) THEN RAISE EXCEPTION 'disposition_external_letter_required'; END IF;
 IF NOT current_user_can_view_record(req.record_id) OR NOT current_user_can_view_record(letter.record_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF NEW.decision='approved' AND NOT disposition_private.request_approval_current(j.id,NEW.round_id) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 NEW.recorded_at:=CURRENT_TIMESTAMP;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_external_task() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.request_document_id IS DISTINCT FROM OLD.request_document_id THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
 IF TG_OP='UPDATE' AND NEW.task_type='external_approval' AND NEW.task_state='completed' AND OLD.task_state<>NEW.task_state AND (NOT disposition_private.external_active(NEW.job_id) OR NOT EXISTS(SELECT 1 FROM disposition_external_approvals WHERE task_id=NEW.id)) THEN RAISE EXCEPTION 'disposition_external_command_required'; END IF;
 IF TG_OP='INSERT' AND NEW.task_type='external_approval' THEN
  IF NOT disposition_private.external_active(NEW.job_id) OR NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=NEW.request_document_id AND d.job_id=NEW.job_id AND d.document_type='destruction_request' AND d.review_round=NEW.review_round AND d.document_state='available') THEN RAISE EXCEPTION 'disposition_request_required'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_physical_confirmation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE acting bigint;key uuid;t disposition_tasks%ROWTYPE;doc disposition_job_documents%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'disposition_physical_immutable'; END IF;
 IF NOT disposition_private.physical_active(NEW.job_id) OR disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_physical_required'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 SELECT * INTO t FROM disposition_tasks WHERE id=NEW.task_id;
 PERFORM disposition_private.check_physical_work(t.id,(SELECT version FROM disposition_jobs WHERE id=NEW.job_id),t.version,acting);
 SELECT * INTO doc FROM disposition_job_documents WHERE id=NEW.certificate_document_id;
 IF t.job_id IS DISTINCT FROM NEW.job_id OR doc.id IS NULL OR doc.job_id<>NEW.job_id OR doc.document_type<>'physical_destruction_certificate' OR doc.document_state<>'available' OR doc.created_by_user_id IS DISTINCT FROM current_user_id() OR doc.provenance->>'physical_command_id' IS DISTINCT FROM key::text OR doc.provenance->>'certificate_reference' IS DISTINCT FROM NEW.certificate_reference OR NOT current_user_can_view_record(doc.record_id) OR NOT current_user_can_list_record_components(doc.record_id) THEN RAISE EXCEPTION 'disposition_physical_certificate_required'; END IF;
 IF NEW.confirmed_by_user_id IS DISTINCT FROM current_user_id() OR NEW.acting_role_id IS DISTINCT FROM acting OR NEW.physical_scope IS DISTINCT FROM disposition_private.physical_scope(NEW.job_id) THEN RAISE EXCEPTION 'disposition_physical_scope_invalid'; END IF;
 NEW.confirmed_at:=CURRENT_TIMESTAMP;
 NEW.confirmation_version:=1;
 NEW.confirmation_text:='أؤكد إتمام الإتلاف الورقي بنجاح / I confirm that physical destruction was completed successfully.';
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_physical_task() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP='INSERT' AND NEW.task_type='physical_destruction' AND NOT disposition_private.external_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_external_command_required'; END IF;
 IF TG_OP='UPDATE' AND OLD.task_type='physical_destruction' AND NEW.task_state='completed' AND OLD.task_state IS DISTINCT FROM NEW.task_state AND NOT disposition_private.physical_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_physical_required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_proposal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; acting bigint; old_proposal disposition_review_proposals%ROWTYPE; facts jsonb; op text;
BEGIN
 PERFORM disposition_private.require_command();op:=disposition_private.context_operation();
 IF TG_OP='UPDATE' AND op='review_decide' AND disposition_private.approval_active(NEW.job_id) THEN
  IF OLD.proposal_state<>'active' OR OLD.review_round<>(SELECT current_review_round FROM disposition_jobs WHERE id=OLD.job_id)
   OR NEW.proposal_state<>'executed' OR (to_jsonb(NEW)-ARRAY['proposal_state','executed_by_user_id','executed_at','execution_message','version','date_updated'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['proposal_state','executed_by_user_id','executed_at','execution_message','version','date_updated']) THEN RAISE EXCEPTION 'disposition_proposal_execution_scope_invalid'; END IF;
  NEW.executed_by_user_id:=current_user_id();NEW.executed_at:=CURRENT_TIMESTAMP;NEW.version:=OLD.version+1;NEW.date_updated:=CURRENT_TIMESTAMP;RETURN NEW;
 END IF;

 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
 IF op NOT IN ('review_save','review_submit') AND NOT disposition_private.approval_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
 t:=disposition_private.review_actor(NEW.job_id);
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF TG_OP='UPDATE' THEN
  IF OLD.proposal_state<>'active' THEN RAISE EXCEPTION 'disposition_proposal_closed'; END IF;
  IF OLD.review_round<>disposition_private.review_round_for_work(OLD.job_id) THEN RAISE EXCEPTION 'disposition_proposal_round_closed'; END IF;
  IF (to_jsonb(NEW)-ARRAY['proposed_values','current_values','reason','proposal_state','last_revised_by_user_id','last_revised_role_id','last_revised_stage','last_revised_round','last_revised_at','withdrawn_by_user_id','withdrawn_at','withdrawal_reason','version','date_updated'])
   IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['proposed_values','current_values','reason','proposal_state','last_revised_by_user_id','last_revised_role_id','last_revised_stage','last_revised_round','last_revised_at','withdrawn_by_user_id','withdrawn_at','withdrawal_reason','version','date_updated']) THEN RAISE EXCEPTION 'disposition_proposal_identity_immutable'; END IF;
  IF NEW.proposal_state NOT IN ('active','withdrawn') THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
  NEW.version:=OLD.version+1;
  NEW.last_revised_by_user_id:=current_user_id();NEW.last_revised_role_id:=acting;NEW.last_revised_stage:=t.workflow_stage;
  NEW.last_revised_round:=NEW.review_round;NEW.last_revised_at:=CURRENT_TIMESTAMP;
 ELSE
  IF NEW.proposal_state<>'active' OR NEW.version<>1 OR NEW.executed_by_user_id IS NOT NULL OR NEW.executed_at IS NOT NULL OR NEW.execution_message IS NOT NULL THEN RAISE EXCEPTION 'disposition_proposal_initial_state_invalid'; END IF;
  IF op='review_submit' OR (op='review_decide' AND disposition_private.approval_active(NEW.job_id)) THEN
   SELECT * INTO old_proposal FROM disposition_review_proposals WHERE id=NEW.carried_from_proposal_id;
   IF NOT FOUND OR old_proposal.job_id<>NEW.job_id OR old_proposal.proposal_state<>'active'
    OR old_proposal.review_round<>(SELECT current_review_round FROM disposition_jobs WHERE id=NEW.job_id)
    OR NEW.review_round<>old_proposal.review_round+1
    OR (NEW.proposer_user_id,NEW.proposer_role_id,NEW.proposer_stage,NEW.proposed_at,NEW.original_review_round,NEW.governing_root_id,NEW.target_aggregation_id,NEW.target_record_id,NEW.proposal_type,NEW.proposed_values,NEW.reason)
     IS DISTINCT FROM (old_proposal.proposer_user_id,old_proposal.proposer_role_id,old_proposal.proposer_stage,old_proposal.proposed_at,old_proposal.original_review_round,old_proposal.governing_root_id,old_proposal.target_aggregation_id,old_proposal.target_record_id,old_proposal.proposal_type,old_proposal.proposed_values,old_proposal.reason)
    THEN RAISE EXCEPTION 'disposition_proposal_carry_invalid'; END IF;
  ELSE
   IF NEW.review_round<>disposition_private.review_round_for_work(NEW.job_id) OR NEW.original_review_round<>NEW.review_round OR NEW.carried_from_proposal_id IS NOT NULL
    OR NEW.proposer_user_id<>current_user_id() OR NEW.proposer_role_id<>acting OR NEW.proposer_stage<>t.workflow_stage THEN RAISE EXCEPTION 'disposition_proposal_actor_invalid'; END IF;
   NEW.last_revised_by_user_id:=NULL;NEW.last_revised_role_id:=NULL;NEW.last_revised_stage:=NULL;NEW.last_revised_round:=NULL;NEW.last_revised_at:=NULL;
   NEW.withdrawn_by_user_id:=NULL;NEW.withdrawn_at:=NULL;NEW.withdrawal_reason:=NULL;
   NEW.proposed_at:=CURRENT_TIMESTAMP;
  END IF;
 END IF;
 IF NEW.proposal_state='withdrawn' THEN
  IF NOT current_user_can_view_aggregation(OLD.target_aggregation_id) OR (OLD.target_record_id IS NOT NULL AND NOT current_user_can_view_record(OLD.target_record_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  NEW.withdrawn_by_user_id:=current_user_id();NEW.withdrawn_at:=CURRENT_TIMESTAMP;
 ELSE
  facts:=disposition_private.proposal_facts(NEW.job_id,NEW.governing_root_id,NEW.target_aggregation_id,NEW.target_record_id,NEW.proposal_type,NEW.proposed_values,NEW.reason);
  NEW.current_values:=facts;
 END IF;
 NEW.date_updated:=CURRENT_TIMESTAMP;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_proposal_effect() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE p disposition_review_proposals%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize',OLD.governing_root_id) AND NEW.details=disposition_private.retained_json(OLD.details) AND (to_jsonb(NEW)-'details')=(to_jsonb(OLD)-'details') THEN RETURN NEW; END IF;

 IF TG_OP<>'INSERT' OR NOT disposition_private.approval_active(NULL,NEW.governing_root_id) THEN RAISE EXCEPTION 'disposition_effect_immutable'; END IF;
 SELECT * INTO p FROM disposition_review_proposals WHERE id=NEW.proposal_id;
 IF NOT FOUND OR NOT disposition_private.approval_active(p.job_id) THEN RAISE EXCEPTION 'disposition_effect_scope_invalid'; END IF;
 NEW.actor_user_id:=current_user_id();NEW.acting_role_id:=(SELECT acting_role_id FROM disposition_private.approval_context WHERE transaction_id=txid_current());NEW.occurred_at:=CURRENT_TIMESTAMP;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_proposal_hold() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE p disposition_review_proposals%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT * INTO p FROM disposition_review_proposals WHERE id=CASE WHEN TG_OP='DELETE' THEN OLD.proposal_id ELSE NEW.proposal_id END;
 PERFORM disposition_private.review_actor(p.job_id);
 IF (disposition_private.context_operation() NOT IN ('review_save','review_submit') AND NOT disposition_private.approval_active(p.job_id)) OR p.proposal_type<>'add_to_holds' OR p.proposal_state<>'active' OR TG_OP='UPDATE' OR NOT (p.review_round=disposition_private.review_round_for_work(p.job_id) OR ((disposition_private.context_operation()='review_submit' OR disposition_private.approval_active(p.job_id)) AND p.review_round=(SELECT current_review_round+1 FROM disposition_jobs WHERE id=p.job_id))) THEN RAISE EXCEPTION 'disposition_proposal_hold_scope_invalid'; END IF;
 IF TG_OP='INSERT' THEN
  IF NOT disposition_private.hold_visible(NEW.hold_id) OR NOT (p.proposed_values->'hold_ids' @> to_jsonb(NEW.hold_id)) THEN RAISE EXCEPTION 'disposition_proposal_hold_scope_invalid'; END IF;
  NEW.hold_snapshot:=(SELECT to_jsonb(h) FROM holds h WHERE id=NEW.hold_id);
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE FUNCTION disposition_private.guard_recovery_resource() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE root bigint;data jsonb;old_data jsonb;target integer;
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 data:=to_jsonb(NEW);old_data:=to_jsonb(OLD);
 root:=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (old_data->>'aggregation_id')::bigint END);
 target:=(data->>'disposition_status')::integer;
 IF OLD.disposition_status=13 AND ((data->'date_closed') IS DISTINCT FROM (old_data->'date_closed') OR (data->'parent_aggregation_id') IS DISTINCT FROM (old_data->'parent_aggregation_id') OR (data->'aggregation_id') IS DISTINCT FROM (old_data->'aggregation_id') OR (data->'medium') IS DISTINCT FROM (old_data->'medium')) THEN RAISE EXCEPTION 'disposition_recovery_command_required'; END IF;
 IF OLD.disposition_status IS DISTINCT FROM target AND (OLD.disposition_status=13 OR target=13 OR (target=10 AND disposition_private.context_operation()='job_terminate')) THEN
  PERFORM disposition_private.require_command();
  IF NOT disposition_private.recovery_active(NULL,root,target) THEN RAISE EXCEPTION 'disposition_recovery_command_required'; END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN disposition_jobs j ON j.id=m.job_id WHERE m.root_aggregation_id=root AND m.membership_state='active' AND j.lifecycle_state='active' AND disposition_private.physical_covered(j.id,root)) AND NOT disposition_private.recovery_active(NULL,root,target) AND
 ((OLD.disposition_status IS DISTINCT FROM target) OR (data->'date_closed') IS DISTINCT FROM (old_data->'date_closed') OR (data->'parent_aggregation_id') IS DISTINCT FROM (old_data->'parent_aggregation_id') OR (data->'aggregation_id') IS DISTINCT FROM (old_data->'aggregation_id') OR (data->'classification_id') IS DISTINCT FROM (old_data->'classification_id') OR (data->'medium') IS DISTINCT FROM (old_data->'medium')) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_resource() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE previous jsonb; following jsonb; fields text[] := ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id']; operation text; inherited smallint;
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

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

CREATE FUNCTION disposition_private.guard_review_draft_fields() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF disposition_private.context_operation()='review_save' THEN
  PERFORM disposition_private.review_actor(CASE WHEN TG_TABLE_NAME='disposition_jobs' THEN (to_jsonb(NEW)->>'id')::bigint ELSE (to_jsonb(NEW)->>'job_id')::bigint END);
  IF TG_TABLE_NAME='disposition_jobs' THEN
   IF (to_jsonb(NEW)-ARRAY['version','date_updated','updated_by_user_id']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','date_updated','updated_by_user_id']) THEN RAISE EXCEPTION 'disposition_save_scope_invalid'; END IF;
  ELSE
   IF (to_jsonb(NEW)-ARRAY['version','date_updated','draft_overall_reason']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','date_updated','draft_overall_reason']) THEN RAISE EXCEPTION 'disposition_save_scope_invalid'; END IF;
   IF NEW.draft_overall_reason IS DISTINCT FROM OLD.draft_overall_reason AND NEW.workflow_stage NOT IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') THEN RAISE EXCEPTION 'disposition_submission_reason_owner_required'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='disposition_tasks' AND to_jsonb(NEW)->>'draft_overall_reason' IS DISTINCT FROM to_jsonb(OLD)->>'draft_overall_reason' THEN RAISE EXCEPTION 'disposition_save_required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_review_note() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; acting bigint;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_save' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_actor(NEW.job_id);
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF NEW.task_id<>t.id OR NEW.author_user_id<>current_user_id() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_own_note_required'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (NEW.id,NEW.job_id,NEW.task_id,NEW.review_round,NEW.workflow_stage,NEW.author_user_id,NEW.date_created) IS DISTINCT FROM (OLD.id,OLD.job_id,OLD.task_id,OLD.review_round,OLD.workflow_stage,OLD.author_user_id,OLD.date_created) THEN RAISE EXCEPTION 'disposition_note_identity_immutable'; END IF;
  NEW.version:=OLD.version+1;
 ELSE
  IF NEW.review_round<>disposition_private.review_round_for_work(NEW.job_id) OR NEW.workflow_stage<>t.workflow_stage OR NEW.version<>1 THEN RAISE EXCEPTION 'disposition_note_context_invalid'; END IF;
  NEW.date_created:=CURRENT_TIMESTAMP;
 END IF;
 NEW.acting_role_id:=acting;NEW.date_updated:=CURRENT_TIMESTAMP;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_template_revision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE command disposition_private.command_receipts%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'disposition_template_immutable'; END IF;
 PERFORM disposition_private.require_command();
 SELECT r.* INTO command FROM disposition_private.command_context c
 JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF command.operation<>'document_save' OR command.payload->>'template_upload' IS DISTINCT FROM 'true'
 OR NOT disposition_private.can_revise_template(command.acting_role_id)
 OR NEW.acting_role_id<>command.acting_role_id OR NEW.uploaded_by_user_id<>current_user_id()
 OR NEW.actor_type<>'user' OR NEW.uploaded_at<>CURRENT_TIMESTAMP
 OR command.payload->>'checksum' IS DISTINCT FROM NEW.checksum
 OR command.payload->>'kind' IS DISTINCT FROM NEW.document_type
 OR command.payload->>'filename' IS DISTINCT FROM NEW.original_filename
 OR command.payload->>'job_id' IS DISTINCT FROM NEW.uploaded_from_job_id::text
 OR (NEW.uploaded_from_job_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM disposition_jobs WHERE id=NEW.uploaded_from_job_id AND job_type='destruction'))
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_template_forbidden'; END IF;
 IF NEW.revision_number<>(SELECT coalesce(max(revision_number),0)+1 FROM disposition_template_revisions WHERE document_type=NEW.document_type)
 THEN RAISE EXCEPTION 'disposition_template_stale'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.guard_workflow() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE job disposition_jobs%ROWTYPE; prior jsonb; following jsonb; op text; uid bigint:=current_user_id(); expected_status integer;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND (disposition_private.context_operation() IN ('final_complete','job_terminate') OR current_setting('app.event_source',true)='migration') AND TG_TABLE_NAME IN ('disposition_review_rounds','disposition_review_decisions','disposition_job_documents')
 AND (to_jsonb(NEW)-ARRAY['membership_snapshot','proposal_snapshot','approval_execution','provenance'])=(to_jsonb(OLD)-ARRAY['membership_snapshot','proposal_snapshot','approval_execution','provenance'])
 AND NOT EXISTS(SELECT 1 FROM jsonb_each(to_jsonb(NEW)) x WHERE x.key=ANY(ARRAY['membership_snapshot','proposal_snapshot','approval_execution','provenance']) AND x.value IS DISTINCT FROM disposition_private.retained_history_json(to_jsonb(OLD)->x.key)) THEN RETURN NEW; END IF;

 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 IF NOT (CASE TG_TABLE_NAME
 WHEN 'disposition_jobs' THEN op IN ('job_create','job_assign','job_owner_change','membership_add','membership_remove','job_terminate','final_complete','review_submit','review_decide','review_save','recalculate','selective_decide')
 WHEN 'disposition_job_memberships' THEN op IN ('membership_add','membership_remove','job_terminate','final_complete','recalculate')
 WHEN 'disposition_tasks' THEN op IN ('job_create','job_assign','task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide','job_terminate','final_complete')
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
  IF TG_OP='UPDATE' AND (NEW.destruction_number IS DISTINCT FROM OLD.destruction_number OR NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND NEW.workflow_stage='external_approval_pending') AND NOT disposition_private.external_active(NEW.id) THEN RAISE EXCEPTION 'disposition_external_command_required'; END IF;
  IF TG_OP='UPDATE' AND NOT disposition_private.hook_applying() AND NOT disposition_private.approval_active(NEW.id) THEN PERFORM disposition_private.require_job_access(NEW.id); END IF;
  IF TG_OP='UPDATE' AND ((NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND NEW.workflow_stage NOT IN ('officer_correction','manager_correction')) OR NEW.disposition_status<>OLD.disposition_status) AND op<>'job_terminate' AND NOT disposition_private.approval_active(NEW.id) THEN PERFORM disposition_private.require_progress(NEW.id); END IF;
  IF TG_OP='INSERT' THEN
   IF NEW.job_type='destruction' THEN
    SELECT value#>>'{}' INTO NEW.review_route FROM application_settings WHERE key='DISPOSITION_DESTRUCTION_REVIEW_ROUTE' FOR SHARE;
    IF NEW.review_route IS NULL THEN RAISE EXCEPTION 'disposition_route_setting_required'; END IF;
    NEW.workflow_stage:=CASE WHEN NEW.review_route='records_manager_only' THEN 'manager_preparation' ELSE 'officer_preparation' END;
   ELSE NEW.review_route:=NULL; END IF;
   IF op<>'job_create' OR NEW.lifecycle_state<>'active' OR NEW.created_by_user_id<>uid OR (NEW.job_type='destruction' AND NEW.workflow_stage NOT IN ('officer_preparation','manager_preparation')) THEN RAISE EXCEPTION 'disposition_invalid_job_creation'; END IF;
   -- Creation precedes preparation: either authorized governance profile may create.
   IF NOT (disposition_private.governance_person(uid,'INFO_GOV_OFFICER') OR disposition_private.governance_person(uid,'INFO_GOV_MGR')) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_not_authorized'; END IF;
   NEW.date_created:=CURRENT_TIMESTAMP;
  ELSE
   IF NEW.owning_org_unit_id IS DISTINCT FROM OLD.owning_org_unit_id THEN
    IF op<>'job_owner_change' OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active')
     OR NEW.current_review_round>0 OR EXISTS(SELECT 1 FROM disposition_review_rounds WHERE job_id=NEW.id)
     OR EXISTS(SELECT 1 FROM event_history WHERE entity_type='disposition_job' AND entity_id=NEW.id AND operation='REVIEW_SUBMIT') THEN RAISE EXCEPTION 'disposition_owning_unit_change_invalid'; END IF;
   END IF;
   IF NEW.review_route IS DISTINCT FROM OLD.review_route THEN RAISE EXCEPTION 'disposition_route_immutable'; END IF;
   IF NEW.job_number<>OLD.job_number OR NEW.job_type<>OLD.job_type OR NEW.created_by_user_id<>OLD.created_by_user_id OR NEW.date_created<>OLD.date_created THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF NEW.lifecycle_state<>OLD.lifecycle_state AND NOT ((op='job_terminate' AND NEW.lifecycle_state='terminated') OR (op='final_complete' AND NEW.lifecycle_state='completed')) THEN RAISE EXCEPTION 'disposition_invalid_lifecycle_transition'; END IF;
   IF NEW.disposition_status<>OLD.disposition_status AND NOT disposition_private.allowed_transition(OLD.disposition_status,NEW.disposition_status,op) THEN RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
   IF NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND (op NOT IN ('review_submit','review_decide','final_complete') OR NOT disposition_private.allowed_stage(OLD.workflow_stage,NEW.workflow_stage)) THEN RAISE EXCEPTION 'disposition_invalid_stage_transition'; END IF;
  END IF;
  expected_status:=CASE NEW.job_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 ELSE 9 END;
  IF NEW.lifecycle_state='active' AND NEW.disposition_status<>expected_status THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
  IF NEW.assigned_user_id IS NOT NULL AND NOT disposition_private.hook_applying() AND (TG_OP='INSERT' OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) THEN
   IF NEW.job_type='destruction' THEN PERFORM disposition_private.require_preparer(NEW.assigned_user_id,NEW.review_route); ELSE PERFORM disposition_private.require_job_person(NEW.assigned_user_id,NEW.job_type); END IF;
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
   IF op<>'final_complete' OR NOT disposition_private.completion_active(NEW.id) THEN RAISE EXCEPTION 'disposition_completion_command_required'; END IF;
   IF EXISTS(SELECT 1 FROM disposition_tasks WHERE job_id=NEW.id AND task_state IN ('open','claimed')) OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active') OR NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=NEW.id) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
  END IF;
  IF NEW.lifecycle_state='terminated' THEN
   NEW.terminated_at:=CURRENT_TIMESTAMP; NEW.terminated_by_user_id:=uid;
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=(following->>'job_id')::bigint FOR UPDATE;
 IF NOT disposition_private.hook_applying() AND NOT disposition_private.approval_active(job.id) AND NOT (op='task_release' AND current_setting('app.actor_type',true)='automated_process') THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF NOT disposition_private.approval_active(job.id) AND TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') AND NOT (op='review_decide' AND COALESCE((SELECT r.payload->>'decision' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())='rejected',false)) THEN PERFORM disposition_private.require_progress(job.id); END IF;
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_tasks' AND following->>'task_type'='certificate_download' AND job.lifecycle_state='completed' AND ((TG_OP='INSERT' AND op='final_complete' AND disposition_private.completion_active(job.id)) OR (TG_OP='UPDATE' AND (op='task_complete' OR op='final_complete' AND disposition_private.completion_active(job.id))))) AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) AND NOT (TG_TABLE_NAME='disposition_job_documents' AND op='document_save' AND following->>'document_type'='proposal_execution_report' AND EXISTS(SELECT 1 FROM disposition_review_rounds approved WHERE approved.job_id=job.id AND approved.round_number=(following->>'review_round')::integer AND approved.approval_execution IS NOT NULL)) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
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
   IF NOT disposition_private.hook_applying(NEW.root_aggregation_id) AND NOT current_user_can_view_aggregation(NEW.root_aggregation_id) AND NOT (disposition_private.destruction_active('finalize',NEW.root_aggregation_id) AND disposition_private.history_resource_access(current_user_id(),'aggregation',NEW.root_aggregation_id)) AND NOT (op='job_terminate' AND disposition_private.retained_access('aggregation',NEW.root_aggregation_id,false)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF NEW.root_aggregation_id<>OLD.root_aggregation_id OR NEW.added_at<>OLD.added_at OR NEW.added_by_user_id<>OLD.added_by_user_id THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF op='recalculate' AND disposition_private.hook_applying(NEW.root_aggregation_id) THEN
    IF (to_jsonb(NEW)-ARRAY['removal_required','removal_required_reason','version','date_updated']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['removal_required','removal_required_reason','version','date_updated']) THEN RAISE EXCEPTION 'disposition_recalculation_scope_invalid'; END IF;
   ELSIF NOT ((op='membership_remove' AND NEW.membership_state='removed') OR (op='job_terminate' AND NEW.membership_state='terminated_history') OR (op='final_complete' AND NEW.membership_state='completed_history')) THEN RAISE EXCEPTION 'disposition_invalid_membership_transition'; END IF;
   IF NEW.membership_state='removed' THEN NEW.removed_at:=CURRENT_TIMESTAMP; NEW.removed_by_user_id:=uid; END IF;
  END IF;
  UPDATE disposition_jobs SET version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=job.id;
 ELSIF TG_TABLE_NAME='disposition_tasks' THEN
  IF TG_OP='UPDATE' AND op IN ('task_claim','task_release','task_reassign') THEN
   IF (to_jsonb(NEW)-(ARRAY['task_state','claimed_by_user_id','claimed_at','released_by_user_id','released_at','reassigned_by_user_id','reassigned_at','version','date_updated'] || CASE WHEN op='task_reassign' THEN ARRAY['destination_role_id','routing_org_unit_id'] ELSE ARRAY[]::text[] END))
    IS DISTINCT FROM (to_jsonb(OLD)-(ARRAY['task_state','claimed_by_user_id','claimed_at','released_by_user_id','released_at','reassigned_by_user_id','reassigned_at','version','date_updated'] || CASE WHEN op='task_reassign' THEN ARRAY['destination_role_id','routing_org_unit_id'] ELSE ARRAY[]::text[] END)) THEN RAISE EXCEPTION 'disposition_task_command_scope_invalid'; END IF;
  END IF;
  IF op='task_release' AND current_setting('app.actor_type',true)='automated_process' THEN
   IF OLD.task_state<>'claimed' OR OLD.destination_role_id IS NULL OR disposition_private.task_eligible(OLD.claimed_by_user_id,OLD.id,OLD.destination_role_id)
    OR (SELECT r.payload->>'task_id' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()) IS DISTINCT FROM OLD.id::text THEN RAISE EXCEPTION 'disposition_task_command_scope_invalid'; END IF;
  END IF;
  IF TG_OP='INSERT' THEN NEW.date_created:=CURRENT_TIMESTAMP; END IF;
  IF NEW.task_state NOT IN ('cancelled','completed') AND NEW.workflow_stage<>job.workflow_stage THEN RAISE EXCEPTION 'disposition_task_stage_mismatch'; END IF;
  IF TG_OP='UPDATE' THEN
   IF NEW.task_type<>OLD.task_type OR NEW.workflow_stage<>OLD.workflow_stage OR NEW.review_round IS DISTINCT FROM OLD.review_round OR NEW.date_created<>OLD.date_created THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF (NEW.destination_user_id,NEW.destination_role_id) IS DISTINCT FROM (OLD.destination_user_id,OLD.destination_role_id) AND op<>'task_reassign' THEN RAISE EXCEPTION 'disposition_reassignment_command_required'; END IF;
   IF op IN ('task_release','task_complete','review_decide') AND NEW.task_state<>'cancelled' AND current_setting('app.actor_type',true)='user'
   AND NOT (op='task_release' AND disposition_private.task_manager(NEW.id,(SELECT acting_role_id FROM disposition_private.command_receipts WHERE command_id=(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())))) AND ((OLD.claimed_by_user_id IS NOT NULL AND OLD.claimed_by_user_id<>uid) OR (OLD.destination_user_id IS NOT NULL AND OLD.destination_user_id<>uid) OR (OLD.destination_role_id IS NOT NULL AND OLD.claimed_by_user_id IS DISTINCT FROM uid)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_claim_required'; END IF;
  END IF;
  IF NEW.task_state='completed' THEN
   IF job.lifecycle_state='completed' AND NOT EXISTS(SELECT 1 FROM event_history WHERE transaction_id=txid_current() AND entity_type='disposition_job' AND entity_id=job.id AND operation IN ('DIGITAL_CERTIFICATE_DOWNLOADED','CERTIFICATE_TASK_COMPLETED') AND metadata->>'task_id'=NEW.id::text) THEN RAISE EXCEPTION 'disposition_certificate_download_required'; END IF;
   PERFORM disposition_private.require_task_actor(NEW.id,(SELECT acting_role_id FROM disposition_private.command_receipts WHERE command_id=(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())),true);
   IF NEW.destination_role_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=NEW.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   NEW.completed_at:=CURRENT_TIMESTAMP; NEW.completed_by_user_id:=uid;
  END IF;
  IF op IN ('task_release','task_reassign') THEN
   IF op='task_release' OR NEW.task_state='open' THEN NEW.claimed_by_user_id:=NULL; NEW.claimed_at:=NULL; END IF;
   IF op='task_release' THEN NEW.released_by_user_id:=uid; NEW.released_at:=CASE WHEN uid IS NOT NULL THEN CURRENT_TIMESTAMP END;
   ELSE NEW.reassigned_by_user_id:=uid; NEW.reassigned_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
  IF TG_OP='UPDATE' AND NEW.task_state<>OLD.task_state AND NOT (
   (op='task_claim' AND OLD.task_state='open' AND NEW.task_state='claimed') OR
   (op IN ('task_release','task_reassign') AND OLD.task_state IN ('open','claimed') AND NEW.task_state IN ('open','claimed')) OR
   ((op IN ('task_complete','review_submit','review_decide') OR op='final_complete' AND disposition_private.completion_active(job.id)) AND OLD.task_state IN ('open','claimed') AND NEW.task_state='completed') OR
   ((op IN ('job_assign','job_terminate','review_submit','review_decide') OR op='final_complete' AND disposition_private.completion_active(job.id)) AND NEW.task_state='cancelled')) THEN RAISE EXCEPTION 'disposition_invalid_task_transition'; END IF;
  IF NEW.task_state='claimed' THEN
   IF NEW.destination_role_id IS NULL THEN RAISE EXCEPTION 'disposition_role_queue_required'; END IF;
   IF NOT disposition_private.task_eligible(NEW.claimed_by_user_id,NEW.id,NEW.destination_role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   IF op<>'task_reassign' AND NEW.claimed_by_user_id<>uid THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   -- Saving work must preserve the original claim, including across transactions.
   IF op IN ('task_claim','task_reassign') THEN NEW.claimed_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='disposition_review_rounds' THEN
  IF TG_OP='UPDATE' AND NEW.approval_execution IS DISTINCT FROM OLD.approval_execution AND (OLD.approval_execution IS NOT NULL OR NOT disposition_private.approval_active(job.id)) THEN RAISE EXCEPTION 'disposition_approval_immutable'; END IF;
  IF TG_OP='INSERT' THEN
   IF NEW.approval_execution IS NOT NULL THEN RAISE EXCEPTION 'disposition_approval_immutable'; END IF;
   NEW.started_at:=CURRENT_TIMESTAMP;
   NEW.submission_reason:=COALESCE(NEW.submission_reason,(SELECT r.reason FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()));
   NEW.proposal_snapshot:=disposition_private.proposal_snapshot(job.id,NEW.round_number);
  ELSE
   IF OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
   IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN NEW.completed_at:=CURRENT_TIMESTAMP; END IF;
   IF OLD.invalidated_at IS NULL AND NEW.invalidated_at IS NOT NULL THEN NEW.invalidated_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
  IF TG_OP='UPDATE' AND (NEW.round_number<>OLD.round_number OR NEW.membership_snapshot<>OLD.membership_snapshot OR NEW.started_at<>OLD.started_at OR NEW.started_by_user_id<>OLD.started_by_user_id OR NEW.submission_reason IS DISTINCT FROM OLD.submission_reason OR NEW.proposal_snapshot IS DISTINCT FROM OLD.proposal_snapshot) THEN RAISE EXCEPTION 'disposition_review_snapshot_immutable'; END IF;
  IF TG_OP='INSERT' AND (NEW.started_by_user_id<>uid OR NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id)) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
  IF TG_OP='INSERT' AND NEW.round_number<>COALESCE((SELECT max(round_number)+1 FROM disposition_review_rounds WHERE job_id=job.id),1) THEN RAISE EXCEPTION 'disposition_round_out_of_order'; END IF;
  IF TG_OP='INSERT' THEN UPDATE disposition_jobs SET current_review_round=NEW.round_number,version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=job.id; END IF;
 ELSIF TG_TABLE_NAME='disposition_review_decisions' THEN
  NEW.decided_at:=CURRENT_TIMESTAMP;
  NEW.proposal_snapshot:=disposition_private.proposal_snapshot(job.id);
  IF NEW.decision='approved' AND NEW.review_stage IN ('records_manager_review','manager_preparation','manager_correction') AND NOT disposition_private.approval_active(job.id) THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
  IF NEW.decision='approved' AND NEW.review_stage='unit_manager_review' AND EXISTS(SELECT 1 FROM disposition_review_proposals p JOIN disposition_job_memberships m ON m.job_id=p.job_id AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active' WHERE p.job_id=job.id AND p.review_round=job.current_review_round AND p.proposal_state='active' AND p.proposal_type='remove_from_job') THEN RAISE EXCEPTION 'disposition_marked_removals_require_rejection'; END IF;
  IF TG_OP<>'INSERT' OR NEW.actor_user_id<>uid OR NEW.acting_role_id<>(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()) OR NOT EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.id=NEW.task_id AND t.job_id=NEW.job_id AND t.workflow_stage=NEW.review_stage AND (t.claimed_by_user_id=uid OR (t.destination_user_id=uid AND t.task_state='open')) AND (t.destination_role_id IS NULL OR EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=t.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)))) THEN RAISE EXCEPTION 'disposition_decision_context_invalid'; END IF;
  IF NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id) THEN RAISE EXCEPTION 'disposition_review_snapshot_stale'; END IF;
  IF NEW.decision='approved' AND NOT disposition_private.approval_active(job.id) AND NEW.membership_snapshot IS DISTINCT FROM (SELECT membership_snapshot FROM disposition_review_rounds WHERE id=NEW.round_id) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
 ELSIF TG_TABLE_NAME='disposition_job_documents' THEN
  IF NEW.document_type='proposal_execution_report' AND NOT EXISTS(SELECT 1 FROM disposition_review_rounds rr WHERE rr.job_id=NEW.job_id AND rr.round_number=NEW.review_round AND rr.approval_execution IS NOT NULL AND rr.id::text=NEW.provenance->>'approval_round_id' AND NEW.provenance#>'{snapshot,source}'=rr.approval_execution AND NEW.provenance#>>'{snapshot,fields,execution.reference}'=rr.approval_execution->>'command_id') THEN RAISE EXCEPTION 'disposition_execution_report_scope_invalid'; END IF;
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

CREATE FUNCTION disposition_private.has_digital_material(p_job bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) u(id) JOIN aggregations a ON a.id=u.id WHERE m.job_id=p_job AND m.membership_state='active' AND a.medium IN ('digital','mixed')) OR
 EXISTS(SELECT 1 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) u(id) JOIN records r ON r.aggregation_id=u.id WHERE m.job_id=p_job AND m.membership_state='active' AND r.medium IN ('digital','mixed'))
$$;

CREATE FUNCTION disposition_private.history_resource_access(p_user bigint, p_kind text, p_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT (CASE WHEN EXISTS(SELECT 1 FROM disposition_retained_records WHERE resource_kind=p_kind AND resource_id=p_id) THEN user_has_global_privilege(p_user,'disposition.jobs.manage') OR user_has_global_privilege(p_user,'audit.view') ELSE true END) AND CASE p_kind WHEN 'aggregation' THEN disposition_private.original_aggregation_access(p_user,p_id) ELSE disposition_private.original_record_access(p_user,p_id) END
$$;

CREATE FUNCTION disposition_private.hold_visible(p_hold bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM holds h WHERE h.id=p_hold AND (
 user_has_global_privilege(current_user_id(),'holds.administer') OR user_has_global_privilege(current_user_id(),'holds.held_items.manage_all')
 OR h.owner_user_id=current_user_id() OR EXISTS(SELECT 1 FROM hold_contributors hc JOIN users u ON u.id=hc.user_id
 WHERE hc.hold_id=h.id AND hc.user_id=current_user_id() AND u.status='active')
 OR EXISTS(SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id WHERE a.user_id=current_user_id()
 AND r.is_information_governance AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))))
$$;

CREATE FUNCTION disposition_private.hook_applying(p_root bigint DEFAULT NULL::bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.recalculation_context WHERE transaction_id=txid_current()
  AND backend_id=pg_backend_pid() AND applying AND (p_root IS NULL OR root_id=p_root))
$$;

CREATE FUNCTION disposition_private.lock_current_blockers(p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.lock_request_facts(p_job bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 PERFORM 1 FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 LOCK TABLE classifications,classification_retention_rules,aggregation_retention_rules,org_units,users IN SHARE MODE;
 PERFORM 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' ORDER BY id FOR UPDATE;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(root_aggregation_id) FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(root_aggregation_id) FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') ORDER BY id FOR UPDATE;
END $$;

CREATE FUNCTION disposition_private.membership_snapshot(p_job bigint) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
 SELECT COALESCE(jsonb_agg(jsonb_build_object('membership_id',m.id,'membership_version',m.version,
  'root_id',m.root_aggregation_id,
  'aggregations',(SELECT jsonb_agg(jsonb_build_object('id',a.id,'version',a.version) ORDER BY a.id) FROM aggregations a WHERE a.id IN (SELECT disposition_private.unit_ids(m.root_aggregation_id))),
  'records',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',r.id,'version',r.version) ORDER BY r.id),'[]'::jsonb) FROM records r WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(m.root_aggregation_id)))) ORDER BY m.id),'[]'::jsonb)
 FROM disposition_job_memberships m WHERE m.job_id=p_job AND m.membership_state='active'
$$;

CREATE FUNCTION disposition_private.minimize_unit_history(p_job bigint, p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT disposition_private.destruction_active('finalize',p_root) THEN RAISE EXCEPTION 'disposition_destruction_command_required'; END IF;
 UPDATE disposition_review_rounds SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot),proposal_snapshot=disposition_private.retained_history_json(proposal_snapshot),approval_execution=disposition_private.retained_history_json(approval_execution) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_review_decisions SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot),proposal_snapshot=disposition_private.retained_history_json(proposal_snapshot) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_job_documents SET provenance=disposition_private.retained_history_json(provenance) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_proposal_effects SET details=disposition_private.retained_json(details) WHERE governing_root_id=p_root;
 UPDATE disposition_private.command_receipts SET payload=disposition_private.retained_command_payload(payload),result=disposition_private.retained_history_json(result)
 WHERE completed_at IS NOT NULL AND (payload->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR payload->>'root_id'=p_root::text OR payload->>'task_id' IN (SELECT id::text FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)) OR result->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR operation='job_create' AND result->>'id'=p_job::text);
 UPDATE event_history SET before_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(before_state) ELSE disposition_private.retained_history_json(before_state) END,after_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(after_state) ELSE disposition_private.retained_history_json(after_state) END,metadata=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(metadata) ELSE disposition_private.retained_history_json(metadata) END
 WHERE (entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root)))
 OR (entity_type='record' AND entity_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))))
 OR (entity_type IN ('digital_component','record_component') AND (SELECT identities->'component_ids' FROM disposition_private.destruction_identities WHERE transaction_id=txid_current() AND root_id=p_root) @> to_jsonb(entity_id))
 OR (entity_type='disposition_job' AND entity_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root))
 OR (entity_type='disposition_task' AND entity_id IN (SELECT id FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_round' AND entity_id IN (SELECT id FROM disposition_review_rounds WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_decision' AND entity_id IN (SELECT id FROM disposition_review_decisions WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_document' AND entity_id IN (SELECT id FROM disposition_job_documents WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_membership' AND entity_id IN (SELECT id FROM disposition_job_memberships WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)));
END $$;

CREATE FUNCTION disposition_private.original_aggregation_access(p_user_id bigint, p_aggregation_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_has_global_privilege(p_user_id,'aggregation.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN aggregations resource ON resource.id=p_aggregation_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     AND (
       user_has_aggregation_permission(p_user_id,p_aggregation_id,'aggregation.view')
       OR EXISTS (SELECT 1 FROM user_role_assignments a
         JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
         JOIN aggregations resource ON resource.id=p_aggregation_id
         JOIN security_levels required ON required.id=resource.security_level_id
         WHERE a.user_id=p_user_id AND r.is_information_governance
           AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     )
$$;

CREATE FUNCTION disposition_private.original_record_access(p_user_id bigint, p_record_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_has_global_privilege(p_user_id,'record.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN records resource ON resource.id=p_record_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     AND (
       user_has_record_permission(p_user_id,p_record_id,'record.view')
       OR EXISTS (SELECT 1 FROM user_role_assignments a
         JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
         JOIN records resource ON resource.id=p_record_id
         JOIN security_levels required ON required.id=resource.security_level_id
         WHERE a.user_id=p_user_id AND r.is_information_governance
           AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     )
$$;

CREATE FUNCTION disposition_private.original_request_approval_current(p_job bigint, p_round bigint) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE rr disposition_review_rounds%ROWTYPE;facts jsonb;rules jsonb;
BEGIN
 SELECT * INTO rr FROM disposition_review_rounds WHERE id=p_round AND job_id=p_job AND round_number=(SELECT current_review_round FROM disposition_jobs WHERE id=p_job);
 IF NOT FOUND OR rr.invalidated_at IS NOT NULL OR rr.approval_execution IS NULL OR jsonb_array_length(rr.approval_execution->'post_membership')=0 THEN RETURN false; END IF;
 facts:=disposition_private.request_facts(p_job);
 IF rr.approval_execution ? 'request_facts' THEN
  RETURN disposition_private.review_fingerprint(facts)=disposition_private.review_fingerprint(rr.approval_execution->'request_facts');
 END IF;
 -- Pre-062 approvals have only immutable versions/rules; do not invent a past
 -- semantic snapshot. Accept them only while the exact saved facts still match.
 SELECT COALESCE(jsonb_agg(jsonb_build_object('root_id',m.root_aggregation_id,'rule',e.rule_snapshot)),'[]') INTO rules
 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.eligibility(m.root_aggregation_id) e WHERE m.job_id=p_job AND m.membership_state='active';
 RETURN disposition_private.review_fingerprint(disposition_private.membership_snapshot(p_job))=disposition_private.review_fingerprint(rr.approval_execution->'post_membership')
 AND disposition_private.review_fingerprint(rules)=disposition_private.review_fingerprint(rr.approval_execution->'post_rules');
END $$;

CREATE FUNCTION disposition_private.person_role(p_user bigint, p_role bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
 WHERE u.id=p_user AND u.status='active' AND u.account_type='person' AND r.id=p_role
 AND role_effectively_active(r.id) AND NOT r.is_system AND r.account_type_restriction IS DISTINCT FROM 'service'
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))
$$;

CREATE FUNCTION disposition_private.physical_active(p_job bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.physical_context p JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE p.transaction_id=txid_current() AND p.backend_id=pg_backend_pid() AND p.job_id=p_job)
$$;

CREATE FUNCTION disposition_private.physical_confirmation_retry(p_id uuid, p_role bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.command_receipts r
 JOIN disposition_tasks t ON t.id=(r.payload->>'task_id')::bigint
 JOIN disposition_jobs j ON j.id=t.job_id
 JOIN disposition_physical_confirmations p ON p.task_id=t.id AND p.job_id=j.id
 JOIN disposition_job_documents d ON d.id=p.certificate_document_id
 WHERE r.command_id=p_id AND r.operation='review_decide' AND r.completed_at IS NOT NULL
 AND r.actor_user_id=current_user_id() AND r.acting_role_id=p_role AND j.lifecycle_state='completed'
 AND d.provenance->>'physical_command_id'=p_id::text
 AND disposition_private.person_role(current_user_id(),p_role)
 AND disposition_private.review_role(j.id,'records_manager_review',p_role)
 AND disposition_private.can_review_content(current_user_id(),j.id)
 AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id))
$$;

CREATE FUNCTION disposition_private.physical_covered(p_job bigint, p_root bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_physical_confirmations p WHERE p.job_id=p_job AND (
 EXISTS(SELECT 1 FROM jsonb_array_elements(p.physical_scope->'aggregations') x WHERE (x->>'root_id')::bigint=p_root) OR
 EXISTS(SELECT 1 FROM jsonb_array_elements(p.physical_scope->'records') x WHERE (x->>'root_id')::bigint=p_root)))
$$;

CREATE FUNCTION disposition_private.physical_item_remaining(p_kind text, p_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT NOT EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE physical_scope @> jsonb_build_object(p_kind,jsonb_build_array(jsonb_build_object('id',p_id))))
$$;

CREATE FUNCTION disposition_private.physical_scope(p_job bigint) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
 WITH units AS (SELECT m.root_aggregation_id,unit.id FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id) WHERE m.job_id=p_job AND m.membership_state='active')
 SELECT jsonb_build_object('aggregations',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',a.id,'root_id',u.root_aggregation_id,'medium',a.medium) ORDER BY a.id),'[]') FROM units u JOIN aggregations a ON a.id=u.id WHERE a.medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('aggregations',a.id)),
 'records',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',r.id,'aggregation_id',r.aggregation_id,'root_id',u.root_aggregation_id,'medium',r.medium) ORDER BY r.id),'[]') FROM units u JOIN records r ON r.aggregation_id=u.id WHERE r.medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('records',r.id)))
$$;

CREATE FUNCTION disposition_private.positive_id(p_value jsonb) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE
    AS $_$
BEGIN
 IF jsonb_typeof(p_value) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
 RETURN COALESCE(jsonb_typeof(p_value)='number' AND p_value::text ~ '^[1-9][0-9]*$' AND p_value::numeric<=9223372036854775807,false);
END $_$;

CREATE FUNCTION disposition_private.preparation_task() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NEW.job_type<>'destruction' THEN RETURN NULL; END IF;
 IF TG_OP='UPDATE' THEN
  IF NEW.assigned_user_id IS NOT DISTINCT FROM OLD.assigned_user_id THEN RETURN NULL; END IF;
  UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=NEW.id AND destination_user_id IS NOT NULL AND task_state IN ('open','claimed');
 END IF;
 IF NEW.assigned_user_id IS NOT NULL AND NEW.workflow_stage IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') THEN
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id)
  VALUES(NEW.id,CASE WHEN NEW.workflow_stage LIKE '%correction' THEN 'correction' ELSE 'preparation' END,NEW.workflow_stage,NULLIF(NEW.current_review_round,0),NEW.assigned_user_id);
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.preserve_artifact_content() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE component bigint; rec bigint;
BEGIN
 IF TG_TABLE_NAME='digital_components' THEN
  component:=OLD.id;
  IF TG_OP='UPDATE' AND (to_jsonb(OLD)-ARRAY['version','date_updated','component_order'])=(to_jsonb(NEW)-ARRAY['version','date_updated','component_order']) THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='digital_component_content_sets' THEN component:=COALESCE(NEW.digital_component_id,OLD.digital_component_id);
 ELSE SELECT digital_component_id INTO component FROM digital_component_content_sets WHERE id=COALESCE(NEW.content_set_id,OLD.content_set_id); END IF;
 IF EXISTS(SELECT 1 FROM disposition_job_documents WHERE digital_component_id=component AND document_state='available') THEN
  RAISE EXCEPTION 'disposition_evidence_version_preserved'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.preserve_physical_outcome() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE job_id=OLD.id) AND NOT disposition_private.physical_active(OLD.id) AND
 NOT disposition_private.completion_active(OLD.id) AND
 NOT (disposition_private.context_operation()='job_terminate' AND disposition_private.recovery_active(OLD.id)) AND
 (NEW.lifecycle_state IS DISTINCT FROM OLD.lifecycle_state OR NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage OR NEW.disposition_status IS DISTINCT FROM OLD.disposition_status OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.proposal_duplicate_key(p jsonb) RETURNS jsonb
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE typ text:=p->>'proposal_type'; values_json jsonb:=p->'proposed_values';
BEGIN
 IF typ IN ('remove_aggregation_relationship','remove_record_relationship') THEN
  RETURN jsonb_build_array(typ,values_json->'relationship_id');
 ELSIF typ='create_aggregation_relationship' THEN
  RETURN jsonb_build_array(typ,disposition_private.proposal_relationship_key(p#>'{current_values,relationship}'));
 ELSIF typ='add_to_holds' THEN
  values_json:=jsonb_build_object('hold_ids',(SELECT jsonb_agg(v ORDER BY v) FROM (SELECT DISTINCT value::text::bigint v FROM jsonb_array_elements(values_json->'hold_ids')) ids));
 ELSIF typ='local_retention_override' THEN
  values_json:=jsonb_set(values_json,'{instructions}',to_jsonb(COALESCE(NULLIF(btrim(values_json->>'instructions'),''),'')));
 END IF;
 RETURN jsonb_build_array(typ,p->'target_aggregation_id',p->'target_record_id',values_json);
END $$;

CREATE FUNCTION disposition_private.proposal_facts(p_job bigint, p_root bigint, p_target bigint, p_record bigint, p_type text, p_values jsonb, p_reason text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE a aggregations%ROWTYPE; target_version bigint; facts jsonb; rel record; selected_id bigint; source_id bigint; target_id bigint; keys text[];
BEGIN
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND root_aggregation_id=p_root AND membership_state='active')
 OR disposition_private.root_id(p_target) IS DISTINCT FROM p_root THEN RAISE EXCEPTION 'disposition_proposal_target_scope_invalid'; END IF;
 SELECT * INTO a FROM aggregations WHERE id=p_target;
 IF NOT FOUND OR NOT current_user_can_view_aggregation(a.id) OR (p_record IS NOT NULL AND NOT current_user_can_view_record(p_record)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF p_record IS NOT NULL AND NOT EXISTS(SELECT 1 FROM records WHERE id=p_record AND aggregation_id=p_target) THEN RAISE EXCEPTION 'disposition_proposal_target_scope_invalid'; END IF;
 facts:=jsonb_build_object('aggregation_id',a.id,'aggregation_version',a.version,'aggregation_number',a.aggregation_number,'title',a.title,'is_vital',a.is_vital,'security_level_id',a.security_level_id);
 IF p_record IS NOT NULL THEN facts:=facts||jsonb_build_object('record',(SELECT jsonb_build_object('id',id,'version',version,'record_number',record_number,'title',title) FROM records WHERE id=p_record)); END IF;
 IF (p_record IS NOT NULL) IS DISTINCT FROM (p_type='remove_record_relationship') THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
 CASE p_type
 WHEN 'remove_from_job' THEN
  IF p_target<>p_root OR NOT disposition_private.review_keys(p_values,ARRAY[]::text[]) OR (p_reason IS NULL OR p_reason ~ '^[[:space:]]*$') THEN RAISE EXCEPTION 'disposition_removal_reason_required'; END IF;
 WHEN 'make_vital' THEN
  IF NOT disposition_private.review_keys(p_values,ARRAY[]::text[]) THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
 WHEN 'blocking_security' THEN
  IF NOT disposition_private.review_keys(p_values,ARRAY['security_level_id']) OR NOT disposition_private.positive_id(p_values->'security_level_id') THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  IF NOT EXISTS(SELECT 1 FROM security_levels proposed JOIN security_levels old ON old.id=a.security_level_id
   WHERE proposed.id=(p_values->>'security_level_id')::bigint AND proposed.level_number>old.level_number AND proposed.prevents_disposition) THEN RAISE EXCEPTION 'disposition_blocking_security_required'; END IF;
  facts:=facts||jsonb_build_object('proposed_security',(SELECT jsonb_build_object('id',id,'code',code,'name',name,'level_number',level_number,'prevents_disposition',prevents_disposition) FROM security_levels WHERE id=(p_values->>'security_level_id')::bigint));
 WHEN 'add_to_holds' THEN
  IF NOT disposition_private.review_keys(p_values,ARRAY['hold_ids']) OR jsonb_typeof(p_values->'hold_ids') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  IF jsonb_array_length(p_values->'hold_ids')=0 OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_values->'hold_ids') v WHERE NOT disposition_private.positive_id(v))
   OR (SELECT count(*)<>count(DISTINCT v) FROM jsonb_array_elements(p_values->'hold_ids') v) THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  FOR selected_id IN SELECT v::text::bigint FROM jsonb_array_elements(p_values->'hold_ids') v LOOP
   IF NOT disposition_private.hold_visible(selected_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_hold_access_required'; END IF;
  END LOOP;
  facts:=facts||jsonb_build_object('holds',(SELECT jsonb_agg(jsonb_build_object('id',id,'code',code,'name',name,'version',version,'valid_from',valid_from,'valid_to',valid_to) ORDER BY id) FROM holds WHERE id IN (SELECT v::text::bigint FROM jsonb_array_elements(p_values->'hold_ids') v)));
 WHEN 'create_aggregation_relationship' THEN
  IF NOT disposition_private.review_keys(p_values,ARRAY['direction','related_aggregation_id','relationship_type_id']) OR NOT disposition_private.positive_id(p_values->'related_aggregation_id') OR NOT disposition_private.positive_id(p_values->'relationship_type_id') OR NOT COALESCE((p_values->>'direction') IN ('outgoing','incoming'),false) THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  selected_id:=(p_values->>'related_aggregation_id')::bigint;
  IF selected_id=p_target THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  IF NOT current_user_can_view_aggregation(selected_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  IF NOT EXISTS(SELECT 1 FROM relationship_types WHERE id=(p_values->>'relationship_type_id')::bigint AND resource_kind='aggregation' AND is_active) THEN RAISE EXCEPTION 'disposition_relationship_type_invalid'; END IF;
  source_id:=CASE WHEN p_values->>'direction'='outgoing' THEN p_target ELSE selected_id END;
  target_id:=CASE WHEN p_values->>'direction'='outgoing' THEN selected_id ELSE p_target END;
  facts:=facts||jsonb_build_object('relationship',jsonb_build_object('resource_kind','aggregation','relationship_type_id',(p_values->>'relationship_type_id')::bigint,'source_id',source_id,'target_id',target_id),
   'related',(SELECT jsonb_build_object('id',id,'version',version,'aggregation_number',aggregation_number,'title',title) FROM aggregations WHERE id=selected_id));
 WHEN 'remove_aggregation_relationship','remove_record_relationship' THEN
  IF NOT disposition_private.review_keys(p_values,ARRAY['relationship_id']) OR NOT disposition_private.positive_id(p_values->'relationship_id') THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  IF p_type='remove_aggregation_relationship' THEN
   SELECT r.id,r.relationship_type_id,r.source_id,r.target_id,r.date_created INTO rel FROM aggregation_relationships r WHERE r.id=(p_values->>'relationship_id')::bigint;
   IF NOT FOUND OR p_target NOT IN (rel.source_id,rel.target_id) THEN RAISE EXCEPTION 'disposition_relationship_invalid'; END IF;
   IF NOT current_user_can_view_aggregation(rel.source_id) OR NOT current_user_can_view_aggregation(rel.target_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  ELSE
   SELECT r.id,r.relationship_type_id,r.source_id,r.target_id,r.date_created INTO rel FROM record_relationships r WHERE r.id=(p_values->>'relationship_id')::bigint;
   IF NOT FOUND OR p_record NOT IN (rel.source_id,rel.target_id) THEN RAISE EXCEPTION 'disposition_relationship_invalid'; END IF;
   IF NOT current_user_can_view_record(rel.source_id) OR NOT current_user_can_view_record(rel.target_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  END IF;
  facts:=facts||jsonb_build_object('relationship',to_jsonb(rel)||jsonb_build_object('resource_kind',CASE WHEN p_type='remove_record_relationship' THEN 'record' ELSE 'aggregation' END,'direction',CASE WHEN COALESCE(p_record,p_target)=rel.source_id THEN 'outgoing' ELSE 'incoming' END));
 WHEN 'local_retention_override' THEN
  IF p_target<>p_root OR NOT disposition_private.review_keys(p_values,ARRAY['current_period_years','final_disposition','instructions','intermediate_period_years'])
   OR jsonb_typeof(p_values->'current_period_years') IS DISTINCT FROM 'number' OR (p_values->>'current_period_years') !~ '^[0-9]+$'
   OR jsonb_typeof(p_values->'intermediate_period_years') IS DISTINCT FROM 'number' OR (p_values->>'intermediate_period_years') !~ '^[0-9]+$'
   OR (p_values->>'current_period_years')::numeric>2147483647 OR (p_values->>'intermediate_period_years')::numeric>2147483647
   OR NOT COALESCE((p_values->>'final_disposition') IN ('destruction','transfer_to_external_archive','selective_preservation','retain_as_local_archives'),false)

   OR jsonb_typeof(p_values->'instructions') NOT IN ('string','null') THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  facts:=facts||jsonb_build_object('local_retention',(SELECT to_jsonb(r) FROM aggregation_retention_rules r WHERE aggregation_id=p_root),
    'classification_rule',(SELECT to_jsonb(r) FROM effective_classification_retention_rule(a.classification_id) r));
 ELSE RAISE EXCEPTION 'disposition_proposal_payload_invalid';
 END CASE;
 RETURN facts;
END $_$;

CREATE FUNCTION disposition_private.proposal_relationship_key(p_relationship jsonb) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
 SELECT CASE WHEN p_relationship IS NULL THEN NULL ELSE jsonb_build_object('kind',p_relationship->>'resource_kind','type',p_relationship->'relationship_type_id',
 'source',CASE WHEN COALESCE((SELECT is_symmetric FROM relationship_types WHERE id=(p_relationship->>'relationship_type_id')::bigint),false) THEN least((p_relationship->>'source_id')::bigint,(p_relationship->>'target_id')::bigint) ELSE (p_relationship->>'source_id')::bigint END,
 'target',CASE WHEN COALESCE((SELECT is_symmetric FROM relationship_types WHERE id=(p_relationship->>'relationship_type_id')::bigint),false) THEN greatest((p_relationship->>'source_id')::bigint,(p_relationship->>'target_id')::bigint) ELSE (p_relationship->>'target_id')::bigint END) END
$$;

CREATE FUNCTION disposition_private.proposal_snapshot(p_job bigint, p_round integer DEFAULT NULL::integer) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
 SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.id),'[]'::jsonb) FROM disposition_review_proposals p
 WHERE p.job_id=p_job AND p.review_round=COALESCE(p_round,disposition_private.review_round_for_work(p_job)) AND p.proposal_state='active'
 AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=p_job AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active')
$$;

CREATE FUNCTION disposition_private.proposal_visible(p_data jsonb) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE rel jsonb; selected_id bigint; saved_effect jsonb;
BEGIN
 IF p_data IS NULL OR p_data='null'::jsonb THEN RETURN true; END IF;
 IF NOT current_user_can_view_aggregation((p_data->>'governing_root_id')::bigint)
 OR NOT current_user_can_view_aggregation((p_data->>'target_aggregation_id')::bigint)
 OR (p_data->>'target_record_id' IS NOT NULL AND NOT current_user_can_view_record((p_data->>'target_record_id')::bigint)) THEN RETURN false; END IF;
 rel:=p_data#>'{current_values,relationship}';
 IF rel IS NOT NULL THEN
  IF rel->>'resource_kind'='record' THEN
   IF NOT current_user_can_view_record((rel->>'source_id')::bigint) OR NOT current_user_can_view_record((rel->>'target_id')::bigint) THEN RETURN false; END IF;
  ELSIF NOT current_user_can_view_aggregation((rel->>'source_id')::bigint) OR NOT current_user_can_view_aggregation((rel->>'target_id')::bigint) THEN RETURN false; END IF;
 END IF;
 IF p_data->>'proposal_type'='add_to_holds' THEN
  FOR selected_id IN SELECT v::text::bigint FROM jsonb_array_elements(p_data#>'{proposed_values,hold_ids}') v LOOP
   IF NOT disposition_private.hold_visible(selected_id) THEN RETURN false; END IF;
  END LOOP;
 END IF;
 FOR saved_effect IN SELECT value FROM jsonb_array_elements(COALESCE(p_data#>'{execution_message,effects}','[]')) LOOP
  IF NOT current_user_can_view_aggregation((saved_effect->>'governing_root_id')::bigint) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION disposition_private.protection_blockers(p_root bigint, p_at timestamp with time zone DEFAULT clock_timestamp()) RETURNS TABLE(resource_kind text, resource_id bigint, is_vital boolean, security_blocked boolean, hold_ids bigint[])
    LANGUAGE sql STABLE
    AS $$
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

CREATE FUNCTION disposition_private.reassign_task(p_task bigint, p_version integer, p_user bigint, p_queue bigint DEFAULT NULL::bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; acting bigint; target bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_reassign' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.version<>p_version OR t.task_state NOT IN ('open','claimed') OR t.destination_role_id IS NULL THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 -- Current claimant may hand over to another eligible person in the SAME queue.
 -- Broader job reassignment remains the separate management command.
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF t.claimed_by_user_id IS DISTINCT FROM current_user_id() AND NOT disposition_private.task_manager(p_task,acting) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_claim_required'; END IF;
 target:=COALESCE(p_queue,t.destination_role_id);
 IF target<>t.destination_role_id AND (NOT disposition_private.task_manager(p_task,acting) OR p_user IS NOT NULL OR NOT disposition_private.review_role(t.job_id,t.workflow_stage,target)
 OR NOT EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,target) AND disposition_private.can_review_content(u.id,t.job_id))) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 IF p_user IS NOT NULL AND NOT disposition_private.task_eligible(p_user,p_task,t.destination_role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 UPDATE disposition_tasks SET task_state=CASE WHEN p_user IS NULL THEN 'open' ELSE 'claimed' END,claimed_by_user_id=p_user,destination_role_id=target,routing_org_unit_id=CASE WHEN t.workflow_stage='records_manager_review' THEN NULL ELSE (SELECT org_unit_id FROM roles WHERE id=target) END WHERE id=p_task RETURNING * INTO t;
 RETURN to_jsonb(t);
END $$;

CREATE FUNCTION disposition_private.reconcile_task(p_task bigint, p_command uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; result jsonb;
BEGIN
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'automated_process' OR current_user_id() IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_worker_required'; END IF;
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.task_state<>'claimed' OR t.destination_role_id IS NULL OR disposition_private.task_eligible(t.claimed_by_user_id,t.id,t.destination_role_id) THEN RETURN jsonb_build_object('changed',false); END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.command_context WHERE transaction_id=txid_current()) THEN RAISE EXCEPTION 'disposition_nested_command'; END IF;
 INSERT INTO disposition_private.command_receipts(command_id,actor_type,operation,payload,reason)
 VALUES(p_command,'automated_process','task_release',jsonb_build_object('task_id',p_task),'Claimant no longer eligible');
 INSERT INTO disposition_private.command_context VALUES(txid_current(),pg_backend_pid(),p_command);
 PERFORM set_config('app.change_reason','Claimant no longer eligible',true);
 UPDATE disposition_tasks SET task_state='open' WHERE id=p_task;
 result:=jsonb_build_object('changed',true,'task_id',p_task);
 PERFORM disposition_private.finish_command(result);
 RETURN result;
END $$;

CREATE FUNCTION disposition_private.record_external_decision(p_task bigint, p_job_version integer, p_task_version integer, p_request bigint, p_decision text, p_notes text, p_number text, p_letter bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE j disposition_jobs%ROWTYPE;t disposition_tasks%ROWTYPE;acting bigint;key uuid;round_id bigint;result_id bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id FOR UPDATE;
 IF t.version IS DISTINCT FROM p_task_version OR j.version IS DISTINCT FROM p_job_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 PERFORM disposition_private.lock_request_facts(j.id);
 IF t.task_type<>'external_approval' OR t.request_document_id IS DISTINCT FROM p_request OR j.workflow_stage<>'external_approval_pending' THEN RAISE EXCEPTION 'disposition_external_request_mismatch'; END IF;
 SELECT (provenance->>'approval_round_id')::bigint INTO round_id FROM disposition_job_documents WHERE id=p_request AND job_id=j.id;
 IF p_decision NOT IN ('approved','rejected') OR p_decision IS NULL THEN RAISE EXCEPTION 'disposition_external_decision_invalid'; END IF;
 IF p_decision='rejected' AND (p_notes IS NULL OR p_notes ~ '^[[:space:]]*$') THEN RAISE EXCEPTION 'disposition_external_notes_required'; END IF;
 IF p_decision='approved' AND (p_number IS NULL OR btrim(p_number)='' OR char_length(p_number)>20) THEN RAISE EXCEPTION 'disposition_destruction_number_invalid'; END IF;
 INSERT INTO disposition_private.external_context VALUES(txid_current(),pg_backend_pid(),key,j.id,'decision');
 IF p_decision='approved' THEN
  INSERT INTO disposition_private.destruction_numbers(number,job_id) VALUES(p_number,j.id) ON CONFLICT(number) DO NOTHING;
  IF NOT EXISTS(SELECT 1 FROM disposition_private.destruction_numbers WHERE number=p_number AND job_id=j.id) THEN RAISE EXCEPTION 'disposition_destruction_number_used'; END IF;
 END IF;
 INSERT INTO disposition_external_approvals(job_id,round_id,request_document_id,task_id,decision,correction_notes,destruction_number,approval_letter_document_id,rejection_letter_document_id,recorded_by_user_id,acting_role_id)
 VALUES(j.id,round_id,p_request,t.id,p_decision,p_notes,CASE WHEN p_decision='approved' THEN p_number END,CASE WHEN p_decision='approved' THEN p_letter END,CASE WHEN p_decision='rejected' THEN p_letter END,current_user_id(),acting) RETURNING id INTO result_id;
 UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
 IF p_decision='rejected' THEN PERFORM disposition_private.route_correction(j.id);
 ELSE UPDATE disposition_jobs SET destruction_number=p_number WHERE id=j.id; PERFORM disposition_private.route_after_external(j.id); END IF;
 PERFORM append_domain_event('disposition_job',j.id,CASE p_decision WHEN 'approved' THEN 'EXTERNAL_APPROVAL_RECORDED' ELSE 'EXTERNAL_REJECTION_RECORDED' END,jsonb_build_object('after',(SELECT to_jsonb(a) FROM disposition_external_approvals a WHERE a.id=result_id),'acting_role_id',acting));
 DELETE FROM disposition_private.external_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('id',result_id,'job_id',j.id,'decision',p_decision,'request_document_id',p_request,'letter_document_id',p_letter,'job_version',(SELECT version FROM disposition_jobs WHERE id=j.id),'workflow_stage',(SELECT workflow_stage FROM disposition_jobs WHERE id=j.id));
END $_$;

CREATE FUNCTION disposition_private.recovery_active(p_job bigint DEFAULT NULL::bigint, p_root bigint DEFAULT 0, p_status integer DEFAULT NULL::integer) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.recovery_context r JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE r.transaction_id=txid_current() AND r.backend_id=pg_backend_pid() AND (p_job IS NULL OR r.job_id=p_job) AND r.root_id=p_root AND (p_status IS NULL OR r.target_status=p_status))
$$;

CREATE FUNCTION disposition_private.recovery_facts(p_job bigint, p_root bigint) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
 SELECT jsonb_build_object('recovery_job_id',p_job,'root_id',p_root,
 'physical_confirmation_id',p.id,'certificate_document_id',p.certificate_document_id,'certificate_reference',p.certificate_reference,
 'preserved_digital_material',coalesce((SELECT jsonb_agg(jsonb_build_object('record_id',d.record_id,'component_id',d.id,'content_set_id',d.active_content_set_id) ORDER BY d.id)
 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),'[]'))
 FROM disposition_physical_confirmations p WHERE p.job_id=p_job
$$;

CREATE FUNCTION disposition_private.recovery_preview(p_job bigint) RETURNS jsonb
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
 IF NOT disposition_private.can_manage() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_authorization_required'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT EXISTS(SELECT 1 FROM disposition_jobs WHERE id=p_job AND lifecycle_state='terminated') THEN RAISE EXCEPTION 'disposition_recovery_job_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.recovery_roots(p_job) r WHERE NOT disposition_private.recovery_unit_visible(r.root_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_recovery_access_required'; END IF;
 RETURN (SELECT jsonb_build_object('affected_count',count(*),'scope_token',md5(coalesce(jsonb_agg(jsonb_build_array(root_id,root_version) ORDER BY root_id),'[]')::text)) FROM disposition_private.recovery_roots(p_job));
END $$;

CREATE FUNCTION disposition_private.recovery_roots(p_job bigint) RETURNS TABLE(root_id bigint, root_version bigint)
    LANGUAGE sql STABLE
    AS $$
 SELECT a.id,a.version FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id JOIN disposition_jobs j ON j.id=m.job_id
 WHERE j.id=p_job AND j.lifecycle_state='terminated' AND m.membership_state='terminated_history' AND a.disposition_status=13
 AND m.id=(SELECT max(h.id) FROM disposition_job_memberships h WHERE h.root_aggregation_id=a.id AND h.membership_state='terminated_history')
$$;

CREATE FUNCTION disposition_private.recovery_unit_visible(p_root bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT (current_user_can_view_aggregation(p_root) OR disposition_private.retained_access('aggregation',p_root,false)) AND NOT EXISTS(SELECT 1 FROM disposition_private.unit_ids(p_root) u(id)
 WHERE NOT (current_user_can_view_aggregation(u.id) OR disposition_private.retained_access('aggregation',u.id,false)) OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=u.id AND NOT (current_user_can_view_record(r.id) OR disposition_private.retained_access('record',r.id,false))))
$$;

CREATE FUNCTION disposition_private.register_processing_copy(p_token uuid, p_component bigint, p_owner bigint, p_kind text, p_worker text DEFAULT NULL::text, p_job bigint DEFAULT NULL::bigint, p_generation bigint DEFAULT NULL::bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE rec bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT record_id INTO rec FROM digital_components WHERE id=p_component FOR SHARE;
 IF rec IS NULL OR EXISTS(SELECT 1 FROM records WHERE id=rec AND disposition_status=10) THEN RAISE EXCEPTION 'content_unavailable'; END IF;
 IF disposition_private.content_reserved(rec) THEN RAISE EXCEPTION 'disposition_processing_cleanup_required'; END IF;
 INSERT INTO disposition_private.processing_copies VALUES(p_token,p_component,p_owner,p_kind,p_worker,p_job,p_generation,clock_timestamp()) ON CONFLICT(token) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM disposition_private.processing_copies WHERE token=p_token AND component_id=p_component AND owner_user_id=p_owner AND kind=p_kind AND worker_id IS NOT DISTINCT FROM p_worker AND indexing_job_id IS NOT DISTINCT FROM p_job AND indexing_generation IS NOT DISTINCT FROM p_generation) THEN RAISE EXCEPTION 'processing_copy_conflict'; END IF;
END $$;

CREATE FUNCTION disposition_private.reject_duplicate_proposal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NEW.proposal_state<>'active' THEN RETURN NEW; END IF;
 -- Commands use this same transaction lock. Authorization/fact validation in
 -- disposition_proposal_guard runs first, before any duplicate is disclosed.
 PERFORM pg_advisory_xact_lock(7357,1);
 IF EXISTS(SELECT 1 FROM disposition_review_proposals p WHERE p.job_id=NEW.job_id
   AND p.review_round=NEW.review_round AND p.proposal_state='active' AND p.id<>NEW.id
   AND disposition_private.proposal_duplicate_key(to_jsonb(p))=disposition_private.proposal_duplicate_key(to_jsonb(NEW))) THEN
  RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='disposition_proposal_duplicate';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.relationship_scope(p_root bigint) RETURNS TABLE(resource_kind text, relationship_id bigint, relationship_type_id bigint, source_id bigint, target_id bigint, source_root_id bigint, target_root_id bigint, is_internal boolean, is_same_job boolean, blocks_final boolean)
    LANGUAGE sql STABLE
    AS $$
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
     AND a.membership_state IN ('active','completed_history') AND b.membership_state IN ('active','completed_history')) same_job FROM links l)
 SELECT kind,id,relationship_type_id,source_id,target_id,source_root,target_root,internal,same_job,NOT(internal OR same_job OR EXISTS(SELECT 1 FROM disposition_job_memberships a JOIN disposition_job_memberships b ON b.job_id=a.job_id JOIN disposition_jobs j ON j.id=a.job_id JOIN aggregations sa ON sa.id=a.root_aggregation_id JOIN aggregations ta ON ta.id=b.root_aggregation_id WHERE j.lifecycle_state='terminated' AND a.root_aggregation_id=source_root AND b.root_aggregation_id=target_root AND a.membership_state IN ('terminated_history','completed_history') AND b.membership_state IN ('terminated_history','completed_history') AND (sa.disposition_status=10 OR ta.disposition_status=10) AND EXISTS(SELECT 1 FROM event_history e WHERE e.entity_type='disposition_job' AND e.entity_id=j.id AND e.operation='DISPOSITION_TERMINATION_OUTCOMES' AND e.metadata->'retained_relationships' @> jsonb_build_array(jsonb_build_array(scoped.kind,scoped.id))))) FROM scoped
$$;

CREATE FUNCTION disposition_private.release_task(p_task bigint, p_version integer) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_release' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.version<>p_version OR t.task_state<>'claimed' OR t.destination_role_id IS NULL THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 UPDATE disposition_tasks SET task_state='open' WHERE id=p_task RETURNING * INTO t;
 RETURN to_jsonb(t);
END $$;

CREATE FUNCTION disposition_private.remove_member(p_member bigint, p_version integer, p_root_version bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.renew_external_review(p_job bigint, p_round bigint, p_version integer) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;acting bigint;key uuid;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.lock_request_facts(p_job);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job;
 IF j.version IS DISTINCT FROM p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF j.lifecycle_state<>'active' OR j.workflow_stage NOT IN ('records_manager_review','manager_preparation','manager_correction','external_approval_pending') OR NOT EXISTS(SELECT 1 FROM disposition_review_rounds r WHERE r.id=p_round AND r.job_id=j.id AND r.round_number=j.current_review_round AND r.approval_execution IS NOT NULL AND r.invalidated_at IS NULL) THEN RAISE EXCEPTION 'disposition_approval_unavailable'; END IF;
 IF NOT (disposition_private.person_role(current_user_id(),acting) AND disposition_private.can_review_content(current_user_id(),j.id) AND (disposition_private.review_role(j.id,'records_manager_review',acting) OR current_user_id()=j.assigned_user_id AND EXISTS(SELECT 1 FROM roles ro JOIN profiles p ON p.id=ro.profile_id WHERE ro.id=acting AND ro.is_information_governance AND p.code=CASE j.review_route WHEN 'records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END))) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 IF disposition_private.request_approval_current(j.id,p_round) THEN RAISE EXCEPTION 'disposition_approval_still_current'; END IF;
 INSERT INTO disposition_private.external_context VALUES(txid_current(),pg_backend_pid(),key,j.id,'invalidate');
 UPDATE disposition_review_rounds SET invalidated_at=CURRENT_TIMESTAMP,invalidation_reason='Approved job facts changed; a new complete review round is required' WHERE id=p_round;
 PERFORM disposition_private.route_correction(j.id);
 PERFORM append_domain_event('disposition_job',j.id,'REVIEW_APPROVAL_INVALIDATED',jsonb_build_object('round_id',p_round,'acting_role_id',acting,'review_route',j.review_route));
 DELETE FROM disposition_private.external_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',j.id,'review_required',true,'job_version',(SELECT version FROM disposition_jobs WHERE id=j.id));
END $$;

CREATE FUNCTION disposition_private.request_approval_current(p_job bigint, p_round bigint) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=p_job) THEN
  RETURN EXISTS(SELECT 1 FROM disposition_review_rounds rr WHERE rr.id=p_round AND rr.job_id=p_job AND rr.round_number=(SELECT current_review_round FROM disposition_jobs WHERE id=p_job) AND rr.invalidated_at IS NULL AND rr.approval_execution IS NOT NULL)
   AND NOT EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=p_job AND m.membership_state='active' AND NOT EXISTS(SELECT 1 FROM disposition_private.destruction_scopes s JOIN disposition_destruction_runs r ON r.id=s.run_id WHERE r.job_id=p_job AND s.root_id=m.root_aggregation_id AND s.scope=disposition_private.destruction_scope(m.root_aggregation_id)));
 END IF;
 RETURN disposition_private.original_request_approval_current(p_job,p_round);
END $$;

CREATE FUNCTION disposition_private.request_digital(p_task bigint, p_job_version bigint, p_task_version bigint, p_confirm boolean) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;t disposition_tasks%ROWTYPE;acting bigint;key uuid;previous disposition_destruction_runs%ROWTYPE;created bigint;root bigint;total integer;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'final_complete' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id FOR UPDATE;
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 IF t.task_type<>'digital_destruction' OR t.version IS DISTINCT FROM p_task_version OR j.version IS DISTINCT FROM p_job_version THEN RAISE EXCEPTION 'disposition_stale_task'; END IF;
 IF p_confirm IS DISTINCT FROM true THEN RAISE EXCEPTION 'disposition_digital_confirmation_required'; END IF;
 SELECT * INTO previous FROM disposition_destruction_runs WHERE job_id=j.id ORDER BY run_number DESC LIMIT 1;
 IF previous.state IN ('queued','running') THEN RAISE EXCEPTION 'disposition_digital_already_running'; END IF;
 IF previous.state='succeeded' THEN RAISE EXCEPTION 'disposition_digital_already_succeeded'; END IF;
 IF previous.last_error_code='disposition_physical_recovery_required' THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 PERFORM disposition_private.check_digital_job(j.id,acting,true);
 SELECT count(*) INTO total FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active';
 IF total=0 THEN RAISE EXCEPTION 'disposition_digital_already_succeeded'; END IF;
 INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),key,NULL,NULL,NULL,'request');
 INSERT INTO disposition_destruction_runs(job_id,request_id,run_number,requested_by_user_id,requested_by_name,acting_role_id,task_id,total_units)
 VALUES(j.id,key,coalesce(previous.run_number,0)+1,current_user_id(),(SELECT name FROM users WHERE id=current_user_id()),acting,t.id,total) RETURNING id INTO created;
 UPDATE disposition_private.destruction_context SET run_id=created WHERE transaction_id=txid_current();
 FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active' ORDER BY root_aggregation_id LOOP
  INSERT INTO disposition_destruction_run_units(run_id,root_id) VALUES(created,root);
  INSERT INTO disposition_private.destruction_scopes VALUES(created,root,disposition_private.destruction_scope(root));
 END LOOP;
 PERFORM append_domain_event('disposition_job',j.id,'DIGITAL_DESTRUCTION_REQUESTED',jsonb_build_object('run_id',created,'command_id',key,'total_units',total,'confirmed',true,'confirmation_version',1,'confirmation_text','أؤكد أن على وثق إتلاف المحتوى الرقمي / I confirm that Wathiq should destroy the digital content'));
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('run_id',created,'job_id',j.id,'state','queued','total_units',total);
END $$;

CREATE FUNCTION disposition_private.request_facts(p_job bigint) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
 WITH members AS (SELECT id,root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active'),
 units AS (SELECT m.root_aggregation_id root_id,disposition_private.unit_ids(m.root_aggregation_id) id FROM members m)
 SELECT disposition_private.canonical_review_json(jsonb_build_object(
 'job',(SELECT jsonb_build_object('id',j.id,'job_number',j.job_number,'job_type',j.job_type,'owning_org_unit_id',j.owning_org_unit_id,'owner',o.name,'assigned_user_id',j.assigned_user_id,'assignee',u.name,'date_created',j.date_created,'review_route',j.review_route) FROM disposition_jobs j JOIN org_units o ON o.id=j.owning_org_unit_id LEFT JOIN users u ON u.id=j.assigned_user_id WHERE j.id=p_job),
 'source',jsonb_build_object(
 'roots',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',m.root_aggregation_id,'membership_id',m.id,'rule_snapshot',e.rule_snapshot) ORDER BY m.root_aggregation_id),'[]') FROM members m CROSS JOIN LATERAL disposition_private.eligibility(m.root_aggregation_id) e),
 'aggregations',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',a.id,'parent_aggregation_id',a.parent_aggregation_id,'aggregation_number',a.aggregation_number,'title',a.title,'medium',a.medium,'date_closed',a.date_closed,'root_id',units.root_id,'classification_id',cl.id,'classification_code',cl.code,'classification_title',cl.title,'owner',o.name,'disposition_status',a.disposition_status) ORDER BY a.id),'[]') FROM units JOIN aggregations a ON a.id=units.id JOIN aggregations root ON root.id=units.root_id JOIN classifications cl ON cl.id=root.classification_id JOIN org_units o ON o.id=a.owning_org_unit_id),
 'records',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',r.id,'aggregation_id',r.aggregation_id,'record_number',r.record_number,'title',r.title,'medium',r.medium,'disposition_status',r.disposition_status) ORDER BY r.id),'[]') FROM units JOIN records r ON r.aggregation_id=units.id))))
$$;

CREATE FUNCTION disposition_private.require_actor(p_role_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'user' OR NOT EXISTS (
  SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id
  JOIN roles r ON r.id=a.role_id JOIN profile_privileges pp ON pp.profile_id=r.profile_id
  JOIN privileges p ON p.id=pp.privilege_id AND p.code='disposition.jobs.manage'
  WHERE u.id=current_user_id() AND u.status='active' AND u.account_type='person'
    AND r.id=p_role_id AND r.is_information_governance AND role_effectively_active(r.id)
    AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 ) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_authorization_required'; END IF;
END $$;

CREATE FUNCTION disposition_private.require_command() RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE command disposition_private.command_receipts%ROWTYPE;
BEGIN
 IF disposition_private.hook_applying() THEN RETURN; END IF;
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid() AND r.completed_at IS NULL;
 IF NOT FOUND OR command.actor_user_id IS DISTINCT FROM current_user_id()
 OR command.actor_type IS DISTINCT FROM current_setting('app.actor_type',true) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 IF command.actor_type='automated_process' THEN
  IF command.operation NOT IN ('eligibility_evaluate','task_release') OR command.actor_user_id IS NOT NULL OR command.acting_role_id IS NOT NULL THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 ELSE
  IF command.operation IN ('task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide') AND command.payload ? 'task_id' THEN
   PERFORM disposition_private.require_task_command((command.payload->>'task_id')::bigint,command.acting_role_id,command.operation);
  ELSE PERFORM disposition_private.require_actor(command.acting_role_id); END IF;
 END IF;
END $$;

CREATE FUNCTION disposition_private.require_job_access(p_job bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state IN ('active','completed_history') AND NOT disposition_private.history_resource_access(current_user_id(),'aggregation',root_aggregation_id)) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
END $$;

CREATE FUNCTION disposition_private.require_job_person(p_user bigint, p_type text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id
 JOIN roles r ON r.id=a.role_id JOIN profiles profile ON profile.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
 WHERE u.id=p_user AND u.status='active' AND u.account_type='person' AND r.is_information_governance
 AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND p.code='disposition.jobs.manage' AND (p_type<>'destruction' OR profile.code='INFO_GOV_OFFICER')) THEN
 RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_not_authorized'; END IF;
END $$;

CREATE FUNCTION disposition_private.require_membership_stage(p_job bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE job disposition_jobs%ROWTYPE;
BEGIN
 IF disposition_private.approval_active(p_job) AND disposition_private.context_operation()='membership_remove' THEN RETURN; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job;
 IF job.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF job.job_type='destruction' AND job.workflow_stage NOT IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') THEN
 RAISE EXCEPTION 'disposition_membership_stage_invalid'; END IF;
 IF job.job_type='destruction' THEN
  IF job.assigned_user_id IS DISTINCT FROM current_user_id() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assigned_preparer_required'; END IF;
  PERFORM disposition_private.require_preparer(current_user_id(),job.review_route);
  IF disposition_private.context_operation() IN ('membership_add','membership_remove') AND NOT EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.job_id=job.id AND t.workflow_stage=job.workflow_stage AND t.destination_user_id=current_user_id() AND t.task_state='open' AND t.task_type IN ('preparation','correction')) THEN RAISE EXCEPTION 'disposition_membership_stage_invalid'; END IF;
 END IF;
END $$;

CREATE FUNCTION disposition_private.require_preparer(p_user bigint, p_route text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT disposition_private.governance_person(p_user,CASE WHEN p_route='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END)
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_not_authorized'; END IF;
END $$;

CREATE FUNCTION disposition_private.require_progress(p_job bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' AND removal_required) THEN
 RAISE EXCEPTION 'disposition_removal_required'; END IF;
END $$;

CREATE FUNCTION disposition_private.require_task_actor(p_task bigint, p_role bigint, p_work boolean DEFAULT false) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE;
BEGIN
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task;
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'user' OR NOT disposition_private.task_eligible(current_user_id(),p_task,p_role)
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 IF p_work AND (t.task_state NOT IN ('open','claimed') OR t.workflow_stage IS DISTINCT FROM (SELECT workflow_stage FROM disposition_jobs WHERE id=t.job_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 IF p_work AND t.destination_role_id IS NOT NULL AND (t.task_state<>'claimed' OR t.claimed_by_user_id IS DISTINCT FROM current_user_id())
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_claim_required'; END IF;
END $$;

CREATE FUNCTION disposition_private.require_task_command(p_task bigint, p_role bigint, p_operation text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF p_operation IN ('task_release','task_reassign') AND disposition_private.task_manager(p_task,p_role) THEN RETURN; END IF;
 PERFORM disposition_private.require_task_actor(p_task,p_role,false);
END $$;

CREATE FUNCTION disposition_private.resolve_partial(p_job bigint, p_root bigint, p_root_version bigint, p_status integer, p_confirm boolean, p_count integer, p_token text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE job disposition_jobs%ROWTYPE;member record;acting bigint;key uuid;preview jsonb;counted integer:=0;facts jsonb;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'resolve_partial' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_actor(acting);
 IF p_status IS NULL OR p_status NOT BETWEEN 2 AND 5 THEN RAISE EXCEPTION 'disposition_recovery_status_invalid'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF job.lifecycle_state IS DISTINCT FROM 'terminated' THEN RAISE EXCEPTION 'disposition_recovery_job_required'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 PERFORM 1 FROM aggregations WHERE id IN (SELECT root_id FROM disposition_private.recovery_roots(p_job)) ORDER BY id FOR UPDATE;
 IF p_root IS NULL THEN
  preview:=disposition_private.recovery_preview(p_job);
  IF p_confirm IS DISTINCT FROM true THEN RAISE EXCEPTION 'disposition_confirmation_required'; END IF;
  IF p_token IS DISTINCT FROM preview->>'scope_token' OR p_count IS DISTINCT FROM (preview->>'affected_count')::integer THEN RAISE EXCEPTION 'disposition_recovery_stale'; END IF;
 END IF;
 FOR member IN SELECT * FROM disposition_private.recovery_roots(p_job) WHERE p_root IS NULL OR root_id=p_root ORDER BY root_id LOOP
  PERFORM disposition_private.lock_current_blockers(member.root_id);
  IF NOT disposition_private.recovery_unit_visible(member.root_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_recovery_access_required'; END IF;
  IF p_root IS NOT NULL AND member.root_version IS DISTINCT FROM p_root_version THEN RAISE EXCEPTION 'disposition_recovery_stale'; END IF;
  IF NOT disposition_private.physical_covered(p_job,member.root_id) THEN RAISE EXCEPTION 'disposition_recovery_scope_invalid'; END IF;
  INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,member.root_id,p_status);
  facts:=disposition_private.recovery_facts(p_job,member.root_id)||jsonb_build_object('command_id',key,'old_status',13,'new_status',p_status,'bulk',p_root IS NULL);
  PERFORM disposition_private.transition_unit(member.root_id,member.root_version,p_status);
  PERFORM append_domain_event('aggregation',member.root_id,'DISPOSITION_PARTIAL_RESOLVED',facts);
  counted:=counted+1;
 END LOOP;
 IF counted=0 THEN RAISE EXCEPTION 'disposition_recovery_empty'; END IF;
 PERFORM append_domain_event('disposition_job',p_job,CASE WHEN p_root IS NULL THEN 'DISPOSITION_PARTIAL_BULK_RESOLVED' ELSE 'DISPOSITION_PARTIAL_RESOLVED' END,jsonb_build_object('recovery_job_id',p_job,'command_id',key,'affected_count',counted,'old_status',13,'new_status',p_status,'root_id',p_root,'certificate_document_id',(SELECT certificate_document_id FROM disposition_physical_confirmations WHERE job_id=p_job)));
 DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',p_job,'affected_count',counted,'new_status',p_status,'command_id',key);
END $$;

CREATE FUNCTION disposition_private.retain_physical_outcome(p_job bigint, p_root bigint, p_event bigint, p_at timestamp with time zone, p_executor bigint, p_name text) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE key uuid;
BEGIN
 IF NOT disposition_private.recovery_active(p_job,p_root,10) THEN RAISE EXCEPTION 'disposition_recovery_command_required'; END IF;
 SELECT command_id INTO key FROM disposition_private.command_context WHERE transaction_id=txid_current();
 INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),key,NULL,p_root,NULL,'finalize') ON CONFLICT(transaction_id) DO UPDATE SET root_id=p_root;
 PERFORM disposition_private.retain_unit(p_job,p_root,NULL,p_event,p_at,p_executor,p_name);
 PERFORM disposition_private.minimize_unit_history(p_job,p_root);
END $$;

CREATE FUNCTION disposition_private.retain_unit(p_job bigint, p_root bigint, p_run bigint, p_event bigint, p_at timestamp with time zone, p_executor bigint, p_name text) RETURNS void
    LANGUAGE plpgsql
    AS $$
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

CREATE FUNCTION disposition_private.retained_access(p_kind text, p_id bigint, p_audit boolean DEFAULT false) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT CASE WHEN p_audit THEN user_has_global_privilege(current_user_id(),'audit.view') ELSE disposition_private.can_manage() END
 AND disposition_private.history_resource_access(current_user_id(),p_kind,p_id)
 AND EXISTS(SELECT 1 FROM disposition_retained_records WHERE resource_kind=p_kind AND resource_id=p_id)
$$;

CREATE FUNCTION disposition_private.retained_command_payload(p_data jsonb) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
 SELECT CASE WHEN p_data ? 'snapshot' THEN jsonb_set(p_data,'{snapshot}',disposition_private.retained_history_json(p_data->'snapshot')) ELSE p_data END
$$;

CREATE FUNCTION disposition_private.retained_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP<>'INSERT' OR NOT disposition_private.destruction_active('finalize',NEW.root_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_retained_record_immutable'; END IF;
 SELECT jsonb_build_object('id',id,'code',code,'title',title,'classification_scheme_id',classification_scheme_id) INTO NEW.classification_snapshot FROM classifications WHERE id=NEW.classification_id;
 SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO NEW.owner_snapshot FROM org_units WHERE id=NEW.owning_org_unit_id;
 RETURN NEW;
END $$;

CREATE FUNCTION disposition_private.retained_history_json(p_data jsonb, p_root bigint DEFAULT NULL::bigint, p_ids jsonb DEFAULT NULL::jsonb) RETURNS jsonb
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE ids jsonb:=p_ids;item record;result jsonb;
BEGIN
 IF p_data IS NULL THEN RETURN NULL; END IF;
 IF p_root IS NULL THEN SELECT root_id INTO p_root FROM disposition_private.destruction_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid(); END IF;
 IF ids IS NULL THEN SELECT identities INTO ids FROM disposition_private.destruction_identities WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root;END IF;
 IF jsonb_typeof(p_data)='array' THEN SELECT coalesce(jsonb_agg(disposition_private.retained_history_json(v,p_root,ids)),'[]') INTO result FROM jsonb_array_elements(p_data) v;RETURN result;
 ELSIF jsonb_typeof(p_data)<>'object' THEN RETURN p_data; END IF;
 IF p_data->>'root_id'=p_root::text OR p_data->>'governing_root_id'=p_root::text OR p_data->>'root_aggregation_id'=p_root::text
 OR (p_data ? 'aggregation_number' AND ids->'aggregation_ids' @> jsonb_build_array(p_data->'id'))
 OR (p_data ? 'record_number' AND ids->'record_ids' @> jsonb_build_array(p_data->'id'))
 OR (p_data ? 'file_name' AND ids->'component_ids' @> jsonb_build_array(p_data->'id'))
 OR (p_data ? 'aggregation.identifier' AND ids->'aggregation_numbers' @> jsonb_build_array(p_data->'aggregation.identifier')) THEN RETURN disposition_private.retained_json(p_data); END IF;
 result:='{}';FOR item IN SELECT * FROM jsonb_each(p_data) LOOP result:=result||jsonb_build_object(item.key,disposition_private.retained_history_json(item.value,p_root,ids));END LOOP;
 RETURN result;
END $$;

CREATE FUNCTION disposition_private.retained_json(p_data jsonb) RETURNS jsonb
    LANGUAGE plpgsql IMMUTABLE
    AS $$
DECLARE result jsonb;item record;value jsonb;
BEGIN
 IF p_data IS NULL THEN RETURN NULL; END IF;
 IF jsonb_typeof(p_data)='array' THEN
  SELECT coalesce(jsonb_agg(disposition_private.retained_json(v)),'[]') INTO result FROM jsonb_array_elements(p_data) v;RETURN result;
 ELSIF jsonb_typeof(p_data)<>'object' THEN RETURN p_data; END IF;
 result:='{}';
 FOR item IN SELECT * FROM jsonb_each(p_data) LOOP
  IF item.key=ANY(ARRAY['id','job_id','job_number','job_type','root_id','root_aggregation_id','governing_root_id','aggregation_id','parent_aggregation_id','record_id','source_id','target_id','relationship_id','relationship_type_id','resource_kind','resource_id','source_root_id','target_root_id','is_internal','is_same_job','medium','disposition_status','old_status','new_status','classification_id','owning_org_unit_id','security_level_id','date_closed','calculated_disposition_at','eligible_status','final_disposition','rule_source','rule_id','defined_by_aggregation_id','defined_by_classification_id','current_period_years','intermediate_period_years','justification','override_justification','accelerated_at','accelerated_by_user_id','acceleration_reason','acceleration','old_evaluation','new_evaluation','rule_snapshot','rule','definition','before','after','acting_role_id','actor_user_id','user_id','executor_user_id','executor_name','confirmed_by_user_id','confirmed_at','completed_at','review_stage','review_round','round_number','decision','decided_at','decision_reason','reason','review_notes','round_id','approval_round_id','physical_confirmation_id','certificate_document_id','request_document_id','approval_letter_document_id','rejection_letter_document_id','document_id','digital_component_id','checksum_algo','checksum_value','checksum','size_in_bytes','component_id','content_set_id','source_component_id','source_content_set_id','count','counts','command_id','operation','run_id','evidence_version','origin','version','source','roots','aggregations','records','components','unit','units','effects','results','post_membership','post_rules','membership_snapshot','proposal_snapshot','proposals','proposed_values','proposal_id','proposal_type','proposal_state','state','executed','execution_result','approval_execution','request_facts','recorded_by_user_id','recorded_at','author_user_id','proposer_user_id','original_proposer_user_id','last_edited_by_user_id','destination_role_id','destination_user_id','assigned_user_id','created_by_user_id','task_id','task_type','workflow_stage','lifecycle_state','review_route','snapshot','fields','groups','template','template_revision_id','template_version','template_checksum','template_reference','approval_round','membership_id','component_order','physical_scope','confirmation_text','confirmation_version','certificate_reference','destruction_number','transfer_number','total_units','affected_count','outcomes','preserved_digital_material','recovery_job_id','bulk','retained_relationships','old_rule','new_rule','error_code','method','event_id','final_disposition_event_id','final_disposition_at','final_disposition_by_user_id','disposition_job_id','captured_at','generated_at','due','access_snapshot','inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','default_child_aggregation_acl_mode','default_child_record_acl_mode','principal_type','role_id','permission_id','grants','authorization_checks','retention_rule_override','acceleration_events']) THEN
   result:=result||jsonb_build_object(item.key,disposition_private.retained_json(item.value));
  END IF;
 END LOOP;RETURN result;
END $$;

CREATE TABLE public.disposition_tasks (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    task_type text NOT NULL,
    workflow_stage text NOT NULL,
    review_round integer,
    task_state text DEFAULT 'open'::text NOT NULL,
    destination_user_id bigint,
    destination_role_id bigint,
    claimed_by_user_id bigint,
    claimed_at timestamp with time zone,
    completed_by_user_id bigint,
    completed_at timestamp with time zone,
    released_by_user_id bigint,
    released_at timestamp with time zone,
    reassigned_by_user_id bigint,
    reassigned_at timestamp with time zone,
    priority integer DEFAULT 0 NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    routing_org_unit_id bigint,
    draft_overall_reason text DEFAULT ''::text NOT NULL,
    request_document_id bigint,
    CONSTRAINT disposition_external_task_request CHECK (((task_type = 'external_approval'::text) = (request_document_id IS NOT NULL))),
    CONSTRAINT disposition_tasks_check CHECK (((destination_user_id IS NULL) <> (destination_role_id IS NULL))),
    CONSTRAINT disposition_tasks_check1 CHECK (((claimed_by_user_id IS NULL) = (claimed_at IS NULL))),
    CONSTRAINT disposition_tasks_check2 CHECK ((((task_state = 'claimed'::text) = (claimed_by_user_id IS NOT NULL)) OR (task_state = ANY (ARRAY['completed'::text, 'cancelled'::text])))),
    CONSTRAINT disposition_tasks_check3 CHECK (((task_state = 'completed'::text) = ((completed_by_user_id IS NOT NULL) AND (completed_at IS NOT NULL)))),
    CONSTRAINT disposition_tasks_check4 CHECK (((completed_by_user_id IS NULL) = (completed_at IS NULL))),
    CONSTRAINT disposition_tasks_check5 CHECK (((released_by_user_id IS NULL) = (released_at IS NULL))),
    CONSTRAINT disposition_tasks_check6 CHECK (((reassigned_by_user_id IS NULL) = (reassigned_at IS NULL))),
    CONSTRAINT disposition_tasks_review_round_check CHECK ((review_round > 0)),
    CONSTRAINT disposition_tasks_task_state_check CHECK ((task_state = ANY (ARRAY['open'::text, 'claimed'::text, 'completed'::text, 'cancelled'::text]))),
    CONSTRAINT disposition_tasks_task_type_check CHECK ((task_type = ANY (ARRAY['preparation'::text, 'correction'::text, 'file_administrator_review'::text, 'unit_manager_review'::text, 'records_manager_review'::text, 'external_approval'::text, 'physical_destruction'::text, 'digital_destruction'::text, 'certificate_download'::text]))),
    CONSTRAINT disposition_tasks_version_check CHECK ((version > 0)),
    CONSTRAINT disposition_tasks_workflow_stage_check CHECK ((workflow_stage = ANY (ARRAY['officer_preparation'::text, 'officer_correction'::text, 'manager_preparation'::text, 'manager_correction'::text, 'file_administrator_review'::text, 'unit_manager_review'::text, 'records_manager_review'::text, 'external_approval_pending'::text, 'physical_destruction'::text, 'digital_destruction'::text, 'certificate_generation'::text])))
);

CREATE FUNCTION disposition_private.review_actor(p_job bigint) RETURNS public.disposition_tasks
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; acting bigint;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT t1.* INTO t FROM disposition_tasks t1 JOIN disposition_private.command_receipts r ON t1.id=(r.payload->>'task_id')::bigint
 JOIN disposition_private.command_context c USING(command_id) WHERE c.transaction_id=txid_current() AND r.completed_at IS NULL;
 IF NOT FOUND OR t.job_id<>p_job THEN RAISE EXCEPTION 'disposition_review_task_required'; END IF;
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 RETURN t;
END $$;

CREATE FUNCTION disposition_private.review_context(p_task bigint, p_job_version integer, p_task_version integer) RETURNS public.disposition_tasks
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; j disposition_jobs%ROWTYPE; acting bigint;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.version<>p_task_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id FOR UPDATE;
 IF j.version<>p_job_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 IF j.job_type<>'destruction' OR j.workflow_stage NOT IN ('officer_preparation','officer_correction','manager_preparation','manager_correction','file_administrator_review','unit_manager_review','records_manager_review')
 THEN RAISE EXCEPTION 'disposition_review_task_required'; END IF;
 RETURN t;
END $$;

CREATE FUNCTION disposition_private.review_decision_comments() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE comments text;
BEGIN
 IF NEW.decision='rejected' AND (NEW.reason IS NULL OR NEW.reason ~ '^[[:space:]]*$')
 THEN RAISE EXCEPTION 'disposition_decision_reason_required'; END IF;
 IF NEW.decision='approved' AND NEW.review_stage IN ('records_manager_review','manager_preparation','manager_correction') THEN
  SELECT review_notes INTO comments FROM disposition_review_notes
   WHERE task_id=NEW.task_id AND author_user_id=NEW.actor_user_id;
  IF comments IS NOT NULL AND comments !~ '^[[:space:]]*$' THEN NEW.reason:=comments; END IF;
 END IF;
 RETURN NEW;
END $_$;

CREATE FUNCTION disposition_private.review_fingerprint(p_value jsonb) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$
 SELECT encode(sha256(convert_to(disposition_private.canonical_review_json(p_value)::text,'UTF8')),'hex')
$$;

CREATE FUNCTION disposition_private.review_keys(p_value jsonb, p_keys text[]) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$
 SELECT jsonb_typeof(p_value)='object' AND COALESCE((SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_value) k),ARRAY[]::text[])=p_keys
$$;

CREATE FUNCTION disposition_private.review_role(p_job bigint, p_stage text, p_role bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 WITH RECURSIVE chain AS (
 SELECT id,parent_org_unit_id,file_administrator_role_id,0 depth FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job)
 UNION ALL SELECT p.id,p.parent_org_unit_id,p.file_administrator_role_id,c.depth+1 FROM org_units p JOIN chain c ON p.id=c.parent_org_unit_id)
 SELECT CASE (CASE WHEN p_stage IN ('physical_destruction','digital_destruction','certificate_generation') THEN 'records_manager_review' ELSE p_stage END)
 WHEN 'file_administrator_review' THEN p_role=(SELECT file_administrator_role_id FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1)
 WHEN 'unit_manager_review' THEN p_role=(SELECT managing_role_id FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job))
 WHEN 'records_manager_review' THEN EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE r.id=p_role AND p.code='INFO_GOV_MGR' AND r.is_information_governance AND v.code='disposition.jobs.manage')
 ELSE false END
$$;

CREATE FUNCTION disposition_private.review_round_for_work(p_job bigint) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
 SELECT greatest(1,current_review_round) FROM disposition_jobs WHERE id=p_job
$$;

CREATE FUNCTION disposition_private.root_id(p_id bigint) RETURNS bigint
    LANGUAGE sql STABLE
    AS $$
 WITH RECURSIVE a AS (SELECT id,parent_aggregation_id FROM aggregations WHERE id=p_id
 UNION ALL SELECT p.id,p.parent_aggregation_id FROM aggregations p JOIN a ON p.id=a.parent_aggregation_id)
 SELECT id FROM a WHERE parent_aggregation_id IS NULL
$$;

CREATE FUNCTION disposition_private.route_after_external(p_job bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE target text;manager_roles bigint[];manager_role bigint;j disposition_jobs%ROWTYPE;scope jsonb;
BEGIN
 PERFORM disposition_private.require_command();
 IF NOT disposition_private.external_active(p_job) THEN RAISE EXCEPTION 'disposition_external_command_required'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job;
 scope:=disposition_private.physical_scope(p_job);
 target:=CASE WHEN jsonb_array_length(scope->'aggregations')+jsonb_array_length(scope->'records')>0 THEN 'physical_destruction' ELSE 'digital_destruction' END;
 SELECT array_agg(r.id ORDER BY r.id) INTO manager_roles FROM roles r WHERE disposition_private.review_role(p_job,'records_manager_review',r.id) AND role_effectively_active(r.id) AND EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,r.id) AND disposition_private.can_review_content(u.id,p_job));
 IF manager_roles IS NULL THEN RAISE EXCEPTION 'disposition_manager_role_required'; END IF;
 UPDATE disposition_jobs SET workflow_stage=target WHERE id=p_job;
 FOREACH manager_role IN ARRAY manager_roles LOOP
 INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_role_id) VALUES(p_job,target,target,j.current_review_round,manager_role);
 END LOOP;
 PERFORM append_domain_event('disposition_job',p_job,'TASK_ROUTED',jsonb_build_object('workflow_stage',target,'destination_role_ids',to_jsonb(manager_roles)));
END $$;

CREATE FUNCTION disposition_private.route_correction(p_job bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 PERFORM disposition_private.require_preparer(j.assigned_user_id,j.review_route);
 IF NOT disposition_private.can_review_content(j.assigned_user_id,p_job) THEN RAISE EXCEPTION 'disposition_assignee_access_required'; END IF;
 UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_state IN ('open','claimed');
 UPDATE disposition_review_rounds SET completed_at=CURRENT_TIMESTAMP WHERE job_id=p_job AND round_number=j.current_review_round AND completed_at IS NULL AND invalidated_at IS NULL;
 UPDATE disposition_jobs SET workflow_stage=CASE WHEN j.review_route='records_manager_only' THEN 'manager_correction' ELSE 'officer_correction' END WHERE id=p_job RETURNING * INTO j;
 INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id)
 VALUES(p_job,'correction',j.workflow_stage,j.current_review_round,j.assigned_user_id);
END $$;

CREATE FUNCTION disposition_private.route_review(p_job bigint, p_stage text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE; role_id bigint; source_unit bigint; destinations bigint[]; selected_stage text:=p_stage; skipped boolean:=false;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation() NOT IN ('review_submit','review_decide') THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF j.job_type<>'destruction' OR j.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF j.review_route='records_manager_only' THEN RAISE EXCEPTION 'disposition_combined_approval_required'; END IF;
 IF p_stage='file_administrator_review' THEN
  IF j.review_route<>'standard' THEN RAISE EXCEPTION 'disposition_saved_route_mismatch'; END IF;
  WITH RECURSIVE chain AS (
   SELECT id,parent_org_unit_id,file_administrator_role_id,0 depth FROM org_units WHERE id=j.owning_org_unit_id
   UNION ALL SELECT p.id,p.parent_org_unit_id,p.file_administrator_role_id,c.depth+1 FROM org_units p JOIN chain c ON p.id=c.parent_org_unit_id)
  SELECT file_administrator_role_id,id INTO role_id,source_unit FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1;
  IF role_id IS NULL THEN selected_stage:='unit_manager_review';skipped:=true; END IF;
 END IF;
 IF selected_stage='unit_manager_review' THEN
  IF j.review_route<>'standard' THEN RAISE EXCEPTION 'disposition_saved_route_mismatch'; END IF;
  SELECT managing_role_id,id INTO role_id,source_unit FROM org_units WHERE id=j.owning_org_unit_id;
 END IF;
 IF selected_stage IN ('file_administrator_review','unit_manager_review') THEN destinations:=ARRAY[role_id];
 ELSIF selected_stage='records_manager_review' THEN
  SELECT array_agg(r.id ORDER BY r.id) INTO destinations FROM roles r WHERE disposition_private.review_role(p_job,selected_stage,r.id)
   AND EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,r.id) AND disposition_private.can_review_content(u.id,p_job));
 ELSE RAISE EXCEPTION 'disposition_review_stage_invalid'; END IF;
 IF destinations IS NULL OR cardinality(destinations)=0 THEN RAISE EXCEPTION 'disposition_reviewer_unavailable'; END IF;
 FOREACH role_id IN ARRAY destinations LOOP
  IF role_id IS NULL OR NOT EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,role_id) AND disposition_private.can_review_content(u.id,p_job))
  THEN RAISE EXCEPTION 'disposition_reviewer_unavailable'; END IF;
 END LOOP;
 -- All resolution checks precede writes; configured-but-unusable never falls back.
 UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_state IN ('open','claimed');
 UPDATE disposition_jobs SET workflow_stage=selected_stage WHERE id=p_job;
 FOREACH role_id IN ARRAY destinations LOOP
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_role_id,routing_org_unit_id)
  VALUES(p_job,selected_stage,selected_stage,j.current_review_round,role_id,source_unit);
 END LOOP;
 PERFORM append_domain_event('disposition_job',p_job,'TASK_ROUTED',jsonb_build_object('review_route',j.review_route,'workflow_stage',selected_stage,'routing_org_unit_id',source_unit,'role_ids',destinations,'file_administrator_skipped',skipped,'skip_reason',CASE WHEN skipped THEN 'not_configured' END));
 RETURN jsonb_build_object('workflow_stage',selected_stage,'file_administrator_skipped',skipped,'routing_org_unit_id',source_unit);
END $$;

CREATE FUNCTION disposition_private.rule_identity(p_evaluation jsonb) RETURNS jsonb
    LANGUAGE sql IMMUTABLE
    AS $$
 SELECT jsonb_build_array(p_evaluation#>'{rule_snapshot,rule_source}',p_evaluation#>'{rule_snapshot,rule_id}',
 p_evaluation#>'{rule_snapshot,defined_by_classification_id}',p_evaluation#>'{rule_snapshot,current_period_years}',
 p_evaluation#>'{rule_snapshot,intermediate_period_years}',p_evaluation#>'{rule_snapshot,final_disposition}',
 p_evaluation#>'{rule_snapshot,instructions}',p_evaluation#>'{rule_snapshot,justification}')
$$;

CREATE FUNCTION disposition_private.save_review_work(p_task bigint, p_job_version integer, p_task_version integer, p_changes jsonb, p_notes text, p_note_version integer, p_overall_reason text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE t disposition_tasks%ROWTYPE; acting bigint; item jsonb; prop disposition_review_proposals%ROWTYPE; note disposition_review_notes%ROWTYPE; facts jsonb; result jsonb:='[]'; selected_id bigint; action text; round_number integer; expected_target bigint;
BEGIN
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_save' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_context(p_task,p_job_version,p_task_version);
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 round_number:=disposition_private.review_round_for_work(t.job_id);
 IF p_overall_reason IS NOT NULL AND t.workflow_stage NOT IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') THEN RAISE EXCEPTION 'disposition_submission_reason_owner_required'; END IF;
 IF jsonb_typeof(p_changes) IS DISTINCT FROM 'array' OR jsonb_array_length(p_changes)>100 THEN RAISE EXCEPTION 'disposition_selection_bounds_invalid'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_changes) LOOP
  action:=item->>'action';
  IF action NOT IN ('create','revise','withdraw') THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
  IF action<>'create' THEN
   SELECT * INTO prop FROM disposition_review_proposals WHERE id=(item->>'proposal_id')::bigint FOR UPDATE;
   IF NOT FOUND OR prop.job_id<>t.job_id OR prop.version<>(item->>'expected_version')::integer THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_proposal'; END IF;
   IF prop.proposal_state<>'active' OR prop.review_round<>round_number THEN RAISE EXCEPTION 'disposition_proposal_closed'; END IF;
  END IF;
  IF action='withdraw' THEN
   DELETE FROM disposition_proposal_holds WHERE proposal_id=prop.id;
   UPDATE disposition_review_proposals SET proposal_state='withdrawn',withdrawal_reason=item->>'reason' WHERE id=prop.id RETURNING * INTO prop;
  ELSE
   IF action='create' THEN
    facts:=disposition_private.proposal_facts(t.job_id,(item->>'governing_root_id')::bigint,(item->>'target_aggregation_id')::bigint,(item->>'target_record_id')::bigint,item->>'proposal_type',item->'proposed_values',item->>'reason');
    expected_target:=COALESCE((facts#>>'{record,version}')::bigint,(facts->>'aggregation_version')::bigint);
   ELSE
    facts:=disposition_private.proposal_facts(t.job_id,prop.governing_root_id,prop.target_aggregation_id,prop.target_record_id,prop.proposal_type,item->'proposed_values',item->>'reason');
    expected_target:=COALESCE((facts#>>'{record,version}')::bigint,(facts->>'aggregation_version')::bigint);
   END IF;
   IF (item->>'target_version')::bigint IS DISTINCT FROM expected_target THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_target'; END IF;
   IF action='create' THEN
    INSERT INTO disposition_review_proposals(job_id,review_round,governing_root_id,target_aggregation_id,target_record_id,proposal_type,proposed_values,current_values,reason,proposer_user_id,proposer_role_id,proposer_stage,original_review_round)
    VALUES(t.job_id,round_number,(item->>'governing_root_id')::bigint,(item->>'target_aggregation_id')::bigint,(item->>'target_record_id')::bigint,item->>'proposal_type',item->'proposed_values',facts,item->>'reason',current_user_id(),acting,t.workflow_stage,round_number) RETURNING * INTO prop;
   ELSE
    DELETE FROM disposition_proposal_holds WHERE proposal_id=prop.id;
    UPDATE disposition_review_proposals SET proposed_values=item->'proposed_values',current_values=facts,reason=item->>'reason' WHERE id=prop.id RETURNING * INTO prop;
   END IF;
   IF prop.proposal_type='add_to_holds' THEN
    FOR selected_id IN SELECT value::text::bigint FROM jsonb_array_elements(prop.proposed_values->'hold_ids') LOOP
     INSERT INTO disposition_proposal_holds(proposal_id,hold_id,hold_snapshot) VALUES(prop.id,selected_id,'{}');
    END LOOP;
   END IF;
  END IF;
  result:=result||jsonb_build_array(jsonb_build_object('id',prop.id,'version',prop.version,'proposal_state',prop.proposal_state));
 END LOOP;
 IF p_notes IS NOT NULL THEN
  SELECT * INTO note FROM disposition_review_notes WHERE task_id=t.id AND author_user_id=current_user_id() FOR UPDATE;
  IF COALESCE(note.version,0) IS DISTINCT FROM p_note_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_notes'; END IF;
  IF note.id IS NULL THEN
   INSERT INTO disposition_review_notes(job_id,task_id,review_round,workflow_stage,author_user_id,acting_role_id,review_notes)
   VALUES(t.job_id,t.id,round_number,t.workflow_stage,current_user_id(),acting,p_notes) RETURNING * INTO note;
  ELSE UPDATE disposition_review_notes SET review_notes=p_notes WHERE id=note.id RETURNING * INTO note; END IF;
 END IF;
 UPDATE disposition_tasks SET draft_overall_reason=COALESCE(p_overall_reason,draft_overall_reason) WHERE id=t.id RETURNING * INTO t;
 UPDATE disposition_jobs SET date_updated=CURRENT_TIMESTAMP WHERE id=t.job_id;
 RETURN jsonb_build_object('job_id',t.job_id,'task_id',t.id,'job_version',(SELECT version FROM disposition_jobs WHERE id=t.job_id),'task_version',t.version,'changes',result,'note_version',note.version);
END $$;

CREATE FUNCTION disposition_private.start_manager_round(p_job bigint, p_version integer) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE; acting bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR j.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF j.review_route<>'records_manager_only' THEN RAISE EXCEPTION 'disposition_saved_route_mismatch'; END IF;
 PERFORM disposition_private.require_membership_stage(p_job);
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF NOT disposition_private.review_role(p_job,'records_manager_review',acting) OR NOT disposition_private.person_role(current_user_id(),acting)
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 PERFORM disposition_private.require_progress(p_job);
 IF NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') THEN RAISE EXCEPTION 'disposition_empty_job'; END IF;
 INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot)
 VALUES(p_job,j.current_review_round+1,current_user_id(),disposition_private.membership_snapshot(p_job));
 RETURN j.current_review_round+1;
END $$;

CREATE FUNCTION disposition_private.start_review(p_job bigint, p_version integer) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE j disposition_jobs%ROWTYPE; result jsonb;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_submit' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR j.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 PERFORM disposition_private.require_membership_stage(p_job);
 PERFORM disposition_private.require_preparer(current_user_id(),j.review_route);
 IF j.review_route='records_manager_only' THEN RAISE EXCEPTION 'disposition_combined_approval_required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') THEN RAISE EXCEPTION 'disposition_empty_job'; END IF;
 PERFORM disposition_private.require_progress(p_job);
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot)
 VALUES(p_job,j.current_review_round+1,current_user_id(),disposition_private.membership_snapshot(p_job));
 result:=disposition_private.route_review(p_job,CASE WHEN j.review_route='standard' THEN 'file_administrator_review' ELSE 'records_manager_review' END);
 RETURN result||jsonb_build_object('review_round',j.current_review_round+1);
END $$;

CREATE FUNCTION disposition_private.submit_review_work(p_task bigint, p_job_version integer, p_task_version integer, p_reason text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE t disposition_tasks%ROWTYPE; p disposition_review_proposals%ROWTYPE; next_id bigint; next_round integer; result jsonb;
BEGIN
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_submit' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_context(p_task,p_job_version,p_task_version);
 IF t.workflow_stage NOT IN ('officer_preparation','officer_correction') THEN RAISE EXCEPTION 'disposition_combined_approval_required'; END IF;
 IF p_reason IS NULL OR p_reason ~ '^[[:space:]]*$' THEN RAISE EXCEPTION 'disposition_submission_reason_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_review_proposals candidate JOIN disposition_job_memberships m ON m.job_id=candidate.job_id AND m.root_aggregation_id=candidate.governing_root_id AND m.membership_state='active'
 WHERE candidate.job_id=t.job_id AND candidate.review_round=disposition_private.review_round_for_work(t.job_id) AND candidate.proposal_type='remove_from_job' AND candidate.proposal_state='active') THEN RAISE EXCEPTION 'disposition_marked_removals_require_correction'; END IF;
 PERFORM disposition_private.validate_active_proposals(t.job_id,disposition_private.review_round_for_work(t.job_id));
 SELECT current_review_round+1 INTO next_round FROM disposition_jobs WHERE id=t.job_id;
 IF next_round>1 THEN
  FOR p IN SELECT p1.* FROM disposition_review_proposals p1 JOIN disposition_job_memberships m ON m.job_id=p1.job_id AND m.root_aggregation_id=p1.governing_root_id AND m.membership_state='active'
   WHERE p1.job_id=t.job_id AND p1.review_round=next_round-1 AND p1.proposal_state='active' ORDER BY p1.id LOOP
   INSERT INTO disposition_review_proposals(job_id,review_round,governing_root_id,target_aggregation_id,target_record_id,proposal_type,proposed_values,current_values,reason,proposer_user_id,proposer_role_id,proposer_stage,proposed_at,original_review_round,carried_from_proposal_id,last_revised_by_user_id,last_revised_role_id,last_revised_stage,last_revised_round,last_revised_at)
   VALUES(p.job_id,next_round,p.governing_root_id,p.target_aggregation_id,p.target_record_id,p.proposal_type,p.proposed_values,p.current_values,p.reason,p.proposer_user_id,p.proposer_role_id,p.proposer_stage,p.proposed_at,p.original_review_round,p.id,p.last_revised_by_user_id,p.last_revised_role_id,p.last_revised_stage,p.last_revised_round,p.last_revised_at) RETURNING id INTO next_id;
   INSERT INTO disposition_proposal_holds(proposal_id,hold_id,hold_snapshot) SELECT next_id,hold_id,hold_snapshot FROM disposition_proposal_holds WHERE proposal_id=p.id;
  END LOOP;
 END IF;
 UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
 result:=disposition_private.start_review(t.job_id,p_job_version);
 RETURN result||jsonb_build_object('job_id',t.job_id,'job_version',(SELECT version FROM disposition_jobs WHERE id=t.job_id));
END $_$;

CREATE FUNCTION disposition_private.task_eligible(p_user bigint, p_task bigint, p_role bigint DEFAULT NULL::bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id
 WHERE t.id=p_task AND (j.lifecycle_state='active' OR j.lifecycle_state='completed' AND t.task_type='certificate_download')
 AND disposition_private.can_review_content(p_user,j.id) AND
 CASE WHEN t.task_type='certificate_download' THEN t.destination_user_id=p_user AND EXISTS(SELECT 1 FROM roles r WHERE disposition_private.person_role(p_user,r.id) AND disposition_private.review_role(j.id,'records_manager_review',r.id) AND (p_role IS NULL OR r.id=p_role)) WHEN t.destination_user_id IS NOT NULL THEN t.destination_user_id=p_user AND j.assigned_user_id=p_user
 AND disposition_private.governance_person(p_user,CASE WHEN j.review_route='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END)
 AND (p_role IS NULL OR EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE r.id=p_role AND r.is_information_governance AND v.code='disposition.jobs.manage'
 AND p.code=CASE WHEN j.review_route='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END
 AND disposition_private.person_role(p_user,r.id)))
 ELSE disposition_private.person_role(p_user,t.destination_role_id)
 AND disposition_private.review_role(j.id,t.workflow_stage,t.destination_role_id)
 AND (p_role IS NULL OR p_role=t.destination_role_id) END),false)
$$;

CREATE FUNCTION disposition_private.task_manager(p_task bigint, p_role bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_tasks t JOIN roles r ON r.id=p_role
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges v ON v.id=pp.privilege_id
 WHERE t.id=p_task AND current_setting('app.actor_type',true)='user' AND r.is_information_governance AND v.code='disposition.jobs.manage'
 AND disposition_private.person_role(current_user_id(),p_role)
 AND disposition_private.can_review_content(current_user_id(),t.job_id))
$$;

CREATE FUNCTION disposition_private.terminate_job(p_job bigint, p_version integer, p_confirm boolean) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE job disposition_jobs%ROWTYPE;member record;root aggregations%ROWTYPE;key uuid;target integer;facts jsonb;outcomes jsonb:='[]';retained_links jsonb;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_terminate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 IF p_confirm IS DISTINCT FROM true THEN RAISE EXCEPTION 'disposition_confirmation_required'; END IF;
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF job.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 SELECT command_id INTO key FROM disposition_private.command_context WHERE transaction_id=txid_current();
 INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,0,NULL);
 FOR member IN SELECT * FROM disposition_job_memberships WHERE job_id=p_job AND membership_state IN ('active','completed_history') ORDER BY root_aggregation_id FOR UPDATE LOOP
  PERFORM disposition_private.lock_current_blockers(member.root_aggregation_id);
  SELECT * INTO root FROM aggregations WHERE id=member.root_aggregation_id;
  IF NOT disposition_private.recovery_unit_visible(root.id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_recovery_access_required'; END IF;
  IF root.disposition_status IN (10,11,12) THEN target:=root.disposition_status;
  ELSIF job.job_type='destruction' AND disposition_private.physical_covered(p_job,root.id) THEN
   target:=CASE WHEN disposition_private.unit_has_digital(root.id) THEN 13 ELSE 10 END;
   facts:=disposition_private.recovery_facts(p_job,root.id);
  ELSE target:=CASE WHEN member.removal_required THEN root.disposition_status ELSE job.disposition_status-4 END;facts:=NULL;
  END IF;
  IF root.disposition_status<>target THEN
   INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,root.id,target);
   PERFORM disposition_private.transition_unit(root.id,root.version,target);
   IF target=13 THEN PERFORM append_domain_event('aggregation',root.id,'DISPOSITION_PARTIALLY_DISPOSED',facts||jsonb_build_object('command_id',key,'old_status',root.disposition_status,'new_status',target)); END IF;
  END IF;
  IF member.membership_state='active' THEN UPDATE disposition_job_memberships SET membership_state='terminated_history' WHERE id=member.id; END IF;
  outcomes:=outcomes||jsonb_build_array(jsonb_build_object('root_id',root.id,'old_status',root.disposition_status,'new_status',target));
 END LOOP;
 SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array(l.resource_kind,l.relationship_id)),'[]') INTO retained_links FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.relationship_scope(m.root_aggregation_id) l WHERE m.job_id=p_job AND l.source_root_id IN (SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job) AND l.target_root_id IN (SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job);
 UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_state IN ('open','claimed');
 UPDATE disposition_jobs SET lifecycle_state='terminated',disposition_status=job.disposition_status-4,termination_reason=current_setting('app.change_reason',true) WHERE id=p_job RETURNING * INTO job;
 PERFORM append_domain_event('disposition_job',p_job,'DISPOSITION_TERMINATION_OUTCOMES',jsonb_build_object('command_id',key,'outcomes',outcomes,'retained_relationships',retained_links));
 DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 RETURN to_jsonb(job);
END $$;

CREATE FUNCTION disposition_private.transition_unit(p_root bigint, p_version bigint, p_status integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE root aggregations%ROWTYPE; uid bigint:=current_user_id(); event_id bigint; op text; recovery_job bigint; physical disposition_physical_confirmations%ROWTYPE; executor_name text;
BEGIN
 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 SELECT * INTO root FROM aggregations WHERE id=p_root FOR UPDATE;
 IF NOT FOUND OR root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF p_status NOT BETWEEN 1 AND 13 OR NOT disposition_private.allowed_transition(root.disposition_status,p_status,op) THEN RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
 IF p_status IN (10,11,12,13) AND NOT ((op='job_terminate' AND p_status IN (10,13) OR op='final_complete' AND p_status=10 AND EXISTS(SELECT 1 FROM disposition_private.recovery_context x WHERE x.transaction_id=txid_current() AND x.root_id=p_root AND disposition_private.completion_active(x.job_id))) AND disposition_private.recovery_active(NULL,p_root,p_status)) THEN RAISE EXCEPTION 'disposition_action_not_implemented'; END IF;
 IF root.date_closed IS NULL AND p_status<>1 THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 IF NOT disposition_private.hook_applying(p_root) AND NOT disposition_private.approval_active(NULL,p_root) AND current_setting('app.actor_type',true)='user' AND NOT user_can_view_aggregation(uid,p_root) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.disposition_status=p_status AND (NOT disposition_private.hook_applying(p_root) OR NOT EXISTS(
  SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>p_status
  UNION ALL SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>p_status)) THEN RETURN; END IF;
 event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_STATUS_CHANGED',jsonb_build_object(
  'old_status',root.disposition_status,'new_status',p_status,'operation',op,
  'command_id',(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())));
 IF p_status=10 THEN
  SELECT job_id INTO recovery_job FROM disposition_private.recovery_context WHERE transaction_id=txid_current() AND root_id=p_root;
  SELECT * INTO physical FROM disposition_physical_confirmations WHERE job_id=recovery_job;
  IF physical.id IS NULL OR NOT disposition_private.physical_covered(recovery_job,p_root) OR disposition_private.unit_has_digital(p_root) THEN RAISE EXCEPTION 'disposition_recovery_scope_invalid'; END IF;
  SELECT e.actor_name INTO executor_name FROM event_history e WHERE e.entity_type='disposition_job' AND e.entity_id=recovery_job AND e.operation='PHYSICAL_DESTRUCTION_CONFIRMED' AND e.metadata#>>'{after,id}'=physical.id::text ORDER BY e.id LIMIT 1;
  event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_UNIT_DESTROYED',jsonb_build_object('recovery_job_id',recovery_job,'root_id',p_root,'physical_confirmation_id',physical.id,'certificate_document_id',physical.certificate_document_id,'executor_user_id',physical.confirmed_by_user_id,'executor_name',coalesce(executor_name,(SELECT name FROM users WHERE id=physical.confirmed_by_user_id)),'completed_at',physical.confirmed_at));
  PERFORM disposition_private.retain_physical_outcome(recovery_job,p_root,event_id,physical.confirmed_at,physical.confirmed_by_user_id,coalesce(executor_name,(SELECT name FROM users WHERE id=physical.confirmed_by_user_id)));
  RETURN;
 END IF;
 UPDATE aggregations SET disposition_status=p_status WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status IS DISTINCT FROM p_status;
 UPDATE records SET disposition_status=p_status WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status IS DISTINCT FROM p_status;
END $$;

CREATE FUNCTION disposition_private.unit_has_digital(p_root bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND medium IN ('digital','mixed')) OR
 EXISTS(SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND medium IN ('digital','mixed'))
$$;

CREATE FUNCTION disposition_private.unit_ids(p_root bigint) RETURNS SETOF bigint
    LANGUAGE sql STABLE
    AS $$
 WITH RECURSIVE a AS (SELECT id FROM aggregations WHERE id=p_root UNION ALL
 SELECT child.id FROM aggregations child JOIN a ON child.parent_aggregation_id=a.id) SELECT id FROM a
$$;

CREATE FUNCTION disposition_private.validate_active_proposals(p_job bigint, p_round integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE p disposition_review_proposals%ROWTYPE;
BEGIN
 FOR p IN SELECT p1.* FROM disposition_review_proposals p1 JOIN disposition_job_memberships m ON m.job_id=p1.job_id AND m.root_aggregation_id=p1.governing_root_id AND m.membership_state='active'
 WHERE p1.job_id=p_job AND p1.review_round=p_round AND p1.proposal_state='active' ORDER BY p1.id LOOP
  PERFORM disposition_private.proposal_facts(p.job_id,p.governing_root_id,p.target_aggregation_id,p.target_record_id,p.proposal_type,p.proposed_values,p.reason);
 END LOOP;
END $$;

CREATE FUNCTION public.aggregation_effective_assigned_location(p_aggregation_id bigint) RETURNS text
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id,parent_aggregation_id,assigned_location,0 AS depth
        FROM aggregations WHERE id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,parent.assigned_location,child.depth+1
        FROM ancestors child
        JOIN aggregations parent ON parent.id=child.parent_aggregation_id
    )
    SELECT assigned_location FROM ancestors
    WHERE assigned_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE FUNCTION public.aggregation_effective_assigned_location_source_id(p_aggregation_id bigint) RETURNS bigint
    LANGUAGE sql STABLE
    AS $$
 WITH RECURSIVE ancestors AS (
  SELECT id,parent_aggregation_id,assigned_location,0 depth FROM aggregations WHERE id=p_aggregation_id
  UNION ALL SELECT p.id,p.parent_aggregation_id,p.assigned_location,a.depth+1 FROM ancestors a JOIN aggregations p ON p.id=a.parent_aggregation_id)
 SELECT id FROM ancestors WHERE assigned_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE FUNCTION public.aggregation_effective_current_location(p_aggregation_id bigint) RETURNS text
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id,parent_aggregation_id,current_location,0 AS depth
        FROM aggregations WHERE id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,parent.current_location,child.depth+1
        FROM ancestors child
        JOIN aggregations parent ON parent.id=child.parent_aggregation_id
    )
    SELECT current_location FROM ancestors
    WHERE current_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE FUNCTION public.aggregation_effective_current_location_source_id(p_aggregation_id bigint) RETURNS bigint
    LANGUAGE sql STABLE
    AS $$
 WITH RECURSIVE ancestors AS (
  SELECT id,parent_aggregation_id,current_location,0 depth FROM aggregations WHERE id=p_aggregation_id
  UNION ALL SELECT p.id,p.parent_aggregation_id,p.current_location,a.depth+1 FROM ancestors a JOIN aggregations p ON p.id=a.parent_aggregation_id)
 SELECT id FROM ancestors WHERE current_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE FUNCTION public.aggregation_effective_retention_rule(p_aggregation_id bigint) RETURNS TABLE(governing_root_aggregation_id bigint, classification_id bigint, rule_source text, rule_id bigint, defined_by_classification_id bigint, inheritance_depth integer, current_period_years integer, intermediate_period_years integer, final_disposition text, instructions text, justification text)
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE root_row record;
BEGIN
    WITH RECURSIVE lineage AS (
        SELECT a.*, 0 AS depth FROM aggregations AS a WHERE a.id = p_aggregation_id
        UNION ALL
        SELECT parent.*, child.depth + 1
        FROM aggregations AS parent
        JOIN lineage AS child ON parent.id = child.parent_aggregation_id
    )
    SELECT lineage.*
    INTO root_row
    FROM lineage WHERE lineage.parent_aggregation_id IS NULL LIMIT 1;

    IF root_row.id IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM aggregation_retention_rules WHERE aggregation_id = root_row.id
    ) THEN
        RETURN QUERY
        SELECT root_row.id, root_row.classification_id, 'aggregation'::text,
               r.id, NULL::bigint, 0,
               r.current_period_years, r.intermediate_period_years,
               r.final_disposition, r.instructions, r.justification
        FROM aggregation_retention_rules AS r
        WHERE r.aggregation_id = root_row.id;
        RETURN;
    END IF;
    RETURN QUERY
    SELECT root_row.id, root_row.classification_id, 'classification'::text,
           r.rule_id, r.defined_by_classification_id, r.inheritance_depth,
           r.current_period_years, r.intermediate_period_years,
           r.final_disposition, r.instructions, NULL::text
    FROM effective_classification_retention_rule(root_row.classification_id) AS r;
END;
$$;

CREATE FUNCTION public.aggregation_has_vital_descendants(p_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE subtree AS (
        SELECT p_id AS id
        UNION ALL
        SELECT child.id
          FROM aggregations child
          JOIN subtree parent ON child.parent_aggregation_id = parent.id
    )
    SELECT EXISTS (
               SELECT 1
                 FROM aggregations
                WHERE id IN (SELECT id FROM subtree)
                  AND id <> p_id
                  AND is_vital
           )
        OR EXISTS (
               SELECT 1
                 FROM records
                WHERE aggregation_id IN (SELECT id FROM subtree)
                  AND is_vital
           )
$$;

CREATE FUNCTION public.allow_governed_aggregation_location_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN IF (NEW.assigned_location IS DISTINCT FROM OLD.assigned_location OR NEW.current_location IS DISTINCT FROM OLD.current_location) AND (current_setting('app.location_change_authorized',true)<>'authorized' OR NULLIF(btrim(current_setting('app.change_reason',true)), '') IS NULL) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='location_change_requires_governed_authorization_and_reason'; END IF; RETURN NEW; END; $$;

CREATE FUNCTION public.allow_governed_review_date_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN IF NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review AND (current_setting('app.review_date_change_authorized',true)<>'authorized' OR NULLIF(btrim(current_setting('app.change_reason',true)), '') IS NULL) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='review_date_change_requires_governed_authorization_and_reason'; END IF; RETURN NEW; END; $$;

CREATE FUNCTION public.allow_governed_vital_status_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN IF NEW.is_vital IS DISTINCT FROM OLD.is_vital AND (current_setting('app.vital_status_change_authorized',true)<>'authorized' OR NULLIF(btrim(current_setting('app.change_reason',true)), '') IS NULL) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='vital_status_change_requires_governed_authorization_and_reason'; END IF; RETURN NEW; END; $$;

CREATE FUNCTION public.append_domain_event(event_entity_type text, event_entity_id bigint, event_operation text, event_metadata jsonb DEFAULT '{}'::jsonb, event_reason text DEFAULT NULL::text) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
DECLARE
    event_id         bigint;
    context_user_id text;
BEGIN
    IF btrim(event_entity_type) = '' OR btrim(event_operation) = '' THEN
        RAISE EXCEPTION 'domain event entity type and operation cannot be blank';
    END IF;
    IF jsonb_typeof(event_metadata) <> 'object' THEN
        RAISE EXCEPTION 'domain event metadata must be a JSON object';
    END IF;

    context_user_id := NULLIF(current_setting('app.user_id', true), '');
    INSERT INTO event_history (
        entity_type,
        entity_id,
        operation,
        actor_user_id,
        actor_type,
        source,
        request_id,
        correlation_id,
        reason,
        metadata
    )
    VALUES (
        event_entity_type,
        event_entity_id,
        event_operation,
        context_user_id::bigint,
        COALESCE(NULLIF(current_setting('app.actor_type', true), ''), 'automated_process'),
        COALESCE(NULLIF(current_setting('app.event_source', true), ''), 'database'),
        NULLIF(current_setting('app.request_id', true), '')::uuid,
        NULLIF(current_setting('app.correlation_id', true), '')::uuid,
        COALESCE(event_reason, NULLIF(current_setting('app.change_reason', true), '')),
        event_metadata
    )
    RETURNING id INTO event_id;
    RETURN event_id;
END;
$$;

CREATE FUNCTION public.append_hold_assignment_domain_events() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE state record;
DECLARE operation_name text:=CASE WHEN TG_OP='INSERT' THEN 'RESOURCE_ADDED_TO_HOLD' ELSE 'RESOURCE_REMOVED_FROM_HOLD' END;
DECLARE resource_type text:=CASE WHEN TG_TABLE_NAME='hold_aggregation_assignments' THEN 'aggregation' ELSE 'record' END;
DECLARE resource_id bigint;
DECLARE metadata jsonb;
BEGIN
    IF TG_OP='UPDATE' THEN RETURN NEW; END IF;
    IF TG_OP='DELETE' THEN state:=OLD; ELSE state:=NEW; END IF;
    IF resource_type='aggregation' THEN resource_id:=state.aggregation_id; ELSE resource_id:=state.record_id; END IF;
    metadata:=jsonb_build_object('hold_id',state.hold_id,'resource_type',resource_type,
                                 'resource_id',resource_id,'assignment_id',state.id);
    IF TG_OP='DELETE' THEN
        IF resource_type='aggregation' THEN
            metadata:=metadata||jsonb_build_object('remaining_effective_hold_ids',COALESCE((SELECT jsonb_agg(hold_id ORDER BY hold_id) FROM effective_holds_for_aggregation(resource_id)),'[]'::jsonb));
        ELSE
            metadata:=metadata||jsonb_build_object('remaining_effective_hold_ids',COALESCE((SELECT jsonb_agg(hold_id ORDER BY hold_id) FROM effective_holds_for_record(resource_id)),'[]'::jsonb));
        END IF;
    END IF;
    PERFORM append_domain_event('hold',state.hold_id,operation_name,metadata);
    PERFORM append_domain_event(resource_type,resource_id,operation_name,metadata);
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.append_hold_definition_domain_event() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE entity_id bigint:=CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
DECLARE operation_name text:=CASE TG_OP WHEN 'INSERT' THEN 'HOLD_CREATED' WHEN 'UPDATE' THEN 'HOLD_UPDATED' ELSE 'HOLD_DELETED' END;
DECLARE old_state jsonb:=CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) ELSE NULL END;
DECLARE new_state jsonb:=CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) ELSE NULL END;
BEGIN
    IF TG_OP='INSERT' THEN
        new_state:=new_state||jsonb_build_object(
            'contributor_user_ids',COALESCE(NULLIF(current_setting('app.hold_contributor_ids',true),'')::jsonb,'[]'::jsonb));
    END IF;
    PERFORM append_domain_event('hold',entity_id,operation_name,
        jsonb_strip_nulls(jsonb_build_object('before',old_state,'after',new_state)));
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.application_setting_value_valid(p_key text, p_value jsonb, p_secret bytea) RETURNS boolean
    LANGUAGE sql STABLE
    AS $_$
 SELECT COALESCE(CASE p_key
 WHEN 'DEFAULT_WORKING_TIMEZONE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=p_value#>>'{}'))
 WHEN 'DEFAULT_ROOT_AGGREGATION_MEDIUM' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') IN ('digital','physical','mixed'))
 WHEN 'REVIEW_WARNING_WINDOW_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'MAX_UPLOAD_SIZE_BYTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CONTENT_SEGMENT_SIZE_BYTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 67108864)
 WHEN 'CONTENT_SEGMENT_CHECKSUMS_ENABLED' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='boolean')
 WHEN 'CONTENT_UPLOAD_SESSION_TTL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CONTENT_CLEANUP_INTERVAL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DOCUMENT_CONVERSION_TIMEOUT_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'MAX_RENDITION_SIZE_BYTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_IDLE_MINUTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_ABSOLUTE_HOURS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_LOCKOUT_ATTEMPTS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_LOCKOUT_MINUTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_PASSWORD_MIN_LENGTH' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 8 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_RETENTION_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_CLEANUP_INTERVAL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_CLEANUP_BATCH_SIZE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_FAVOURITE_ITEM_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_RECENT_ITEM_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_RECENT_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_REVIEW_PREVIEW_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CLASSIFICATION_RECENT_SELECTION_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'USER_DETAILS_SESSION_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'FULL_TEXT_SEARCH_ENABLED' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='boolean')
 WHEN 'CONTENT_INDEXING_SCHEDULING_ENABLED' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='boolean')
 WHEN 'CONTENT_INDEXING_HISTORY_RETENTION_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CONTENT_INDEXING_CLEANUP_BATCH_SIZE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'TEXT_INDEXER_RATE_LIMIT_PER_MINUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'SEARCH_RATE_LIMIT_PER_MINUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUDIT_TRAIL_SEARCH_RESULT_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DISPOSITION_DESTRUCTION_REVIEW_ROUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') IN ('standard','simplified','records_manager_only'))
 WHEN 'DISPOSITION_CLASSIFICATION_SCHEME_ID' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)))
 WHEN 'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)))
 WHEN 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)))
 WHEN 'DISPOSITION_EXTERNAL_AUTHORITY_NAME' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')
 WHEN 'DISPOSITION_EXTERNAL_AUTHORITY_EMAIL' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') ~ '^[^[:space:]@]+@[^[:space:]@]+$')))
 WHEN 'DISPOSITION_DESTRUCTION_REMINDER_MONTHS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'SMTP_HOST' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'SMTP_PORT' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 65535)))
 WHEN 'SMTP_SECURITY' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') IN ('starttls','implicit_tls'))))
 WHEN 'SMTP_AUTH_ENABLED' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='boolean')))
 WHEN 'SMTP_USERNAME' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'SMTP_PASSWORD' THEN p_value='null'::jsonb AND (p_secret IS NULL OR convert_from(p_secret,'UTF8') ~ '^fernet:v1:[A-Za-z0-9_=-]+$')
 WHEN 'SMTP_SENDER_EMAIL' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') ~ '^[^[:space:]@]+@[^[:space:]@]+$')))
 WHEN 'SMTP_SENDER_NAME' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'SMTP_REPLY_TO_EMAIL' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') ~ '^[^[:space:]@]+@[^[:space:]@]+$')))
 WHEN 'SMTP_TIMEOUT_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DISPOSITION_RECORDS_UNIT_EMAIL' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') ~ '^[^[:space:]@]+@[^[:space:]@]+$')))
 WHEN 'DISPOSITION_RECORDS_UNIT_PHONE' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'DISPOSITION_ORGANIZATION_NAME' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'DISPOSITION_REQUEST_LANGUAGE' THEN p_secret IS NULL AND jsonb_typeof(p_value)='string' AND p_value#>>'{}' IN ('manager_preference','arabic_first_bilingual')
 ELSE false END,false)
$_$;

CREATE FUNCTION public.application_settings_set_valid() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 WITH dest AS (
  SELECT (SELECT value FROM application_settings WHERE key='DISPOSITION_CLASSIFICATION_SCHEME_ID') AS scheme
 ), auth AS (
  SELECT (SELECT value FROM application_settings WHERE key='SMTP_AUTH_ENABLED') AS enabled,
   (SELECT value FROM application_settings WHERE key='SMTP_USERNAME') AS username,
   (SELECT protected_secret IS NOT NULL FROM application_settings WHERE key='SMTP_PASSWORD') AS password_set
 )
 SELECT NOT EXISTS(
  SELECT 1 FROM application_settings s LEFT JOIN classifications c ON c.id=s.classification_reference_id
  CROSS JOIN dest WHERE s.classification_reference_id IS NOT NULL AND
   (dest.scheme='null'::jsonb OR NOT c.is_terminal OR c.classification_scheme_id<>(dest.scheme#>>'{}')::bigint)
 ) AND NOT EXISTS(SELECT 1 FROM auth WHERE enabled='true'::jsonb
  AND (username='null'::jsonb OR NOT password_set))

$$;

CREATE FUNCTION public.apply_application_settings(p_changes jsonb, p_reason text, p_migration_id text DEFAULT NULL::text) RETURNS void
    LANGUAGE plpgsql
    AS $_$
DECLARE item jsonb; old_row application_settings%ROWTYPE; submitted text[]; related text[];
 previous_reason text; previous_source text; new_value jsonb; new_secret bytea; group_name text;
BEGIN
 IF NOT user_has_global_privilege(current_user_id(),'app.settings.manage') OR
    NOT EXISTS(SELECT 1 FROM users WHERE id=current_user_id() AND account_type='person' AND status='active') THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_access_denied';
 END IF;
 IF btrim(COALESCE(p_reason,''))='' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_reason_required';
 END IF;
 IF jsonb_typeof(p_changes)<>'array' OR jsonb_array_length(p_changes) NOT BETWEEN 1 AND 51 THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_invalid_update';
 END IF;
 SELECT array_agg(value->>'key' ORDER BY value->>'key') INTO submitted FROM jsonb_array_elements(p_changes);
 IF cardinality(submitted)<>(SELECT count(DISTINCT k) FROM unnest(submitted) k) OR
    EXISTS(SELECT 1 FROM unnest(submitted) k WHERE k IS NULL OR NOT EXISTS(SELECT 1 FROM application_settings WHERE key=k)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_invalid_update';
 END IF;
 FOREACH group_name IN ARRAY ARRAY['destinations','smtp'] LOOP
  related:=CASE group_name WHEN 'destinations' THEN ARRAY['DISPOSITION_CLASSIFICATION_SCHEME_ID','DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID']::text[] ELSE ARRAY['SMTP_AUTH_ENABLED','SMTP_HOST','SMTP_PASSWORD','SMTP_PORT','SMTP_REPLY_TO_EMAIL','SMTP_SECURITY','SMTP_SENDER_EMAIL','SMTP_SENDER_NAME','SMTP_TIMEOUT_SECONDS','SMTP_USERNAME']::text[] END;
  IF submitted&&related AND NOT submitted@>related THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_group_required';
  END IF;
 END LOOP;
 IF p_migration_id IS NOT NULL AND btrim(p_migration_id)='' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_invalid_update';
 END IF;
 -- Stable row lock order shared with concurrent grouped administration/migration.
 PERFORM 1 FROM application_settings WHERE key=ANY(submitted) ORDER BY key FOR UPDATE;
 previous_reason:=current_setting('app.change_reason',true);
 previous_source:=current_setting('app.event_source',true);
 PERFORM set_config('app.change_reason',p_reason,true);
 IF p_migration_id IS NOT NULL THEN PERFORM set_config('app.event_source','migration',true); END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_changes) ORDER BY value->>'key' LOOP
  SELECT * INTO old_row FROM application_settings WHERE key=item->>'key';
  IF p_migration_id IS NOT NULL AND EXISTS(SELECT 1 FROM application_settings_migration_keys
    WHERE migration_id=p_migration_id AND key=old_row.key) THEN CONTINUE; END IF;
  IF NOT COALESCE(jsonb_typeof(item->'expected_version')='number' AND item->>'expected_version' ~ '^[1-9][0-9]*$' AND
     (item->>'expected_version')::numeric=old_row.version,false) THEN
   RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='application_settings_stale_version';
  END IF;
  new_value:=COALESCE(item->'value',old_row.value);
  new_secret:=CASE WHEN item ? 'encrypted_secret' THEN
   CASE WHEN item->>'encrypted_secret' IS NULL THEN NULL ELSE convert_to(item->>'encrypted_secret','UTF8') END
   ELSE old_row.protected_secret END;
  IF old_row.key='SMTP_PASSWORD' AND new_value<>'null'::jsonb THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_setting_value_invalid';
  END IF;
  IF p_migration_id IS NOT NULL AND old_row.provenance<>'default' AND
     (new_value,new_secret) IS DISTINCT FROM (old_row.value,old_row.protected_secret) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_migration_conflict';
  END IF;
  IF (p_migration_id IS NULL AND (item ? 'value' OR item ? 'encrypted_secret')) OR
     (p_migration_id IS NOT NULL AND old_row.provenance='default' AND (item ? 'value' OR item ? 'encrypted_secret')) THEN
   UPDATE application_settings SET value=new_value,protected_secret=new_secret,
    provenance=CASE WHEN p_migration_id IS NULL THEN 'configured' ELSE 'migrated' END WHERE key=old_row.key;
  END IF;
  IF p_migration_id IS NOT NULL THEN
   INSERT INTO application_settings_migration_keys(migration_id,key,completed_by_user_id,resulting_version)
    SELECT p_migration_id,key,current_user_id(),version FROM application_settings WHERE key=old_row.key;
   PERFORM append_domain_event('application_setting',old_row.id,'APPLICATION_SETTINGS_MIGRATION_COMPLETED',
    jsonb_build_object('setting_key',old_row.key,'migration_id',p_migration_id));
  END IF;
 END LOOP;
 IF NOT application_settings_set_valid() THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_group_inconsistent';
 END IF;
 PERFORM set_config('app.change_reason',COALESCE(previous_reason,''),true);
 PERFORM set_config('app.event_source',COALESCE(previous_source,''),true);
END $_$;

CREATE FUNCTION public.assert_aggregation_effectively_open(p_aggregation_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    blocker record;
BEGIN
    IF p_aggregation_id IS NULL THEN
        RETURN;
    END IF;

    -- Lock every ancestor in a stable order. Closing or reparenting an ancestor
    -- must wait for in-flight content changes, and vice versa.
    PERFORM 1
    FROM aggregations AS locked
    WHERE locked.id IN (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_aggregation_id
            FROM aggregations
            WHERE id = p_aggregation_id
            UNION ALL
            SELECT parent.id, parent.parent_aggregation_id
            FROM aggregations AS parent
            JOIN ancestors ON parent.id = ancestors.parent_aggregation_id
        )
        SELECT id FROM ancestors
    )
    ORDER BY locked.id
    FOR SHARE;

    WITH RECURSIVE ancestors AS (
        SELECT id, parent_aggregation_id, aggregation_number, title, date_closed, 0 AS depth
        FROM aggregations
        WHERE id = p_aggregation_id
        UNION ALL
        SELECT parent.id, parent.parent_aggregation_id, parent.aggregation_number,
               parent.title, parent.date_closed, child.depth + 1
        FROM aggregations AS parent
        JOIN ancestors AS child ON parent.id = child.parent_aggregation_id
    )
    SELECT id, aggregation_number, title, date_closed
    INTO blocker
    FROM ancestors
    WHERE date_closed IS NOT NULL
    ORDER BY depth
    LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = format(
                'aggregation %s (%s) is closed by aggregation %s (%s); records and digital content in this subtree are immutable',
                p_aggregation_id,
                (SELECT aggregation_number FROM aggregations WHERE id = p_aggregation_id),
                blocker.id,
                blocker.aggregation_number
            );
    END IF;
END;
$$;

CREATE FUNCTION public.assert_record_effectively_open(p_record_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    aggregation_key bigint;
BEGIN
    SELECT aggregation_id
    INTO aggregation_key
    FROM records
    WHERE id = p_record_id
    FOR SHARE;

    IF aggregation_key IS NOT NULL THEN
        PERFORM assert_aggregation_effectively_open(aggregation_key);
    END IF;
END;
$$;

CREATE FUNCTION public.audit_application_setting() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE safe jsonb; reference_field text;
BEGIN
 safe:=jsonb_build_object('setting_key',NEW.key,'version',NEW.version,'provenance',NEW.provenance);
 IF NEW.key='SMTP_PASSWORD' THEN
  safe:=safe||jsonb_build_object('credential_changed',TG_OP='UPDATE','is_set',NEW.protected_secret IS NOT NULL);
 ELSE
  safe:=safe||jsonb_build_object('new_value',NEW.value,
   'old_value',CASE WHEN TG_OP='UPDATE' THEN OLD.value END);
  reference_field:=CASE
   WHEN NEW.key='DISPOSITION_CLASSIFICATION_SCHEME_ID' THEN 'classification_scheme_id'
   WHEN NEW.key IN ('DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID',
                   'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID') THEN 'classification_id'
  END;
  IF reference_field IS NOT NULL THEN
   -- Persist identities at the change, rather than resolving mutable names
   -- when an administrator later opens the historical event.
   safe:=safe||jsonb_build_object(
    'new_reference',event_reference_identity(reference_field,(NEW.value#>>'{}')::bigint),
    'old_reference',CASE WHEN TG_OP='UPDATE' THEN
     event_reference_identity(reference_field,(OLD.value#>>'{}')::bigint) END);
  END IF;
 END IF;
 PERFORM append_domain_event('application_setting',NEW.id,
  CASE WHEN TG_OP='INSERT' THEN 'APPLICATION_SETTING_SEEDED' ELSE 'APPLICATION_SETTING_CHANGED' END,safe);
 RETURN NEW;
END $$;

CREATE FUNCTION public.bump_digital_component_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['active_content_set_id', 'upload_completed_at'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['active_content_set_id', 'upload_completed_at']) THEN
        NEW.version := OLD.version + 1;
    ELSE
        NEW.version := OLD.version;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.bump_entity_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.check_application_settings_set() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT application_settings_set_valid() THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_group_inconsistent';
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.classification_is_effectively_active(p_classification_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE lineage AS (
        SELECT id, parent_classification_id, date_deactivated
        FROM classifications WHERE id = p_classification_id
        UNION ALL
        SELECT parent.id, parent.parent_classification_id, parent.date_deactivated
        FROM classifications AS parent
        JOIN lineage AS child ON parent.id = child.parent_classification_id
    )
    SELECT EXISTS (SELECT 1 FROM lineage)
       AND NOT EXISTS (SELECT 1 FROM lineage WHERE date_deactivated IS NOT NULL);
$$;

CREATE FUNCTION public.classification_scheme_is_eligible(p_scheme_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(
        date_deactivated IS NULL
        AND date_published IS NOT NULL
        AND date_published <= CURRENT_TIMESTAMP,
        false
    )
    FROM classification_schemes
    WHERE id = p_scheme_id;
$$;

CREATE FUNCTION public.contextual_acl_roles(p_owner bigint, p_principal text) RETURNS TABLE(role_id bigint, org_unit_id bigint)
    LANGUAGE sql STABLE
    AS $$
 WITH RECURSIVE chain AS (
  SELECT id,parent_org_unit_id,managing_role_id,file_administrator_role_id,0 AS depth
   FROM org_units WHERE id=p_owner
  UNION ALL
  SELECT parent.id,parent.parent_org_unit_id,parent.managing_role_id,parent.file_administrator_role_id,child.depth+1
   FROM org_units parent JOIN chain child ON parent.id=child.parent_org_unit_id
 ), selected AS (
  SELECT managing_role_id AS role_id,id AS org_unit_id FROM chain
   WHERE p_principal='owning_and_higher_level_unit_managers'
  UNION ALL
  SELECT file_administrator_role_id,id FROM
   (SELECT * FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1) nearest
   WHERE p_principal='effective_file_administrator'
 )
 SELECT selected.role_id,selected.org_unit_id FROM selected JOIN roles role ON role.id=selected.role_id
 WHERE role.org_unit_id=selected.org_unit_id AND NOT role.is_system
   AND role.account_type_restriction IS DISTINCT FROM 'service' AND role_effectively_active(role.id)
$$;

CREATE FUNCTION public.current_hold_actor_is_manager(p_hold_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT EXISTS(
        SELECT 1
        FROM holds hold
        JOIN users actor
          ON actor.id=NULLIF(current_setting('app.user_id',true),'')::bigint
        WHERE hold.id=p_hold_id
          AND actor.account_type='person'
          AND actor.date_deactivated IS NULL
          AND actor.date_suspended IS NULL
          AND (
              user_has_global_privilege(actor.id,'holds.administer')
              OR user_has_global_privilege(actor.id,'holds.held_items.manage_all')
              OR hold.owner_user_id=actor.id
              OR EXISTS (
                  SELECT 1
                  FROM hold_contributors contributor
                  WHERE contributor.hold_id=hold.id
                    AND contributor.user_id=actor.id
              )
          )
    )
$$;

CREATE FUNCTION public.current_user_can_aggregation_operation(bigint, text, text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $_$
  SELECT current_user_id() IS NOT NULL
     AND user_can_aggregation_operation(current_user_id(),$1,$2,$3)
$_$;

CREATE FUNCTION public.current_user_can_list_record_components(p_record_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT current_user_can_view_record(p_record_id)
     AND (user_has_record_permission(current_user_id(),p_record_id,'record.component.list')
          OR EXISTS(SELECT 1 FROM records resource
                    WHERE resource.id=p_record_id
                      AND user_has_governance_clearance(current_user_id(),resource.security_level_id)))
$$;

CREATE FUNCTION public.current_user_can_record_component_operation(p_record_id bigint, p_privilege text, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT current_user_can_view_record(p_record_id)
     AND user_has_global_privilege(current_user_id(),p_privilege)
     AND (user_has_record_permission(current_user_id(),p_record_id,p_permission)
          OR EXISTS(SELECT 1 FROM records resource
                    WHERE resource.id=p_record_id
                      AND user_has_governance_clearance(current_user_id(),resource.security_level_id)))
$$;

CREATE FUNCTION public.current_user_can_record_operation(bigint, text, text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $_$
  SELECT current_user_id() IS NOT NULL
     AND user_can_record_operation(current_user_id(),$1,$2,$3)
$_$;

CREATE FUNCTION public.current_user_can_view_aggregation(p_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT current_user_id() IS NOT NULL AND user_can_view_aggregation(current_user_id(),p_id)
$$;

CREATE FUNCTION public.current_user_can_view_event_resource(p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $_$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
DECLARE proposal_data jsonb;
BEGIN
 IF p_entity_type IN ('aggregation','record') AND EXISTS(SELECT 1 FROM disposition_retained_records WHERE resource_kind=p_entity_type AND resource_id=p_entity_id) THEN RETURN disposition_private.retained_access(p_entity_type,p_entity_id,true) OR disposition_private.retained_access(p_entity_type,p_entity_id,false); END IF;

 IF p_entity_type='aggregation' AND p_after ? 'recovery_job_id' THEN
  IF NOT disposition_private.recovery_unit_visible(p_entity_id) THEN RETURN false; END IF;
  IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=(p_after->>'certificate_document_id')::bigint AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)) THEN RETURN false; END IF;
 END IF;
 IF p_entity_type='disposition_job' AND COALESCE(p_after,p_before) ? 'certificate_document_id' AND NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=(COALESCE(p_after,p_before)->>'certificate_document_id')::bigint AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)) THEN RETURN false; END IF;
  IF p_entity_type='disposition_job' AND COALESCE(p_after,p_before) ? 'request_document_id' THEN
    IF EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id IN (
      (COALESCE(p_after,p_before)->>'request_document_id')::bigint,
      (COALESCE(p_after,p_before)->>'approval_letter_document_id')::bigint,
      (COALESCE(p_after,p_before)->>'rejection_letter_document_id')::bigint)
      AND (NOT current_user_can_view_record(d.record_id) OR NOT current_user_can_list_record_components(d.record_id))) THEN RETURN false; END IF;
  END IF;

  IF p_entity_type='disposition_review_proposal' THEN
   SELECT job_id INTO disposition_job FROM disposition_review_proposals WHERE id=p_entity_id;
   RETURN disposition_job IS NOT NULL AND disposition_private.proposal_visible(p_before) AND disposition_private.proposal_visible(p_after)
    AND current_user_can_view_event_resource('disposition_job',disposition_job,NULL,NULL);
  ELSIF p_entity_type='disposition_review_note' THEN
   SELECT job_id INTO disposition_job FROM disposition_review_notes WHERE id=p_entity_id;
   RETURN disposition_job IS NOT NULL AND current_user_can_view_event_resource('disposition_job',disposition_job,NULL,NULL);
  END IF;
  FOR proposal_data IN SELECT value FROM jsonb_array_elements(COALESCE(p_before->'proposal_snapshot','[]')) UNION ALL SELECT value FROM jsonb_array_elements(COALESCE(p_after->'proposal_snapshot','[]')) LOOP
   IF NOT disposition_private.proposal_visible(proposal_data) THEN RETURN false; END IF;
  END LOOP;
  IF p_entity_type IN ('disposition_job','disposition_job_membership','disposition_task','disposition_review_round','disposition_review_decision','disposition_job_document') THEN
    CASE p_entity_type
    WHEN 'disposition_job' THEN disposition_job:=p_entity_id;
    WHEN 'disposition_job_membership' THEN SELECT job_id INTO disposition_job FROM disposition_job_memberships WHERE id=p_entity_id;
    WHEN 'disposition_task' THEN SELECT job_id INTO disposition_job FROM disposition_tasks WHERE id=p_entity_id;
    WHEN 'disposition_review_round' THEN SELECT job_id INTO disposition_job FROM disposition_review_rounds WHERE id=p_entity_id;
    WHEN 'disposition_review_decision' THEN SELECT job_id INTO disposition_job FROM disposition_review_decisions WHERE id=p_entity_id;
    WHEN 'disposition_job_document' THEN
      SELECT job_id,d.record_id INTO disposition_job,record_id FROM disposition_job_documents d WHERE id=p_entity_id;
      IF record_id IS NOT NULL AND NOT current_user_can_view_record(record_id) THEN RETURN false; END IF;
      IF EXISTS(SELECT 1 FROM disposition_job_documents d JOIN disposition_job_documents previous ON previous.id=d.supersedes_document_id
        WHERE d.id=p_entity_id AND NOT current_user_can_view_record(previous.record_id)) THEN RETURN false; END IF;
    END CASE;
    IF disposition_job IS NULL OR NOT EXISTS(SELECT 1 FROM disposition_jobs WHERE id=disposition_job) THEN RETURN false; END IF;
    -- Historical snapshots may identify former members and their descendants.
    -- Apply existing whole-event redaction if any protected resource is hidden.
    RETURN NOT EXISTS(SELECT 1 FROM disposition_job_memberships m
      CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
      WHERE m.job_id=disposition_job AND (NOT disposition_private.history_resource_access(current_user_id(),'aggregation',unit.id)
        OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=unit.id AND NOT disposition_private.history_resource_access(current_user_id(),'record',r.id))));
  END IF;
  IF p_entity_type IN ('aggregation_relationship','record_relationship') THEN
    IF p_entity_type='aggregation_relationship' THEN
      RETURN current_user_can_view_aggregation((COALESCE(p_after,p_before)->>'source_id')::bigint)
         AND current_user_can_view_aggregation((COALESCE(p_after,p_before)->>'target_id')::bigint);
    END IF;
    RETURN current_user_can_view_record((COALESCE(p_after,p_before)->>'source_id')::bigint)
       AND current_user_can_view_record((COALESCE(p_after,p_before)->>'target_id')::bigint);
  END IF;
  IF p_entity_type='aggregation' THEN
    IF EXISTS (SELECT 1 FROM aggregations WHERE id=p_entity_id) THEN
      RETURN current_user_can_view_aggregation(p_entity_id);
    END IF;
    historical_level_id := COALESCE(
      CASE WHEN (p_before->>'security_level_id') ~ '^[0-9]+$' THEN (p_before->>'security_level_id')::bigint END,
      CASE WHEN (p_after->>'security_level_id') ~ '^[0-9]+$' THEN (p_after->>'security_level_id')::bigint END
    );
  ELSIF p_entity_type='record' THEN
    IF EXISTS (SELECT 1 FROM records WHERE id=p_entity_id) THEN
      RETURN current_user_can_view_record(p_entity_id);
    END IF;
    historical_level_id := COALESCE(
      CASE WHEN (p_before->>'security_level_id') ~ '^[0-9]+$' THEN (p_before->>'security_level_id')::bigint END,
      CASE WHEN (p_after->>'security_level_id') ~ '^[0-9]+$' THEN (p_after->>'security_level_id')::bigint END
    );
  ELSIF p_entity_type IN ('digital_component','record_component') THEN
    SELECT component.record_id INTO record_id FROM digital_components component WHERE component.id=p_entity_id;
    IF record_id IS NULL THEN
      record_id := COALESCE(
        CASE WHEN (p_after->>'record_id') ~ '^[0-9]+$' THEN (p_after->>'record_id')::bigint END,
        CASE WHEN (p_before->>'record_id') ~ '^[0-9]+$' THEN (p_before->>'record_id')::bigint END
      );
    END IF;
    RETURN record_id IS NOT NULL AND (current_user_can_view_record(record_id) OR disposition_private.retained_access('record',record_id,true) OR disposition_private.retained_access('record',record_id,false));
  ELSE
    RETURN true;
  END IF;
  IF historical_level_id IS NOT NULL THEN
    RETURN user_has_global_privilege(current_user_id(),'audit.view') AND EXISTS (
      SELECT 1 FROM user_role_assignments assignment
      JOIN roles role ON role.id=assignment.role_id
      JOIN security_levels role_level ON role_level.id=role.security_level_id
      JOIN security_levels required ON required.id=historical_level_id
      WHERE assignment.user_id=current_user_id()
        AND assignment.valid_from<=CURRENT_TIMESTAMP
        AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
        AND role_effectively_active(role.id)
        AND role_level.level_number>=required.level_number
    );
  END IF;
  RETURN false;
END $_$;

CREATE FUNCTION public.current_user_can_view_record(p_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT current_user_id() IS NOT NULL AND user_can_view_record(current_user_id(),p_id)
$$;

CREATE FUNCTION public.current_user_id() RETURNS bigint
    LANGUAGE sql STABLE
    AS $$
  SELECT NULLIF(current_setting('app.user_id',true),'')::bigint
$$;

CREATE FUNCTION public.current_user_owns_open_draft(p_draft_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT current_user_id() IS NOT NULL AND EXISTS(
    SELECT 1 FROM record_drafts draft
    JOIN users owner ON owner.id=draft.owner_user_id
    WHERE draft.id=p_draft_id AND draft.owner_user_id=current_user_id()
      AND draft.expires_at>CURRENT_TIMESTAMP
      AND owner.status='active')
$$;

CREATE FUNCTION public.default_entity_security_level() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.security_level_id IS NOT NULL THEN RETURN NEW; END IF;
    IF TG_TABLE_NAME = 'aggregations'
       AND NULLIF(to_jsonb(NEW)->>'parent_aggregation_id', '') IS NOT NULL THEN
        SELECT security_level_id INTO NEW.security_level_id
        FROM aggregations
        WHERE id = (to_jsonb(NEW)->>'parent_aggregation_id')::bigint;
    END IF;
    NEW.security_level_id := COALESCE(NEW.security_level_id, lowest_security_level_id());
    IF NEW.security_level_id IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='no security level is configured';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.default_role_profile() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.profile_id IS NULL THEN
        SELECT id INTO NEW.profile_id FROM profiles WHERE code='ALL_PRIVS';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.delete_unused_classification_scheme() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    deleted_count integer;
BEGIN
    IF OLD.date_published IS NOT NULL THEN
        RAISE EXCEPTION 'published classification schemes must be unpublished before deletion';
    END IF;
    IF OLD.date_first_used IS NOT NULL THEN
        RAISE EXCEPTION 'a classification scheme that has governed an aggregation cannot be deleted';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM aggregations AS a
        JOIN classifications AS c ON c.id = a.classification_id
        WHERE c.classification_scheme_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'classification scheme has classifications assigned to aggregations';
    END IF;

    LOOP
        DELETE FROM classifications AS candidate
        WHERE candidate.classification_scheme_id = OLD.id
          AND NOT EXISTS (
              SELECT 1 FROM classifications AS child
              WHERE child.parent_classification_id = candidate.id
          );
        GET DIAGNOSTICS deleted_count = ROW_COUNT;
        EXIT WHEN deleted_count = 0;
    END LOOP;

    IF EXISTS (SELECT 1 FROM classifications WHERE classification_scheme_id = OLD.id) THEN
        RAISE EXCEPTION 'classification scheme hierarchy could not be deleted safely';
    END IF;
    RETURN OLD;
END;
$$;

CREATE FUNCTION public.effective_classification_retention_rule(p_classification_id bigint) RETURNS TABLE(rule_id bigint, defined_by_classification_id bigint, inheritance_depth integer, current_period_years integer, intermediate_period_years integer, final_disposition text, instructions text)
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE ancestors AS (
        SELECT c.id, c.parent_classification_id, 0 AS depth
        FROM classifications AS c
        WHERE c.id = p_classification_id
        UNION ALL
        SELECT parent.id, parent.parent_classification_id, child.depth + 1
        FROM classifications AS parent
        JOIN ancestors AS child ON parent.id = child.parent_classification_id
    )
    SELECT rule.id, rule.classification_id, ancestors.depth,
           rule.current_period_years, rule.intermediate_period_years,
           rule.final_disposition, rule.instructions
    FROM ancestors
    JOIN classification_retention_rules AS rule
      ON rule.classification_id = ancestors.id
    ORDER BY ancestors.depth
    LIMIT 1;
$$;

CREATE FUNCTION public.effective_holds_for_aggregation(p_aggregation_id bigint, p_at_time timestamp with time zone DEFAULT statement_timestamp()) RETURNS TABLE(hold_id bigint, code text, name text, preserve_resource_state boolean, is_direct boolean, is_inherited boolean, nearest_assigned_aggregation_id bigint)
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE ancestry AS (
        SELECT aggregation.id,aggregation.parent_aggregation_id,0 AS depth
        FROM aggregations aggregation WHERE aggregation.id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,child.depth+1
        FROM aggregations parent JOIN ancestry child ON child.parent_aggregation_id=parent.id
    ), matched AS (
        SELECT assignment.hold_id,ancestry.id AS assigned_aggregation_id,ancestry.depth
        FROM ancestry
        JOIN hold_aggregation_assignments assignment ON assignment.aggregation_id=ancestry.id
    )
    SELECT hold.id,hold.code,hold.name,hold.preserve_resource_state,
           bool_or(matched.depth=0),bool_or(matched.depth>0),
           (array_agg(matched.assigned_aggregation_id ORDER BY matched.depth))[1]
    FROM matched JOIN holds hold ON hold.id=matched.hold_id
    WHERE hold.valid_from<=p_at_time AND (hold.valid_to IS NULL OR p_at_time<hold.valid_to)
    GROUP BY hold.id,hold.code,hold.name,hold.preserve_resource_state
$$;

CREATE FUNCTION public.effective_holds_for_record(p_record_id bigint, p_at_time timestamp with time zone DEFAULT statement_timestamp()) RETURNS TABLE(hold_id bigint, code text, name text, preserve_resource_state boolean, is_direct boolean, is_inherited boolean, nearest_assigned_aggregation_id bigint)
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE record_row AS (
        SELECT id,aggregation_id FROM records WHERE id=p_record_id
    ), ancestry AS (
        SELECT aggregation.id,aggregation.parent_aggregation_id,0 AS depth
        FROM aggregations aggregation JOIN record_row ON record_row.aggregation_id=aggregation.id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,child.depth+1
        FROM aggregations parent JOIN ancestry child ON child.parent_aggregation_id=parent.id
    ), matched AS (
        SELECT assignment.hold_id,true AS direct,false AS inherited,
               NULL::bigint AS assigned_aggregation_id,NULL::integer AS depth
        FROM record_row JOIN hold_record_assignments assignment ON assignment.record_id=record_row.id
        UNION ALL
        SELECT assignment.hold_id,false,true,ancestry.id,ancestry.depth
        FROM ancestry
        JOIN hold_aggregation_assignments assignment ON assignment.aggregation_id=ancestry.id
    )
    SELECT hold.id,hold.code,hold.name,hold.preserve_resource_state,
           bool_or(matched.direct),bool_or(matched.inherited),
           (array_agg(matched.assigned_aggregation_id ORDER BY matched.depth NULLS LAST)
             FILTER (WHERE matched.assigned_aggregation_id IS NOT NULL))[1]
    FROM matched JOIN holds hold ON hold.id=matched.hold_id
    WHERE hold.valid_from<=p_at_time AND (hold.valid_to IS NULL OR p_at_time<hold.valid_to)
    GROUP BY hold.id,hold.code,hold.name,hold.preserve_resource_state
$$;

CREATE FUNCTION public.enforce_aggregation_medium_hierarchy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.parent_aggregation_id IS NOT NULL THEN
        SELECT medium INTO parent_medium FROM aggregations
         WHERE id=NEW.parent_aggregation_id FOR UPDATE;
        IF parent_medium IS NULL OR NEW.medium IS DISTINCT FROM parent_medium THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='aggregation_medium_mismatch',
                MESSAGE='aggregation_medium_mismatch: a child aggregation must use its parent medium';
        END IF;
    END IF;
    IF TG_OP='UPDATE' AND NEW.medium IS DISTINCT FROM OLD.medium AND (
        EXISTS (SELECT 1 FROM aggregations WHERE parent_aggregation_id=OLD.id)
        OR EXISTS (SELECT 1 FROM records WHERE aggregation_id=OLD.id)) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='medium_change_requires_empty_aggregation',
            MESSAGE='medium_change_requires_empty_aggregation: an aggregation must be empty before changing medium';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_aggregation_ownership() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    parent_owner bigint;
    target_owner bigint;
    confirmed boolean := COALESCE(NULLIF(current_setting('app.ownership_move_confirmed', true), '')::boolean, false);
    propagating boolean := current_setting('app.ownership_propagation', true) = 'authorized';
    correcting boolean := current_setting('app.ownership_correction_authorized', true) = 'authorized';
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.parent_aggregation_id IS NOT NULL THEN
            SELECT owning_org_unit_id INTO STRICT parent_owner
            FROM aggregations WHERE id = NEW.parent_aggregation_id FOR UPDATE;
            NEW.owning_org_unit_id := parent_owner;
        ELSIF NEW.owning_org_unit_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='23502', MESSAGE='root aggregation ownership is required';
        END IF;
        RETURN NEW;
    END IF;
    IF propagating THEN RETURN NEW; END IF;

    IF correcting THEN
        IF OLD.parent_aggregation_id IS NOT NULL OR NEW.parent_aggregation_id IS NOT NULL
           OR NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id
           OR NULLIF(btrim(current_setting('app.change_reason', true)), '') IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='ownership correction is restricted to root aggregations and requires a reason';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.parent_aggregation_id IS NOT DISTINCT FROM OLD.parent_aggregation_id THEN
        IF NEW.owning_org_unit_id IS DISTINCT FROM OLD.owning_org_unit_id THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='owning_org_unit_id cannot be changed directly';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.parent_aggregation_id IS NULL THEN
        target_owner := OLD.owning_org_unit_id;
    ELSE
        SELECT owning_org_unit_id INTO STRICT target_owner
        FROM aggregations WHERE id = NEW.parent_aggregation_id FOR UPDATE;
    END IF;

    IF target_owner IS DISTINCT FROM OLD.owning_org_unit_id AND (
        NOT confirmed OR NULLIF(btrim(current_setting('app.change_reason', true)), '') IS NULL
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='ownership-changing aggregation moves require a reason and explicit confirmation';
    END IF;
    NEW.owning_org_unit_id := target_owner;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_digital_component_record_medium() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE record_medium text;
BEGIN
    SELECT medium INTO record_medium FROM records WHERE id=NEW.record_id FOR UPDATE;
    IF record_medium='physical' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            CONSTRAINT='physical_record_disallows_digital_components',
            MESSAGE='physical_record_disallows_digital_components: physical records cannot have digital components';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_draft_component_record_medium() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE draft_medium text;
BEGIN
    SELECT medium INTO draft_medium FROM record_drafts WHERE id=NEW.draft_id FOR UPDATE;
    IF draft_medium IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='record_medium_required_before_components',
            MESSAGE='record_medium_required_before_components: select a record medium before adding digital components';
    ELSIF draft_medium='physical' THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='physical_record_disallows_digital_components',
            MESSAGE='physical_record_disallows_digital_components: physical record drafts cannot have digital components';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_future_next_review_date() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_of_next_review IS NOT NULL
       AND (TG_OP='INSERT' OR NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review)
       AND NEW.date_of_next_review<=CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='date_of_next_review must be in the future';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_future_review_date() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN IF NEW.date_of_next_review IS NOT NULL AND (TG_OP='INSERT' OR NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review) AND NEW.date_of_next_review <= CURRENT_TIMESTAMP THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='date_of_next_review_must_be_future'; END IF; RETURN NEW; END; $$;

CREATE FUNCTION public.enforce_hold_assignment_policy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE target_hold_id bigint:=CASE WHEN TG_OP='DELETE' THEN OLD.hold_id ELSE NEW.hold_id END;
BEGIN
    PERFORM lock_hold_policy_exclusive();
    IF NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_change_reason_required';
    END IF;
    IF NOT current_hold_actor_is_manager(target_hold_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_manager_required';
    END IF;
    IF TG_OP='INSERT' AND NEW.assigned_by_user_id IS NULL THEN
        NEW.assigned_by_user_id:=NULLIF(current_setting('app.user_id',true),'')::bigint;
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.enforce_hold_change_reason() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE hold_created_in_transaction boolean:=false;
BEGIN
    PERFORM lock_hold_policy_exclusive();
    IF TG_TABLE_NAME='hold_contributors' AND TG_OP='DELETE' AND pg_trigger_depth()>1 THEN
        RETURN OLD;
    END IF;
    IF TG_TABLE_NAME='hold_contributors' AND TG_OP='INSERT' THEN
        SELECT xmin::text=pg_current_xact_id()::text INTO hold_created_in_transaction
        FROM holds WHERE id=NEW.hold_id;
    END IF;
    IF NOT hold_created_in_transaction
       AND NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_change_reason_required';
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.enforce_one_enabled_default_language() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF (SELECT count(*) FROM supported_languages WHERE is_default AND is_enabled) <> 1 THEN
        RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='exactly_one_enabled_default_language_required';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION public.enforce_record_draft_medium_hierarchy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
    SELECT medium INTO parent_medium FROM aggregations WHERE id=NEW.aggregation_id FOR UPDATE;
    IF NEW.medium IS NULL THEN
        NEW.medium:=parent_medium;
    ELSIF parent_medium IS NULL OR (parent_medium<>'mixed' AND NEW.medium IS DISTINCT FROM parent_medium) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='record_medium_not_allowed_by_parent',
            MESSAGE='record_medium_not_allowed_by_parent: draft medium is incompatible with its parent aggregation';
    END IF;
    IF NEW.medium='physical' AND (TG_OP='INSERT' OR OLD.medium IS DISTINCT FROM NEW.medium)
       AND EXISTS (SELECT 1 FROM record_draft_components WHERE draft_id=NEW.id) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='physical_record_has_staged_components',
            MESSAGE='physical_record_has_staged_components: remove staged components before changing the draft medium';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_record_medium_hierarchy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
    SELECT medium INTO parent_medium FROM aggregations WHERE id=NEW.aggregation_id FOR UPDATE;
    IF parent_medium IS NULL OR (parent_medium<>'mixed' AND NEW.medium IS DISTINCT FROM parent_medium) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='record_medium_not_allowed_by_parent',
            MESSAGE='record_medium_not_allowed_by_parent: record medium is incompatible with its parent aggregation';
    END IF;
    IF TG_OP='UPDATE' AND NEW.medium='physical' AND NEW.medium IS DISTINCT FROM OLD.medium
       AND EXISTS (SELECT 1 FROM digital_components WHERE record_id=OLD.id) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='physical_record_has_digital_components',
            MESSAGE='physical_record_has_digital_components: a record with digital components cannot become physical';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_record_ownership() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_owner bigint;
    confirmed boolean := COALESCE(NULLIF(current_setting('app.ownership_move_confirmed', true), '')::boolean, false);
    propagating boolean := current_setting('app.ownership_propagation', true) = 'authorized';
BEGIN
    IF TG_OP = 'UPDATE' AND propagating THEN RETURN NEW; END IF;
    IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
    SELECT owning_org_unit_id INTO STRICT target_owner
    FROM aggregations WHERE id = NEW.aggregation_id FOR UPDATE;
    IF TG_OP = 'INSERT' THEN
        NEW.owning_org_unit_id := target_owner;
        RETURN NEW;
    END IF;
    IF NEW.aggregation_id IS NOT DISTINCT FROM OLD.aggregation_id THEN
        IF NEW.owning_org_unit_id IS DISTINCT FROM OLD.owning_org_unit_id THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='owning_org_unit_id cannot be changed directly';
        END IF;
        RETURN NEW;
    END IF;
    IF target_owner IS DISTINCT FROM OLD.owning_org_unit_id AND (
        NOT confirmed OR NULLIF(btrim(current_setting('app.change_reason', true)), '') IS NULL
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='ownership-changing record moves require a reason and explicit confirmation';
    END IF;
    NEW.owning_org_unit_id := target_owner;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_resource_security_hierarchy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    resource_level integer;
    parent_level integer;
    child_max integer;
BEGIN
    SELECT level_number INTO STRICT resource_level
    FROM security_levels WHERE id = NEW.security_level_id;
    IF TG_TABLE_NAME = 'records' THEN
        IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
        SELECT level.level_number INTO parent_level
        FROM aggregations parent JOIN security_levels level ON level.id=parent.security_level_id
        WHERE parent.id=NEW.aggregation_id;
        IF parent_level IS NULL THEN RETURN NEW; END IF;
        IF parent_level < resource_level THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
                DETAIL=format('record level %s exceeds parent aggregation level %s',resource_level,parent_level);
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.parent_aggregation_id IS NOT NULL THEN
        SELECT level.level_number INTO parent_level
        FROM aggregations parent JOIN security_levels level ON level.id=parent.security_level_id
        WHERE parent.id=NEW.parent_aggregation_id;
        IF parent_level IS NULL THEN RETURN NEW; END IF;
        IF parent_level < resource_level THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
                DETAIL=format('aggregation level %s exceeds parent aggregation level %s',resource_level,parent_level);
        END IF;
    END IF;
    SELECT max(level_number) INTO child_max FROM (
        SELECT level.level_number FROM aggregations child
        JOIN security_levels level ON level.id=child.security_level_id
        WHERE child.parent_aggregation_id=NEW.id
        UNION ALL
        SELECT level.level_number FROM records child
        JOIN security_levels level ON level.id=child.security_level_id
        WHERE child.aggregation_id=NEW.id
    ) children;
    IF child_max IS NOT NULL AND resource_level < child_max THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
            DETAIL=format('aggregation level %s is below contained resource level %s',resource_level,child_max);
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.enforce_saved_search_change_reason() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='saved_search_change_reason_required';
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.enforce_security_level_catalogue_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.level_number IS DISTINCT FROM OLD.level_number AND EXISTS (
        SELECT 1 FROM aggregations child
        JOIN aggregations parent ON parent.id=child.parent_aggregation_id
        JOIN security_levels child_level ON child_level.id=child.security_level_id
        JOIN security_levels parent_level ON parent_level.id=parent.security_level_id
        WHERE (CASE WHEN parent_level.id=NEW.id THEN NEW.level_number ELSE parent_level.level_number END)
            < (CASE WHEN child_level.id=NEW.id THEN NEW.level_number ELSE child_level.level_number END)
        UNION ALL
        SELECT 1 FROM records child
        JOIN aggregations parent ON parent.id=child.aggregation_id
        JOIN security_levels child_level ON child_level.id=child.security_level_id
        JOIN security_levels parent_level ON parent_level.id=parent.security_level_id
        WHERE (CASE WHEN parent_level.id=NEW.id THEN NEW.level_number ELSE parent_level.level_number END)
            < (CASE WHEN child_level.id=NEW.id THEN NEW.level_number ELSE child_level.level_number END)
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
            DETAIL='changing this catalogue number would invalidate a resource hierarchy';
    END IF;
    NEW.date_updated := CURRENT_TIMESTAMP;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.event_entity_identity_snapshot(event_entity_type text, event_entity_id bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    snapshot jsonb;
BEGIN
    CASE event_entity_type
        WHEN 'aggregation' THEN
            SELECT jsonb_build_object('id', id, 'code', aggregation_number, 'title', title)
            INTO snapshot FROM aggregations WHERE id = event_entity_id;
        WHEN 'record' THEN
            SELECT jsonb_build_object('id', id, 'code', record_number, 'title', title)
            INTO snapshot FROM records WHERE id = event_entity_id;
        WHEN 'digital_component' THEN
            SELECT jsonb_build_object('id', id, 'name', file_name)
            INTO snapshot FROM digital_components WHERE id = event_entity_id;
        WHEN 'classification_scheme' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'title', title)
            INTO snapshot FROM classification_schemes WHERE id = event_entity_id;
        WHEN 'classification' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'title', title)
            INTO snapshot FROM classifications WHERE id = event_entity_id;
        WHEN 'org_unit' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM org_units WHERE id = event_entity_id;
        WHEN 'role' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM roles WHERE id = event_entity_id;
        WHEN 'user' THEN
            SELECT jsonb_build_object('id', id, 'name', name, 'email', email)
            INTO snapshot FROM users WHERE id = event_entity_id;
        WHEN 'profile' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM profiles WHERE id = event_entity_id;
        WHEN 'security_level' THEN
            SELECT jsonb_build_object(
                'id', id, 'code', code, 'name', name, 'level_number', level_number
            ) INTO snapshot FROM security_levels WHERE id = event_entity_id;
        ELSE
            snapshot := NULL;
    END CASE;
    RETURN snapshot;
END;
$$;

CREATE FUNCTION public.event_reference_identity(reference_field text, reference_id bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE snapshot jsonb;
DECLARE existing_snapshots jsonb;
BEGIN
    CASE reference_field
        WHEN 'profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'old_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'new_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'security_level_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name,'level_number',level_number) INTO snapshot FROM security_levels WHERE id=reference_id;
        WHEN 'classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'parent_classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'classification_scheme_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classification_schemes WHERE id=reference_id;
        WHEN 'aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'parent_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'destination_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'record_id' THEN SELECT jsonb_build_object('id',id,'code',record_number,'title',title) INTO snapshot FROM records WHERE id=reference_id;
        WHEN 'role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'managing_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'file_administrator_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'supervisor_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'owner_user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'parent_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'owning_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        ELSE snapshot := NULL;
    END CASE;
    RETURN snapshot;
END;
$$;

CREATE FUNCTION public.event_state_reference_snapshots(event_state jsonb) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE reference_field text; reference_value text; snapshot jsonb; snapshots jsonb := '{}'::jsonb;
BEGIN
    IF event_state IS NULL OR jsonb_typeof(event_state) <> 'object' THEN RETURN snapshots; END IF;
    FOREACH reference_field IN ARRAY ARRAY[
        'profile_id','old_profile_id','new_profile_id','security_level_id',
        'classification_id','parent_classification_id','classification_scheme_id',
        'aggregation_id','parent_aggregation_id','destination_aggregation_id',
        'record_id','role_id','supervisor_role_id','user_id','owner_user_id',
        'org_unit_id','parent_org_unit_id','owning_org_unit_id'
    ] LOOP
        reference_value := event_state ->> reference_field;
        IF reference_value IS NOT NULL AND reference_value ~ '^[0-9]+$' THEN
            snapshot := event_reference_identity(reference_field,reference_value::bigint);
            IF snapshot IS NOT NULL THEN snapshots := snapshots || jsonb_build_object(reference_field,snapshot); END IF;
        END IF;
    END LOOP;
    RETURN snapshots;
END;
$_$;

CREATE FUNCTION public.guard_application_setting() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE installer boolean;
BEGIN
 installer := current_user_id() IS NULL AND
  COALESCE(current_setting('app.event_source',true),'') IN ('seeding','migration');
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_protected';
 END IF;
 IF TG_OP='INSERT' AND NOT installer THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_protected';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF NOT user_has_global_privilege(current_user_id(),'app.settings.manage') OR
     NOT EXISTS(SELECT 1 FROM users WHERE id=current_user_id() AND account_type='person' AND status='active') THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_access_denied';
  END IF;
  IF btrim(COALESCE(current_setting('app.change_reason',true),''))='' THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_reason_required';
  END IF;
  IF (NEW.id,NEW.key) IS DISTINCT FROM (OLD.id,OLD.key) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_identity_immutable';
  END IF;
  NEW.version:=OLD.version+1;
  NEW.date_updated:=CURRENT_TIMESTAMP;
  NEW.updated_by_user_id:=current_user_id();
  IF NEW.provenance='default' THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_provenance_invalid';
  END IF;
 END IF;
 IF NOT application_setting_value_valid(NEW.key,NEW.value,NEW.protected_secret) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_setting_value_invalid';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.guard_relationship_type() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT user_has_global_privilege(current_user_id(),'relationships.administer')
    AND COALESCE(current_setting('app.event_source',true),'') NOT IN ('seeding','migration') THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationships_administer_required';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.resource_kind,NEW.code,NEW.is_symmetric)
     IS DISTINCT FROM (OLD.resource_kind,OLD.code,OLD.is_symmetric) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_type_identity_immutable';
 END IF;
 IF TG_OP<>'DELETE' THEN
  IF NOT COALESCE(jsonb_typeof(NEW.translations->'ar')='object',false)
     OR NOT COALESCE(jsonb_typeof(NEW.translations->'ar'->'forward_name')='string',false)
     OR NOT COALESCE(jsonb_typeof(NEW.translations->'ar'->'reverse_name')='string',false)
     OR btrim(NEW.translations->'ar'->>'forward_name')=''
     OR btrim(NEW.translations->'ar'->>'reverse_name')=''
     OR (NEW.is_symmetric AND NEW.translations->'ar'->>'forward_name'
                             IS DISTINCT FROM NEW.translations->'ar'->>'reverse_name') THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_arabic_labels_required';
  END IF;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE FUNCTION public.guard_resource_relationship() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE item record; definition relationship_types; kind text;
BEGIN
 kind:=TG_ARGV[0];
 -- A parent resource deletion is authorized by its own existing deletion path.
 -- Permit only genuine FK cascades; explicit unlinking still requires both endpoints.
 IF TG_OP='DELETE' AND pg_trigger_depth()>1 THEN
  IF (kind='aggregation' AND (NOT EXISTS(SELECT 1 FROM aggregations WHERE id=OLD.source_id)
                             OR NOT EXISTS(SELECT 1 FROM aggregations WHERE id=OLD.target_id)))
     OR (kind='record' AND (NOT EXISTS(SELECT 1 FROM records WHERE id=OLD.source_id)
                           OR NOT EXISTS(SELECT 1 FROM records WHERE id=OLD.target_id))) THEN
   RETURN OLD;
  END IF;
 END IF;
 IF TG_OP='UPDATE' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_immutable_remove_and_recreate';
 END IF;
 IF NOT user_has_global_privilege(current_user_id(),'relationships.link') THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationships_link_required';
 END IF;
 item:=CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
 SELECT * INTO definition FROM relationship_types WHERE id=item.relationship_type_id FOR SHARE;
 IF definition.resource_kind IS DISTINCT FROM kind THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_type_scope_mismatch';
 END IF;
 IF TG_OP='INSERT' AND NOT definition.is_active THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_type_inactive';
 END IF;
 IF kind='aggregation' THEN
  PERFORM id FROM aggregations WHERE id IN (item.source_id,item.target_id) ORDER BY id FOR SHARE;
  IF NOT current_user_can_view_aggregation(item.source_id) OR NOT current_user_can_view_aggregation(item.target_id) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationship_endpoint_access_required';
  END IF;
 ELSE
  PERFORM id FROM records WHERE id IN (item.source_id,item.target_id) ORDER BY id FOR SHARE;
  IF NOT current_user_can_view_record(item.source_id) OR NOT current_user_can_view_record(item.target_id) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationship_endpoint_access_required';
  END IF;
 END IF;
 IF TG_OP='INSERT' AND definition.is_symmetric AND NEW.source_id>NEW.target_id THEN
  NEW.source_id:=item.target_id; NEW.target_id:=item.source_id;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE FUNCTION public.guard_settings_migration_completion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP<>'INSERT' OR NOT user_has_global_privilege(current_user_id(),'app.settings.manage') OR
    btrim(COALESCE(current_setting('app.change_reason',true),''))='' OR
    NEW.completed_by_user_id<>current_user_id() OR
    NEW.resulting_version<>(SELECT version FROM application_settings WHERE key=NEW.key) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_completion_protected';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.hold_is_effective(p_hold_id bigint, p_at_time timestamp with time zone DEFAULT statement_timestamp()) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(
        (hold.valid_from<=p_at_time AND (hold.valid_to IS NULL OR p_at_time<hold.valid_to)),
        false
    ) FROM holds hold WHERE hold.id=p_hold_id
$$;

CREATE FUNCTION public.initialize_resource_acls() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE creator_role_id bigint := NULLIF(current_setting('app.creator_acl_role_id',true),'')::bigint;
  acl_scope record;
BEGIN
  IF creator_role_id IS NULL THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='aggregations' THEN
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.history.view']);
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  ELSE
    INSERT INTO record_acl_grants(record_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  END IF;
  FOR acl_scope IN SELECT * FROM (VALUES
    ('aggregation_acl_grants','aggregation_id','aggregation'),
    ('aggregation_child_aggregation_acl_defaults','aggregation_id','aggregation'),
    ('aggregation_child_record_acl_defaults','aggregation_id','record'),
    ('record_acl_grants','record_id','record')) AS scopes(table_name,owner_column,resource_type)
  LOOP
    IF (TG_TABLE_NAME='aggregations' AND acl_scope.table_name<>'record_acl_grants')
      OR (TG_TABLE_NAME='records' AND acl_scope.table_name='record_acl_grants') THEN
      EXECUTE format('INSERT INTO %I(%I,principal_type,permission_id)
        SELECT $1,principal,id FROM permissions CROSS JOIN
        (VALUES (''owning_and_higher_level_unit_managers''),(''effective_file_administrator'')) AS principals(principal)
        WHERE code=ANY(CASE WHEN principal=''owning_and_higher_level_unit_managers'' THEN $2 ELSE $3 END)',acl_scope.table_name,acl_scope.owner_column)
      USING NEW.id,
        CASE WHEN acl_scope.resource_type='aggregation' THEN ARRAY['aggregation.view','aggregation.history.view']
          ELSE ARRAY['record.view','record.component.list','record.component.view','record.component.download'] END,
        CASE WHEN acl_scope.resource_type='aggregation' THEN ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.acl.manage','aggregation.history.view']
          ELSE ARRAY['record.view','record.acl.manage','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print'] END;
    END IF;
  END LOOP;
  RETURN NEW;
END $_$;

CREATE FUNCTION public.lock_hold_policy_exclusive() RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN PERFORM pg_advisory_xact_lock(7246,1); END;
$$;

CREATE FUNCTION public.lock_hold_policy_shared() RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN PERFORM pg_advisory_xact_lock_shared(7246,1); END;
$$;

CREATE FUNCTION public.lowest_security_level_id() RETURNS bigint
    LANGUAGE sql STABLE
    AS $$
    SELECT id FROM security_levels ORDER BY level_number, id LIMIT 1
$$;

CREATE FUNCTION public.messaging_capture_component_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM message_record_captures WHERE id=NEW.capture_id
      AND xmin::text::bigint=(txid_current()%4294967296)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_already_committed';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_capture_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE keys text[];
BEGIN
 keys:=CASE TG_TABLE_NAME WHEN 'message_record_captures' THEN ARRAY['selected_envelope_id','record_id']
 ELSE ARRAY['envelope_id','digital_component_id'] END;
 IF (to_jsonb(NEW)-keys) IS DISTINCT FROM (to_jsonb(OLD)-keys) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_immutable';
 END IF;
 IF EXISTS(SELECT 1 FROM unnest(keys) k WHERE to_jsonb(NEW)->k IS DISTINCT FROM to_jsonb(OLD)->k
    AND to_jsonb(NEW)->k<>'null'::jsonb) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_reference_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_count_delivery() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 INSERT INTO messaging_operational_metrics(metric,value,observations)
 VALUES('notifications_emitted',1,1) ON CONFLICT(metric,instance_id,producer_code)
 DO UPDATE SET value=messaging_operational_metrics.value+1,observations=messaging_operational_metrics.observations+1,last_observed_at=CURRENT_TIMESTAMP;
 IF NOT (SELECT is_test FROM message_envelopes WHERE id=NEW.envelope_id) THEN
  INSERT INTO messaging_operational_metrics(metric,value,observations) VALUES('fanout_count',1,1)
  ON CONFLICT(metric,instance_id,producer_code) DO UPDATE SET value=messaging_operational_metrics.value+1,observations=messaging_operational_metrics.observations+1,last_observed_at=CURRENT_TIMESTAMP;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_default_level() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NEW.security_level_id IS NULL THEN
  SELECT id INTO NEW.security_level_id FROM security_levels ORDER BY level_number LIMIT 1;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_delivery_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 -- Denormalize only the ordering instant, never message content; this permits
 -- the recipient/sent-time/UUID index to serve Inbox keyset pagination.
 SELECT sent_at INTO NEW.created_at FROM message_envelopes WHERE id=NEW.envelope_id;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_delivery_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['read_at','deleted_at','purge_after','deletion_reason']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['read_at','deleted_at','purge_after','deletion_reason'])
 OR (OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at)
 OR (OLD.purge_after IS NOT NULL AND NEW.purge_after IS DISTINCT FROM OLD.purge_after AND NOT (NEW.purge_after IS NULL AND NEW.deleted_at IS NULL AND EXISTS(SELECT 1 FROM message_envelopes WHERE id=OLD.envelope_id AND expires_at>CURRENT_TIMESTAMP)))
 OR (NEW.deleted_at IS NOT NULL AND NEW.purge_after IS NULL) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_delivery_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_draft_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NEW.id<>OLD.id OR NEW.owner_user_id<>OLD.owner_user_id OR NEW.date_created<>OLD.date_created
 OR NEW.version<>OLD.version+1 THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_draft_version_invalid';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_guard_notification_coverage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE active_id uuid;
BEGIN
 INSERT INTO messaging_notification_configuration_guard(singleton,revision) VALUES (true,1)
 ON CONFLICT(singleton) DO UPDATE SET revision=messaging_notification_configuration_guard.revision+1;
 IF TG_TABLE_NAME='system_notification_producers' THEN
  active_id := NEW.active_configuration_version_id;
  IF active_id IS NULL THEN
   RETURN NEW;
  END IF;
  IF NEW.required_for_business_commit AND NOT EXISTS (
   SELECT 1 FROM system_notification_configuration_versions WHERE id=active_id AND enabled
  ) THEN
   RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='notification_required_cannot_disable';
  END IF;
  IF EXISTS (
   SELECT 1 FROM supported_languages l WHERE (l.is_enabled OR l.language_tag='en')
   AND NOT EXISTS (SELECT 1 FROM system_notification_configuration_translations t
    WHERE t.configuration_version_id=active_id AND t.language_tag=l.language_tag
    AND t.review_status='published' AND t.reviewed_by_user_id IS NOT NULL AND t.reviewed_at IS NOT NULL
    AND btrim(t.subject_template)<>'' AND btrim(t.body_template_rich_text)<>'')
  ) THEN
   RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='notification_language_coverage_required';
  END IF;
 ELSIF NEW.is_enabled AND EXISTS (
  SELECT 1 FROM system_notification_producers p WHERE p.active_configuration_version_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM system_notification_configuration_translations t
   WHERE t.configuration_version_id=p.active_configuration_version_id AND t.language_tag=NEW.language_tag
   AND t.review_status='published' AND t.reviewed_by_user_id IS NOT NULL AND t.reviewed_at IS NOT NULL)
 ) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='notification_language_coverage_required';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_mailbox_envelope_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['sender_deleted_at','sender_purge_after']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['sender_deleted_at','sender_purge_after'])
 OR (OLD.sender_purge_after IS NOT NULL AND NEW.sender_purge_after IS DISTINCT FROM OLD.sender_purge_after AND NOT (NEW.sender_purge_after IS NULL AND NEW.sender_deleted_at IS NULL AND OLD.expires_at>CURRENT_TIMESTAMP))
 OR (NEW.sender_deleted_at IS NOT NULL AND NEW.sender_purge_after IS NULL) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_mailbox_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NEW.user_id<>OLD.user_id OR NEW.last_sequence<>OLD.last_sequence+1 THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_mailbox_sequence_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_notify_delivery() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM pg_notify('wathiq_messages', json_build_object(
        'delivery_id', NEW.id,
        'recipient_user_id', NEW.recipient_user_id,
        'mailbox_sequence', NEW.mailbox_sequence
    )::text);
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.messaging_receipt_purge_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF to_regclass('pg_temp.messaging_purge_members') IS NULL
 OR (to_jsonb(NEW)-'result_purged_at') IS DISTINCT FROM (to_jsonb(OLD)-'result_purged_at')
 OR OLD.result_purged_at IS NOT NULL OR NEW.result_purged_at IS NULL THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_receipt_immutable';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_temp.messaging_purge_members WHERE id=OLD.result_envelope_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_receipt_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_reject_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE envelope uuid; allowed boolean;
BEGIN
 IF TG_OP='DELETE' AND TG_TABLE_NAME=ANY(ARRAY['message_envelopes','message_envelope_localizations',
 'message_recipient_selectors','message_addressees','message_deliveries','message_resource_links',
 'message_action_completions','message_action_amendments']) AND to_regclass('pg_temp.messaging_purge_members') IS NOT NULL THEN
  envelope:=CASE TG_TABLE_NAME WHEN 'message_envelopes' THEN (to_jsonb(OLD)->>'id')::uuid
   WHEN 'message_action_amendments' THEN (to_jsonb(OLD)->>'original_envelope_id')::uuid
   WHEN 'message_action_completions' THEN (to_jsonb(OLD)->>'reply_envelope_id')::uuid
   ELSE (to_jsonb(OLD)->>'envelope_id')::uuid END;
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM pg_temp.messaging_purge_members WHERE id=$1)' INTO allowed USING envelope;
  IF allowed THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_immutable';
END $_$;

CREATE FUNCTION public.messaging_resource_link_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF num_nonnulls(NEW.aggregation_id,NEW.record_id)<>1
 OR (CASE NEW.resource_kind WHEN 'aggregation' THEN NEW.aggregation_id
 WHEN 'record' THEN NEW.record_id END)
 IS DISTINCT FROM NEW.target_id_snapshot THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_resource_target_mismatch';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_resource_link_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['aggregation_id','record_id'])
 IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['aggregation_id','record_id'])
 OR num_nonnulls(NEW.aggregation_id,NEW.record_id)<>0
 OR EXISTS(SELECT 1 FROM aggregations WHERE id=OLD.aggregation_id)
 OR EXISTS(SELECT 1 FROM records WHERE id=OLD.record_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_resource_link_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_snapshot_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE inserting_low bigint; current_full bigint:=pg_current_xact_id()::text::bigint; inserting_full bigint;
BEGIN
 SELECT xmin::text::bigint INTO inserting_low FROM message_envelopes WHERE id=NEW.envelope_id;
 IF inserting_low IS NOT NULL THEN
  inserting_full:=current_full+mod(inserting_low-mod(current_full,4294967296)+4294967296+2147483648,4294967296)-2147483648;
  IF inserting_full>0 AND pg_xact_status(inserting_full::text::xid8)='in progress' THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='message_snapshot_already_committed';
END $$;

CREATE FUNCTION public.messaging_user_clearance(p_user bigint) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
 SELECT max(l.level_number)::integer FROM users u
 JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
 JOIN security_levels l ON l.id=r.security_level_id
 WHERE u.id=p_user AND u.status='active' AND u.account_type='person'
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND role_effectively_active(r.id)
$$;

CREATE FUNCTION public.messaging_user_eligible(p_user bigint, p_level integer) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT COALESCE(messaging_user_clearance(p_user)>=p_level,false)
 AND user_has_global_privilege(p_user,'messaging.user_messages.exchange')
$$;

CREATE FUNCTION public.messaging_validate_amendment() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE original message_envelopes; previous message_action_amendments;
BEGIN
 SELECT * INTO original FROM message_envelopes WHERE id=NEW.original_envelope_id FOR UPDATE;
 SELECT * INTO previous FROM message_action_amendments WHERE original_envelope_id=NEW.original_envelope_id
 AND sequence<NEW.sequence ORDER BY sequence DESC LIMIT 1;
 IF original.message_kind<>'user_message' OR NOT original.action_required OR original.sender_user_id<>NEW.created_by_user_id
 OR original.is_test OR original.sender_deleted_at IS NOT NULL OR original.expires_at<=clock_timestamp()
 OR NEW.created_by_user_id<>current_user_id()
 OR (NEW.new_due_at IS NOT NULL AND NEW.new_due_at<=clock_timestamp())
 OR NEW.sequence<>COALESCE(previous.sequence,0)+1
 OR ROW(NEW.previous_action_required,NEW.previous_due_date,NEW.previous_due_timezone,NEW.previous_due_at)
 IS DISTINCT FROM ROW(COALESCE(previous.new_action_required,original.action_required),
 CASE WHEN previous.id IS NULL THEN original.action_due_date ELSE previous.new_due_date END,
 CASE WHEN previous.id IS NULL THEN original.action_due_timezone ELSE previous.new_due_timezone END,
 CASE WHEN previous.id IS NULL THEN original.action_due_at ELSE previous.new_due_at END)
 OR NOT EXISTS(SELECT 1 FROM message_envelopes WHERE action_amendment_id=NEW.id AND sender_user_id=NEW.created_by_user_id)
 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_amendment_invalid'; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.messaging_validate_capture() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE total integer; provenance integer; selected integer;
BEGIN
 SELECT count(*),count(*) FILTER(WHERE component_kind='provenance'),count(*) FILTER(WHERE is_selected_message)
 INTO total,provenance,selected FROM message_record_capture_components WHERE capture_id=NEW.id;
 IF total<2 OR provenance<>1 OR selected<>1 OR NEW.selected_envelope_id IS DISTINCT FROM NEW.selected_envelope_id_at_capture
 OR NEW.record_id IS DISTINCT FROM NEW.record_id_at_capture
 OR EXISTS(SELECT 1 FROM message_record_capture_components x LEFT JOIN digital_components d ON d.id=x.digital_component_id
    WHERE x.capture_id=NEW.id AND (x.component_order>total
    OR (x.component_kind='provenance' AND x.component_order<>total)
    OR (x.component_kind='message' AND x.envelope_id IS DISTINCT FROM x.envelope_id_at_capture)
    OR (x.is_selected_message AND x.envelope_id IS DISTINCT FROM NEW.selected_envelope_id)
    OR x.digital_component_id IS DISTINCT FROM x.digital_component_id_at_capture OR d.record_id IS DISTINCT FROM NEW.record_id OR d.component_order IS DISTINCT FROM x.component_order)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_incomplete';
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.messaging_validate_completion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM message_deliveries d JOIN message_envelopes original ON original.id=d.envelope_id
 JOIN message_envelopes reply ON reply.id=NEW.reply_envelope_id
 WHERE d.id=NEW.original_delivery_id AND d.recipient_user_id=NEW.completed_by_user_id
 AND d.recipient_type='to'
 AND reply.sender_user_id=NEW.completed_by_user_id AND reply.relationship_kind='reply'
 AND reply.related_delivery_id=d.id AND NEW.completed_by_user_id=current_user_id()
 AND EXISTS(SELECT 1 FROM message_addressees a WHERE a.envelope_id=reply.id AND a.user_id=original.sender_user_id AND a.recipient_type='to')
 AND original.action_required AND original.message_kind='user_message'
 AND NOT EXISTS(SELECT 1 FROM message_action_amendments a WHERE a.original_envelope_id=original.id AND NOT a.new_action_required)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_completion_invalid';
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.messaging_validate_delivery() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM message_mailboxes WHERE user_id=NEW.recipient_user_id AND last_sequence=NEW.mailbox_sequence) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_sequence_not_allocated';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.messaging_validate_envelope() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE e message_envelopes; parent message_envelopes;
BEGIN
 SELECT * INTO e FROM message_envelopes WHERE id=NEW.id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM message_recipient_selectors WHERE envelope_id=e.id AND recipient_type='to')
 OR NOT EXISTS(SELECT 1 FROM message_addressees WHERE envelope_id=e.id AND recipient_type='to')
 OR EXISTS(SELECT 1 FROM message_addressees a LEFT JOIN message_deliveries d
       ON d.envelope_id=a.envelope_id AND d.recipient_user_id=a.user_id
       WHERE a.envelope_id=e.id AND (d.id IS NULL OR a.user_id=e.sender_user_id))
 OR NOT EXISTS(SELECT 1 FROM message_request_receipts WHERE result_envelope_id=e.id) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_incomplete_fanout';
 END IF;
 IF e.sender_kind='system' AND e.security_level_id<>(SELECT id FROM security_levels ORDER BY level_number LIMIT 1) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_system_level';
 END IF;
 IF e.action_due_date IS NOT NULL AND
   (NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=e.action_due_timezone)
    OR e.action_due_at IS DISTINCT FROM ((e.action_due_date+1)::timestamp AT TIME ZONE e.action_due_timezone)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_due_boundary';
 END IF;
 IF e.related_delivery_id IS NOT NULL THEN
  SELECT original.* INTO parent FROM message_envelopes original
  JOIN message_deliveries d ON d.envelope_id=original.id
  WHERE d.id=e.related_delivery_id AND d.recipient_user_id=e.sender_user_id;
 ELSIF e.related_envelope_id IS NOT NULL THEN
  SELECT * INTO parent FROM message_envelopes WHERE id=e.related_envelope_id AND sender_user_id=e.sender_user_id;
 END IF;
 IF e.relationship_kind IS NOT NULL AND (parent.id IS NULL OR parent.message_kind='action_amendment_notice'
 OR parent.is_test OR (SELECT level_number FROM security_levels WHERE id=parent.security_level_id)>
 (SELECT level_number FROM security_levels WHERE id=e.security_level_id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_relationship_invalid';
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.messaging_validate_receipt() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NEW.result_purged_at IS NULL AND NOT EXISTS(SELECT 1 FROM message_envelopes e WHERE e.id=NEW.result_envelope_id
 AND e.sender_user_id IS NOT DISTINCT FROM NEW.principal_user_id
 AND e.system_producer_code IS NOT DISTINCT FROM NEW.producer_code
 AND e.request_id=NEW.request_id
 AND ((NEW.operation_kind='send' AND e.message_kind<>'action_amendment_notice')
 OR (NEW.operation_kind='amendment' AND e.action_amendment_id=NEW.result_amendment_id))) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_receipt_result_mismatch';
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.normalize_aggregation_acl_inheritance() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.parent_aggregation_id IS NULL THEN NEW.inherit_acl_from_parent := false; END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION public.org_unit_effectively_active(p_org_unit_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id, parent_org_unit_id, date_deactivated
          FROM org_units WHERE id = p_org_unit_id
        UNION ALL
        SELECT parent.id, parent.parent_org_unit_id, parent.date_deactivated
          FROM org_units parent
          JOIN ancestors child ON parent.id = child.parent_org_unit_id
    )
    SELECT COALESCE(bool_and(date_deactivated IS NULL), false) FROM ancestors;
$$;

CREATE FUNCTION public.populate_event_actor_snapshot() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    stored_name  text;
    stored_email text;
BEGIN
    IF NEW.actor_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.actor_name IS NULL OR NEW.actor_email IS NULL THEN
        SELECT name, email INTO stored_name, stored_email
        FROM users
        WHERE id = NEW.actor_user_id;
    END IF;

    NEW.actor_name := COALESCE(
        NEW.actor_name,
        NULLIF(current_setting('app.actor_name', true), ''),
        stored_name
    );
    NEW.actor_email := COALESCE(
        NEW.actor_email,
        NULLIF(current_setting('app.actor_email', true), ''),
        stored_email
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.populate_event_reference_snapshots() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    snapshots      jsonb := '{}'::jsonb;
    state_snapshot jsonb;
BEGIN
    state_snapshot := event_state_reference_snapshots(NEW.before_state);
    IF state_snapshot <> '{}'::jsonb THEN
        snapshots := snapshots || jsonb_build_object('before', state_snapshot);
    END IF;

    state_snapshot := event_state_reference_snapshots(NEW.after_state);
    IF state_snapshot <> '{}'::jsonb THEN
        snapshots := snapshots || jsonb_build_object('after', state_snapshot);
    END IF;

    state_snapshot := event_state_reference_snapshots(NEW.metadata);
    IF state_snapshot <> '{}'::jsonb THEN
        snapshots := snapshots || jsonb_build_object('metadata', state_snapshot);
    END IF;

    state_snapshot := event_entity_identity_snapshot(NEW.entity_type, NEW.entity_id);
    IF state_snapshot IS NOT NULL THEN
        snapshots := snapshots || jsonb_build_object('entity', state_snapshot);
    END IF;

    IF snapshots <> '{}'::jsonb THEN
        NEW.metadata := NEW.metadata || jsonb_build_object('reference_snapshots', snapshots);
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.populate_event_relationship_snapshot() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    assignment_state jsonb;
    user_snapshot     jsonb;
    role_snapshot     jsonb;
BEGIN
    IF NEW.entity_type <> 'user_role_assignment' THEN
        RETURN NEW;
    END IF;

    assignment_state := COALESCE(NEW.after_state, NEW.before_state);
    SELECT jsonb_build_object('id', id, 'name', name, 'email', email)
    INTO user_snapshot
    FROM users
    WHERE id = (assignment_state ->> 'user_id')::bigint;

    SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
    INTO role_snapshot
    FROM roles
    WHERE id = (assignment_state ->> 'role_id')::bigint;

    NEW.metadata := NEW.metadata || jsonb_build_object(
        'assignment_parties',
        jsonb_build_object('user', user_snapshot, 'role', role_snapshot)
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.populate_hold_event_reference_snapshots() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE state jsonb:=COALESCE(NEW.after_state,NEW.before_state,'{}'::jsonb);
DECLARE snapshots jsonb:='{}'::jsonb;
DECLARE reference_id bigint;
DECLARE snapshot jsonb;
DECLARE existing_snapshots jsonb;
BEGIN
    IF NEW.entity_type='hold' THEN
        snapshots:=jsonb_build_object('hold',jsonb_strip_nulls(jsonb_build_object(
            'id',NEW.entity_id,'code',state->>'code','name',state->>'name')));
    ELSIF NEW.entity_type IN ('hold_contributor','hold_aggregation_assignment','hold_record_assignment') THEN
        reference_id:=NULLIF(state->>'hold_id','')::bigint;
        SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot
        FROM holds WHERE id=reference_id;
        IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('hold',snapshot); END IF;
        IF NEW.entity_type='hold_contributor' THEN
            reference_id:=NULLIF(state->>'user_id','')::bigint;
            SELECT jsonb_strip_nulls(jsonb_build_object('id',id,'name',name,'email',email)) INTO snapshot
            FROM users WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('user',snapshot); END IF;
        ELSIF NEW.entity_type='hold_aggregation_assignment' THEN
            reference_id:=NULLIF(state->>'aggregation_id','')::bigint;
            SELECT jsonb_build_object('id',id,'number',aggregation_number,'title',title) INTO snapshot
            FROM aggregations WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('aggregation',snapshot); END IF;
        ELSE
            reference_id:=NULLIF(state->>'record_id','')::bigint;
            SELECT jsonb_build_object('id',id,'number',record_number,'title',title) INTO snapshot
            FROM records WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('record',snapshot); END IF;
        END IF;
    ELSE
        IF NEW.metadata ? 'hold_id' THEN
            reference_id:=NULLIF(NEW.metadata->>'hold_id','')::bigint;
            SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot
            FROM holds WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('hold',snapshot); END IF;
        ELSE
            RETURN NEW;
        END IF;
    END IF;
    IF snapshots<>'{}'::jsonb THEN
        existing_snapshots:=COALESCE(NEW.metadata->'reference_snapshots','{}'::jsonb);
        NEW.metadata:=NEW.metadata||jsonb_build_object(
            'reference_snapshots',existing_snapshots||snapshots);
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.prevent_aggregation_cycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.parent_aggregation_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF EXISTS (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_aggregation_id
            FROM aggregations
            WHERE id = NEW.parent_aggregation_id

            UNION ALL

            SELECT aggregation.id, aggregation.parent_aggregation_id
            FROM aggregations AS aggregation
            JOIN ancestors ON aggregation.id = ancestors.parent_aggregation_id
        )
        SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'aggregation hierarchy cannot contain a cycle';
    END IF;

    RETURN NEW;
END;
$$;

CREATE FUNCTION public.prevent_nonempty_hold_deletion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM hold_aggregation_assignments WHERE hold_id=OLD.id)
       OR EXISTS (SELECT 1 FROM hold_record_assignments WHERE hold_id=OLD.id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_not_empty';
    END IF;
    RETURN OLD;
END;
$$;

CREATE FUNCTION public.prevent_org_unit_cycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.parent_org_unit_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_org_unit_id
            FROM org_units WHERE id = NEW.parent_org_unit_id
            UNION ALL
            SELECT parent.id, parent.parent_org_unit_id
            FROM org_units AS parent
            JOIN ancestors ON parent.id = ancestors.parent_org_unit_id
        )
        SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'organizational unit hierarchy cannot contain a cycle';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.prevent_role_supervision_cycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.supervisor_role_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        WITH RECURSIVE supervisors AS (
            SELECT id, supervisor_role_id
            FROM roles WHERE id = NEW.supervisor_role_id
            UNION ALL
            SELECT supervisor.id, supervisor.supervisor_role_id
            FROM roles AS supervisor
            JOIN supervisors ON supervisor.id = supervisors.supervisor_role_id
        )
        SELECT 1 FROM supervisors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'role supervision hierarchy cannot contain a cycle';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.propagate_aggregation_ownership() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE previous_context text;
BEGIN
    IF NEW.owning_org_unit_id IS NOT DISTINCT FROM OLD.owning_org_unit_id
       OR current_setting('app.ownership_propagation', true) = 'authorized' THEN
        RETURN NEW;
    END IF;
    previous_context := current_setting('app.ownership_propagation', true);
    PERFORM set_config('app.ownership_propagation', 'authorized', true);
    WITH RECURSIVE descendants(id) AS (
        SELECT child.id FROM aggregations child WHERE child.parent_aggregation_id = NEW.id
        UNION ALL
        SELECT child.id FROM descendants parent
        JOIN aggregations child ON child.parent_aggregation_id = parent.id
    )
    UPDATE aggregations child SET owning_org_unit_id = NEW.owning_org_unit_id
    FROM descendants WHERE child.id = descendants.id
      AND child.owning_org_unit_id IS DISTINCT FROM NEW.owning_org_unit_id;
    WITH RECURSIVE subtree(id) AS (
        SELECT NEW.id
        UNION ALL
        SELECT child.id FROM subtree parent
        JOIN aggregations child ON child.parent_aggregation_id = parent.id
    )
    UPDATE records record SET owning_org_unit_id = NEW.owning_org_unit_id
    FROM subtree WHERE record.aggregation_id = subtree.id
      AND record.owning_org_unit_id IS DISTINCT FROM NEW.owning_org_unit_id;
    PERFORM set_config('app.ownership_propagation', COALESCE(previous_context, ''), true);
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.protect_blob_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_content_set_id bigint;
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=(SELECT d.record_id FROM digital_component_content_sets s JOIN digital_components d ON d.id=s.digital_component_id WHERE s.id=OLD.content_set_id)))) THEN RETURN OLD; END IF;

    target_content_set_id := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.content_set_id ELSE NEW.content_set_id END;
    PERFORM assert_record_effectively_open(
        (SELECT dc.record_id
           FROM digital_component_content_sets content_set
           JOIN digital_components dc ON dc.id = content_set.digital_component_id
          WHERE content_set.id = target_content_set_id)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.protect_classification_deletion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    scheme_row classification_schemes%ROWTYPE;
BEGIN
    SELECT * INTO scheme_row FROM classification_schemes WHERE id = OLD.classification_scheme_id;
    IF scheme_row.date_deactivated IS NOT NULL THEN
        RAISE EXCEPTION 'classifications cannot be deleted while their scheme is deactivated';
    END IF;
    IF scheme_row.date_published IS NOT NULL THEN
        RAISE EXCEPTION 'classification scheme must be unpublished before deleting classifications';
    END IF;
    IF OLD.date_first_used IS NOT NULL THEN
        RAISE EXCEPTION 'a classification that has governed an aggregation cannot be deleted; deactivate it instead';
    END IF;
    IF EXISTS (SELECT 1 FROM classifications WHERE parent_classification_id = OLD.id) THEN
        RAISE EXCEPTION 'classification has children; delete its child classifications first';
    END IF;
    IF EXISTS (SELECT 1 FROM aggregations WHERE classification_id = OLD.id) THEN
        RAISE EXCEPTION 'classification is assigned to an aggregation and cannot be deleted';
    END IF;
    IF NULLIF(current_setting('app.change_reason', true), '') IS NULL THEN
        RAISE EXCEPTION 'deleting a classification requires a change reason';
    END IF;
    RETURN OLD;
END;
$$;

CREATE FUNCTION public.protect_closed_aggregation_hierarchy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE closure_source_id bigint;
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

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

CREATE FUNCTION public.protect_component_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=OLD.record_id))) THEN RETURN OLD; END IF;

    IF TG_OP = 'INSERT' THEN
        PERFORM assert_record_effectively_open(NEW.record_id);
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM assert_record_effectively_open(OLD.record_id);
        RETURN OLD;
    END IF;

    PERFORM assert_record_effectively_open(OLD.record_id);
    IF NEW.record_id IS DISTINCT FROM OLD.record_id THEN
        PERFORM assert_record_effectively_open(NEW.record_id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.protect_content_set_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_component_id bigint;
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=(SELECT record_id FROM digital_components WHERE id=OLD.digital_component_id)))) THEN RETURN OLD; END IF;

    target_component_id := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
    PERFORM assert_record_effectively_open(
        (SELECT record_id FROM digital_components WHERE id = target_component_id)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.protect_designated_role_unit() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM org_units WHERE
  (managing_role_id=NEW.id OR file_administrator_role_id=NEW.id)
  AND (id IS DISTINCT FROM NEW.org_unit_id OR NEW.is_system
    OR NEW.account_type_restriction='service')) THEN
  RAISE EXCEPTION 'role is designated by an organizational unit; clear or replace its designation first' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.protect_held_component_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE component_id bigint;
DECLARE held_record_id bigint;
DECLARE failure_code text;
BEGIN
    PERFORM lock_hold_policy_shared();
    IF TG_TABLE_NAME='digital_components' THEN
        held_record_id:=CASE WHEN TG_OP='DELETE' THEN OLD.record_id ELSE NEW.record_id END;
    ELSIF TG_TABLE_NAME='digital_component_content_sets' THEN
        component_id:=CASE WHEN TG_OP='DELETE' THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
        SELECT record_id INTO held_record_id FROM digital_components WHERE id=component_id;
    ELSIF TG_TABLE_NAME='digital_component_blobs' THEN
        SELECT component.digital_component_id INTO component_id
        FROM digital_component_content_sets component
        WHERE component.id=CASE WHEN TG_OP='DELETE' THEN OLD.content_set_id ELSE NEW.content_set_id END;
        SELECT record_id INTO held_record_id FROM digital_components WHERE id=component_id;
    ELSE
        component_id:=CASE WHEN TG_OP='DELETE' THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
        IF component_id IS NOT NULL THEN SELECT record_id INTO held_record_id FROM digital_components WHERE id=component_id; END IF;
    END IF;
    IF held_record_id IS NOT NULL AND resource_has_effective_hold('record',held_record_id) THEN
        failure_code:=CASE TG_OP WHEN 'INSERT' THEN 'effective_hold_prevents_component_addition'
          WHEN 'DELETE' THEN 'effective_hold_prevents_component_deletion'
          ELSE 'effective_hold_prevents_component_replacement' END;
        -- Resolve table-specific fields only after selecting their row type.
        IF TG_TABLE_NAME='digital_components' AND TG_OP='UPDATE' THEN
            IF NEW.component_order IS DISTINCT FROM OLD.component_order THEN
                failure_code:='effective_hold_prevents_component_reordering';
            END IF;
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE=failure_code;
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.protect_held_resource() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE blocked boolean;
DECLARE allowed_old jsonb;
DECLARE allowed_new jsonb;
BEGIN
    PERFORM lock_hold_policy_shared();
    -- Recording an immutable physical outcome or redirecting preserved material
    -- changes only disposition bookkeeping; the hold and all content remain.
    IF TG_OP='UPDATE' AND disposition_private.context_operation() IN ('job_terminate','resolve_partial')
      AND disposition_private.recovery_active(NULL,disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END),NEW.disposition_status)
      AND ((OLD.disposition_status=6 AND NEW.disposition_status IN (10,13)) OR (OLD.disposition_status=13 AND NEW.disposition_status BETWEEN 2 AND 5))
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','final_disposition_event_id'])=(to_jsonb(OLD)-ARRAY['disposition_status','version','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','final_disposition_event_id']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;

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
    -- Eligibility bookkeeping does not alter content, hold assignments or held metadata.
    -- Acceleration's separate closure update still passes the ordinary hold guard.
    IF TG_OP='UPDATE' AND OLD.disposition_status=1 AND NEW.disposition_status BETWEEN 2 AND 5
      AND disposition_private.context_operation() IN ('eligibility_evaluate','eligibility_accelerate')
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

CREATE FUNCTION public.protect_record_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 IF TG_OP='UPDATE' AND disposition_private.context_operation() IS NOT NULL
 AND (to_jsonb(NEW)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated'])=(to_jsonb(OLD)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated']) THEN
  PERFORM disposition_private.require_command(); RETURN NEW;
 END IF;
 IF TG_OP='INSERT' THEN PERFORM assert_aggregation_effectively_open(NEW.aggregation_id); RETURN NEW; END IF;
 IF TG_OP='DELETE' THEN PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN OLD; END IF;
 IF current_setting('app.vital_status_change_authorized',true)='authorized' AND NEW.is_vital IS DISTINCT FROM OLD.is_vital AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.review_date_change_authorized',true)='authorized' AND NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review AND (to_jsonb(NEW)-'date_of_next_review'-'version')=(to_jsonb(OLD)-'date_of_next_review'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.security_level_change_authorized',true)='authorized' AND NEW.security_level_id IS DISTINCT FROM OLD.security_level_id AND (to_jsonb(NEW)-'security_level_id'-'version')=(to_jsonb(OLD)-'security_level_id'-'version') THEN RETURN NEW; END IF;
 PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN NEW;
END; $$;

CREATE FUNCTION public.protect_text_indexer_profile() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.code='TEXT_INDEXER_SERVICE' THEN
        IF TG_OP='UPDATE' THEN
            IF ROW(
                NEW.id,NEW.code,NEW.name,NEW.description,NEW.is_system,
                NEW.date_created
            ) IS NOT DISTINCT FROM ROW(
                OLD.id,OLD.code,OLD.name,OLD.description,OLD.is_system,
                OLD.date_created
            ) THEN
                RETURN NEW;
            END IF;
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='TEXT_INDEXER_SERVICE profile is protected';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.protect_text_indexer_profile_membership() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_profile_id bigint;
    target_privilege_id bigint;
    target_profile_code text;
    target_privilege_code text;
BEGIN
    IF TG_OP='DELETE' THEN
        target_profile_id:=OLD.profile_id;
        target_privilege_id:=OLD.privilege_id;
    ELSE
        target_profile_id:=NEW.profile_id;
        target_privilege_id:=NEW.privilege_id;
    END IF;
    SELECT code INTO target_profile_code FROM profiles
    WHERE id=target_profile_id;
    SELECT code INTO target_privilege_code FROM privileges
    WHERE id=target_privilege_id;
    IF target_profile_code='TEXT_INDEXER_SERVICE' THEN
        IF TG_OP='DELETE' OR target_privilege_code<>'content.index.execute' THEN
            RAISE EXCEPTION USING ERRCODE='P0001',
                MESSAGE='TEXT_INDEXER_SERVICE profile is protected and contains exactly content.index.execute';
        END IF;
    END IF;
    IF TG_OP='DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.protect_text_indexer_role() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.code='text-indexer-service' AND OLD.is_system THEN
        IF TG_OP='UPDATE' THEN
            IF ROW(
                NEW.id,NEW.org_unit_id,NEW.supervisor_role_id,NEW.code,NEW.name,
                NEW.description,NEW.date_created,NEW.date_deactivated,
                NEW.security_level_id,NEW.profile_id,NEW.is_information_governance,
                NEW.is_system,NEW.account_type_restriction
            ) IS NOT DISTINCT FROM ROW(
                OLD.id,OLD.org_unit_id,OLD.supervisor_role_id,OLD.code,OLD.name,
                OLD.description,OLD.date_created,OLD.date_deactivated,
                OLD.security_level_id,OLD.profile_id,OLD.is_information_governance,
                OLD.is_system,OLD.account_type_restriction
            ) THEN
                RETURN NEW;
            END IF;
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='text-indexer-service role is protected';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.protect_vital_resource_deletion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    vital_count integer;
BEGIN
    IF TG_TABLE_NAME = 'records' THEN
        IF OLD.is_vital THEN
            RAISE EXCEPTION USING
                ERRCODE = 'P0001',
                MESSAGE = 'vital_resource_deletion_blocked';
        END IF;
        RETURN OLD;
    END IF;

    PERFORM 1 FROM aggregations WHERE id = OLD.id FOR UPDATE;
    IF OLD.is_vital THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'vital_resource_deletion_blocked';
    END IF;

    WITH RECURSIVE subtree AS (
        SELECT OLD.id AS id
        UNION ALL
        SELECT child.id
          FROM aggregations child
          JOIN subtree parent ON child.parent_aggregation_id = parent.id
    )
    SELECT count(*)
      INTO vital_count
      FROM (
          SELECT id
            FROM aggregations
           WHERE id IN (SELECT id FROM subtree)
             AND id <> OLD.id
             AND is_vital
          UNION ALL
          SELECT id
            FROM records
           WHERE aggregation_id IN (SELECT id FROM subtree)
             AND is_vital
      ) vital;

    IF vital_count > 0 THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'vital_descendant_deletion_blocked';
    END IF;
    RETURN OLD;
END;
$$;

CREATE FUNCTION public.record_classification_governance_first_use() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    scheme_id bigint;
    used_at timestamptz := CURRENT_TIMESTAMP;
BEGIN
    IF NEW.classification_id IS NULL
       OR (TG_OP = 'UPDATE' AND NEW.classification_id IS NOT DISTINCT FROM OLD.classification_id) THEN
        RETURN NEW;
    END IF;

    SELECT classification_scheme_id INTO scheme_id
    FROM classifications
    WHERE id = NEW.classification_id;

    WITH RECURSIVE lineage AS (
        SELECT id, parent_classification_id
        FROM classifications WHERE id = NEW.classification_id
        UNION ALL
        SELECT parent.id, parent.parent_classification_id
        FROM classifications AS parent
        JOIN lineage AS child ON parent.id = child.parent_classification_id
    )
    UPDATE classifications
    SET date_first_used = used_at
    WHERE id IN (SELECT id FROM lineage) AND date_first_used IS NULL;

    UPDATE classification_schemes
    SET date_first_used = used_at
    WHERE id = scheme_id AND date_first_used IS NULL;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.record_classification_selection() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE context_user_id text;
BEGIN
    context_user_id := NULLIF(current_setting('app.user_id', true), '');
    IF context_user_id IS NOT NULL
       AND NEW.parent_aggregation_id IS NULL
       AND NEW.classification_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.classification_id IS DISTINCT FROM OLD.classification_id) THEN
        INSERT INTO user_classification_selections (
            user_id, classification_id, last_selected_at, selection_count
        ) VALUES (context_user_id::bigint, NEW.classification_id, CURRENT_TIMESTAMP, 1)
        ON CONFLICT (user_id, classification_id) DO UPDATE
        SET last_selected_at = EXCLUDED.last_selected_at,
            selection_count = user_classification_selections.selection_count + 1;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.record_entity_history() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE old_state jsonb; new_state jsonb; entity_key bigint; changed text[]; context_user_id text; context_metadata text;
BEGIN
 IF TG_OP='UPDATE' AND current_setting('app.suppress_ordinary_history',true)='authorized' THEN RETURN NEW; END IF;
 old_state:=CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END;
 new_state:=CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END;
 entity_key:=CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
 SELECT coalesce(array_agg(key ORDER BY key),ARRAY[]::text[]) INTO changed FROM (
  SELECT key FROM jsonb_object_keys(coalesce(old_state,'{}'::jsonb)||coalesce(new_state,'{}'::jsonb)) key
  WHERE old_state->key IS DISTINCT FROM new_state->key) differences;
 context_user_id:=nullif(current_setting('app.user_id',true),''); context_metadata:=nullif(current_setting('app.event_metadata',true),'');
 INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,request_id,correlation_id,before_state,after_state,changed_fields,reason,metadata)
 VALUES(TG_ARGV[0],entity_key,CASE TG_OP WHEN 'INSERT' THEN 'CREATE' ELSE TG_OP END,context_user_id::bigint,
  coalesce(nullif(current_setting('app.actor_type',true),''),'automated_process'),coalesce(nullif(current_setting('app.event_source',true),''),'database'),
  nullif(current_setting('app.request_id',true),'')::uuid,nullif(current_setting('app.correlation_id',true),'')::uuid,old_state,new_state,changed,
  nullif(current_setting('app.change_reason',true),''),coalesce(context_metadata::jsonb,'{}'::jsonb));
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END; $$;

CREATE FUNCTION public.record_localization_catalogue_history() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE old_state jsonb; new_state jsonb; changed text[]; stable_key text;
BEGIN
    old_state:=CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END;
    new_state:=CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END;
    SELECT COALESCE(array_agg(key ORDER BY key),ARRAY[]::text[]) INTO changed
      FROM jsonb_object_keys(COALESCE(old_state,'{}'::jsonb)||COALESCE(new_state,'{}'::jsonb)) key
     WHERE old_state->key IS DISTINCT FROM new_state->key;
    stable_key:=COALESCE(new_state->>'message_key',old_state->>'message_key')||COALESCE('|'||COALESCE(new_state->>'language_tag',old_state->>'language_tag'),'');
    INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,request_id,correlation_id,before_state,after_state,changed_fields,reason,metadata)
    VALUES (TG_ARGV[0],hashtextextended(stable_key,0),CASE TG_OP WHEN 'INSERT' THEN 'CREATE' ELSE TG_OP END,
      NULLIF(current_setting('app.user_id',true),'')::bigint,
      COALESCE(NULLIF(current_setting('app.actor_type',true),''),'automated_process'),
      COALESCE(NULLIF(current_setting('app.event_source',true),''),'database'),
      NULLIF(current_setting('app.request_id',true),'')::uuid,NULLIF(current_setting('app.correlation_id',true),'')::uuid,
      old_state,new_state,changed,NULLIF(current_setting('app.change_reason',true),''),
      COALESCE(NULLIF(current_setting('app.event_metadata',true),'')::jsonb,'{}'::jsonb));
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.record_user_preference_history() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    old_state jsonb;
    new_state jsonb;
    changed text[];
BEGIN
    old_state := CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END;
    new_state := CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END;
    SELECT COALESCE(array_agg(key ORDER BY key),ARRAY[]::text[]) INTO changed
      FROM jsonb_object_keys(COALESCE(old_state,'{}'::jsonb) || COALESCE(new_state,'{}'::jsonb)) key
     WHERE old_state -> key IS DISTINCT FROM new_state -> key;
    INSERT INTO event_history(
        entity_type,entity_id,operation,actor_user_id,actor_type,source,
        request_id,correlation_id,before_state,after_state,changed_fields,reason,metadata
    ) VALUES (
        'user_preference',CASE WHEN TG_OP='DELETE' THEN OLD.user_id ELSE NEW.user_id END,
        CASE TG_OP WHEN 'INSERT' THEN 'CREATE' ELSE TG_OP END,
        NULLIF(current_setting('app.user_id',true),'')::bigint,
        COALESCE(NULLIF(current_setting('app.actor_type',true),''),'automated_process'),
        COALESCE(NULLIF(current_setting('app.event_source',true),''),'database'),
        NULLIF(current_setting('app.request_id',true),'')::uuid,
        NULLIF(current_setting('app.correlation_id',true),'')::uuid,
        old_state,new_state,changed,
        NULLIF(current_setting('app.change_reason',true),''),
        COALESCE(NULLIF(current_setting('app.event_metadata',true),'')::jsonb,'{}'::jsonb)
    );
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.refresh_aggregation_metadata_search_document() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO aggregation_search_documents(
        aggregation_id,search_vector,text_search_config,indexed_at,index_config_version
    ) VALUES (
        NEW.id,
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.aggregation_number,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.title,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.description,'')),'B'),
        'pg_catalog.simple'::regconfig,
        CURRENT_TIMESTAMP,
        'fts-metadata-v1'
    )
    ON CONFLICT(aggregation_id) DO UPDATE SET
        search_vector=EXCLUDED.search_vector,
        text_search_config=EXCLUDED.text_search_config,
        indexed_at=EXCLUDED.indexed_at,
        index_config_version=EXCLUDED.index_config_version;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.refresh_record_metadata_search_document() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO record_search_documents(
        record_id,search_vector,text_search_config,indexed_at,index_config_version
    ) VALUES (
        NEW.id,
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.record_number,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.title,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.description,'')),'B'),
        'pg_catalog.simple'::regconfig,
        CURRENT_TIMESTAMP,
        'fts-metadata-v1'
    )
    ON CONFLICT(record_id) DO UPDATE SET
        search_vector=EXCLUDED.search_vector,
        text_search_config=EXCLUDED.text_search_config,
        indexed_at=EXCLUDED.indexed_at,
        index_config_version=EXCLUDED.index_config_version;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.reject_application_settings_removal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_protected'; END $$;

CREATE FUNCTION public.reject_event_history_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 -- Content minimization is confined to an actual protected erasure command.
 -- Identity, actor, operation, time, reason and event linkage cannot change.
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND (disposition_private.context_operation() IN ('final_complete','job_terminate') OR current_setting('app.event_source',true)='migration')
 AND (NEW.before_state IS NOT DISTINCT FROM disposition_private.retained_json(OLD.before_state) OR NEW.before_state IS NOT DISTINCT FROM disposition_private.retained_history_json(OLD.before_state))
 AND (NEW.after_state IS NOT DISTINCT FROM disposition_private.retained_json(OLD.after_state) OR NEW.after_state IS NOT DISTINCT FROM disposition_private.retained_history_json(OLD.after_state))
 AND (NEW.metadata=disposition_private.retained_json(OLD.metadata) OR NEW.metadata=disposition_private.retained_history_json(OLD.metadata))
 AND (to_jsonb(NEW)-ARRAY['before_state','after_state','metadata'])=(to_jsonb(OLD)-ARRAY['before_state','after_state','metadata']) THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'event history is immutable';
END $$;

CREATE FUNCTION public.reject_service_account_password() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM users account WHERE account.id=NEW.user_id AND account.account_type='service') THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='service accounts cannot have interactive passwords';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.remove_internal_audit_fields() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.changed_fields := array_remove(NEW.changed_fields, 'version');
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.require_localization_change_reason() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='localization_change_reason_required';
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION public.resource_has_effective_hold(p_resource_type text, p_resource_id bigint, p_at_time timestamp with time zone DEFAULT statement_timestamp()) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
    IF p_resource_type='aggregation' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_aggregation(p_resource_id,p_at_time));
    ELSIF p_resource_type='record' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_record(p_resource_id,p_at_time));
    END IF;
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='unknown hold resource type';
END;
$$;

CREATE FUNCTION public.resource_state_changes_blocked(p_resource_type text, p_resource_id bigint, p_at_time timestamp with time zone DEFAULT statement_timestamp()) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
    IF p_resource_type='aggregation' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_aggregation(p_resource_id,p_at_time)
                      WHERE preserve_resource_state);
    ELSIF p_resource_type='record' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_record(p_resource_id,p_at_time)
                      WHERE preserve_resource_state);
    END IF;
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='unknown hold resource type';
END;
$$;

CREATE FUNCTION public.role_effectively_active(p_role_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(
        role.date_deactivated IS NULL
        AND CASE
            WHEN role.is_system THEN
                role.account_type_restriction='service' AND role.org_unit_id IS NULL
            ELSE org_unit_effectively_active(role.org_unit_id)
        END,
        false
    )
    FROM roles role WHERE role.id=p_role_id;
$$;

CREATE FUNCTION public.schedule_component_content_indexing() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    active_set digital_component_content_sets%ROWTYPE;
    schedule_trigger text;
BEGIN
    IF NEW.content_status<>'available' OR NEW.active_content_set_id IS NULL THEN
        UPDATE digital_component_search_documents SET status='stale',date_updated=CURRENT_TIMESTAMP
         WHERE digital_component_id=NEW.id;
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT active_set FROM digital_component_content_sets
     WHERE id=NEW.active_content_set_id AND digital_component_id=NEW.id AND status='active';
    schedule_trigger:=CASE WHEN TG_OP='INSERT' OR OLD.active_content_set_id IS NULL THEN 'upload' ELSE 'replacement' END;
    UPDATE digital_component_search_documents SET status='stale',date_updated=CURRENT_TIMESTAMP
     WHERE digital_component_id=NEW.id AND content_set_id IS DISTINCT FROM active_set.id;
    INSERT INTO digital_component_search_documents(
        digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
        status,extraction_config_version,index_config_version,date_updated
    ) VALUES (NEW.id,NEW.record_id,active_set.id,active_set.checksum_algo,active_set.checksum_value,
              'pending','tika-4.0.0-ocr-eng-ara-v1','fts-content-v1',CURRENT_TIMESTAMP)
    ON CONFLICT(digital_component_id) DO UPDATE SET
        record_id=EXCLUDED.record_id,content_set_id=EXCLUDED.content_set_id,
        content_checksum_algo=EXCLUDED.content_checksum_algo,
        content_checksum_value=EXCLUDED.content_checksum_value,status='pending',
        extraction_config_version=EXCLUDED.extraction_config_version,
        index_config_version=EXCLUDED.index_config_version,indexed_at=NULL,
        last_error_code=NULL,last_error_summary=NULL,date_updated=CURRENT_TIMESTAMP;
    IF coalesce(nullif(current_setting('app.content_indexing_scheduling_enabled',true),''),
        (SELECT value#>>'{}' FROM application_settings WHERE key='CONTENT_INDEXING_SCHEDULING_ENABLED'))::boolean IS DISTINCT FROM true THEN
        RETURN NEW;
    END IF;
    INSERT INTO content_indexing_jobs(
        digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
        trigger,extraction_config_version,index_config_version,extractor_version,required_capabilities
    ) VALUES (NEW.id,NEW.record_id,active_set.id,active_set.checksum_algo,active_set.checksum_value,
              schedule_trigger,'tika-4.0.0-ocr-eng-ara-v1','fts-content-v1','4.0.0',
              jsonb_build_object('mime_type',NEW.mime_type,'max_input_bytes',52428800))
    ON CONFLICT(digital_component_id,content_set_id,extraction_config_version,index_config_version,extractor_version)
        WHERE status IN ('queued','leased') DO NOTHING;
    RETURN NEW;
END $$;

CREATE FUNCTION public.set_aggregation_default_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_created IS NULL THEN
        NEW.date_created := CURRENT_TIMESTAMP;
    END IF;

    IF NEW.date_opened IS NULL THEN
        NEW.date_opened := NEW.date_created;
    END IF;

    RETURN NEW;
END;
$$;

CREATE FUNCTION public.set_assignment_default_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_assigned IS NULL THEN
        NEW.date_assigned := CURRENT_TIMESTAMP;
    END IF;
    IF NEW.valid_from IS NULL THEN
        NEW.valid_from := NEW.date_assigned;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.set_originated_default_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_created IS NULL THEN
        NEW.date_created := CURRENT_TIMESTAMP;
    END IF;

    IF NEW.date_originated IS NULL THEN
        NEW.date_originated := NEW.date_created;
    END IF;

    RETURN NEW;
END;
$$;

CREATE FUNCTION public.set_user_management_default_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_created IS NULL THEN
        NEW.date_created := CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.touch_authorization_catalogue() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.date_updated := CURRENT_TIMESTAMP;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.touch_classification_date_updated() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.date_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.touch_hold() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN NEW.version:=OLD.version+1; NEW.date_updated:=CURRENT_TIMESTAMP; RETURN NEW; END;
$$;

CREATE FUNCTION public.touch_localization_row() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.date_updated := CURRENT_TIMESTAMP;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.touch_record_draft() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.date_updated := CURRENT_TIMESTAMP;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.touch_saved_search() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.date_updated:=CURRENT_TIMESTAMP;
    NEW.version:=OLD.version+1;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.user_can_aggregation_operation(p_user_id bigint, p_aggregation_id bigint, p_privilege text, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_can_view_aggregation(p_user_id,p_aggregation_id)
     AND user_has_global_privilege(p_user_id,p_privilege)
     AND (user_has_aggregation_permission(p_user_id,p_aggregation_id,p_permission)
          OR EXISTS(SELECT 1 FROM aggregations resource
                    WHERE resource.id=p_aggregation_id
                      AND user_has_governance_clearance(p_user_id,resource.security_level_id)))
$$;

CREATE FUNCTION public.user_can_record_operation(p_user_id bigint, p_record_id bigint, p_privilege text, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_can_view_record(p_user_id,p_record_id)
     AND user_has_global_privilege(p_user_id,p_privilege)
     AND (user_has_record_permission(p_user_id,p_record_id,p_permission)
          OR EXISTS(SELECT 1 FROM records resource
                    WHERE resource.id=p_record_id
                      AND user_has_governance_clearance(p_user_id,resource.security_level_id)))
$$;

CREATE FUNCTION public.user_can_view_aggregation(p_user_id bigint, p_aggregation_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM aggregations WHERE id=p_aggregation_id AND disposition_status<>10) AND disposition_private.original_aggregation_access(p_user_id,p_aggregation_id)
$$;

CREATE FUNCTION public.user_can_view_record(p_user_id bigint, p_record_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM records WHERE id=p_record_id AND disposition_status<>10) AND disposition_private.original_record_access(p_user_id,p_record_id)
$$;

CREATE FUNCTION public.user_has_aggregation_permission(p_user_id bigint, p_aggregation_id bigint, p_permission text) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
  cursor_row aggregations%ROWTYPE;
  parent_row aggregations%ROWTYPE;
  source_id bigint;
  source_kind text;
  target_owner_id bigint;
BEGIN
  SELECT * INTO cursor_row FROM aggregations WHERE id=p_aggregation_id;
  IF NOT FOUND THEN RETURN false; END IF;
  target_owner_id := cursor_row.owning_org_unit_id;
  IF NOT cursor_row.inherit_acl_from_parent OR cursor_row.parent_aggregation_id IS NULL THEN
    source_id := cursor_row.id; source_kind := 'resource';
  ELSE
    LOOP
      SELECT * INTO parent_row FROM aggregations WHERE id=cursor_row.parent_aggregation_id;
      IF NOT FOUND THEN RETURN false; END IF;
      IF parent_row.default_child_aggregation_acl_mode='custom' THEN
        source_id := parent_row.id; source_kind := 'child_default'; EXIT;
      ELSIF NOT parent_row.inherit_acl_from_parent OR parent_row.parent_aggregation_id IS NULL THEN
        source_id := parent_row.id; source_kind := 'resource'; EXIT;
      END IF;
      cursor_row := parent_row;
    END LOOP;
  END IF;

  IF source_kind='resource' THEN
    RETURN EXISTS (
      SELECT 1 FROM aggregation_acl_grants grant_row
      JOIN permissions permission ON permission.id=grant_row.permission_id
      WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
        AND (grant_row.principal_type='everyone'
          OR (grant_row.principal_type='role' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(assignment.role_id)))
          OR user_matches_contextual_acl(p_user_id,target_owner_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            JOIN roles role ON role.id=assignment.role_id
            WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(role.id))))
    );
  END IF;
  RETURN EXISTS (
    SELECT 1 FROM aggregation_child_aggregation_acl_defaults grant_row
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
        OR (grant_row.principal_type='role' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(assignment.role_id)))
        OR user_matches_contextual_acl(p_user_id,target_owner_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          JOIN roles role ON role.id=assignment.role_id
          WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(role.id))))
  );
END $$;

CREATE FUNCTION public.user_has_destination_record_permission(p_user_id bigint, p_aggregation_id bigint, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT EXISTS(
    SELECT 1 FROM aggregations resource
    JOIN aggregation_child_record_acl_defaults grant_row
      ON grant_row.aggregation_id=resource.id
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE resource.id=p_aggregation_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;

CREATE FUNCTION public.user_has_global_privilege(p_user_id bigint, p_code text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT EXISTS (
    SELECT 1
      FROM users account
      JOIN user_role_assignments assignment ON assignment.user_id=account.id
      JOIN roles role ON role.id=assignment.role_id
      JOIN profile_privileges membership ON membership.profile_id=role.profile_id
      JOIN privileges privilege ON privilege.id=membership.privilege_id
     WHERE account.id=p_user_id AND account.status='active'
       AND assignment.valid_from<=CURRENT_TIMESTAMP
       AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
       AND role_effectively_active(role.id)
       AND privilege.code=p_code
  )
$$;

CREATE FUNCTION public.user_has_governance_clearance(p_user_id bigint, p_security_level_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT EXISTS(
    SELECT 1 FROM user_role_assignments assignment
    JOIN roles role ON role.id=assignment.role_id
    JOIN security_levels role_level ON role_level.id=role.security_level_id
    JOIN security_levels required ON required.id=p_security_level_id
    WHERE assignment.user_id=p_user_id AND role.is_information_governance
      AND assignment.valid_from<=CURRENT_TIMESTAMP
      AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
      AND role_effectively_active(role.id)
      AND role_level.level_number>=required.level_number)
$$;

CREATE FUNCTION public.user_has_record_permission(p_user_id bigint, p_record_id bigint, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN record_acl_grants grant_row ON NOT resource.inherit_acl_from_parent
      AND grant_row.record_id=resource.id AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  ) OR EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN aggregation_child_record_acl_defaults grant_row
      ON resource.inherit_acl_from_parent AND grant_row.aggregation_id=resource.aggregation_id
      AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;

CREATE FUNCTION public.user_matches_contextual_acl(p_user bigint, p_owner bigint, p_principal text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT EXISTS(SELECT 1 FROM contextual_acl_roles(p_owner,p_principal) match
  JOIN user_role_assignments assignment ON assignment.role_id=match.role_id
  WHERE assignment.user_id=p_user AND assignment.valid_from<=CURRENT_TIMESTAMP
   AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP))
$$;

CREATE FUNCTION public.validate_acl_dependencies() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE owner_id bigint; owner_column text; missing boolean;
BEGIN
  owner_column := TG_ARGV[0];
  owner_id := CASE WHEN TG_OP='DELETE' THEN (to_jsonb(OLD)->>owner_column)::bigint ELSE (to_jsonb(NEW)->>owner_column)::bigint END;
  EXECUTE format($query$
    SELECT EXISTS(
      SELECT 1 FROM %I grant_row
      JOIN permission_dependencies dependency ON dependency.permission_id=grant_row.permission_id
      WHERE grant_row.%I=$1
        AND grant_row.principal_type=$2
        AND grant_row.role_id IS NOT DISTINCT FROM $3
        AND NOT EXISTS (
          SELECT 1 FROM %I required_grant
          WHERE required_grant.%I=grant_row.%I
            AND required_grant.principal_type=grant_row.principal_type
            AND required_grant.role_id IS NOT DISTINCT FROM grant_row.role_id
            AND required_grant.permission_id=dependency.required_permission_id))
  $query$,TG_TABLE_NAME,owner_column,TG_TABLE_NAME,owner_column,owner_column)
  INTO missing USING owner_id,
    CASE WHEN TG_OP='DELETE' THEN OLD.principal_type ELSE NEW.principal_type END,
    CASE WHEN TG_OP='DELETE' THEN OLD.role_id ELSE NEW.role_id END;
  IF missing THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='permission_dependency_violation';
  END IF;
  RETURN NULL;
END $_$;

CREATE FUNCTION public.validate_acl_permission_type() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE expected text;
BEGIN
  expected := CASE WHEN TG_TABLE_NAME='aggregation_child_record_acl_defaults' OR TG_TABLE_NAME='record_acl_grants' THEN 'record' ELSE 'aggregation' END;
  IF NOT EXISTS (SELECT 1 FROM permissions WHERE id=NEW.permission_id AND resource_type=expected) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='acl_permission_type_mismatch';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION public.validate_acl_role_clearance() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE owner_id bigint; sufficient boolean;
BEGIN
  IF NEW.principal_type <> 'role' THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='record_acl_grants' THEN
    SELECT role_level.level_number>=resource_level.level_number INTO sufficient
    FROM roles role JOIN security_levels role_level ON role_level.id=role.security_level_id
    JOIN records resource ON resource.id=NEW.record_id
    JOIN security_levels resource_level ON resource_level.id=resource.security_level_id
    WHERE role.id=NEW.role_id;
  ELSE
    SELECT role_level.level_number>=resource_level.level_number INTO sufficient
    FROM roles role JOIN security_levels role_level ON role_level.id=role.security_level_id
    JOIN aggregations resource ON resource.id=NEW.aggregation_id
    JOIN security_levels resource_level ON resource_level.id=resource.security_level_id
    WHERE role.id=NEW.role_id;
  END IF;
  IF NOT coalesce(sufficient,false) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='role_clearance_below_resource';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION public.validate_active_role_assignment() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    selected_account_type text;
    selected_role_restriction text;
    selected_role_is_system boolean;
BEGIN
    SELECT account_type INTO selected_account_type
    FROM users
    WHERE id=NEW.user_id AND date_deactivated IS NULL AND date_suspended IS NULL;
    IF selected_account_type IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role assignments require an active user';
    END IF;
    SELECT account_type_restriction,is_system
      INTO selected_role_restriction,selected_role_is_system
      FROM roles WHERE id=NEW.role_id;
    IF NOT role_effectively_active(NEW.role_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role assignments require an effectively active role and organization hierarchy';
    END IF;
    IF selected_role_restriction IS NOT NULL
       AND selected_role_restriction<>selected_account_type THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role account type restriction does not match user account type';
    END IF;
    IF selected_role_is_system AND EXISTS (
        SELECT 1 FROM user_role_assignments existing
        WHERE existing.user_id=NEW.user_id AND existing.id<>COALESCE(NEW.id,0)
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='service system role must be the account only role assignment';
    END IF;
    IF NOT selected_role_is_system AND EXISTS (
        SELECT 1 FROM user_role_assignments existing
        JOIN roles existing_role ON existing_role.id=existing.role_id
        WHERE existing.user_id=NEW.user_id AND existing.id<>COALESCE(NEW.id,0)
          AND existing_role.is_system AND existing_role.account_type_restriction='service'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='service system role must be the account only role assignment';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_aggregation_classification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    classification_terminal boolean;
    scheme_id bigint;
BEGIN
    IF NEW.parent_aggregation_id IS NULL THEN
        IF NEW.classification_id IS NULL THEN
            RAISE EXCEPTION 'root aggregations must have a classification';
        END IF;
        SELECT is_terminal, classification_scheme_id
        INTO classification_terminal, scheme_id
        FROM classifications WHERE id = NEW.classification_id;
        IF NOT COALESCE(classification_terminal, false) THEN
            RAISE EXCEPTION 'root aggregations must use a terminal classification';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM effective_classification_retention_rule(NEW.classification_id)
        ) THEN
            RAISE EXCEPTION 'selected classification has no effective retention rule';
        END IF;
        IF TG_OP = 'INSERT'
           OR NEW.classification_id IS DISTINCT FROM OLD.classification_id
           OR NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id THEN
            IF NOT classification_scheme_is_eligible(scheme_id) THEN
                RAISE EXCEPTION 'selected classification scheme is not active and published';
            END IF;
            IF NOT classification_is_effectively_active(NEW.classification_id) THEN
                RAISE EXCEPTION 'selected classification or one of its ancestors is deactivated';
            END IF;
        END IF;
    ELSIF NEW.classification_id IS NOT NULL THEN
        RAISE EXCEPTION 'child aggregations cannot have a classification';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_aggregation_closure_date() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_closed IS NOT NULL AND NEW.date_closed > CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'date_closed cannot be in the future';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_classification_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated > CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'classification date_deactivated cannot be in the future';
    END IF;
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated < NEW.date_created THEN
        RAISE EXCEPTION 'classification date_deactivated cannot precede date_created';
    END IF;
    IF TG_OP = 'UPDATE'
       AND OLD.date_first_used IS NOT NULL
       AND NEW.date_first_used IS DISTINCT FROM OLD.date_first_used THEN
        RAISE EXCEPTION 'classification date_first_used is immutable once set';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_classification_scheme_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated > CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'classification scheme date_deactivated cannot be in the future';
    END IF;
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated < NEW.date_created THEN
        RAISE EXCEPTION 'classification scheme date_deactivated cannot precede date_created';
    END IF;
    IF TG_OP = 'UPDATE'
       AND OLD.date_first_used IS NOT NULL
       AND NEW.date_first_used IS DISTINCT FROM OLD.date_first_used THEN
        RAISE EXCEPTION 'classification scheme date_first_used is immutable once set';
    END IF;
    IF TG_OP = 'UPDATE'
       AND OLD.date_published IS NOT NULL
       AND NEW.date_published IS NULL THEN
        IF OLD.date_first_used IS NOT NULL THEN
            RAISE EXCEPTION 'a classification scheme that has governed an aggregation cannot be unpublished';
        END IF;
        IF NULLIF(current_setting('app.change_reason', true), '') IS NULL THEN
            RAISE EXCEPTION 'unpublishing a classification scheme requires a change reason';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_classification_structure() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    parent_scheme bigint;
    parent_terminal boolean;
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.classification_scheme_id IS DISTINCT FROM OLD.classification_scheme_id THEN
        RAISE EXCEPTION 'a classification cannot be moved to another scheme';
    END IF;

    IF NEW.parent_classification_id IS NOT NULL THEN
        SELECT classification_scheme_id, is_terminal
        INTO parent_scheme, parent_terminal
        FROM classifications
        WHERE id = NEW.parent_classification_id;
        IF parent_scheme IS NULL THEN
            RAISE EXCEPTION 'parent classification does not exist';
        END IF;
        IF parent_scheme <> NEW.classification_scheme_id THEN
            RAISE EXCEPTION 'parent classification must belong to the same scheme';
        END IF;
        IF parent_terminal THEN
            RAISE EXCEPTION 'terminal classifications cannot contain child classifications';
        END IF;
        IF EXISTS (
            WITH RECURSIVE descendants AS (
                SELECT id FROM classifications WHERE parent_classification_id = NEW.id
                UNION ALL
                SELECT child.id
                FROM classifications AS child
                JOIN descendants AS parent ON child.parent_classification_id = parent.id
            )
            SELECT 1 FROM descendants WHERE id = NEW.parent_classification_id
        ) THEN
            RAISE EXCEPTION 'classification hierarchy cannot contain a cycle';
        END IF;
    END IF;

    IF NEW.is_terminal AND EXISTS (
        SELECT 1 FROM classifications WHERE parent_classification_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'a classification with children cannot be terminal';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.is_terminal AND NOT NEW.is_terminal
       AND EXISTS (SELECT 1 FROM aggregations WHERE classification_id = NEW.id) THEN
        RAISE EXCEPTION 'an assigned terminal classification cannot become a branch';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_component_search_identity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.content_set_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM digital_component_content_sets content_set
        WHERE content_set.id=NEW.content_set_id
          AND content_set.digital_component_id=NEW.digital_component_id
    ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='search content set does not belong to component'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM digital_components component
        WHERE component.id=NEW.digital_component_id AND component.record_id=NEW.record_id
    ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='search record does not match component'; END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION public.validate_hold_person_reference() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE selected_user_id bigint;
BEGIN
    IF TG_TABLE_NAME='holds' THEN
        selected_user_id:=NEW.owner_user_id;
    ELSE
        selected_user_id:=NEW.user_id;
    END IF;
    IF NOT EXISTS(SELECT 1 FROM users WHERE id=selected_user_id AND account_type='person'
                  AND date_deactivated IS NULL AND date_suspended IS NULL) THEN
        RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='hold_owner_or_contributor_must_be_active_person';
    END IF;
    IF TG_TABLE_NAME='hold_contributors' THEN
        IF EXISTS(SELECT 1 FROM holds WHERE id=NEW.hold_id AND owner_user_id=NEW.user_id) THEN
            RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='hold_owner_cannot_be_contributor';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_multilingual_entity_translations() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE locale_entry record;field_entry record;allowed_fields text[];
BEGIN
 IF NEW.translations IS NULL THEN RETURN NEW;END IF;
 allowed_fields:=CASE WHEN TG_TABLE_NAME IN ('classification_schemes','classifications') THEN ARRAY['title','description'] ELSE ARRAY['name','description'] END;
 FOR locale_entry IN SELECT key,value FROM jsonb_each(NEW.translations) LOOP
  IF locale_entry.key !~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$' OR NOT EXISTS(SELECT 1 FROM supported_languages WHERE language_tag=locale_entry.key AND is_enabled) OR jsonb_typeof(locale_entry.value)<>'object' OR locale_entry.value='{}'::jsonb THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='invalid_entity_translation_locale',DETAIL=locale_entry.key;END IF;
  FOR field_entry IN SELECT key,value FROM jsonb_each(locale_entry.value) LOOP
   IF NOT field_entry.key=ANY(allowed_fields) OR jsonb_typeof(field_entry.value)<>'string' OR btrim(field_entry.value #>> '{}')='' OR field_entry.value #>> '{}'<>btrim(field_entry.value #>> '{}') THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='invalid_entity_translation_field',DETAIL=locale_entry.key||'.'||field_entry.key;END IF;
  END LOOP;
 END LOOP;RETURN NEW;
END;$_$;

CREATE FUNCTION public.validate_org_unit_designated_roles() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE designated bigint;
BEGIN
 FOREACH designated IN ARRAY ARRAY[NEW.managing_role_id,NEW.file_administrator_role_id] LOOP
  IF designated IS NOT NULL AND NOT EXISTS (
   SELECT 1 FROM roles WHERE id=designated AND org_unit_id=NEW.id AND NOT is_system
    AND account_type_restriction IS DISTINCT FROM 'service'
  ) THEN RAISE EXCEPTION 'designated role must belong to the same unit and be a non-system person role' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NEW.file_administrator_role_id IS DISTINCT FROM OLD.file_administrator_role_id
   AND NEW.file_administrator_role_id IS NOT NULL
   AND NOT role_effectively_active(NEW.file_administrator_role_id) THEN
  RAISE EXCEPTION 'File Administrator role must be active' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.validate_root_aggregation_retention_rules() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE invalid_number text;
BEGIN
    SELECT a.aggregation_number INTO invalid_number
    FROM aggregation_retention_rules AS rule
    JOIN aggregations AS a ON a.id = rule.aggregation_id
    WHERE a.parent_aggregation_id IS NOT NULL
    ORDER BY a.id LIMIT 1;
    IF invalid_number IS NOT NULL THEN
        RAISE EXCEPTION 'child aggregation % cannot have a local retention rule', invalid_number;
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION public.validate_saved_search_owner() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM users owner
        WHERE owner.id=NEW.owner_user_id AND owner.account_type='person'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='saved_search_owner_must_be_person';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_service_account_credential() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM users account
        WHERE account.id=NEW.service_user_id AND account.account_type='service'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='API key target must be a service account';
    END IF;
    IF NEW.created_by_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM users actor
        WHERE actor.id=NEW.created_by_user_id AND actor.account_type='person'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='API key creator must be a person account';
    END IF;
    IF NEW.revoked_by_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM users actor
        WHERE actor.id=NEW.revoked_by_user_id AND actor.account_type='person'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='API key revoker must be a person account';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.validate_terminal_classification_rules() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE missing_code text;
BEGIN
    SELECT c.code INTO missing_code
    FROM classifications AS c
    WHERE c.is_terminal
      AND NOT EXISTS (
          SELECT 1 FROM effective_classification_retention_rule(c.id)
      )
    ORDER BY c.id LIMIT 1;
    IF missing_code IS NOT NULL THEN
        RAISE EXCEPTION 'terminal classification % has no effective retention rule', missing_code;
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION public.validate_user_management_lifecycle_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated > clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE=TG_TABLE_NAME || ' deactivation date cannot be in the future';
    END IF;
    IF TG_TABLE_NAME = 'users'
       AND NULLIF(to_jsonb(NEW)->>'date_suspended', '')::timestamptz > clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='user suspension date cannot be in the future';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE disposition_private.approval_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    command_id uuid NOT NULL,
    job_id bigint NOT NULL,
    task_id bigint NOT NULL,
    acting_role_id bigint NOT NULL,
    membership_snapshot jsonb NOT NULL,
    proposal_snapshot jsonb NOT NULL,
    phase text NOT NULL,
    current_proposal_id bigint,
    reason_used text,
    reason_source text
);

CREATE TABLE disposition_private.command_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    command_id uuid NOT NULL
);

CREATE TABLE disposition_private.command_receipts (
    command_id uuid NOT NULL,
    actor_user_id bigint,
    acting_role_id bigint,
    operation text NOT NULL,
    payload jsonb NOT NULL,
    reason text NOT NULL,
    result jsonb,
    started_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    completed_at timestamp with time zone,
    actor_type text DEFAULT 'user'::text NOT NULL,
    CONSTRAINT command_receipts_check CHECK (((result IS NULL) = (completed_at IS NULL))),
    CONSTRAINT command_receipts_operation_check CHECK ((operation = ANY (ARRAY['job_create'::text, 'job_assign'::text, 'membership_add'::text, 'membership_remove'::text, 'eligibility_evaluate'::text, 'eligibility_accelerate'::text, 'job_terminate'::text, 'resolve_partial'::text, 'task_claim'::text, 'task_release'::text, 'task_reassign'::text, 'task_complete'::text, 'review_save'::text, 'review_submit'::text, 'review_decide'::text, 'document_save'::text, 'selective_decide'::text, 'final_complete'::text, 'recalculate'::text, 'job_owner_change'::text]))),
    CONSTRAINT command_receipts_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT command_receipts_reason_check CHECK (((operation = ANY (ARRAY['job_create'::text, 'membership_add'::text, 'task_claim'::text])) OR (btrim(reason) <> ''::text))),
    CONSTRAINT disposition_command_actor CHECK ((((actor_type = 'user'::text) AND (actor_user_id IS NOT NULL) AND (acting_role_id IS NOT NULL)) OR ((actor_type = 'automated_process'::text) AND (actor_user_id IS NULL) AND (acting_role_id IS NULL) AND (operation = ANY (ARRAY['eligibility_evaluate'::text, 'task_release'::text])))))
);

CREATE TABLE disposition_private.communication_context (
    transaction_id bigint NOT NULL
);

CREATE TABLE disposition_private.completion_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    command_id uuid NOT NULL,
    job_id bigint NOT NULL
);

CREATE TABLE disposition_private.completion_work (
    job_id bigint NOT NULL,
    request_id uuid NOT NULL,
    task_id bigint NOT NULL,
    requested_by_user_id bigint NOT NULL,
    acting_role_id bigint NOT NULL,
    state text NOT NULL,
    requested_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    claim_token uuid,
    last_error_code text,
    document_id bigint,
    CONSTRAINT completion_work_state_check CHECK ((state = ANY (ARRAY['queued'::text, 'running'::text, 'failed'::text, 'succeeded'::text])))
);

CREATE TABLE disposition_private.destruction_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    command_id uuid,
    run_id bigint,
    root_id bigint,
    claim_token uuid,
    mode text NOT NULL,
    CONSTRAINT destruction_context_mode_check CHECK ((mode = ANY (ARRAY['request'::text, 'claim'::text, 'fail'::text, 'delete'::text, 'finalize'::text])))
);

CREATE TABLE disposition_private.destruction_identities (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    root_id bigint NOT NULL,
    identities jsonb NOT NULL
);

CREATE TABLE disposition_private.destruction_numbers (
    number text NOT NULL,
    job_id bigint NOT NULL,
    CONSTRAINT destruction_numbers_number_check CHECK (((btrim(number) <> ''::text) AND (char_length(number) <= 20)))
);

CREATE TABLE disposition_private.destruction_scopes (
    run_id bigint NOT NULL,
    root_id bigint NOT NULL,
    scope jsonb NOT NULL
);

CREATE TABLE disposition_private.email_payloads (
    attempt_id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    checksum text NOT NULL,
    database_id text NOT NULL,
    encrypted_password bytea,
    worker_token uuid,
    lease_expires_at timestamp with time zone
);

CREATE TABLE disposition_private.external_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    command_id uuid NOT NULL,
    job_id bigint NOT NULL,
    phase text NOT NULL,
    CONSTRAINT external_context_phase_check CHECK ((phase = ANY (ARRAY['request'::text, 'decision'::text, 'invalidate'::text])))
);

CREATE TABLE disposition_private.job_number_counters (
    job_type text NOT NULL,
    number_year integer NOT NULL,
    last_number bigint NOT NULL,
    CONSTRAINT job_number_counters_job_type_check CHECK ((job_type = ANY (ARRAY['destruction'::text, 'permanent_transfer'::text, 'selective_transfer'::text, 'local_archives'::text]))),
    CONSTRAINT job_number_counters_last_number_check CHECK ((last_number > 0))
);

CREATE TABLE disposition_private.physical_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    command_id uuid NOT NULL,
    job_id bigint NOT NULL
);

CREATE TABLE disposition_private.processing_copies (
    token uuid NOT NULL,
    component_id bigint NOT NULL,
    owner_user_id bigint NOT NULL,
    kind text NOT NULL,
    worker_id text,
    indexing_job_id bigint,
    indexing_generation bigint,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT processing_copies_kind_check CHECK ((kind = ANY (ARRAY['rendition'::text, 'text_indexing'::text])))
);

CREATE TABLE disposition_private.recalculation_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    root_id bigint NOT NULL,
    old_evaluation jsonb NOT NULL,
    old_status smallint NOT NULL,
    cause text NOT NULL,
    applying boolean DEFAULT false NOT NULL,
    target_status smallint
);

CREATE TABLE disposition_private.recovery_context (
    transaction_id bigint NOT NULL,
    backend_id integer NOT NULL,
    command_id uuid NOT NULL,
    job_id bigint NOT NULL,
    root_id bigint DEFAULT 0 NOT NULL,
    target_status integer
);

CREATE TABLE disposition_private.reminder_checkpoints (
    producer_code text NOT NULL,
    scheduled_at timestamp with time zone NOT NULL,
    recipient_user_id bigint NOT NULL,
    sent_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);

CREATE TABLE disposition_private.reminder_schedule (
    producer_code text NOT NULL,
    anchor_at timestamp with time zone NOT NULL,
    months integer NOT NULL,
    setting_version integer NOT NULL,
    interval_index integer DEFAULT 1 NOT NULL,
    recipient_after bigint DEFAULT 0 NOT NULL,
    CONSTRAINT reminder_schedule_months_check CHECK ((months > 0))
);

CREATE TABLE public.aggregation_acl_grants (
    id bigint NOT NULL,
    aggregation_id bigint NOT NULL,
    principal_type text NOT NULL,
    role_id bigint,
    permission_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT aggregation_acl_grants_principal_valid CHECK ((((principal_type = 'role'::text) AND (role_id IS NOT NULL)) OR ((principal_type = ANY (ARRAY['everyone'::text, 'org_unit_members'::text, 'owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text])) AND (role_id IS NULL)))),
    CONSTRAINT aggregation_acl_grants_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.aggregation_acl_grants_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.aggregation_acl_grants_id_seq OWNED BY public.aggregation_acl_grants.id;

CREATE TABLE public.aggregation_child_aggregation_acl_defaults (
    id bigint DEFAULT nextval('public.aggregation_acl_grants_id_seq'::regclass) CONSTRAINT aggregation_acl_grants_id_not_null NOT NULL,
    principal_type text CONSTRAINT aggregation_acl_grants_principal_type_not_null NOT NULL,
    role_id bigint,
    permission_id bigint CONSTRAINT aggregation_acl_grants_permission_id_not_null NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP CONSTRAINT aggregation_acl_grants_date_created_not_null NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP CONSTRAINT aggregation_acl_grants_date_updated_not_null NOT NULL,
    version integer DEFAULT 1 CONSTRAINT aggregation_acl_grants_version_not_null NOT NULL,
    aggregation_id bigint CONSTRAINT aggregation_child_aggregation_acl_defau_aggregation_id_not_null NOT NULL,
    CONSTRAINT aggregation_child_aggregation_acl_defaults_principal_valid CHECK ((((principal_type = 'role'::text) AND (role_id IS NOT NULL)) OR ((principal_type = ANY (ARRAY['everyone'::text, 'org_unit_members'::text, 'owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text])) AND (role_id IS NULL))))
);

CREATE TABLE public.aggregation_child_record_acl_defaults (
    id bigint DEFAULT nextval('public.aggregation_acl_grants_id_seq'::regclass) CONSTRAINT aggregation_acl_grants_id_not_null NOT NULL,
    principal_type text CONSTRAINT aggregation_acl_grants_principal_type_not_null NOT NULL,
    role_id bigint,
    permission_id bigint CONSTRAINT aggregation_acl_grants_permission_id_not_null NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP CONSTRAINT aggregation_acl_grants_date_created_not_null NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP CONSTRAINT aggregation_acl_grants_date_updated_not_null NOT NULL,
    version integer DEFAULT 1 CONSTRAINT aggregation_acl_grants_version_not_null NOT NULL,
    aggregation_id bigint NOT NULL,
    CONSTRAINT aggregation_child_record_acl_defaults_principal_valid CHECK ((((principal_type = 'role'::text) AND (role_id IS NOT NULL)) OR ((principal_type = ANY (ARRAY['everyone'::text, 'org_unit_members'::text, 'owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text])) AND (role_id IS NULL))))
);

CREATE TABLE public.aggregation_relationships (
    id bigint NOT NULL,
    relationship_type_id bigint NOT NULL,
    source_id bigint NOT NULL,
    target_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT aggregation_relationships_check CHECK ((source_id <> target_id))
);

CREATE SEQUENCE public.aggregation_relationships_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.aggregation_relationships_id_seq OWNED BY public.aggregation_relationships.id;

CREATE TABLE public.aggregation_retention_rules (
    id bigint NOT NULL,
    aggregation_id bigint NOT NULL,
    current_period_years integer NOT NULL,
    intermediate_period_years integer NOT NULL,
    final_disposition text NOT NULL,
    instructions text,
    justification text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT aggregation_retention_rules_current_period_years_check CHECK ((current_period_years >= 0)),
    CONSTRAINT aggregation_retention_rules_final_disposition_check CHECK ((final_disposition = ANY (ARRAY['destruction'::text, 'transfer_to_external_archive'::text, 'selective_preservation'::text, 'retain_as_local_archives'::text]))),
    CONSTRAINT aggregation_retention_rules_intermediate_period_years_check CHECK ((intermediate_period_years >= 0)),
    CONSTRAINT aggregation_retention_rules_justification_check CHECK ((btrim(justification) <> ''::text)),
    CONSTRAINT aggregation_retention_rules_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.aggregation_retention_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.aggregation_retention_rules_id_seq OWNED BY public.aggregation_retention_rules.id;

CREATE TABLE public.aggregation_search_documents (
    aggregation_id bigint NOT NULL,
    search_vector tsvector NOT NULL,
    text_search_config regconfig NOT NULL,
    indexed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    index_config_version text NOT NULL,
    CONSTRAINT aggregation_search_documents_config_version_not_blank CHECK ((btrim(index_config_version) <> ''::text))
);

CREATE TABLE public.aggregations (
    id bigint NOT NULL,
    parent_aggregation_id bigint,
    aggregation_number text,
    title text,
    description text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_opened timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    date_closed timestamp with time zone,
    version bigint DEFAULT 1 NOT NULL,
    classification_id bigint,
    security_level_id bigint NOT NULL,
    inherit_acl_from_parent boolean DEFAULT true NOT NULL,
    default_child_aggregation_acl_mode text DEFAULT 'mirror_resource_acl'::text NOT NULL,
    resource_acl_version integer DEFAULT 1 NOT NULL,
    child_aggregation_acl_version integer DEFAULT 1 NOT NULL,
    child_record_acl_version integer DEFAULT 1 NOT NULL,
    owning_org_unit_id bigint NOT NULL,
    medium text DEFAULT 'mixed'::text NOT NULL,
    is_vital boolean DEFAULT false NOT NULL,
    date_of_next_review timestamp with time zone,
    assigned_location text,
    current_location text,
    disposition_status smallint DEFAULT 1 NOT NULL,
    final_disposition_at timestamp with time zone,
    final_disposition_by_user_id bigint,
    disposition_job_id bigint,
    destruction_number text,
    transfer_number text,
    final_disposition_event_id bigint,
    CONSTRAINT aggregations_acl_versions_positive CHECK (((resource_acl_version > 0) AND (child_aggregation_acl_version > 0) AND (child_record_acl_version > 0))),
    CONSTRAINT aggregations_assigned_location_valid CHECK (((assigned_location IS NULL) OR ((assigned_location = btrim(assigned_location)) AND (assigned_location <> ''::text) AND (char_length(assigned_location) <= 200)))),
    CONSTRAINT aggregations_child_acl_mode_valid CHECK ((default_child_aggregation_acl_mode = ANY (ARRAY['mirror_resource_acl'::text, 'custom'::text]))),
    CONSTRAINT aggregations_current_location_valid CHECK (((current_location IS NULL) OR ((current_location = btrim(current_location)) AND (current_location <> ''::text) AND (char_length(current_location) <= 200)))),
    CONSTRAINT aggregations_dates_in_order CHECK (((date_closed IS NULL) OR (date_closed >= date_opened))),
    CONSTRAINT aggregations_disposition_status_check CHECK (((disposition_status >= 1) AND (disposition_status <= 13))),
    CONSTRAINT aggregations_medium_valid CHECK ((medium = ANY (ARRAY['digital'::text, 'physical'::text, 'mixed'::text]))),
    CONSTRAINT aggregations_not_own_parent CHECK (((parent_aggregation_id IS NULL) OR (parent_aggregation_id <> id))),
    CONSTRAINT aggregations_number_not_blank CHECK ((btrim(aggregation_number) <> ''::text)),
    CONSTRAINT aggregations_root_acl_inheritance_valid CHECK ((((parent_aggregation_id IS NULL) AND (NOT inherit_acl_from_parent)) OR (parent_aggregation_id IS NOT NULL))),
    CONSTRAINT aggregations_root_classification_consistent CHECK ((((parent_aggregation_id IS NULL) AND (classification_id IS NOT NULL)) OR ((parent_aggregation_id IS NOT NULL) AND (classification_id IS NULL)))),
    CONSTRAINT aggregations_title_not_blank CHECK ((btrim(title) <> ''::text)),
    CONSTRAINT aggregations_version_positive CHECK ((version > 0)),
    CONSTRAINT live_aggregation_identity_required CHECK (((disposition_status = 10) OR ((aggregation_number IS NOT NULL) AND (title IS NOT NULL) AND (date_opened IS NOT NULL))))
);

CREATE SEQUENCE public.aggregations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.aggregations_id_seq OWNED BY public.aggregations.id;

CREATE TABLE public.application_settings (
    id bigint NOT NULL,
    key text NOT NULL,
    value jsonb NOT NULL,
    protected_secret bytea,
    provenance text DEFAULT 'default'::text NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by_user_id bigint,
    scheme_reference_id bigint GENERATED ALWAYS AS (
CASE
    WHEN ((key = 'DISPOSITION_CLASSIFICATION_SCHEME_ID'::text) AND (jsonb_typeof(value) = 'number'::text)) THEN ((value #>> '{}'::text[]))::bigint
    ELSE NULL::bigint
END) STORED,
    classification_reference_id bigint GENERATED ALWAYS AS (
CASE
    WHEN ((key = ANY (ARRAY['DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID'::text, 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID'::text])) AND (jsonb_typeof(value) = 'number'::text)) THEN ((value #>> '{}'::text[]))::bigint
    ELSE NULL::bigint
END) STORED,
    CONSTRAINT application_settings_provenance_check CHECK ((provenance = ANY (ARRAY['default'::text, 'configured'::text, 'migrated'::text]))),
    CONSTRAINT application_settings_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.application_settings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.application_settings_id_seq OWNED BY public.application_settings.id;

CREATE TABLE public.application_settings_migration_keys (
    migration_id text NOT NULL,
    key text NOT NULL,
    completed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    completed_by_user_id bigint CONSTRAINT application_settings_migration_ke_completed_by_user_id_not_null NOT NULL,
    resulting_version bigint NOT NULL,
    CONSTRAINT application_settings_migration_keys_migration_id_check CHECK ((btrim(migration_id) <> ''::text)),
    CONSTRAINT application_settings_migration_keys_resulting_version_check CHECK ((resulting_version > 0))
);

CREATE TABLE public.application_settings_state (
    singleton boolean DEFAULT true NOT NULL,
    database_id uuid DEFAULT gen_random_uuid() NOT NULL,
    installation_kind text NOT NULL,
    CONSTRAINT application_settings_state_installation_kind_check CHECK ((installation_kind = ANY (ARRAY['fresh'::text, 'upgrade'::text]))),
    CONSTRAINT application_settings_state_singleton_check CHECK (singleton)
);

CREATE VIEW public.authorized_aggregation_search_documents AS
 SELECT aggregation_id,
    search_vector,
    text_search_config,
    indexed_at,
    index_config_version
   FROM public.aggregation_search_documents document
  WHERE public.current_user_can_view_aggregation(aggregation_id);

CREATE VIEW public.authorized_aggregations_for_search AS
 SELECT resource.id,
    resource.parent_aggregation_id,
    resource.classification_id,
    resource.aggregation_number,
    resource.title,
    resource.description,
    resource.date_created,
    resource.date_opened,
    resource.date_closed,
    resource.security_level_id,
    resource.inherit_acl_from_parent,
    resource.default_child_aggregation_acl_mode,
    resource.resource_acl_version,
    resource.child_aggregation_acl_version,
    resource.child_record_acl_version,
    resource.version,
    resource.owning_org_unit_id,
    resource.medium,
    resource.is_vital,
    resource.date_of_next_review,
    resource.assigned_location,
    resource.current_location,
        CASE
            WHEN (resource.disposition_status <> 10) THEN public.aggregation_effective_assigned_location(resource.id)
            ELSE NULL::text
        END AS effective_assigned_location,
        CASE
            WHEN (resource.disposition_status <> 10) THEN public.aggregation_effective_current_location(resource.id)
            ELSE NULL::text
        END AS effective_current_location,
        CASE
            WHEN ((resource.disposition_status <> 10) AND public.current_user_can_view_aggregation(public.aggregation_effective_assigned_location_source_id(resource.id))) THEN public.aggregation_effective_assigned_location_source_id(resource.id)
            ELSE NULL::bigint
        END AS effective_assigned_location_source_aggregation_id,
        CASE
            WHEN ((resource.disposition_status <> 10) AND public.current_user_can_view_aggregation(public.aggregation_effective_current_location_source_id(resource.id))) THEN public.aggregation_effective_current_location_source_id(resource.id)
            ELSE NULL::bigint
        END AS effective_current_location_source_aggregation_id,
    (hold_state.effective_hold_count > 0) AS on_effective_hold,
    hold_state.resource_state_changes_blocked,
    hold_state.effective_hold_ids,
    resource.disposition_status,
    resource.final_disposition_at,
    resource.final_disposition_by_user_id,
    resource.disposition_job_id,
    resource.destruction_number,
    resource.transfer_number,
    resource.final_disposition_event_id
   FROM (public.aggregations resource
     CROSS JOIN LATERAL ( SELECT (count(*))::integer AS effective_hold_count,
            COALESCE(bool_or(effective.preserve_resource_state), false) AS resource_state_changes_blocked,
            COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id), '{}'::bigint[]) AS effective_hold_ids
           FROM public.effective_holds_for_aggregation(resource.id) effective(hold_id, code, name, preserve_resource_state, is_direct, is_inherited, nearest_assigned_aggregation_id)) hold_state)
  WHERE ((resource.disposition_status <> ALL (ARRAY[10, 11, 12])) OR (disposition_private.can_manage() AND ((resource.disposition_status <> 10) OR disposition_private.retained_access('aggregation'::text, resource.id, false))));

CREATE TABLE public.event_history (
    id bigint NOT NULL,
    occurred_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    transaction_id bigint DEFAULT ((pg_current_xact_id())::text)::bigint NOT NULL,
    entity_type text NOT NULL,
    entity_id bigint NOT NULL,
    operation text NOT NULL,
    actor_user_id bigint,
    actor_name text,
    actor_email text,
    actor_type text DEFAULT 'automated_process'::text NOT NULL,
    source text DEFAULT 'database'::text NOT NULL,
    request_id uuid,
    correlation_id uuid,
    before_state jsonb,
    after_state jsonb,
    changed_fields text[] DEFAULT ARRAY[]::text[] NOT NULL,
    reason text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT event_history_actor_type_not_blank CHECK ((btrim(actor_type) <> ''::text)),
    CONSTRAINT event_history_actor_type_valid CHECK ((actor_type = ANY (ARRAY['user'::text, 'anonymous'::text, 'automated_process'::text]))),
    CONSTRAINT event_history_entity_type_not_blank CHECK ((btrim(entity_type) <> ''::text)),
    CONSTRAINT event_history_metadata_is_object CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT event_history_operation_not_blank CHECK ((btrim(operation) <> ''::text)),
    CONSTRAINT event_history_row_change_states_valid CHECK ((((operation = 'CREATE'::text) AND (before_state IS NULL) AND (after_state IS NOT NULL)) OR ((operation = 'UPDATE'::text) AND (before_state IS NOT NULL) AND (after_state IS NOT NULL)) OR ((operation = 'DELETE'::text) AND (before_state IS NOT NULL) AND (after_state IS NULL)) OR (operation <> ALL (ARRAY['CREATE'::text, 'UPDATE'::text, 'DELETE'::text])))),
    CONSTRAINT event_history_source_not_blank CHECK ((btrim(source) <> ''::text))
);

CREATE VIEW public.authorized_event_history AS
 SELECT event.id,
    event.occurred_at,
    event.transaction_id,
    event.entity_type,
    event.entity_id,
    event.operation,
        CASE
            WHEN visible.allowed THEN event.actor_user_id
            ELSE NULL::bigint
        END AS actor_user_id,
        CASE
            WHEN visible.allowed THEN event.actor_name
            ELSE NULL::text
        END AS actor_name,
        CASE
            WHEN visible.allowed THEN event.actor_email
            ELSE NULL::text
        END AS actor_email,
    event.actor_type,
    event.source,
    event.request_id,
    event.correlation_id,
        CASE
            WHEN visible.allowed THEN event.before_state
            ELSE NULL::jsonb
        END AS before_state,
        CASE
            WHEN visible.allowed THEN event.after_state
            ELSE NULL::jsonb
        END AS after_state,
        CASE
            WHEN visible.allowed THEN event.changed_fields
            ELSE ARRAY[]::text[]
        END AS changed_fields,
        CASE
            WHEN visible.allowed THEN event.reason
            ELSE NULL::text
        END AS reason,
        CASE
            WHEN visible.allowed THEN event.metadata
            ELSE jsonb_build_object('redacted', true, 'reason', 'resource_access_denied')
        END AS metadata
   FROM (public.event_history event
     CROSS JOIN LATERAL ( SELECT public.current_user_can_view_event_resource(event.entity_type, event.entity_id, COALESCE(event.before_state,
                CASE
                    WHEN (event.entity_type ~~ 'disposition_%'::text) THEN (event.metadata -> 'before'::text)
                    ELSE NULL::jsonb
                END), COALESCE(event.after_state,
                CASE
                    WHEN ((event.entity_type = 'aggregation'::text) AND (event.metadata ? 'recovery_job_id'::text)) THEN event.metadata
                    WHEN (event.entity_type ~~ 'disposition_%'::text) THEN (event.metadata -> 'after'::text)
                    ELSE NULL::jsonb
                END)) AS allowed) visible);

CREATE TABLE public.record_search_documents (
    record_id bigint NOT NULL,
    search_vector tsvector NOT NULL,
    text_search_config regconfig NOT NULL,
    indexed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    index_config_version text NOT NULL,
    CONSTRAINT record_search_documents_config_version_not_blank CHECK ((btrim(index_config_version) <> ''::text))
);

CREATE VIEW public.authorized_record_search_documents AS
 SELECT record_id,
    search_vector,
    text_search_config,
    indexed_at,
    index_config_version
   FROM public.record_search_documents document
  WHERE public.current_user_can_view_record(record_id);

CREATE TABLE public.records (
    id bigint NOT NULL,
    aggregation_id bigint NOT NULL,
    record_number text,
    title text,
    description text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_originated timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    version bigint DEFAULT 1 NOT NULL,
    security_level_id bigint NOT NULL,
    inherit_acl_from_parent boolean DEFAULT true NOT NULL,
    resource_acl_version integer DEFAULT 1 NOT NULL,
    owning_org_unit_id bigint NOT NULL,
    medium text DEFAULT 'mixed'::text NOT NULL,
    is_vital boolean DEFAULT false NOT NULL,
    date_of_next_review timestamp with time zone,
    disposition_status smallint DEFAULT 1 NOT NULL,
    final_disposition_at timestamp with time zone,
    final_disposition_by_user_id bigint,
    disposition_job_id bigint,
    destruction_number text,
    transfer_number text,
    final_disposition_event_id bigint,
    CONSTRAINT live_record_identity_required CHECK (((disposition_status = 10) OR ((record_number IS NOT NULL) AND (title IS NOT NULL) AND (date_originated IS NOT NULL)))),
    CONSTRAINT records_disposition_status_check CHECK (((disposition_status >= 1) AND (disposition_status <= 13))),
    CONSTRAINT records_medium_valid CHECK ((medium = ANY (ARRAY['digital'::text, 'physical'::text, 'mixed'::text]))),
    CONSTRAINT records_number_not_blank CHECK ((btrim(record_number) <> ''::text)),
    CONSTRAINT records_resource_acl_version_check CHECK ((resource_acl_version > 0)),
    CONSTRAINT records_title_not_blank CHECK ((btrim(title) <> ''::text)),
    CONSTRAINT records_version_positive CHECK ((version > 0))
);

CREATE VIEW public.authorized_records_for_search AS
 SELECT resource.id,
    resource.aggregation_id,
    resource.record_number,
    resource.title,
    resource.description,
    resource.date_created,
    resource.date_originated,
    resource.security_level_id,
    resource.inherit_acl_from_parent,
    resource.resource_acl_version,
    resource.version,
    resource.owning_org_unit_id,
    resource.medium,
    resource.is_vital,
    resource.date_of_next_review,
    public.aggregation_effective_assigned_location(resource.aggregation_id) AS effective_assigned_location,
    public.aggregation_effective_current_location(resource.aggregation_id) AS effective_current_location,
        CASE
            WHEN public.current_user_can_view_aggregation(public.aggregation_effective_assigned_location_source_id(resource.aggregation_id)) THEN public.aggregation_effective_assigned_location_source_id(resource.aggregation_id)
            ELSE NULL::bigint
        END AS effective_assigned_location_source_aggregation_id,
        CASE
            WHEN public.current_user_can_view_aggregation(public.aggregation_effective_current_location_source_id(resource.aggregation_id)) THEN public.aggregation_effective_current_location_source_id(resource.aggregation_id)
            ELSE NULL::bigint
        END AS effective_current_location_source_aggregation_id,
    (hold_state.effective_hold_count > 0) AS on_effective_hold,
    hold_state.resource_state_changes_blocked,
    hold_state.effective_hold_ids,
    resource.disposition_status,
    resource.final_disposition_at,
    resource.final_disposition_by_user_id,
    resource.disposition_job_id,
    resource.destruction_number,
    resource.transfer_number,
    resource.final_disposition_event_id
   FROM (public.records resource
     CROSS JOIN LATERAL ( SELECT (count(*))::integer AS effective_hold_count,
            COALESCE(bool_or(effective.preserve_resource_state), false) AS resource_state_changes_blocked,
            COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id), '{}'::bigint[]) AS effective_hold_ids
           FROM public.effective_holds_for_record(resource.id) effective(hold_id, code, name, preserve_resource_state, is_direct, is_inherited, nearest_assigned_aggregation_id)) hold_state)
  WHERE ((resource.disposition_status <> ALL (ARRAY[10, 11, 12])) OR (disposition_private.can_manage() AND ((resource.disposition_status <> 10) OR disposition_private.retained_access('record'::text, resource.id, false))));

CREATE TABLE public.classification_retention_rules (
    id bigint NOT NULL,
    classification_id bigint NOT NULL,
    current_period_years integer NOT NULL,
    intermediate_period_years integer CONSTRAINT classification_retention_rul_intermediate_period_years_not_null NOT NULL,
    final_disposition text NOT NULL,
    instructions text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT classification_retention_rules_current_period_years_check CHECK ((current_period_years >= 0)),
    CONSTRAINT classification_retention_rules_final_disposition_check CHECK ((final_disposition = ANY (ARRAY['destruction'::text, 'transfer_to_external_archive'::text, 'selective_preservation'::text, 'retain_as_local_archives'::text]))),
    CONSTRAINT classification_retention_rules_intermediate_period_years_check CHECK ((intermediate_period_years >= 0)),
    CONSTRAINT classification_retention_rules_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.classification_retention_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.classification_retention_rules_id_seq OWNED BY public.classification_retention_rules.id;

CREATE TABLE public.classification_schemes (
    id bigint NOT NULL,
    code text NOT NULL,
    title text NOT NULL,
    description text,
    authority text,
    scope_note text,
    edition text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_published timestamp with time zone,
    date_deactivated timestamp with time zone,
    date_first_used timestamp with time zone,
    version bigint DEFAULT 1 NOT NULL,
    translations jsonb,
    CONSTRAINT classification_schemes_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT classification_schemes_dates_in_order CHECK (((date_deactivated IS NULL) OR (date_deactivated >= date_created))),
    CONSTRAINT classification_schemes_first_use_in_order CHECK (((date_first_used IS NULL) OR (date_first_used >= date_created))),
    CONSTRAINT classification_schemes_title_not_blank CHECK ((btrim(title) <> ''::text)),
    CONSTRAINT classification_schemes_translations_object CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text))),
    CONSTRAINT classification_schemes_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.classification_schemes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.classification_schemes_id_seq OWNED BY public.classification_schemes.id;

CREATE TABLE public.classifications (
    id bigint NOT NULL,
    classification_scheme_id bigint NOT NULL,
    parent_classification_id bigint,
    code text NOT NULL,
    title text NOT NULL,
    description text,
    authority text,
    scope_note text,
    keywords text,
    is_terminal boolean DEFAULT false NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_deactivated timestamp with time zone,
    date_first_used timestamp with time zone,
    version bigint DEFAULT 1 NOT NULL,
    translations jsonb,
    CONSTRAINT classifications_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT classifications_dates_in_order CHECK (((date_deactivated IS NULL) OR (date_deactivated >= date_created))),
    CONSTRAINT classifications_first_use_in_order CHECK (((date_first_used IS NULL) OR (date_first_used >= date_created))),
    CONSTRAINT classifications_not_own_parent CHECK (((parent_classification_id IS NULL) OR (parent_classification_id <> id))),
    CONSTRAINT classifications_title_not_blank CHECK ((btrim(title) <> ''::text)),
    CONSTRAINT classifications_translations_object CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text))),
    CONSTRAINT classifications_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.classifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.classifications_id_seq OWNED BY public.classifications.id;

CREATE TABLE public.content_indexing_attempts (
    id bigint NOT NULL,
    digital_component_id bigint,
    record_id bigint,
    content_set_id bigint,
    content_checksum_algo text NOT NULL,
    content_checksum_value text NOT NULL,
    trigger text NOT NULL,
    requested_by_user_id bigint,
    job_id bigint,
    worker_id text,
    lease_generation bigint,
    status text NOT NULL,
    attempt_no integer NOT NULL,
    queued_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    extractor_name text,
    extractor_version text,
    extraction_config_version text NOT NULL,
    index_config_version text NOT NULL,
    characters_extracted bigint,
    chunks_created integer,
    ocr_used boolean DEFAULT false NOT NULL,
    error_code text,
    error_summary text,
    request_id text,
    correlation_id text,
    CONSTRAINT content_indexing_attempts_attempt_no_check CHECK ((attempt_no > 0)),
    CONSTRAINT content_indexing_attempts_characters_extracted_check CHECK (((characters_extracted IS NULL) OR (characters_extracted >= 0))),
    CONSTRAINT content_indexing_attempts_chunks_created_check CHECK (((chunks_created IS NULL) OR (chunks_created >= 0))),
    CONSTRAINT content_indexing_attempts_error_bounded CHECK (((error_summary IS NULL) OR (length(error_summary) <= 500))),
    CONSTRAINT content_indexing_attempts_status_valid CHECK ((status = ANY (ARRAY['processing'::text, 'succeeded'::text, 'failed'::text, 'unsupported'::text, 'cancelled'::text, 'lease_lost'::text, 'skipped'::text])))
);

CREATE SEQUENCE public.content_indexing_attempts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.content_indexing_attempts_id_seq OWNED BY public.content_indexing_attempts.id;

CREATE TABLE public.content_indexing_batch_items (
    batch_id uuid NOT NULL,
    digital_component_id bigint,
    job_id bigint,
    disposition text NOT NULL,
    component_identifier bigint NOT NULL,
    CONSTRAINT content_indexing_batch_items_disposition_check CHECK ((disposition = ANY (ARRAY['queued'::text, 'already_in_progress'::text, 'unsupported_or_no_content'::text])))
);

CREATE TABLE public.content_indexing_batches (
    id uuid NOT NULL,
    record_id bigint,
    requested_by_user_id bigint,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    total_components integer NOT NULL,
    queued_count integer NOT NULL,
    already_in_progress_count integer NOT NULL,
    unavailable_count integer NOT NULL,
    CONSTRAINT content_indexing_batch_counts_valid CHECK ((((queued_count + already_in_progress_count) + unavailable_count) = total_components)),
    CONSTRAINT content_indexing_batches_already_in_progress_count_check CHECK ((already_in_progress_count >= 0)),
    CONSTRAINT content_indexing_batches_queued_count_check CHECK ((queued_count >= 0)),
    CONSTRAINT content_indexing_batches_total_components_check CHECK ((total_components >= 0)),
    CONSTRAINT content_indexing_batches_unavailable_count_check CHECK ((unavailable_count >= 0))
);

CREATE TABLE public.content_indexing_jobs (
    id bigint NOT NULL,
    digital_component_id bigint NOT NULL,
    record_id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    content_checksum_algo text NOT NULL,
    content_checksum_value text NOT NULL,
    trigger text NOT NULL,
    priority smallint DEFAULT 0 NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    not_before timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamp with time zone,
    lease_generation bigint DEFAULT 0 NOT NULL,
    attempt_no integer DEFAULT 0 NOT NULL,
    extraction_config_version text NOT NULL,
    index_config_version text NOT NULL,
    extractor_version text NOT NULL,
    required_capabilities jsonb DEFAULT '{}'::jsonb NOT NULL,
    queued_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT content_indexing_jobs_attempt_no_check CHECK ((attempt_no >= 0)),
    CONSTRAINT content_indexing_jobs_capabilities_object CHECK ((jsonb_typeof(required_capabilities) = 'object'::text)),
    CONSTRAINT content_indexing_jobs_lease_generation_check CHECK ((lease_generation >= 0)),
    CONSTRAINT content_indexing_jobs_lease_shape CHECK ((((status = 'leased'::text) AND (lease_owner IS NOT NULL) AND (lease_token IS NOT NULL) AND (lease_expires_at IS NOT NULL)) OR (status <> 'leased'::text))),
    CONSTRAINT content_indexing_jobs_priority_check CHECK (((priority >= '-100'::integer) AND (priority <= 100))),
    CONSTRAINT content_indexing_jobs_status_valid CHECK ((status = ANY (ARRAY['queued'::text, 'leased'::text, 'succeeded'::text, 'failed'::text, 'unsupported'::text, 'cancelled'::text, 'skipped'::text]))),
    CONSTRAINT content_indexing_jobs_trigger_valid CHECK ((trigger = ANY (ARRAY['upload'::text, 'replacement'::text, 'manual_component'::text, 'manual_record'::text, 'backfill'::text, 'retry'::text, 'config_change'::text])))
);

CREATE SEQUENCE public.content_indexing_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.content_indexing_jobs_id_seq OWNED BY public.content_indexing_jobs.id;

CREATE TABLE public.content_indexing_operations (
    job_id bigint NOT NULL,
    lease_generation bigint NOT NULL,
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    response jsonb NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT content_indexing_operations_key_bounded CHECK (((btrim(idempotency_key) <> ''::text) AND (length(idempotency_key) <= 200))),
    CONSTRAINT content_indexing_operations_operation_check CHECK ((operation = ANY (ARRAY['chunk'::text, 'complete'::text, 'fail'::text])))
);

CREATE TABLE public.content_indexing_result_chunks (
    job_id bigint NOT NULL,
    lease_generation bigint NOT NULL,
    chunk_no integer NOT NULL,
    page_from integer,
    page_to integer,
    extracted_text text NOT NULL,
    text_digest text NOT NULL,
    detected_language text,
    language_decision text NOT NULL,
    text_search_config regconfig NOT NULL,
    characters_count integer NOT NULL,
    date_staged timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT content_indexing_result_chunks_characters_count_check CHECK ((characters_count >= 0)),
    CONSTRAINT content_indexing_result_chunks_chunk_no_check CHECK ((chunk_no >= 0)),
    CONSTRAINT result_chunks_digest_format CHECK ((text_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT result_chunks_language_decision_valid CHECK ((language_decision = ANY (ARRAY['english'::text, 'arabic'::text, 'mixed'::text, 'unknown'::text, 'short'::text, 'low_confidence'::text, 'unsupported_script'::text, 'code_like'::text]))),
    CONSTRAINT result_chunks_pages_valid CHECK ((((page_from IS NULL) AND (page_to IS NULL)) OR ((page_from > 0) AND (page_to >= page_from)))),
    CONSTRAINT result_chunks_text_bounded CHECK ((length(extracted_text) <= 20000))
);

CREATE TABLE public.content_upload_sessions (
    id bigint NOT NULL,
    digital_component_id bigint,
    draft_component_id bigint,
    content_set_id bigint,
    status text DEFAULT 'uploading'::text NOT NULL,
    next_segment_no integer DEFAULT 0 NOT NULL,
    bytes_received bigint DEFAULT 0 NOT NULL,
    expected_size bigint,
    checksum_algo text DEFAULT 'sha256'::text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone DEFAULT (CURRENT_TIMESTAMP + '1 day'::interval) NOT NULL,
    CONSTRAINT content_upload_sessions_bytes_received_check CHECK ((bytes_received >= 0)),
    CONSTRAINT content_upload_sessions_check CHECK (((((digital_component_id IS NOT NULL))::integer + ((draft_component_id IS NOT NULL))::integer) = 1)),
    CONSTRAINT content_upload_sessions_check1 CHECK ((((digital_component_id IS NOT NULL) AND (content_set_id IS NOT NULL)) OR ((draft_component_id IS NOT NULL) AND (content_set_id IS NULL)))),
    CONSTRAINT content_upload_sessions_expected_size_check CHECK (((expected_size IS NULL) OR (expected_size >= 0))),
    CONSTRAINT content_upload_sessions_next_segment_no_check CHECK ((next_segment_no >= 0)),
    CONSTRAINT content_upload_sessions_status_check CHECK ((status = ANY (ARRAY['uploading'::text, 'interrupted'::text, 'finalizing'::text, 'completed'::text, 'failed'::text, 'cancelled'::text, 'expired'::text])))
);

CREATE SEQUENCE public.content_upload_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.content_upload_sessions_id_seq OWNED BY public.content_upload_sessions.id;

CREATE TABLE public.digital_component_blobs (
    id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    segment_no integer NOT NULL,
    segment_size integer NOT NULL,
    segment_checksum_algo text,
    segment_checksum_value text,
    content bytea NOT NULL,
    date_stored timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT digital_component_blobs_check CHECK ((segment_size = octet_length(content))),
    CONSTRAINT digital_component_blobs_segment_no_check CHECK ((segment_no >= 0)),
    CONSTRAINT digital_component_blobs_segment_size_check CHECK ((segment_size > 0))
);

CREATE SEQUENCE public.digital_component_blobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.digital_component_blobs_id_seq OWNED BY public.digital_component_blobs.id;

CREATE TABLE public.digital_component_content_sets (
    id bigint NOT NULL,
    digital_component_id bigint NOT NULL,
    status text NOT NULL,
    size_in_bytes bigint,
    segment_count integer,
    checksum_algo text,
    checksum_value text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_completed timestamp with time zone,
    CONSTRAINT digital_component_content_sets_segment_count_check CHECK (((segment_count IS NULL) OR (segment_count >= 0))),
    CONSTRAINT digital_component_content_sets_size_in_bytes_check CHECK (((size_in_bytes IS NULL) OR (size_in_bytes >= 0))),
    CONSTRAINT digital_component_content_sets_status_check CHECK ((status = ANY (ARRAY['staged'::text, 'active'::text, 'superseded'::text, 'failed'::text])))
);

CREATE SEQUENCE public.digital_component_content_sets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.digital_component_content_sets_id_seq OWNED BY public.digital_component_content_sets.id;

CREATE TABLE public.digital_component_search_chunks (
    id bigint NOT NULL,
    digital_component_id bigint NOT NULL,
    chunk_no integer NOT NULL,
    page_from integer,
    page_to integer,
    extracted_text text NOT NULL,
    search_vector tsvector NOT NULL,
    text_search_config regconfig NOT NULL,
    CONSTRAINT component_search_chunks_pages_valid CHECK ((((page_from IS NULL) AND (page_to IS NULL)) OR ((page_from > 0) AND (page_to >= page_from)))),
    CONSTRAINT component_search_chunks_text_bounded CHECK ((length(extracted_text) <= 20000)),
    CONSTRAINT digital_component_search_chunks_chunk_no_check CHECK ((chunk_no >= 0))
);

CREATE SEQUENCE public.digital_component_search_chunks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.digital_component_search_chunks_id_seq OWNED BY public.digital_component_search_chunks.id;

CREATE TABLE public.digital_component_search_documents (
    digital_component_id bigint CONSTRAINT digital_component_search_document_digital_component_id_not_null NOT NULL,
    record_id bigint NOT NULL,
    content_set_id bigint,
    content_checksum_algo text,
    content_checksum_value text,
    status text NOT NULL,
    detected_mime_type text,
    detected_language text,
    extractor_name text,
    extractor_version text,
    extraction_config_version text CONSTRAINT digital_component_search_doc_extraction_config_version_not_null NOT NULL,
    index_config_version text CONSTRAINT digital_component_search_document_index_config_version_not_null NOT NULL,
    indexed_at timestamp with time zone,
    last_attempt_at timestamp with time zone,
    last_error_code text,
    last_error_summary text,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT component_search_error_summary_bounded CHECK (((last_error_summary IS NULL) OR (length(last_error_summary) <= 500))),
    CONSTRAINT component_search_identity_complete CHECK ((((content_set_id IS NULL) AND (content_checksum_algo IS NULL) AND (content_checksum_value IS NULL)) OR ((content_set_id IS NOT NULL) AND (btrim(content_checksum_algo) <> ''::text) AND (btrim(content_checksum_value) <> ''::text)))),
    CONSTRAINT component_search_status_valid CHECK ((status = ANY (ARRAY['pending'::text, 'processing'::text, 'indexed'::text, 'unsupported'::text, 'failed'::text, 'stale'::text])))
);

CREATE TABLE public.digital_components (
    id bigint NOT NULL,
    record_id bigint NOT NULL,
    component_order integer NOT NULL,
    file_name text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_originated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    mime_type text NOT NULL,
    size_in_bytes bigint NOT NULL,
    checksum_algo text NOT NULL,
    checksum_value text NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    storage_backend text DEFAULT 'postgresql'::text NOT NULL,
    storage_key text,
    content_status text DEFAULT 'pending'::text NOT NULL,
    active_content_set_id bigint,
    upload_completed_at timestamp with time zone,
    CONSTRAINT digital_components_checksum_algo_not_blank CHECK ((btrim(checksum_algo) <> ''::text)),
    CONSTRAINT digital_components_checksum_value_not_blank CHECK ((btrim(checksum_value) <> ''::text)),
    CONSTRAINT digital_components_content_status_valid CHECK ((content_status = ANY (ARRAY['pending'::text, 'uploading'::text, 'available'::text, 'failed'::text, 'quarantined'::text, 'deleted'::text]))),
    CONSTRAINT digital_components_file_name_not_blank CHECK ((btrim(file_name) <> ''::text)),
    CONSTRAINT digital_components_mime_type_not_blank CHECK ((btrim(mime_type) <> ''::text)),
    CONSTRAINT digital_components_order_positive CHECK ((component_order > 0)),
    CONSTRAINT digital_components_size_nonnegative CHECK ((size_in_bytes >= 0)),
    CONSTRAINT digital_components_storage_backend_valid CHECK ((storage_backend = ANY (ARRAY['postgresql'::text, 's3'::text]))),
    CONSTRAINT digital_components_storage_location_valid CHECK ((((storage_backend = 'postgresql'::text) AND (storage_key IS NULL)) OR ((storage_backend = 's3'::text) AND (storage_key IS NOT NULL) AND (btrim(storage_key) <> ''::text)))),
    CONSTRAINT digital_components_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.digital_components_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.digital_components_id_seq OWNED BY public.digital_components.id;

CREATE TABLE public.disposition_destruction_manifest_items (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    root_id bigint NOT NULL,
    resource_kind text NOT NULL,
    resource_id bigint NOT NULL,
    record_id bigint,
    source_component_id bigint,
    source_content_set_id bigint,
    checksum_algo text,
    checksum_value text,
    size_in_bytes bigint,
    medium text NOT NULL,
    destruction_state text DEFAULT 'queued'::text CONSTRAINT disposition_destruction_manifest_ite_destruction_state_not_null NOT NULL,
    destroyed_at timestamp with time zone,
    run_id bigint NOT NULL,
    CONSTRAINT disposition_destruction_manifest_items_check CHECK (((destruction_state = 'succeeded'::text) = (destroyed_at IS NOT NULL))),
    CONSTRAINT disposition_destruction_manifest_items_check1 CHECK (((checksum_algo IS NULL) = (checksum_value IS NULL))),
    CONSTRAINT disposition_destruction_manifest_items_destruction_state_check CHECK ((destruction_state = ANY (ARRAY['queued'::text, 'succeeded'::text]))),
    CONSTRAINT disposition_destruction_manifest_items_medium_check CHECK ((medium = ANY (ARRAY['physical'::text, 'digital'::text, 'mixed'::text]))),
    CONSTRAINT disposition_destruction_manifest_items_resource_kind_check CHECK ((resource_kind = ANY (ARRAY['aggregation'::text, 'record'::text, 'component'::text]))),
    CONSTRAINT disposition_destruction_manifest_items_size_in_bytes_check CHECK ((size_in_bytes >= 0))
);

CREATE SEQUENCE public.disposition_destruction_manifest_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_destruction_manifest_items_id_seq OWNED BY public.disposition_destruction_manifest_items.id;

CREATE TABLE public.disposition_destruction_run_units (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    root_id bigint NOT NULL,
    state text DEFAULT 'queued'::text NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    last_error_code text,
    last_error_message text,
    version bigint DEFAULT 1 NOT NULL,
    claim_token uuid,
    CONSTRAINT disposition_destruction_run_units_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT disposition_destruction_run_units_check CHECK (((last_error_code IS NULL) = (last_error_message IS NULL))),
    CONSTRAINT disposition_destruction_run_units_state_check CHECK ((state = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'failed'::text]))),
    CONSTRAINT disposition_destruction_run_units_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.disposition_destruction_run_units_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_destruction_run_units_id_seq OWNED BY public.disposition_destruction_run_units.id;

CREATE TABLE public.disposition_destruction_runs (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    request_id uuid NOT NULL,
    run_number integer NOT NULL,
    state text DEFAULT 'queued'::text NOT NULL,
    requested_by_user_id bigint NOT NULL,
    requested_by_name text NOT NULL,
    acting_role_id bigint NOT NULL,
    task_id bigint NOT NULL,
    requested_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    total_units integer NOT NULL,
    completed_units integer DEFAULT 0 NOT NULL,
    failed_units integer DEFAULT 0 NOT NULL,
    last_error_code text,
    last_error_message text,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT disposition_destruction_runs_check CHECK (((completed_units + failed_units) <= total_units)),
    CONSTRAINT disposition_destruction_runs_check1 CHECK (((last_error_code IS NULL) = (last_error_message IS NULL))),
    CONSTRAINT disposition_destruction_runs_completed_units_check CHECK ((completed_units >= 0)),
    CONSTRAINT disposition_destruction_runs_failed_units_check CHECK ((failed_units >= 0)),
    CONSTRAINT disposition_destruction_runs_last_error_message_check CHECK (((last_error_message IS NULL) OR (length(last_error_message) <= 200))),
    CONSTRAINT disposition_destruction_runs_run_number_check CHECK ((run_number > 0)),
    CONSTRAINT disposition_destruction_runs_state_check CHECK ((state = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'failed'::text]))),
    CONSTRAINT disposition_destruction_runs_total_units_check CHECK ((total_units > 0)),
    CONSTRAINT disposition_destruction_runs_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.disposition_destruction_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_destruction_runs_id_seq OWNED BY public.disposition_destruction_runs.id;

CREATE TABLE public.disposition_email_attempts (
    id bigint NOT NULL,
    command_id uuid NOT NULL,
    job_id bigint NOT NULL,
    document_id bigint NOT NULL,
    review_round integer,
    actor_user_id bigint NOT NULL,
    actor_type text DEFAULT 'user'::text NOT NULL,
    acting_role_id bigint NOT NULL,
    recipient text NOT NULL,
    sender text NOT NULL,
    configuration jsonb NOT NULL,
    requested_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    status text DEFAULT 'sending'::text NOT NULL,
    outcome_at timestamp with time zone,
    message_id text,
    server_message_id text,
    error_code text,
    smtp_code integer,
    CONSTRAINT disposition_email_attempts_actor_type_check CHECK ((actor_type = 'user'::text)),
    CONSTRAINT disposition_email_attempts_check CHECK (((status = 'sending'::text) = (outcome_at IS NULL))),
    CONSTRAINT disposition_email_attempts_configuration_check CHECK ((NOT (configuration ? 'password'::text))),
    CONSTRAINT disposition_email_attempts_status_check CHECK ((status = ANY (ARRAY['sending'::text, 'smtp_accepted'::text, 'failed'::text, 'unknown'::text])))
);

ALTER TABLE public.disposition_email_attempts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.disposition_email_attempts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

CREATE TABLE public.disposition_external_approvals (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    round_id bigint NOT NULL,
    request_document_id bigint NOT NULL,
    task_id bigint NOT NULL,
    decision text NOT NULL,
    correction_notes text,
    destruction_number text,
    approval_letter_document_id bigint,
    rejection_letter_document_id bigint,
    recorded_by_user_id bigint NOT NULL,
    acting_role_id bigint NOT NULL,
    recorded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT disposition_external_approvals_check CHECK ((((decision = 'approved'::text) AND (destruction_number IS NOT NULL) AND (btrim(destruction_number) <> ''::text) AND (char_length(destruction_number) <= 20) AND (approval_letter_document_id IS NOT NULL) AND (rejection_letter_document_id IS NULL)) OR ((decision = 'rejected'::text) AND (correction_notes IS NOT NULL) AND (correction_notes !~ '^[[:space:]]*$'::text) AND (destruction_number IS NULL) AND (approval_letter_document_id IS NULL) AND (rejection_letter_document_id IS NOT NULL)))),
    CONSTRAINT disposition_external_approvals_decision_check CHECK ((decision = ANY (ARRAY['approved'::text, 'rejected'::text]))),
    CONSTRAINT disposition_external_approvals_version_check CHECK ((version = 1))
);

CREATE SEQUENCE public.disposition_external_approvals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_external_approvals_id_seq OWNED BY public.disposition_external_approvals.id;

CREATE TABLE public.disposition_job_documents (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    document_type text NOT NULL,
    document_state text NOT NULL,
    review_round integer,
    record_id bigint,
    digital_component_id bigint,
    created_by_user_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    checksum_algo text,
    checksum text,
    template_version text,
    version integer DEFAULT 1 NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    origin text NOT NULL,
    supersedes_document_id bigint,
    evidence_version integer DEFAULT 1 NOT NULL,
    classification_scheme_id bigint,
    classification_id bigint,
    aggregation_id bigint,
    acting_role_id bigint,
    provenance jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT disposition_job_documents_check CHECK (((document_state <> 'available'::text) OR ((record_id IS NOT NULL) AND (digital_component_id IS NOT NULL) AND (NULLIF(btrim(checksum), ''::text) IS NOT NULL) AND (NULLIF(btrim(checksum_algo), ''::text) IS NOT NULL)))),
    CONSTRAINT disposition_job_documents_document_state_check CHECK ((document_state = ANY (ARRAY['generating'::text, 'available'::text, 'failed'::text]))),
    CONSTRAINT disposition_job_documents_document_type_check CHECK ((document_type = ANY (ARRAY['destruction_request'::text, 'external_rejection_letter'::text, 'external_approval_letter'::text, 'physical_destruction_certificate'::text, 'digital_destruction_certificate'::text, 'proposal_execution_report'::text, 'physical_preparation_report'::text]))),
    CONSTRAINT disposition_job_documents_evidence_version_check CHECK ((evidence_version > 0)),
    CONSTRAINT disposition_job_documents_origin_check CHECK ((origin = ANY (ARRAY['uploaded'::text, 'generated'::text]))),
    CONSTRAINT disposition_job_documents_provenance_check CHECK ((jsonb_typeof(provenance) = 'object'::text)),
    CONSTRAINT disposition_job_documents_review_round_check CHECK ((review_round > 0)),
    CONSTRAINT disposition_job_documents_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.disposition_job_documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_job_documents_id_seq OWNED BY public.disposition_job_documents.id;

CREATE TABLE public.disposition_job_memberships (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    root_aggregation_id bigint NOT NULL,
    membership_state text DEFAULT 'active'::text NOT NULL,
    added_by_user_id bigint NOT NULL,
    added_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    removed_by_user_id bigint,
    removed_at timestamp with time zone,
    removal_reason text,
    version integer DEFAULT 1 NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    removal_required boolean DEFAULT false NOT NULL,
    removal_required_reason text,
    CONSTRAINT disposition_job_memberships_membership_state_check CHECK ((membership_state = ANY (ARRAY['active'::text, 'removed'::text, 'terminated_history'::text, 'completed_history'::text]))),
    CONSTRAINT disposition_job_memberships_version_check CHECK ((version > 0)),
    CONSTRAINT disposition_membership_removal CHECK ((((membership_state = 'removed'::text) AND (removed_by_user_id IS NOT NULL) AND (removed_at IS NOT NULL) AND (NULLIF(btrim(removal_reason), ''::text) IS NOT NULL)) OR ((membership_state <> 'removed'::text) AND (removed_by_user_id IS NULL) AND (removed_at IS NULL) AND (removal_reason IS NULL)))),
    CONSTRAINT disposition_removal_required_reason CHECK (((removal_required AND (removal_required_reason IS NOT NULL) AND (removal_required_reason = ANY (ARRAY['reopened'::text, 'retention_rule_changed'::text]))) OR ((NOT removal_required) AND (removal_required_reason IS NULL))))
);

CREATE SEQUENCE public.disposition_job_memberships_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_job_memberships_id_seq OWNED BY public.disposition_job_memberships.id;

CREATE TABLE public.disposition_jobs (
    id bigint NOT NULL,
    job_number text NOT NULL,
    job_type text NOT NULL,
    lifecycle_state text DEFAULT 'active'::text NOT NULL,
    workflow_stage text,
    disposition_status smallint NOT NULL,
    owning_org_unit_id bigint,
    assigned_user_id bigint,
    current_review_round integer DEFAULT 0 NOT NULL,
    created_by_user_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    completed_by_user_id bigint,
    completed_by_name text,
    completed_at timestamp with time zone,
    terminated_by_user_id bigint,
    terminated_at timestamp with time zone,
    termination_reason text,
    destruction_number text,
    transfer_number text,
    final_event_id bigint,
    version integer DEFAULT 1 NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by_user_id bigint,
    review_route text,
    CONSTRAINT disposition_jobs_completion CHECK ((((lifecycle_state = 'completed'::text) AND (disposition_status = ANY (ARRAY[10, 11, 12])) AND (completed_at IS NOT NULL) AND (completed_by_user_id IS NOT NULL) AND (completed_by_name IS NOT NULL) AND (final_event_id IS NOT NULL)) OR ((lifecycle_state <> 'completed'::text) AND (disposition_status <> ALL (ARRAY[10, 11, 12])) AND (completed_at IS NULL) AND (completed_by_user_id IS NULL) AND (completed_by_name IS NULL) AND (final_event_id IS NULL)))),
    CONSTRAINT disposition_jobs_current_review_round_check CHECK ((current_review_round >= 0)),
    CONSTRAINT disposition_jobs_destruction_number_check CHECK (((destruction_number IS NULL) OR ((btrim(destruction_number) <> ''::text) AND (char_length(destruction_number) <= 20)))),
    CONSTRAINT disposition_jobs_disposition_status_check CHECK (((disposition_status >= 1) AND (disposition_status <= 13))),
    CONSTRAINT disposition_jobs_job_number_check CHECK ((btrim(job_number) <> ''::text)),
    CONSTRAINT disposition_jobs_job_type_check CHECK ((job_type = ANY (ARRAY['destruction'::text, 'permanent_transfer'::text, 'selective_transfer'::text, 'local_archives'::text]))),
    CONSTRAINT disposition_jobs_lifecycle_state_check CHECK ((lifecycle_state = ANY (ARRAY['active'::text, 'completed'::text, 'terminated'::text]))),
    CONSTRAINT disposition_jobs_numbers CHECK ((((destruction_number IS NULL) OR (job_type = 'destruction'::text)) AND ((transfer_number IS NULL) OR (job_type = 'permanent_transfer'::text)) AND ((disposition_status <> 10) OR (destruction_number IS NOT NULL)) AND ((disposition_status <> 11) OR (transfer_number IS NOT NULL)))),
    CONSTRAINT disposition_jobs_stage CHECK ((((job_type = 'destruction'::text) AND (owning_org_unit_id IS NOT NULL) AND (workflow_stage IS NOT NULL) AND (workflow_stage = ANY (ARRAY['officer_preparation'::text, 'officer_correction'::text, 'manager_preparation'::text, 'manager_correction'::text, 'file_administrator_review'::text, 'unit_manager_review'::text, 'records_manager_review'::text, 'external_approval_pending'::text, 'physical_destruction'::text, 'digital_destruction'::text, 'certificate_generation'::text]))) OR ((job_type <> 'destruction'::text) AND (workflow_stage IS NULL)))),
    CONSTRAINT disposition_jobs_termination CHECK ((((lifecycle_state = 'terminated'::text) AND (terminated_at IS NOT NULL) AND (terminated_by_user_id IS NOT NULL) AND (NULLIF(btrim(termination_reason), ''::text) IS NOT NULL)) OR ((lifecycle_state <> 'terminated'::text) AND (terminated_at IS NULL) AND (terminated_by_user_id IS NULL) AND (termination_reason IS NULL)))),
    CONSTRAINT disposition_jobs_transfer_number_check CHECK (((transfer_number IS NULL) OR ((btrim(transfer_number) <> ''::text) AND (char_length(transfer_number) <= 20)))),
    CONSTRAINT disposition_jobs_version_check CHECK ((version > 0)),
    CONSTRAINT disposition_saved_route CHECK ((((job_type = 'destruction'::text) AND (review_route IS NOT NULL) AND (review_route = ANY (ARRAY['standard'::text, 'simplified'::text, 'records_manager_only'::text]))) OR ((job_type <> 'destruction'::text) AND (review_route IS NULL))))
);

CREATE SEQUENCE public.disposition_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_jobs_id_seq OWNED BY public.disposition_jobs.id;

CREATE TABLE public.disposition_physical_confirmations (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    task_id bigint NOT NULL,
    successful boolean NOT NULL,
    certificate_reference text CONSTRAINT disposition_physical_confirmatio_certificate_reference_not_null NOT NULL,
    certificate_document_id bigint CONSTRAINT disposition_physical_confirmat_certificate_document_id_not_null NOT NULL,
    confirmed_by_user_id bigint CONSTRAINT disposition_physical_confirmation_confirmed_by_user_id_not_null NOT NULL,
    acting_role_id bigint NOT NULL,
    confirmed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    confirmation_text text NOT NULL,
    confirmation_version integer CONSTRAINT disposition_physical_confirmation_confirmation_version_not_null NOT NULL,
    physical_scope jsonb NOT NULL,
    CONSTRAINT disposition_physical_confirmations_certificate_reference_check CHECK ((btrim(certificate_reference) <> ''::text)),
    CONSTRAINT disposition_physical_confirmations_confirmation_version_check CHECK ((confirmation_version = 1)),
    CONSTRAINT disposition_physical_confirmations_physical_scope_check CHECK ((jsonb_typeof(physical_scope) = 'object'::text)),
    CONSTRAINT disposition_physical_confirmations_successful_check CHECK (successful)
);

ALTER TABLE public.disposition_physical_confirmations ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.disposition_physical_confirmations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

CREATE TABLE public.disposition_proposal_effects (
    id bigint NOT NULL,
    proposal_id bigint NOT NULL,
    governing_root_id bigint NOT NULL,
    effect_type text NOT NULL,
    previous_status smallint NOT NULL,
    resulting_status smallint NOT NULL,
    membership_id bigint,
    occurred_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    actor_user_id bigint NOT NULL,
    acting_role_id bigint NOT NULL,
    details jsonb NOT NULL,
    CONSTRAINT disposition_proposal_effects_details_check CHECK ((jsonb_typeof(details) = 'object'::text)),
    CONSTRAINT disposition_proposal_effects_effect_type_check CHECK ((effect_type = ANY (ARRAY['resource_changed'::text, 'unit_blocked'::text, 'unit_removed'::text, 'cascading_unit_removed'::text, 'status_recalculated'::text]))),
    CONSTRAINT disposition_proposal_effects_previous_status_check CHECK (((previous_status >= 1) AND (previous_status <= 13))),
    CONSTRAINT disposition_proposal_effects_resulting_status_check CHECK (((resulting_status >= 1) AND (resulting_status <= 13)))
);

CREATE SEQUENCE public.disposition_proposal_effects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_proposal_effects_id_seq OWNED BY public.disposition_proposal_effects.id;

CREATE TABLE public.disposition_proposal_holds (
    proposal_id bigint NOT NULL,
    hold_id bigint NOT NULL,
    hold_snapshot jsonb NOT NULL,
    CONSTRAINT disposition_proposal_holds_hold_id_check CHECK ((hold_id > 0))
);

CREATE TABLE public.disposition_retained_records (
    resource_kind text NOT NULL,
    resource_id bigint NOT NULL,
    root_id bigint NOT NULL,
    job_id bigint NOT NULL,
    run_id bigint,
    parent_resource_id bigint,
    classification_id bigint NOT NULL,
    owning_org_unit_id bigint NOT NULL,
    date_closed timestamp with time zone,
    calculated_disposition_at timestamp with time zone,
    rule_snapshot jsonb NOT NULL,
    acceleration jsonb DEFAULT '[]'::jsonb NOT NULL,
    security_level_id bigint NOT NULL,
    access_snapshot jsonb NOT NULL,
    medium text NOT NULL,
    destruction_number text NOT NULL,
    executor_user_id bigint NOT NULL,
    executor_name text NOT NULL,
    destroyed_at timestamp with time zone NOT NULL,
    physical_confirmation_id bigint,
    digital_confirmation_event_id bigint,
    final_event_id bigint NOT NULL,
    classification_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    owner_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    method text NOT NULL,
    CONSTRAINT disposition_retained_records_medium_check CHECK ((medium = ANY (ARRAY['physical'::text, 'digital'::text, 'mixed'::text]))),
    CONSTRAINT disposition_retained_records_method_check CHECK ((method = ANY (ARRAY['confirmed_physical'::text, 'postgresql_transactional_erasure'::text]))),
    CONSTRAINT disposition_retained_records_resource_kind_check CHECK ((resource_kind = ANY (ARRAY['aggregation'::text, 'record'::text])))
);

CREATE TABLE public.disposition_review_decisions (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    round_id bigint NOT NULL,
    review_stage text NOT NULL,
    decision text NOT NULL,
    task_id bigint NOT NULL,
    actor_user_id bigint NOT NULL,
    acting_role_id bigint NOT NULL,
    reason text NOT NULL,
    decided_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    membership_snapshot jsonb NOT NULL,
    proposal_snapshot jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT disposition_review_decisions_decision_check CHECK ((decision = ANY (ARRAY['approved'::text, 'rejected'::text]))),
    CONSTRAINT disposition_review_decisions_membership_snapshot_check CHECK ((jsonb_typeof(membership_snapshot) = 'array'::text)),
    CONSTRAINT disposition_review_decisions_proposal_snapshot_check CHECK ((jsonb_typeof(proposal_snapshot) = 'array'::text)),
    CONSTRAINT disposition_review_decisions_reason_check CHECK ((btrim(reason) <> ''::text)),
    CONSTRAINT disposition_review_decisions_review_stage_check CHECK ((review_stage = ANY (ARRAY['file_administrator_review'::text, 'unit_manager_review'::text, 'records_manager_review'::text, 'manager_preparation'::text, 'manager_correction'::text])))
);

CREATE SEQUENCE public.disposition_review_decisions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_review_decisions_id_seq OWNED BY public.disposition_review_decisions.id;

CREATE TABLE public.disposition_review_notes (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    task_id bigint NOT NULL,
    review_round integer NOT NULL,
    workflow_stage text NOT NULL,
    author_user_id bigint NOT NULL,
    acting_role_id bigint NOT NULL,
    review_notes text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT disposition_review_notes_review_round_check CHECK ((review_round > 0)),
    CONSTRAINT disposition_review_notes_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.disposition_review_notes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_review_notes_id_seq OWNED BY public.disposition_review_notes.id;

CREATE TABLE public.disposition_review_proposals (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    review_round integer NOT NULL,
    governing_root_id bigint NOT NULL,
    target_aggregation_id bigint NOT NULL,
    target_record_id bigint,
    proposal_type text NOT NULL,
    proposal_state text DEFAULT 'active'::text NOT NULL,
    proposed_values jsonb NOT NULL,
    current_values jsonb NOT NULL,
    reason text,
    proposer_user_id bigint NOT NULL,
    proposer_role_id bigint NOT NULL,
    proposer_stage text NOT NULL,
    proposed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    original_review_round integer NOT NULL,
    carried_from_proposal_id bigint,
    last_revised_by_user_id bigint,
    last_revised_role_id bigint,
    last_revised_stage text,
    last_revised_round integer,
    last_revised_at timestamp with time zone,
    withdrawn_by_user_id bigint,
    withdrawn_at timestamp with time zone,
    withdrawal_reason text,
    executed_by_user_id bigint,
    executed_at timestamp with time zone,
    execution_message jsonb,
    version integer DEFAULT 1 NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT disposition_review_proposals_check CHECK (((proposal_type <> 'remove_from_job'::text) OR ((target_record_id IS NULL) AND (target_aggregation_id = governing_root_id) AND (reason IS NOT NULL) AND (reason !~ '^[[:space:]]*$'::text)))),
    CONSTRAINT disposition_review_proposals_check1 CHECK (((target_record_id IS NOT NULL) = (proposal_type = 'remove_record_relationship'::text))),
    CONSTRAINT disposition_review_proposals_check2 CHECK (((proposal_state = 'withdrawn'::text) = ((withdrawn_by_user_id IS NOT NULL) AND (withdrawn_at IS NOT NULL)))),
    CONSTRAINT disposition_review_proposals_check3 CHECK (((proposal_state <> ALL (ARRAY['executed'::text, 'failed'::text])) OR (executed_at IS NOT NULL))),
    CONSTRAINT disposition_review_proposals_current_values_check CHECK ((jsonb_typeof(current_values) = 'object'::text)),
    CONSTRAINT disposition_review_proposals_original_review_round_check CHECK ((original_review_round > 0)),
    CONSTRAINT disposition_review_proposals_proposal_state_check CHECK ((proposal_state = ANY (ARRAY['active'::text, 'withdrawn'::text, 'executed'::text, 'failed'::text]))),
    CONSTRAINT disposition_review_proposals_proposal_type_check CHECK ((proposal_type = ANY (ARRAY['remove_from_job'::text, 'make_vital'::text, 'blocking_security'::text, 'add_to_holds'::text, 'create_aggregation_relationship'::text, 'remove_aggregation_relationship'::text, 'remove_record_relationship'::text, 'local_retention_override'::text]))),
    CONSTRAINT disposition_review_proposals_proposed_values_check CHECK ((jsonb_typeof(proposed_values) = 'object'::text)),
    CONSTRAINT disposition_review_proposals_review_round_check CHECK ((review_round > 0)),
    CONSTRAINT disposition_review_proposals_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.disposition_review_proposals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_review_proposals_id_seq OWNED BY public.disposition_review_proposals.id;

CREATE TABLE public.disposition_review_rounds (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    round_number integer NOT NULL,
    started_by_user_id bigint NOT NULL,
    started_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    membership_snapshot jsonb NOT NULL,
    completed_at timestamp with time zone,
    invalidated_at timestamp with time zone,
    invalidation_reason text,
    version integer DEFAULT 1 NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    submission_reason text,
    proposal_snapshot jsonb DEFAULT '[]'::jsonb NOT NULL,
    approval_execution jsonb,
    CONSTRAINT disposition_review_rounds_approval_execution_check CHECK (((approval_execution IS NULL) OR (jsonb_typeof(approval_execution) = 'object'::text))),
    CONSTRAINT disposition_review_rounds_check CHECK (((invalidated_at IS NOT NULL) = (NULLIF(btrim(invalidation_reason), ''::text) IS NOT NULL))),
    CONSTRAINT disposition_review_rounds_membership_snapshot_check CHECK ((jsonb_typeof(membership_snapshot) = 'array'::text)),
    CONSTRAINT disposition_review_rounds_proposal_snapshot_check CHECK ((jsonb_typeof(proposal_snapshot) = 'array'::text)),
    CONSTRAINT disposition_review_rounds_round_number_check CHECK ((round_number > 0)),
    CONSTRAINT disposition_review_rounds_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.disposition_review_rounds_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_review_rounds_id_seq OWNED BY public.disposition_review_rounds.id;

CREATE SEQUENCE public.disposition_tasks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.disposition_tasks_id_seq OWNED BY public.disposition_tasks.id;

CREATE TABLE public.disposition_template_revisions (
    id bigint NOT NULL,
    document_type text NOT NULL,
    revision_number integer NOT NULL,
    original_filename text NOT NULL,
    content bytea NOT NULL,
    checksum text NOT NULL,
    uploaded_by_user_id bigint NOT NULL,
    acting_role_id bigint NOT NULL,
    actor_type text DEFAULT 'user'::text NOT NULL,
    uploaded_from_job_id bigint,
    uploaded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT disposition_template_revisions_actor_type_check CHECK ((actor_type = 'user'::text)),
    CONSTRAINT disposition_template_revisions_check CHECK ((checksum = encode(sha256(content), 'hex'::text))),
    CONSTRAINT disposition_template_revisions_content_check CHECK ((octet_length(content) > 0)),
    CONSTRAINT disposition_template_revisions_document_type_check CHECK ((document_type = ANY (ARRAY['destruction_request'::text, 'digital_destruction_certificate'::text, 'proposal_execution_report'::text, 'physical_preparation_report'::text]))),
    CONSTRAINT disposition_template_revisions_original_filename_check CHECK (((btrim(original_filename) <> ''::text) AND (lower("right"(original_filename, 5)) = '.docx'::text))),
    CONSTRAINT disposition_template_revisions_revision_number_check CHECK ((revision_number > 0))
);

ALTER TABLE public.disposition_template_revisions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.disposition_template_revisions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

CREATE SEQUENCE public.event_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.event_history_id_seq OWNED BY public.event_history.id;

CREATE TABLE public.hold_aggregation_assignments (
    id bigint NOT NULL,
    hold_id bigint NOT NULL,
    aggregation_id bigint NOT NULL,
    assigned_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by_user_id bigint,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT hold_aggregation_assignments_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.hold_aggregation_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.hold_aggregation_assignments_id_seq OWNED BY public.hold_aggregation_assignments.id;

CREATE TABLE public.hold_contributors (
    id bigint NOT NULL,
    hold_id bigint NOT NULL,
    user_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT hold_contributors_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.hold_contributors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.hold_contributors_id_seq OWNED BY public.hold_contributors.id;

CREATE TABLE public.hold_notification_reminders (
    hold_id bigint NOT NULL,
    end_at timestamp with time zone NOT NULL,
    processed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.hold_record_assignments (
    id bigint NOT NULL,
    hold_id bigint NOT NULL,
    record_id bigint NOT NULL,
    assigned_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by_user_id bigint,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT hold_record_assignments_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.hold_record_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.hold_record_assignments_id_seq OWNED BY public.hold_record_assignments.id;

CREATE TABLE public.holds (
    id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    valid_from timestamp with time zone NOT NULL,
    valid_to timestamp with time zone,
    owner_user_id bigint NOT NULL,
    preserve_resource_state boolean DEFAULT false NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT holds_code_valid CHECK (((code = btrim(code)) AND (code <> ''::text) AND (char_length(code) <= 100))),
    CONSTRAINT holds_dates_in_order CHECK (((valid_to IS NULL) OR (valid_to > valid_from))),
    CONSTRAINT holds_description_length CHECK (((description IS NULL) OR (char_length(description) <= 4000))),
    CONSTRAINT holds_name_valid CHECK (((name = btrim(name)) AND (name <> ''::text) AND (char_length(name) <= 300))),
    CONSTRAINT holds_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.holds_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.holds_id_seq OWNED BY public.holds.id;

CREATE TABLE public.login_sessions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    session_token_hash bytea NOT NULL,
    csrf_token_hash bytea NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_seen_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    absolute_expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by bigint,
    client_ip inet,
    user_agent text,
    CONSTRAINT login_sessions_absolute_expiry_valid CHECK ((absolute_expires_at >= expires_at)),
    CONSTRAINT login_sessions_expiry_valid CHECK ((expires_at > date_created))
);

CREATE SEQUENCE public.login_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.login_sessions_id_seq OWNED BY public.login_sessions.id;

CREATE TABLE public.message_action_amendments (
    id uuid NOT NULL,
    original_envelope_id uuid NOT NULL,
    sequence integer NOT NULL,
    amendment_kind text NOT NULL,
    previous_action_required boolean NOT NULL,
    previous_due_date date,
    previous_due_timezone text,
    previous_due_at timestamp with time zone,
    new_action_required boolean NOT NULL,
    new_due_date date,
    new_due_timezone text,
    new_due_at timestamp with time zone,
    reason text NOT NULL,
    created_by_user_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    request_id uuid NOT NULL,
    CONSTRAINT message_action_amendments_amendment_kind_check CHECK ((amendment_kind = ANY (ARRAY['due_date_added'::text, 'due_date_changed'::text, 'due_date_removed'::text, 'action_withdrawn'::text]))),
    CONSTRAINT message_action_amendments_check CHECK ((num_nonnulls(previous_due_date, previous_due_timezone, previous_due_at) = ANY (ARRAY[0, 3]))),
    CONSTRAINT message_action_amendments_check1 CHECK ((num_nonnulls(new_due_date, new_due_timezone, new_due_at) = ANY (ARRAY[0, 3]))),
    CONSTRAINT message_action_amendments_check2 CHECK ((((amendment_kind = 'due_date_added'::text) AND (previous_due_date IS NULL) AND (new_due_date IS NOT NULL) AND new_action_required) OR ((amendment_kind = 'due_date_changed'::text) AND (previous_due_date IS NOT NULL) AND (new_due_date IS NOT NULL) AND new_action_required AND (((previous_due_date IS DISTINCT FROM new_due_date) OR (previous_due_timezone IS DISTINCT FROM new_due_timezone)) OR (previous_due_at IS DISTINCT FROM new_due_at))) OR ((amendment_kind = 'due_date_removed'::text) AND (previous_due_date IS NOT NULL) AND (new_due_date IS NULL) AND new_action_required) OR ((amendment_kind = 'action_withdrawn'::text) AND (NOT new_action_required) AND (new_due_date IS NULL)))),
    CONSTRAINT message_action_amendments_previous_action_required_check CHECK (previous_action_required),
    CONSTRAINT message_action_amendments_reason_check CHECK (((btrim(reason) <> ''::text) AND (char_length(reason) <= 2000))),
    CONSTRAINT message_action_amendments_sequence_check CHECK ((sequence > 0))
);

CREATE TABLE public.message_action_completions (
    original_delivery_id uuid NOT NULL,
    reply_envelope_id uuid NOT NULL,
    completed_by_user_id bigint NOT NULL,
    completed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.message_addressees (
    envelope_id uuid NOT NULL,
    user_id bigint NOT NULL,
    recipient_name text NOT NULL,
    recipient_type text NOT NULL,
    ordinal integer NOT NULL,
    CONSTRAINT message_addressees_ordinal_check CHECK ((ordinal >= 0)),
    CONSTRAINT message_addressees_recipient_name_check CHECK ((btrim(recipient_name) <> ''::text)),
    CONSTRAINT message_addressees_recipient_type_check CHECK ((recipient_type = ANY (ARRAY['to'::text, 'cc'::text])))
);

CREATE TABLE public.message_capture_drafts (
    draft_id bigint NOT NULL,
    capture_id uuid NOT NULL,
    selected_envelope_id uuid NOT NULL,
    root_envelope_id uuid NOT NULL,
    language_tag text NOT NULL,
    direction text NOT NULL,
    CONSTRAINT message_capture_drafts_direction_check CHECK ((direction = ANY (ARRAY['ltr'::text, 'rtl'::text])))
);

CREATE TABLE public.message_deliveries (
    id uuid NOT NULL,
    envelope_id uuid NOT NULL,
    recipient_user_id bigint NOT NULL,
    recipient_type text NOT NULL,
    mailbox_sequence bigint NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    language_tag_at_send text NOT NULL,
    read_at timestamp with time zone,
    deleted_at timestamp with time zone,
    purge_after timestamp with time zone,
    deletion_reason text,
    CONSTRAINT message_deliveries_check CHECK ((((deleted_at IS NULL) AND (deletion_reason IS NULL)) OR ((deleted_at IS NOT NULL) AND (purge_after IS NOT NULL) AND (deletion_reason IS NOT NULL) AND (deletion_reason = ANY (ARRAY['user_deleted'::text, 'retention_expired'::text]))))),
    CONSTRAINT message_deliveries_mailbox_sequence_check CHECK ((mailbox_sequence > 0)),
    CONSTRAINT message_deliveries_recipient_type_check CHECK ((recipient_type = ANY (ARRAY['to'::text, 'cc'::text])))
);

CREATE TABLE public.message_draft_recipient_selectors (
    id bigint NOT NULL,
    draft_id uuid NOT NULL,
    recipient_type text NOT NULL,
    selector_kind text NOT NULL,
    user_id bigint,
    role_id bigint,
    org_unit_id bigint,
    display_name text NOT NULL,
    ordinal integer NOT NULL,
    CONSTRAINT message_draft_recipient_selectors_check CHECK ((((selector_kind = 'user'::text) AND (user_id IS NOT NULL) AND (role_id IS NULL) AND (org_unit_id IS NULL)) OR ((selector_kind = 'role'::text) AND (role_id IS NOT NULL) AND (user_id IS NULL) AND (org_unit_id IS NULL)) OR ((selector_kind = 'org_unit'::text) AND (org_unit_id IS NOT NULL) AND (user_id IS NULL) AND (role_id IS NULL)) OR ((selector_kind = 'everyone'::text) AND (user_id IS NULL) AND (role_id IS NULL) AND (org_unit_id IS NULL)))),
    CONSTRAINT message_draft_recipient_selectors_display_name_check CHECK ((btrim(display_name) <> ''::text)),
    CONSTRAINT message_draft_recipient_selectors_ordinal_check CHECK ((ordinal >= 0)),
    CONSTRAINT message_draft_recipient_selectors_recipient_type_check CHECK ((recipient_type = ANY (ARRAY['to'::text, 'cc'::text])))
);

CREATE SEQUENCE public.message_draft_recipient_selectors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.message_draft_recipient_selectors_id_seq OWNED BY public.message_draft_recipient_selectors.id;

CREATE TABLE public.message_draft_resource_links (
    id bigint NOT NULL,
    draft_id uuid NOT NULL,
    link_token uuid NOT NULL,
    ordinal integer NOT NULL,
    resource_kind text NOT NULL,
    target_id_snapshot bigint NOT NULL,
    aggregation_id bigint,
    record_id bigint,
    security_level_id_at_send bigint NOT NULL,
    CONSTRAINT message_draft_resource_links_check CHECK ((num_nonnulls(aggregation_id, record_id) <= 1)),
    CONSTRAINT message_draft_resource_links_ordinal_check CHECK ((ordinal >= 0)),
    CONSTRAINT message_draft_resource_links_resource_kind_check CHECK ((resource_kind = ANY (ARRAY['aggregation'::text, 'record'::text])))
);

CREATE SEQUENCE public.message_draft_resource_links_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.message_draft_resource_links_id_seq OWNED BY public.message_draft_resource_links.id;

CREATE TABLE public.message_drafts (
    id uuid NOT NULL,
    owner_user_id bigint NOT NULL,
    subject text,
    priority text DEFAULT 'normal'::text NOT NULL,
    body_rich_text text,
    security_level_id bigint NOT NULL,
    action_required boolean NOT NULL,
    action_due_date date,
    action_due_timezone text,
    read_receipt_requested boolean NOT NULL,
    relationship_kind text,
    related_delivery_id uuid,
    related_envelope_id uuid,
    version bigint DEFAULT 1 NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    purge_after timestamp with time zone,
    deletion_reason text,
    expiry_restoration_days integer DEFAULT 30 NOT NULL,
    CONSTRAINT message_drafts_body_rich_text_check CHECK (((body_rich_text IS NULL) OR (octet_length(body_rich_text) <= 65536))),
    CONSTRAINT message_drafts_check CHECK (((action_due_date IS NULL) = (action_due_timezone IS NULL))),
    CONSTRAINT message_drafts_check1 CHECK ((action_required OR (action_due_date IS NULL))),
    CONSTRAINT message_drafts_check2 CHECK ((((deleted_at IS NULL) AND (purge_after IS NULL) AND (deletion_reason IS NULL)) OR ((deleted_at IS NOT NULL) AND (purge_after IS NOT NULL) AND (deletion_reason IS NOT NULL) AND (deletion_reason = ANY (ARRAY['expired'::text, 'discarded'::text]))))),
    CONSTRAINT message_drafts_expiry_restoration_days_check CHECK (((expiry_restoration_days >= 1) AND (expiry_restoration_days <= 36500))),
    CONSTRAINT message_drafts_priority_check CHECK ((priority = ANY (ARRAY['normal'::text, 'high'::text, 'very_high'::text]))),
    CONSTRAINT message_drafts_relationship_kind_check CHECK (((relationship_kind IS NULL) OR (relationship_kind = ANY (ARRAY['reply'::text, 'forward'::text, 'follow_up'::text])))),
    CONSTRAINT message_drafts_subject_check CHECK (((subject IS NULL) OR (char_length(subject) <= 255))),
    CONSTRAINT message_drafts_version_check CHECK ((version > 0))
);

CREATE TABLE public.message_envelope_localizations (
    envelope_id uuid NOT NULL,
    language_tag text NOT NULL,
    subject text NOT NULL,
    body_rich_text text NOT NULL,
    direction text NOT NULL,
    rendered_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT message_envelope_localizations_body_rich_text_check CHECK ((octet_length(body_rich_text) <= 65536)),
    CONSTRAINT message_envelope_localizations_direction_check CHECK ((direction = ANY (ARRAY['ltr'::text, 'rtl'::text]))),
    CONSTRAINT message_envelope_localizations_subject_check CHECK ((((char_length(subject) >= 1) AND (char_length(subject) <= 255)) AND (btrim(subject) <> ''::text)))
);

CREATE TABLE public.message_envelopes (
    id uuid NOT NULL,
    sender_user_id bigint,
    sender_name text NOT NULL,
    sender_kind text NOT NULL,
    message_kind text NOT NULL,
    action_amendment_id uuid,
    system_producer_code text,
    system_configuration_version_id uuid,
    source_event_type text,
    source_event_id text,
    triggered_by_user_id bigint,
    is_test boolean DEFAULT false NOT NULL,
    test_run_id uuid,
    test_initiated_by_user_id bigint,
    subject text NOT NULL,
    priority text DEFAULT 'normal'::text NOT NULL,
    body_rich_text text NOT NULL,
    security_level_id bigint NOT NULL,
    action_required boolean NOT NULL,
    action_due_date date,
    action_due_timezone text,
    action_due_at timestamp with time zone,
    read_receipt_requested boolean NOT NULL,
    relationship_kind text,
    related_delivery_id uuid,
    related_envelope_id uuid,
    sent_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    sender_deleted_at timestamp with time zone,
    sender_purge_after timestamp with time zone,
    request_id uuid NOT NULL,
    expiry_restoration_days integer DEFAULT 30 NOT NULL,
    CONSTRAINT message_envelopes_body_rich_text_check CHECK ((octet_length(body_rich_text) <= 65536)),
    CONSTRAINT message_envelopes_check CHECK (((sender_kind = 'user'::text) = (sender_user_id IS NOT NULL))),
    CONSTRAINT message_envelopes_check1 CHECK (((sender_kind = 'system'::text) = (message_kind = 'system_notification'::text))),
    CONSTRAINT message_envelopes_check10 CHECK (((action_required IS TRUE) OR (action_due_date IS NULL))),
    CONSTRAINT message_envelopes_check11 CHECK (((sender_kind <> 'system'::text) OR ((sender_name = 'system'::text) AND (NOT action_required) AND (NOT read_receipt_requested)))),
    CONSTRAINT message_envelopes_check12 CHECK (((message_kind <> 'action_amendment_notice'::text) OR ((relationship_kind IS NULL) AND (NOT is_test) AND (NOT action_required) AND (NOT read_receipt_requested)))),
    CONSTRAINT message_envelopes_check2 CHECK (((message_kind = 'action_amendment_notice'::text) = (action_amendment_id IS NOT NULL))),
    CONSTRAINT message_envelopes_check3 CHECK ((((sender_kind = 'system'::text) AND (system_producer_code IS NOT NULL) AND (system_configuration_version_id IS NOT NULL) AND (source_event_type IS NOT NULL) AND (source_event_id IS NOT NULL) AND ((length(source_event_id) >= 1) AND (length(source_event_id) <= 255))) OR ((sender_kind = 'user'::text) AND (system_producer_code IS NULL) AND (system_configuration_version_id IS NULL) AND (source_event_type IS NULL) AND (source_event_id IS NULL) AND (triggered_by_user_id IS NULL)))),
    CONSTRAINT message_envelopes_check4 CHECK (((is_test AND (sender_kind = 'system'::text) AND (test_run_id IS NOT NULL) AND (test_initiated_by_user_id IS NOT NULL)) OR ((NOT is_test) AND (test_run_id IS NULL) AND (test_initiated_by_user_id IS NULL)))),
    CONSTRAINT message_envelopes_check5 CHECK (COALESCE((((relationship_kind IS NULL) AND (related_delivery_id IS NULL) AND (related_envelope_id IS NULL)) OR ((relationship_kind = 'reply'::text) AND (related_delivery_id IS NOT NULL) AND (related_envelope_id IS NULL)) OR ((relationship_kind = 'follow_up'::text) AND (related_delivery_id IS NULL) AND (related_envelope_id IS NOT NULL)) OR ((relationship_kind = 'forward'::text) AND (num_nonnulls(related_delivery_id, related_envelope_id) = 1))), false)),
    CONSTRAINT message_envelopes_check6 CHECK (((sender_deleted_at IS NULL) OR (sender_purge_after IS NOT NULL))),
    CONSTRAINT message_envelopes_check7 CHECK (((sender_kind = 'user'::text) OR ((sender_deleted_at IS NULL) AND (sender_purge_after IS NULL)))),
    CONSTRAINT message_envelopes_check8 CHECK ((expires_at > sent_at)),
    CONSTRAINT message_envelopes_check9 CHECK ((num_nonnulls(action_due_date, action_due_timezone, action_due_at) = ANY (ARRAY[0, 3]))),
    CONSTRAINT message_envelopes_expiry_restoration_days_check CHECK (((expiry_restoration_days >= 1) AND (expiry_restoration_days <= 36500))),
    CONSTRAINT message_envelopes_message_kind_check CHECK ((message_kind = ANY (ARRAY['user_message'::text, 'system_notification'::text, 'action_amendment_notice'::text]))),
    CONSTRAINT message_envelopes_priority_check CHECK ((priority = ANY (ARRAY['normal'::text, 'high'::text, 'very_high'::text]))),
    CONSTRAINT message_envelopes_sender_kind_check CHECK ((sender_kind = ANY (ARRAY['user'::text, 'system'::text]))),
    CONSTRAINT message_envelopes_sender_name_check CHECK ((btrim(sender_name) <> ''::text)),
    CONSTRAINT message_envelopes_subject_check CHECK ((((char_length(subject) >= 1) AND (char_length(subject) <= 255)) AND (btrim(subject) <> ''::text)))
);

CREATE TABLE public.message_mailboxes (
    user_id bigint NOT NULL,
    last_sequence bigint DEFAULT 0 NOT NULL,
    CONSTRAINT message_mailboxes_last_sequence_check CHECK ((last_sequence >= 0))
);

CREATE TABLE public.message_recipient_selectors (
    id bigint NOT NULL,
    envelope_id uuid NOT NULL,
    recipient_type text NOT NULL,
    selector_kind text NOT NULL,
    user_id bigint,
    role_id bigint,
    org_unit_id bigint,
    display_name text NOT NULL,
    ordinal integer NOT NULL,
    CONSTRAINT message_recipient_selectors_check CHECK ((((selector_kind = 'user'::text) AND (user_id IS NOT NULL) AND (role_id IS NULL) AND (org_unit_id IS NULL)) OR ((selector_kind = 'role'::text) AND (role_id IS NOT NULL) AND (user_id IS NULL) AND (org_unit_id IS NULL)) OR ((selector_kind = 'org_unit'::text) AND (org_unit_id IS NOT NULL) AND (user_id IS NULL) AND (role_id IS NULL)) OR ((selector_kind = 'everyone'::text) AND (user_id IS NULL) AND (role_id IS NULL) AND (org_unit_id IS NULL)))),
    CONSTRAINT message_recipient_selectors_display_name_check CHECK ((btrim(display_name) <> ''::text)),
    CONSTRAINT message_recipient_selectors_ordinal_check CHECK ((ordinal >= 0)),
    CONSTRAINT message_recipient_selectors_recipient_type_check CHECK ((recipient_type = ANY (ARRAY['to'::text, 'cc'::text])))
);

CREATE SEQUENCE public.message_recipient_selectors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.message_recipient_selectors_id_seq OWNED BY public.message_recipient_selectors.id;

CREATE TABLE public.message_record_capture_components (
    id bigint NOT NULL,
    capture_id uuid NOT NULL,
    component_kind text NOT NULL,
    envelope_id uuid,
    envelope_id_at_capture uuid,
    digital_component_id bigint,
    digital_component_id_at_capture bigint CONSTRAINT message_record_capture_comp_digital_component_id_at_ca_not_null NOT NULL,
    component_order integer NOT NULL,
    is_selected_message boolean NOT NULL,
    CONSTRAINT message_record_capture_components_check CHECK ((((component_kind = 'message'::text) AND (envelope_id_at_capture IS NOT NULL) AND (is_selected_message = (component_order = 1))) OR ((component_kind = 'provenance'::text) AND (envelope_id IS NULL) AND (envelope_id_at_capture IS NULL) AND (NOT is_selected_message)))),
    CONSTRAINT message_record_capture_components_component_order_check CHECK ((component_order > 0))
);

CREATE SEQUENCE public.message_record_capture_components_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.message_record_capture_components_id_seq OWNED BY public.message_record_capture_components.id;

CREATE TABLE public.message_record_captures (
    id uuid NOT NULL,
    selected_envelope_id uuid,
    selected_envelope_id_at_capture uuid CONSTRAINT message_record_captures_selected_envelope_id_at_captur_not_null NOT NULL,
    record_id bigint,
    record_id_at_capture bigint NOT NULL,
    captured_by_user_id bigint NOT NULL,
    captured_by_name text NOT NULL,
    captured_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT message_record_captures_captured_by_name_check CHECK ((btrim(captured_by_name) <> ''::text))
);

CREATE TABLE public.message_request_receipts (
    id bigint NOT NULL,
    operation_kind text NOT NULL,
    principal_user_id bigint,
    producer_code text,
    request_id uuid NOT NULL,
    request_fingerprint text NOT NULL,
    source_event_type text,
    source_event_id text,
    result_envelope_id uuid NOT NULL,
    result_amendment_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    result_purged_at timestamp with time zone,
    CONSTRAINT message_request_receipts_check CHECK ((num_nonnulls(principal_user_id, producer_code) = 1)),
    CONSTRAINT message_request_receipts_check1 CHECK (((operation_kind <> 'amendment'::text) OR (principal_user_id IS NOT NULL))),
    CONSTRAINT message_request_receipts_check2 CHECK (((operation_kind = 'amendment'::text) = (result_amendment_id IS NOT NULL))),
    CONSTRAINT message_request_receipts_check3 CHECK (((source_event_type IS NULL) = (source_event_id IS NULL))),
    CONSTRAINT message_request_receipts_operation_kind_check CHECK ((operation_kind = ANY (ARRAY['send'::text, 'amendment'::text]))),
    CONSTRAINT message_request_receipts_request_fingerprint_check CHECK ((length(request_fingerprint) = 64))
);

CREATE SEQUENCE public.message_request_receipts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.message_request_receipts_id_seq OWNED BY public.message_request_receipts.id;

CREATE TABLE public.message_resource_links (
    id bigint NOT NULL,
    envelope_id uuid NOT NULL,
    link_token uuid NOT NULL,
    ordinal integer NOT NULL,
    resource_kind text NOT NULL,
    target_id_snapshot bigint NOT NULL,
    aggregation_id bigint,
    record_id bigint,
    security_level_id_at_send bigint NOT NULL,
    CONSTRAINT message_resource_links_check CHECK ((num_nonnulls(aggregation_id, record_id) <= 1)),
    CONSTRAINT message_resource_links_ordinal_check CHECK ((ordinal >= 0)),
    CONSTRAINT message_resource_links_resource_kind_check CHECK ((resource_kind = ANY (ARRAY['aggregation'::text, 'record'::text])))
);

CREATE SEQUENCE public.message_resource_links_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.message_resource_links_id_seq OWNED BY public.message_resource_links.id;

CREATE TABLE public.messaging_cleanup_groups (
    group_key uuid NOT NULL,
    member_count bigint NOT NULL,
    expired_count bigint NOT NULL,
    eligible_at timestamp with time zone NOT NULL,
    observed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    failure_count bigint DEFAULT 0 NOT NULL,
    oldest_failure_at timestamp with time zone
);

CREATE TABLE public.messaging_gateway_health (
    instance_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    listener_connected boolean NOT NULL,
    listener_generation bigint NOT NULL,
    notifications_received bigint NOT NULL,
    last_notification_at timestamp with time zone,
    active_connections integer NOT NULL,
    slow_disconnects bigint NOT NULL,
    host_addresses inet[],
    api_port integer,
    CONSTRAINT messaging_gateway_health_api_port_check CHECK (((api_port >= 1) AND (api_port <= 65535)))
);

CREATE TABLE public.messaging_notification_configuration_guard (
    singleton boolean DEFAULT true NOT NULL,
    revision bigint NOT NULL,
    CONSTRAINT messaging_notification_configuration_guard_singleton_check CHECK (singleton)
);

CREATE TABLE public.messaging_operational_metrics (
    metric text NOT NULL,
    instance_id text DEFAULT ''::text NOT NULL,
    producer_code text DEFAULT ''::text NOT NULL,
    value double precision DEFAULT 0 NOT NULL,
    observations bigint DEFAULT 0 NOT NULL,
    last_observed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    unresolved_since timestamp with time zone
);

CREATE TABLE public.org_units (
    id bigint NOT NULL,
    parent_org_unit_id bigint,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_deactivated timestamp with time zone,
    version bigint DEFAULT 1 NOT NULL,
    status text GENERATED ALWAYS AS (
CASE
    WHEN (date_deactivated IS NULL) THEN 'active'::text
    ELSE 'inactive'::text
END) STORED,
    translations jsonb,
    managing_role_id bigint,
    file_administrator_role_id bigint,
    CONSTRAINT org_units_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT org_units_dates_in_order CHECK (((date_deactivated IS NULL) OR (date_deactivated >= date_created))),
    CONSTRAINT org_units_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT org_units_not_own_parent CHECK (((parent_org_unit_id IS NULL) OR (parent_org_unit_id <> id))),
    CONSTRAINT org_units_translations_object CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text))),
    CONSTRAINT org_units_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.org_units_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.org_units_id_seq OWNED BY public.org_units.id;

CREATE TABLE public.organizational_ownership_assignment_runs (
    id bigint NOT NULL,
    migration_version text CONSTRAINT organizational_ownership_assignment__migration_version_not_null NOT NULL,
    started_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    root_count bigint NOT NULL,
    aggregation_count bigint CONSTRAINT organizational_ownership_assignment__aggregation_count_not_null NOT NULL,
    record_count bigint NOT NULL,
    before_counts_by_unit jsonb CONSTRAINT organizational_ownership_assignm_before_counts_by_unit_not_null NOT NULL,
    after_counts_by_unit jsonb,
    CONSTRAINT ownership_assignment_run_after_counts_object CHECK (((after_counts_by_unit IS NULL) OR (jsonb_typeof(after_counts_by_unit) = 'object'::text))),
    CONSTRAINT ownership_assignment_run_before_counts_object CHECK ((jsonb_typeof(before_counts_by_unit) = 'object'::text)),
    CONSTRAINT ownership_assignment_run_counts_nonnegative CHECK (((root_count >= 0) AND (aggregation_count >= 0) AND (record_count >= 0))),
    CONSTRAINT ownership_assignment_run_version_not_blank CHECK ((btrim(migration_version) <> ''::text))
);

CREATE SEQUENCE public.organizational_ownership_assignment_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.organizational_ownership_assignment_runs_id_seq OWNED BY public.organizational_ownership_assignment_runs.id;

CREATE VIEW public.organizational_ownership_diagnostics AS
 SELECT 'aggregation'::text AS resource_type,
    child.id AS resource_id,
    child.parent_aggregation_id AS parent_resource_id,
    child.owning_org_unit_id,
    parent.owning_org_unit_id AS expected_owning_org_unit_id,
        CASE
            WHEN (child.owning_org_unit_id IS NULL) THEN 'missing_owner'::text
            ELSE 'owner_mismatch'::text
        END AS issue
   FROM (public.aggregations child
     LEFT JOIN public.aggregations parent ON ((parent.id = child.parent_aggregation_id)))
  WHERE ((child.owning_org_unit_id IS NULL) OR ((child.parent_aggregation_id IS NOT NULL) AND (child.owning_org_unit_id IS DISTINCT FROM parent.owning_org_unit_id)))
UNION ALL
 SELECT 'record'::text AS resource_type,
    record.id AS resource_id,
    record.aggregation_id AS parent_resource_id,
    record.owning_org_unit_id,
    parent.owning_org_unit_id AS expected_owning_org_unit_id,
        CASE
            WHEN (record.owning_org_unit_id IS NULL) THEN 'missing_owner'::text
            ELSE 'owner_mismatch'::text
        END AS issue
   FROM (public.records record
     JOIN public.aggregations parent ON ((parent.id = record.aggregation_id)))
  WHERE ((record.owning_org_unit_id IS NULL) OR (record.owning_org_unit_id IS DISTINCT FROM parent.owning_org_unit_id));

CREATE TABLE public.organizational_ownership_root_assignments (
    root_aggregation_id bigint CONSTRAINT organizational_ownership_root_assi_root_aggregation_id_not_null NOT NULL,
    run_id bigint NOT NULL,
    selected_role_id bigint CONSTRAINT organizational_ownership_root_assignm_selected_role_id_not_null NOT NULL,
    selected_role_code text CONSTRAINT organizational_ownership_root_assig_selected_role_code_not_null NOT NULL,
    selected_role_name text CONSTRAINT organizational_ownership_root_assig_selected_role_name_not_null NOT NULL,
    owning_org_unit_id bigint CONSTRAINT organizational_ownership_root_assig_owning_org_unit_id_not_null NOT NULL,
    owning_org_unit_code text CONSTRAINT organizational_ownership_root_ass_owning_org_unit_code_not_null NOT NULL,
    owning_org_unit_name text CONSTRAINT organizational_ownership_root_ass_owning_org_unit_name_not_null NOT NULL,
    match_score integer NOT NULL,
    assignment_method text CONSTRAINT organizational_ownership_root_assign_assignment_method_not_null NOT NULL,
    root_title text NOT NULL,
    root_description text,
    assigned_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT organizational_ownership_root_assignmen_assignment_method_check CHECK ((assignment_method = ANY (ARRAY['text_match'::text, 'score_tie_stable_distribution'::text, 'no_text_match_stable_distribution'::text]))),
    CONSTRAINT organizational_ownership_root_assignments_match_score_check CHECK ((match_score >= 0))
);

CREATE TABLE public.permission_dependencies (
    permission_id bigint NOT NULL,
    required_permission_id bigint NOT NULL,
    CONSTRAINT permission_dependencies_check CHECK ((permission_id <> required_permission_id))
);

CREATE TABLE public.permissions (
    id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    resource_type text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT permissions_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT permissions_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT permissions_resource_type_check CHECK ((resource_type = ANY (ARRAY['aggregation'::text, 'record'::text])))
);

CREATE SEQUENCE public.permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.permissions_id_seq OWNED BY public.permissions.id;

CREATE TABLE public.privilege_dependencies (
    privilege_id bigint NOT NULL,
    required_privilege_id bigint NOT NULL,
    CONSTRAINT privilege_dependencies_not_self CHECK ((privilege_id <> required_privilege_id))
);

CREATE TABLE public.privileges (
    id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    category text NOT NULL,
    is_reserved boolean DEFAULT false NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    account_type_restriction text,
    CONSTRAINT privileges_account_type_restriction_valid CHECK (((account_type_restriction IS NULL) OR (account_type_restriction = ANY (ARRAY['person'::text, 'service'::text])))),
    CONSTRAINT privileges_category_valid CHECK ((category = ANY (ARRAY['administration'::text, 'aggregation'::text, 'record'::text, 'component'::text, 'exceptional'::text]))),
    CONSTRAINT privileges_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT privileges_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT privileges_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.privileges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.privileges_id_seq OWNED BY public.privileges.id;

CREATE TABLE public.profile_privileges (
    id bigint NOT NULL,
    profile_id bigint NOT NULL,
    privilege_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT profile_privileges_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.profile_privileges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.profile_privileges_id_seq OWNED BY public.profile_privileges.id;

CREATE TABLE public.profiles (
    id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    is_system boolean DEFAULT false NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    translations jsonb,
    CONSTRAINT profiles_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT profiles_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT profiles_translations_object CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text))),
    CONSTRAINT profiles_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.profiles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.profiles_id_seq OWNED BY public.profiles.id;

CREATE TABLE public.record_acl_grants (
    id bigint NOT NULL,
    record_id bigint NOT NULL,
    principal_type text NOT NULL,
    role_id bigint,
    permission_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT record_acl_grants_principal_valid CHECK ((((principal_type = 'role'::text) AND (role_id IS NOT NULL)) OR ((principal_type = ANY (ARRAY['everyone'::text, 'org_unit_members'::text, 'owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text])) AND (role_id IS NULL)))),
    CONSTRAINT record_acl_grants_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.record_acl_grants_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.record_acl_grants_id_seq OWNED BY public.record_acl_grants.id;

CREATE TABLE public.record_draft_component_blobs (
    id bigint NOT NULL,
    record_draft_component_id bigint NOT NULL,
    segment_no integer NOT NULL,
    segment_size integer NOT NULL,
    segment_checksum_algo text,
    segment_checksum_value text,
    content bytea NOT NULL,
    date_stored timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT record_draft_component_blobs_check CHECK ((segment_size = octet_length(content))),
    CONSTRAINT record_draft_component_blobs_segment_no_check CHECK ((segment_no >= 0)),
    CONSTRAINT record_draft_component_blobs_segment_size_check CHECK ((segment_size > 0))
);

CREATE SEQUENCE public.record_draft_component_blobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.record_draft_component_blobs_id_seq OWNED BY public.record_draft_component_blobs.id;

CREATE TABLE public.record_draft_components (
    id bigint NOT NULL,
    draft_id bigint NOT NULL,
    component_order integer NOT NULL,
    file_name text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_originated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    mime_type text NOT NULL,
    size_in_bytes bigint NOT NULL,
    checksum_algo text NOT NULL,
    checksum_value text NOT NULL,
    content_status text DEFAULT 'uploading'::text NOT NULL,
    segment_count integer,
    upload_completed_at timestamp with time zone,
    CONSTRAINT record_draft_components_component_order_check CHECK ((component_order > 0)),
    CONSTRAINT record_draft_components_content_status_check CHECK ((content_status = ANY (ARRAY['uploading'::text, 'interrupted'::text, 'finalizing'::text, 'available'::text, 'failed'::text, 'cancelled'::text, 'expired'::text]))),
    CONSTRAINT record_draft_components_file_name_check CHECK ((btrim(file_name) <> ''::text)),
    CONSTRAINT record_draft_components_segment_count_check CHECK (((segment_count IS NULL) OR (segment_count >= 0))),
    CONSTRAINT record_draft_components_size_in_bytes_check CHECK ((size_in_bytes >= 0))
);

CREATE SEQUENCE public.record_draft_components_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.record_draft_components_id_seq OWNED BY public.record_draft_components.id;

CREATE TABLE public.record_drafts (
    id bigint NOT NULL,
    owner_user_id bigint,
    aggregation_id bigint,
    record_number text,
    title text,
    description text,
    date_originated timestamp with time zone,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone DEFAULT (CURRENT_TIMESTAMP + '7 days'::interval) NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    security_level_id bigint,
    medium text,
    is_vital boolean DEFAULT false NOT NULL,
    date_of_next_review timestamp with time zone,
    CONSTRAINT record_drafts_medium_valid CHECK (((medium IS NULL) OR (medium = ANY (ARRAY['digital'::text, 'physical'::text, 'mixed'::text])))),
    CONSTRAINT record_drafts_version_check CHECK ((version > 0))
);

CREATE SEQUENCE public.record_drafts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.record_drafts_id_seq OWNED BY public.record_drafts.id;

CREATE TABLE public.record_relationships (
    id bigint NOT NULL,
    relationship_type_id bigint NOT NULL,
    source_id bigint NOT NULL,
    target_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT record_relationships_check CHECK ((source_id <> target_id))
);

CREATE SEQUENCE public.record_relationships_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.record_relationships_id_seq OWNED BY public.record_relationships.id;

CREATE SEQUENCE public.records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.records_id_seq OWNED BY public.records.id;

CREATE TABLE public.relationship_types (
    id bigint NOT NULL,
    resource_kind text NOT NULL,
    code text NOT NULL,
    forward_name text NOT NULL,
    reverse_name text NOT NULL,
    is_symmetric boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    translations jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT relationship_types_check CHECK (((NOT is_symmetric) OR (forward_name = reverse_name))),
    CONSTRAINT relationship_types_code_check CHECK ((code ~ '^[a-z][a-z0-9_]*$'::text)),
    CONSTRAINT relationship_types_forward_name_check CHECK ((btrim(forward_name) <> ''::text)),
    CONSTRAINT relationship_types_resource_kind_check CHECK ((resource_kind = ANY (ARRAY['aggregation'::text, 'record'::text]))),
    CONSTRAINT relationship_types_reverse_name_check CHECK ((btrim(reverse_name) <> ''::text)),
    CONSTRAINT relationship_types_translations_check CHECK ((jsonb_typeof(translations) = 'object'::text))
);

CREATE SEQUENCE public.relationship_types_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.relationship_types_id_seq OWNED BY public.relationship_types.id;

CREATE TABLE public.roles (
    id bigint NOT NULL,
    org_unit_id bigint,
    supervisor_role_id bigint,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_deactivated timestamp with time zone,
    version bigint DEFAULT 1 NOT NULL,
    security_level_id bigint NOT NULL,
    profile_id bigint NOT NULL,
    is_information_governance boolean DEFAULT false NOT NULL,
    status text GENERATED ALWAYS AS (
CASE
    WHEN (date_deactivated IS NULL) THEN 'active'::text
    ELSE 'inactive'::text
END) STORED,
    is_system boolean DEFAULT false NOT NULL,
    account_type_restriction text,
    translations jsonb,
    CONSTRAINT roles_account_type_restriction_valid CHECK (((account_type_restriction IS NULL) OR (account_type_restriction = ANY (ARRAY['person'::text, 'service'::text])))),
    CONSTRAINT roles_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT roles_dates_in_order CHECK (((date_deactivated IS NULL) OR (date_deactivated >= date_created))),
    CONSTRAINT roles_everyone_code_reserved CHECK ((lower(btrim(code)) <> 'everyone'::text)),
    CONSTRAINT roles_everyone_name_reserved CHECK ((lower(btrim(name)) <> 'everyone'::text)),
    CONSTRAINT roles_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT roles_not_own_supervisor CHECK (((supervisor_role_id IS NULL) OR (supervisor_role_id <> id))),
    CONSTRAINT roles_org_unit_members_code_reserved CHECK ((lower(btrim(code)) <> 'org_unit_members'::text)),
    CONSTRAINT roles_org_unit_members_name_reserved CHECK ((lower(btrim(name)) <> 'all org unit members'::text)),
    CONSTRAINT roles_system_service_shape CHECK (((is_system AND (account_type_restriction = 'service'::text) AND (org_unit_id IS NULL) AND (supervisor_role_id IS NULL) AND (NOT is_information_governance)) OR ((NOT is_system) AND (account_type_restriction IS NULL) AND (org_unit_id IS NOT NULL)))),
    CONSTRAINT roles_translations_object CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text))),
    CONSTRAINT roles_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.roles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;

CREATE TABLE public.saved_search_org_unit_grants (
    saved_search_id bigint NOT NULL,
    org_unit_id bigint NOT NULL
);

CREATE TABLE public.saved_search_role_grants (
    saved_search_id bigint NOT NULL,
    role_id bigint NOT NULL
);

CREATE TABLE public.saved_searches (
    id bigint NOT NULL,
    owner_user_id bigint NOT NULL,
    name text NOT NULL,
    category text,
    description text,
    resource_type text NOT NULL,
    definition jsonb NOT NULL,
    audience_mode text DEFAULT 'private'::text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT saved_searches_audience_mode_valid CHECK ((audience_mode = ANY (ARRAY['private'::text, 'shared'::text]))),
    CONSTRAINT saved_searches_category_valid CHECK (((category IS NULL) OR ((btrim(category) <> ''::text) AND (length(category) <= 80)))),
    CONSTRAINT saved_searches_definition_valid CHECK (((jsonb_typeof(definition) = 'object'::text) AND ((definition ->> 'schema_version'::text) = '1'::text) AND ((definition ->> 'resource_type'::text) = resource_type) AND (jsonb_typeof((definition -> 'request'::text)) = 'object'::text) AND ((definition ->> 'max_results'::text) ~ '^[0-9]+$'::text) AND ((((definition ->> 'max_results'::text))::integer >= 1) AND (((definition ->> 'max_results'::text))::integer <= 5000)))),
    CONSTRAINT saved_searches_description_bounded CHECK (((description IS NULL) OR (length(description) <= 500))),
    CONSTRAINT saved_searches_name_bounded CHECK ((length(name) <= 120)),
    CONSTRAINT saved_searches_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT saved_searches_resource_type_valid CHECK ((resource_type = ANY (ARRAY['record'::text, 'aggregation'::text]))),
    CONSTRAINT saved_searches_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.saved_searches_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.saved_searches_id_seq OWNED BY public.saved_searches.id;

CREATE TABLE public.schema_migrations (
    id bigint NOT NULL,
    version text NOT NULL,
    applied_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT schema_migrations_version_not_blank CHECK ((btrim(version) <> ''::text))
);

CREATE SEQUENCE public.schema_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.schema_migrations_id_seq OWNED BY public.schema_migrations.id;

CREATE TABLE public.security_levels (
    id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    level_number integer NOT NULL,
    prevents_disposition boolean DEFAULT false NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    description text,
    translations jsonb,
    CONSTRAINT security_levels_code_not_blank CHECK ((btrim(code) <> ''::text)),
    CONSTRAINT security_levels_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT security_levels_number_nonnegative CHECK ((level_number >= 0)),
    CONSTRAINT security_levels_translations_object CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text))),
    CONSTRAINT security_levels_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.security_levels_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.security_levels_id_seq OWNED BY public.security_levels.id;

CREATE TABLE public.service_account_credentials (
    id bigint NOT NULL,
    service_user_id bigint NOT NULL,
    name text NOT NULL,
    credential_identifier text NOT NULL,
    secret_hash text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    last_worker_id text,
    date_revoked timestamp with time zone,
    created_by_user_id bigint,
    revoked_by_user_id bigint,
    CONSTRAINT service_account_credentials_expiry_valid CHECK ((expires_at > date_created)),
    CONSTRAINT service_account_credentials_hash_format CHECK ((secret_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT service_account_credentials_identifier_format CHECK ((credential_identifier ~ '^[0-9A-HJKMNP-TV-Z]{26}$'::text)),
    CONSTRAINT service_account_credentials_last_worker_not_blank CHECK (((last_worker_id IS NULL) OR (btrim(last_worker_id) <> ''::text))),
    CONSTRAINT service_account_credentials_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT service_account_credentials_revocation_state CHECK ((((status = 'active'::text) AND (date_revoked IS NULL) AND (revoked_by_user_id IS NULL)) OR ((status = 'revoked'::text) AND (date_revoked IS NOT NULL)))),
    CONSTRAINT service_account_credentials_status_valid CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);

CREATE SEQUENCE public.service_account_credentials_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.service_account_credentials_id_seq OWNED BY public.service_account_credentials.id;

CREATE TABLE public.supported_languages (
    id bigint NOT NULL,
    language_tag text NOT NULL,
    english_name text NOT NULL,
    native_name text NOT NULL,
    direction text NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    formatting_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    catalogue_revision bigint DEFAULT 1 NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT supported_languages_default_enabled CHECK (((NOT is_default) OR is_enabled)),
    CONSTRAINT supported_languages_direction_valid CHECK ((direction = ANY (ARRAY['ltr'::text, 'rtl'::text]))),
    CONSTRAINT supported_languages_english_name_not_blank CHECK ((btrim(english_name) <> ''::text)),
    CONSTRAINT supported_languages_formatting_object CHECK ((jsonb_typeof(formatting_config) = 'object'::text)),
    CONSTRAINT supported_languages_native_name_not_blank CHECK ((btrim(native_name) <> ''::text)),
    CONSTRAINT supported_languages_revision_positive CHECK ((catalogue_revision > 0)),
    CONSTRAINT supported_languages_tag_shape CHECK ((language_tag ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'::text)),
    CONSTRAINT supported_languages_version_positive CHECK ((version > 0))
);

ALTER TABLE public.supported_languages ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.supported_languages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

CREATE TABLE public.system_notification_configuration_audiences (
    id bigint NOT NULL,
    configuration_version_id uuid CONSTRAINT system_notification_configur_configuration_version_id_not_null1 NOT NULL,
    recipient_type text CONSTRAINT system_notification_configuration_audie_recipient_type_not_null NOT NULL,
    selector_kind text CONSTRAINT system_notification_configuration_audien_selector_kind_not_null NOT NULL,
    user_id bigint,
    role_id bigint,
    org_unit_id bigint,
    display_name text CONSTRAINT system_notification_configuration_audienc_display_name_not_null NOT NULL,
    ordinal integer NOT NULL,
    CONSTRAINT system_notification_configuration_audience_recipient_type_check CHECK ((recipient_type = ANY (ARRAY['to'::text, 'cc'::text]))),
    CONSTRAINT system_notification_configuration_audiences_check CHECK ((((selector_kind = 'user'::text) AND (user_id IS NOT NULL) AND (role_id IS NULL) AND (org_unit_id IS NULL)) OR ((selector_kind = 'role'::text) AND (role_id IS NOT NULL) AND (user_id IS NULL) AND (org_unit_id IS NULL)) OR ((selector_kind = 'org_unit'::text) AND (org_unit_id IS NOT NULL) AND (user_id IS NULL) AND (role_id IS NULL)))),
    CONSTRAINT system_notification_configuration_audiences_display_name_check CHECK ((btrim(display_name) <> ''::text)),
    CONSTRAINT system_notification_configuration_audiences_ordinal_check CHECK ((ordinal >= 0))
);

CREATE SEQUENCE public.system_notification_configuration_audiences_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.system_notification_configuration_audiences_id_seq OWNED BY public.system_notification_configuration_audiences.id;

CREATE TABLE public.system_notification_configuration_translations (
    configuration_version_id uuid CONSTRAINT system_notification_configura_configuration_version_id_not_null NOT NULL,
    language_tag text CONSTRAINT system_notification_configuration_transla_language_tag_not_null NOT NULL,
    subject_template text CONSTRAINT system_notification_configuration_tra_subject_template_not_null NOT NULL,
    body_template_rich_text text CONSTRAINT system_notification_configura_body_template_rich_text_not_null1 NOT NULL,
    review_status text CONSTRAINT system_notification_configuration_transl_review_status_not_null NOT NULL,
    reviewed_by_user_id bigint,
    reviewed_at timestamp with time zone,
    CONSTRAINT system_notification_configuratio_body_template_rich_text_check1 CHECK ((octet_length(body_template_rich_text) <= 65536)),
    CONSTRAINT system_notification_configuration_transl_subject_template_check CHECK ((((char_length(subject_template) >= 1) AND (char_length(subject_template) <= 255)) AND (btrim(subject_template) <> ''::text))),
    CONSTRAINT system_notification_configuration_translati_review_status_check CHECK ((review_status = ANY (ARRAY['draft'::text, 'reviewed'::text, 'published'::text]))),
    CONSTRAINT system_notification_configuration_translations_check CHECK (((review_status = 'draft'::text) OR ((reviewed_by_user_id IS NOT NULL) AND (reviewed_at IS NOT NULL))))
);

CREATE TABLE public.system_notification_configuration_versions (
    id uuid NOT NULL,
    producer_code text CONSTRAINT system_notification_configuration_versio_producer_code_not_null NOT NULL,
    version integer NOT NULL,
    enabled boolean NOT NULL,
    subject_template text CONSTRAINT system_notification_configuration_ver_subject_template_not_null NOT NULL,
    body_template_rich_text text CONSTRAINT system_notification_configurat_body_template_rich_text_not_null NOT NULL,
    priority text DEFAULT 'normal'::text NOT NULL,
    audience_mode text CONSTRAINT system_notification_configuration_versio_audience_mode_not_null NOT NULL,
    resource_presentation jsonb CONSTRAINT system_notification_configuratio_resource_presentation_not_null NOT NULL,
    operational_owner text CONSTRAINT system_notification_configuration_ve_operational_owner_not_null NOT NULL,
    change_reason text CONSTRAINT system_notification_configuration_versio_change_reason_not_null NOT NULL,
    created_by_user_id bigint CONSTRAINT system_notification_configuration_v_created_by_user_id_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT system_notification_configuration_body_template_rich_text_check CHECK ((octet_length(body_template_rich_text) <= 65536)),
    CONSTRAINT system_notification_configuration_v_resource_presentation_check CHECK ((jsonb_typeof(resource_presentation) = 'object'::text)),
    CONSTRAINT system_notification_configuration_versi_operational_owner_check CHECK ((btrim(operational_owner) <> ''::text)),
    CONSTRAINT system_notification_configuration_versio_subject_template_check CHECK ((((char_length(subject_template) >= 1) AND (char_length(subject_template) <= 255)) AND (btrim(subject_template) <> ''::text))),
    CONSTRAINT system_notification_configuration_versions_change_reason_check CHECK ((btrim(change_reason) <> ''::text)),
    CONSTRAINT system_notification_configuration_versions_priority_check CHECK ((priority = ANY (ARRAY['normal'::text, 'high'::text, 'very_high'::text]))),
    CONSTRAINT system_notification_configuration_versions_version_check CHECK ((version > 0))
);

CREATE TABLE public.system_notification_producers (
    producer_code text NOT NULL,
    feature_code text NOT NULL,
    event_type text NOT NULL,
    required_for_business_commit boolean CONSTRAINT system_notification_produce_required_for_business_comm_not_null NOT NULL,
    contract_version integer NOT NULL,
    contract_definition jsonb NOT NULL,
    active_configuration_version_id uuid,
    name text,
    translations jsonb,
    CONSTRAINT system_notification_producers_contract_definition_check CHECK ((jsonb_typeof(contract_definition) = 'object'::text)),
    CONSTRAINT system_notification_producers_contract_version_check CHECK ((contract_version > 0)),
    CONSTRAINT system_notification_producers_name_check CHECK (((name IS NULL) OR (btrim(name) <> ''::text))),
    CONSTRAINT system_notification_producers_translations_check CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text)))
);

CREATE TABLE public.text_indexing_workers (
    service_user_id bigint NOT NULL,
    worker_id text NOT NULL,
    contract_version text NOT NULL,
    extractor_version text NOT NULL,
    extraction_config_version text NOT NULL,
    index_config_version text NOT NULL,
    capabilities jsonb NOT NULL,
    registered_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_contact_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    active_until timestamp with time zone NOT NULL,
    current_job_id bigint,
    CONSTRAINT text_indexing_workers_capabilities_object CHECK ((jsonb_typeof(capabilities) = 'object'::text)),
    CONSTRAINT text_indexing_workers_id_bounded CHECK (((btrim(worker_id) <> ''::text) AND (length(worker_id) <= 200)))
);

CREATE TABLE public.ui_message_definitions (
    message_key text NOT NULL,
    context_group text NOT NULL,
    default_text text NOT NULL,
    semantic_meaning text NOT NULL,
    common_locations jsonb NOT NULL,
    translator_guidance text NOT NULL,
    grammatical_role text NOT NULL,
    parameter_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    rendered_example text NOT NULL,
    is_html boolean DEFAULT false NOT NULL,
    is_deprecated boolean DEFAULT false NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT ui_message_definitions_context_not_blank CHECK ((btrim(context_group) <> ''::text)),
    CONSTRAINT ui_message_definitions_default_not_blank CHECK ((btrim(default_text) <> ''::text)),
    CONSTRAINT ui_message_definitions_example_not_blank CHECK ((btrim(rendered_example) <> ''::text)),
    CONSTRAINT ui_message_definitions_guidance_not_blank CHECK ((btrim(translator_guidance) <> ''::text)),
    CONSTRAINT ui_message_definitions_key_shape CHECK ((message_key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'::text)),
    CONSTRAINT ui_message_definitions_locations_array CHECK (((jsonb_typeof(common_locations) = 'array'::text) AND (jsonb_array_length(common_locations) > 0))),
    CONSTRAINT ui_message_definitions_meaning_not_blank CHECK ((btrim(semantic_meaning) <> ''::text)),
    CONSTRAINT ui_message_definitions_parameter_object CHECK ((jsonb_typeof(parameter_schema) = 'object'::text)),
    CONSTRAINT ui_message_definitions_role_not_blank CHECK ((btrim(grammatical_role) <> ''::text)),
    CONSTRAINT ui_message_definitions_version_positive CHECK ((version > 0))
);

CREATE TABLE public.ui_message_translations (
    message_key text NOT NULL,
    language_tag text NOT NULL,
    translated_text text NOT NULL,
    published_text text,
    status text DEFAULT 'draft'::text NOT NULL,
    origin text DEFAULT 'source_copy'::text NOT NULL,
    generation_metadata jsonb,
    needs_review boolean DEFAULT false NOT NULL,
    updated_by_user_id bigint,
    reviewed_by_user_id bigint,
    date_reviewed timestamp with time zone,
    published_by_user_id bigint,
    date_published timestamp with time zone,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT ui_message_translations_generated_reviewed_before_publish CHECK (((origin <> 'generated'::text) OR (published_text IS NULL) OR ((reviewed_by_user_id IS NOT NULL) AND (date_reviewed IS NOT NULL)))),
    CONSTRAINT ui_message_translations_generation_object CHECK (((generation_metadata IS NULL) OR (jsonb_typeof(generation_metadata) = 'object'::text))),
    CONSTRAINT ui_message_translations_origin_valid CHECK ((origin = ANY (ARRAY['source_copy'::text, 'manual'::text, 'generated'::text, 'imported'::text]))),
    CONSTRAINT ui_message_translations_publish_pair CHECK (((published_by_user_id IS NULL) = (date_published IS NULL))),
    CONSTRAINT ui_message_translations_published_not_blank CHECK (((published_text IS NULL) OR (btrim(published_text) <> ''::text))),
    CONSTRAINT ui_message_translations_review_pair CHECK (((reviewed_by_user_id IS NULL) = (date_reviewed IS NULL))),
    CONSTRAINT ui_message_translations_source_copy_not_published CHECK (((lower(language_tag) = 'en'::text) OR (origin <> 'source_copy'::text) OR ((status = 'draft'::text) AND (published_text IS NULL) AND (published_by_user_id IS NULL) AND (date_published IS NULL)))),
    CONSTRAINT ui_message_translations_status_valid CHECK ((status = ANY (ARRAY['draft'::text, 'published'::text]))),
    CONSTRAINT ui_message_translations_text_not_blank CHECK ((btrim(translated_text) <> ''::text)),
    CONSTRAINT ui_message_translations_version_positive CHECK ((version > 0))
);

CREATE TABLE public.user_classification_selections (
    user_id bigint NOT NULL,
    classification_id bigint NOT NULL,
    last_selected_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    selection_count bigint DEFAULT 1 NOT NULL,
    CONSTRAINT user_classification_selections_selection_count_check CHECK ((selection_count > 0))
);

CREATE TABLE public.user_credentials (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    password_hash text NOT NULL,
    must_change_password boolean DEFAULT true NOT NULL,
    temporary_expires_at timestamp with time zone,
    password_changed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    failed_attempt_count integer DEFAULT 0 NOT NULL,
    last_failed_at timestamp with time zone,
    locked_until timestamp with time zone,
    last_authenticated_at timestamp with time zone,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT user_credentials_failed_attempts_nonnegative CHECK ((failed_attempt_count >= 0)),
    CONSTRAINT user_credentials_password_hash_not_blank CHECK ((btrim(password_hash) <> ''::text))
);

CREATE SEQUENCE public.user_credentials_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_credentials_id_seq OWNED BY public.user_credentials.id;

CREATE TABLE public.user_favourite_aggregations (
    user_id bigint NOT NULL,
    aggregation_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.user_favourite_records (
    user_id bigint NOT NULL,
    record_id bigint NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.user_preferences (
    user_id bigint NOT NULL,
    language_tag text NOT NULL,
    working_timezone text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT user_preferences_timezone_not_blank CHECK ((btrim(working_timezone) <> ''::text)),
    CONSTRAINT user_preferences_version_positive CHECK ((version > 0))
);

CREATE TABLE public.user_role_assignments (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    role_id bigint NOT NULL,
    date_assigned timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    valid_from timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    valid_until timestamp with time zone,
    version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT user_role_assignments_dates_in_order CHECK (((valid_until IS NULL) OR (valid_until >= valid_from))),
    CONSTRAINT user_role_assignments_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.user_role_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_role_assignments_id_seq OWNED BY public.user_role_assignments.id;

CREATE TABLE public.users (
    id bigint NOT NULL,
    name text NOT NULL,
    email text,
    external_id text,
    account_type text DEFAULT 'person'::text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    date_deactivated timestamp with time zone,
    version bigint DEFAULT 1 NOT NULL,
    date_suspended timestamp with time zone,
    status text GENERATED ALWAYS AS (
CASE
    WHEN (date_deactivated IS NOT NULL) THEN 'inactive'::text
    WHEN (date_suspended IS NOT NULL) THEN 'suspended'::text
    ELSE 'active'::text
END) STORED,
    description text,
    translations jsonb,
    CONSTRAINT users_account_type_valid CHECK ((account_type = ANY (ARRAY['person'::text, 'service'::text]))),
    CONSTRAINT users_dates_in_order CHECK ((((date_deactivated IS NULL) OR (date_deactivated >= date_created)) AND ((date_suspended IS NULL) OR (date_suspended >= date_created)))),
    CONSTRAINT users_email_not_blank CHECK (((email IS NULL) OR (btrim(email) <> ''::text))),
    CONSTRAINT users_external_id_not_blank CHECK (((external_id IS NULL) OR (btrim(external_id) <> ''::text))),
    CONSTRAINT users_lifecycle_dates_exclusive CHECK (((date_deactivated IS NULL) OR (date_suspended IS NULL))),
    CONSTRAINT users_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT users_translations_object CHECK (((translations IS NULL) OR (jsonb_typeof(translations) = 'object'::text))),
    CONSTRAINT users_version_positive CHECK ((version > 0))
);

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

ALTER TABLE ONLY public.aggregation_acl_grants ALTER COLUMN id SET DEFAULT nextval('public.aggregation_acl_grants_id_seq'::regclass);

ALTER TABLE ONLY public.aggregation_relationships ALTER COLUMN id SET DEFAULT nextval('public.aggregation_relationships_id_seq'::regclass);

ALTER TABLE ONLY public.aggregation_retention_rules ALTER COLUMN id SET DEFAULT nextval('public.aggregation_retention_rules_id_seq'::regclass);

ALTER TABLE ONLY public.aggregations ALTER COLUMN id SET DEFAULT nextval('public.aggregations_id_seq'::regclass);

ALTER TABLE ONLY public.application_settings ALTER COLUMN id SET DEFAULT nextval('public.application_settings_id_seq'::regclass);

ALTER TABLE ONLY public.classification_retention_rules ALTER COLUMN id SET DEFAULT nextval('public.classification_retention_rules_id_seq'::regclass);

ALTER TABLE ONLY public.classification_schemes ALTER COLUMN id SET DEFAULT nextval('public.classification_schemes_id_seq'::regclass);

ALTER TABLE ONLY public.classifications ALTER COLUMN id SET DEFAULT nextval('public.classifications_id_seq'::regclass);

ALTER TABLE ONLY public.content_indexing_attempts ALTER COLUMN id SET DEFAULT nextval('public.content_indexing_attempts_id_seq'::regclass);

ALTER TABLE ONLY public.content_indexing_jobs ALTER COLUMN id SET DEFAULT nextval('public.content_indexing_jobs_id_seq'::regclass);

ALTER TABLE ONLY public.content_upload_sessions ALTER COLUMN id SET DEFAULT nextval('public.content_upload_sessions_id_seq'::regclass);

ALTER TABLE ONLY public.digital_component_blobs ALTER COLUMN id SET DEFAULT nextval('public.digital_component_blobs_id_seq'::regclass);

ALTER TABLE ONLY public.digital_component_content_sets ALTER COLUMN id SET DEFAULT nextval('public.digital_component_content_sets_id_seq'::regclass);

ALTER TABLE ONLY public.digital_component_search_chunks ALTER COLUMN id SET DEFAULT nextval('public.digital_component_search_chunks_id_seq'::regclass);

ALTER TABLE ONLY public.digital_components ALTER COLUMN id SET DEFAULT nextval('public.digital_components_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_destruction_manifest_items ALTER COLUMN id SET DEFAULT nextval('public.disposition_destruction_manifest_items_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_destruction_run_units ALTER COLUMN id SET DEFAULT nextval('public.disposition_destruction_run_units_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_destruction_runs ALTER COLUMN id SET DEFAULT nextval('public.disposition_destruction_runs_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_external_approvals ALTER COLUMN id SET DEFAULT nextval('public.disposition_external_approvals_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_job_documents ALTER COLUMN id SET DEFAULT nextval('public.disposition_job_documents_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_job_memberships ALTER COLUMN id SET DEFAULT nextval('public.disposition_job_memberships_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_jobs ALTER COLUMN id SET DEFAULT nextval('public.disposition_jobs_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_proposal_effects ALTER COLUMN id SET DEFAULT nextval('public.disposition_proposal_effects_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_review_decisions ALTER COLUMN id SET DEFAULT nextval('public.disposition_review_decisions_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_review_notes ALTER COLUMN id SET DEFAULT nextval('public.disposition_review_notes_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_review_proposals ALTER COLUMN id SET DEFAULT nextval('public.disposition_review_proposals_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_review_rounds ALTER COLUMN id SET DEFAULT nextval('public.disposition_review_rounds_id_seq'::regclass);

ALTER TABLE ONLY public.disposition_tasks ALTER COLUMN id SET DEFAULT nextval('public.disposition_tasks_id_seq'::regclass);

ALTER TABLE ONLY public.event_history ALTER COLUMN id SET DEFAULT nextval('public.event_history_id_seq'::regclass);

ALTER TABLE ONLY public.hold_aggregation_assignments ALTER COLUMN id SET DEFAULT nextval('public.hold_aggregation_assignments_id_seq'::regclass);

ALTER TABLE ONLY public.hold_contributors ALTER COLUMN id SET DEFAULT nextval('public.hold_contributors_id_seq'::regclass);

ALTER TABLE ONLY public.hold_record_assignments ALTER COLUMN id SET DEFAULT nextval('public.hold_record_assignments_id_seq'::regclass);

ALTER TABLE ONLY public.holds ALTER COLUMN id SET DEFAULT nextval('public.holds_id_seq'::regclass);

ALTER TABLE ONLY public.login_sessions ALTER COLUMN id SET DEFAULT nextval('public.login_sessions_id_seq'::regclass);

ALTER TABLE ONLY public.message_draft_recipient_selectors ALTER COLUMN id SET DEFAULT nextval('public.message_draft_recipient_selectors_id_seq'::regclass);

ALTER TABLE ONLY public.message_draft_resource_links ALTER COLUMN id SET DEFAULT nextval('public.message_draft_resource_links_id_seq'::regclass);

ALTER TABLE ONLY public.message_recipient_selectors ALTER COLUMN id SET DEFAULT nextval('public.message_recipient_selectors_id_seq'::regclass);

ALTER TABLE ONLY public.message_record_capture_components ALTER COLUMN id SET DEFAULT nextval('public.message_record_capture_components_id_seq'::regclass);

ALTER TABLE ONLY public.message_request_receipts ALTER COLUMN id SET DEFAULT nextval('public.message_request_receipts_id_seq'::regclass);

ALTER TABLE ONLY public.message_resource_links ALTER COLUMN id SET DEFAULT nextval('public.message_resource_links_id_seq'::regclass);

ALTER TABLE ONLY public.org_units ALTER COLUMN id SET DEFAULT nextval('public.org_units_id_seq'::regclass);

ALTER TABLE ONLY public.organizational_ownership_assignment_runs ALTER COLUMN id SET DEFAULT nextval('public.organizational_ownership_assignment_runs_id_seq'::regclass);

ALTER TABLE ONLY public.permissions ALTER COLUMN id SET DEFAULT nextval('public.permissions_id_seq'::regclass);

ALTER TABLE ONLY public.privileges ALTER COLUMN id SET DEFAULT nextval('public.privileges_id_seq'::regclass);

ALTER TABLE ONLY public.profile_privileges ALTER COLUMN id SET DEFAULT nextval('public.profile_privileges_id_seq'::regclass);

ALTER TABLE ONLY public.profiles ALTER COLUMN id SET DEFAULT nextval('public.profiles_id_seq'::regclass);

ALTER TABLE ONLY public.record_acl_grants ALTER COLUMN id SET DEFAULT nextval('public.record_acl_grants_id_seq'::regclass);

ALTER TABLE ONLY public.record_draft_component_blobs ALTER COLUMN id SET DEFAULT nextval('public.record_draft_component_blobs_id_seq'::regclass);

ALTER TABLE ONLY public.record_draft_components ALTER COLUMN id SET DEFAULT nextval('public.record_draft_components_id_seq'::regclass);

ALTER TABLE ONLY public.record_drafts ALTER COLUMN id SET DEFAULT nextval('public.record_drafts_id_seq'::regclass);

ALTER TABLE ONLY public.record_relationships ALTER COLUMN id SET DEFAULT nextval('public.record_relationships_id_seq'::regclass);

ALTER TABLE ONLY public.records ALTER COLUMN id SET DEFAULT nextval('public.records_id_seq'::regclass);

ALTER TABLE ONLY public.relationship_types ALTER COLUMN id SET DEFAULT nextval('public.relationship_types_id_seq'::regclass);

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);

ALTER TABLE ONLY public.saved_searches ALTER COLUMN id SET DEFAULT nextval('public.saved_searches_id_seq'::regclass);

ALTER TABLE ONLY public.schema_migrations ALTER COLUMN id SET DEFAULT nextval('public.schema_migrations_id_seq'::regclass);

ALTER TABLE ONLY public.security_levels ALTER COLUMN id SET DEFAULT nextval('public.security_levels_id_seq'::regclass);

ALTER TABLE ONLY public.service_account_credentials ALTER COLUMN id SET DEFAULT nextval('public.service_account_credentials_id_seq'::regclass);

ALTER TABLE ONLY public.system_notification_configuration_audiences ALTER COLUMN id SET DEFAULT nextval('public.system_notification_configuration_audiences_id_seq'::regclass);

ALTER TABLE ONLY public.user_credentials ALTER COLUMN id SET DEFAULT nextval('public.user_credentials_id_seq'::regclass);

ALTER TABLE ONLY public.user_role_assignments ALTER COLUMN id SET DEFAULT nextval('public.user_role_assignments_id_seq'::regclass);

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER TABLE ONLY disposition_private.approval_context
    ADD CONSTRAINT approval_context_pkey PRIMARY KEY (transaction_id);

ALTER TABLE ONLY disposition_private.command_context
    ADD CONSTRAINT command_context_pkey PRIMARY KEY (transaction_id);

ALTER TABLE ONLY disposition_private.command_receipts
    ADD CONSTRAINT command_receipts_pkey PRIMARY KEY (command_id);

ALTER TABLE ONLY disposition_private.communication_context
    ADD CONSTRAINT communication_context_pkey PRIMARY KEY (transaction_id);

ALTER TABLE ONLY disposition_private.completion_context
    ADD CONSTRAINT completion_context_pkey PRIMARY KEY (transaction_id);

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_document_id_key UNIQUE (document_id);

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_pkey PRIMARY KEY (job_id);

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_request_id_key UNIQUE (request_id);

ALTER TABLE ONLY disposition_private.destruction_context
    ADD CONSTRAINT destruction_context_pkey PRIMARY KEY (transaction_id);

ALTER TABLE ONLY disposition_private.destruction_identities
    ADD CONSTRAINT destruction_identities_pkey PRIMARY KEY (transaction_id, root_id);

ALTER TABLE ONLY disposition_private.destruction_numbers
    ADD CONSTRAINT destruction_numbers_pkey PRIMARY KEY (number);

ALTER TABLE ONLY disposition_private.destruction_scopes
    ADD CONSTRAINT destruction_scopes_pkey PRIMARY KEY (run_id, root_id);

ALTER TABLE ONLY disposition_private.email_payloads
    ADD CONSTRAINT email_payloads_pkey PRIMARY KEY (attempt_id);

ALTER TABLE ONLY disposition_private.external_context
    ADD CONSTRAINT external_context_pkey PRIMARY KEY (transaction_id);

ALTER TABLE ONLY disposition_private.job_number_counters
    ADD CONSTRAINT job_number_counters_pkey PRIMARY KEY (job_type, number_year);

ALTER TABLE ONLY disposition_private.physical_context
    ADD CONSTRAINT physical_context_pkey PRIMARY KEY (transaction_id);

ALTER TABLE ONLY disposition_private.processing_copies
    ADD CONSTRAINT processing_copies_pkey PRIMARY KEY (token);

ALTER TABLE ONLY disposition_private.recalculation_context
    ADD CONSTRAINT recalculation_context_pkey PRIMARY KEY (transaction_id, backend_id, root_id);

ALTER TABLE ONLY disposition_private.recovery_context
    ADD CONSTRAINT recovery_context_pkey PRIMARY KEY (transaction_id, root_id);

ALTER TABLE ONLY disposition_private.reminder_checkpoints
    ADD CONSTRAINT reminder_checkpoints_pkey PRIMARY KEY (producer_code, scheduled_at, recipient_user_id);

ALTER TABLE ONLY disposition_private.reminder_schedule
    ADD CONSTRAINT reminder_schedule_pkey PRIMARY KEY (producer_code);

ALTER TABLE ONLY public.aggregation_acl_grants
    ADD CONSTRAINT aggregation_acl_grants_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.aggregation_child_aggregation_acl_defaults
    ADD CONSTRAINT aggregation_child_aggregation_acl_defaults_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.aggregation_child_record_acl_defaults
    ADD CONSTRAINT aggregation_child_record_acl_defaults_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.aggregation_relationships
    ADD CONSTRAINT aggregation_relationships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.aggregation_relationships
    ADD CONSTRAINT aggregation_relationships_relationship_type_id_source_id_ta_key UNIQUE (relationship_type_id, source_id, target_id);

ALTER TABLE ONLY public.aggregation_retention_rules
    ADD CONSTRAINT aggregation_retention_rules_aggregation_id_key UNIQUE (aggregation_id);

ALTER TABLE ONLY public.aggregation_retention_rules
    ADD CONSTRAINT aggregation_retention_rules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.aggregation_search_documents
    ADD CONSTRAINT aggregation_search_documents_pkey PRIMARY KEY (aggregation_id);

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_aggregation_number_key UNIQUE (aggregation_number);

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.application_settings
    ADD CONSTRAINT application_settings_id_key UNIQUE (id);

ALTER TABLE ONLY public.application_settings_migration_keys
    ADD CONSTRAINT application_settings_migration_keys_pkey PRIMARY KEY (migration_id, key);

ALTER TABLE ONLY public.application_settings
    ADD CONSTRAINT application_settings_pkey PRIMARY KEY (key);

ALTER TABLE ONLY public.application_settings_state
    ADD CONSTRAINT application_settings_state_database_id_key UNIQUE (database_id);

ALTER TABLE ONLY public.application_settings_state
    ADD CONSTRAINT application_settings_state_pkey PRIMARY KEY (singleton);

ALTER TABLE ONLY public.classification_retention_rules
    ADD CONSTRAINT classification_retention_rules_classification_id_key UNIQUE (classification_id);

ALTER TABLE ONLY public.classification_retention_rules
    ADD CONSTRAINT classification_retention_rules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.classification_schemes
    ADD CONSTRAINT classification_schemes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.classifications
    ADD CONSTRAINT classifications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.digital_component_search_chunks
    ADD CONSTRAINT component_search_chunks_unique UNIQUE (digital_component_id, chunk_no);

ALTER TABLE ONLY public.content_indexing_attempts
    ADD CONSTRAINT content_indexing_attempts_generation_unique UNIQUE (job_id, lease_generation);

ALTER TABLE ONLY public.content_indexing_attempts
    ADD CONSTRAINT content_indexing_attempts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.content_indexing_batch_items
    ADD CONSTRAINT content_indexing_batch_items_pkey PRIMARY KEY (batch_id, component_identifier);

ALTER TABLE ONLY public.content_indexing_batches
    ADD CONSTRAINT content_indexing_batches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.content_indexing_jobs
    ADD CONSTRAINT content_indexing_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.content_indexing_operations
    ADD CONSTRAINT content_indexing_operations_pkey PRIMARY KEY (job_id, lease_generation, operation, idempotency_key);

ALTER TABLE ONLY public.content_indexing_result_chunks
    ADD CONSTRAINT content_indexing_result_chunks_pkey PRIMARY KEY (job_id, lease_generation, chunk_no);

ALTER TABLE ONLY public.content_upload_sessions
    ADD CONSTRAINT content_upload_sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.digital_component_blobs
    ADD CONSTRAINT digital_component_blobs_content_set_id_segment_no_key UNIQUE (content_set_id, segment_no);

ALTER TABLE ONLY public.digital_component_blobs
    ADD CONSTRAINT digital_component_blobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.digital_component_content_sets
    ADD CONSTRAINT digital_component_content_sets_digital_component_id_id_key UNIQUE (digital_component_id, id);

ALTER TABLE ONLY public.digital_component_content_sets
    ADD CONSTRAINT digital_component_content_sets_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.digital_component_search_chunks
    ADD CONSTRAINT digital_component_search_chunks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.digital_component_search_documents
    ADD CONSTRAINT digital_component_search_documents_pkey PRIMARY KEY (digital_component_id);

ALTER TABLE ONLY public.digital_components
    ADD CONSTRAINT digital_components_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.digital_components
    ADD CONSTRAINT digital_components_record_order_unique UNIQUE (record_id, component_order) DEFERRABLE;

ALTER TABLE ONLY public.disposition_destruction_manifest_items
    ADD CONSTRAINT disposition_destruction_manifest_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_destruction_run_units
    ADD CONSTRAINT disposition_destruction_run_units_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_destruction_run_units
    ADD CONSTRAINT disposition_destruction_run_units_run_id_root_id_key UNIQUE (run_id, root_id);

ALTER TABLE ONLY public.disposition_destruction_runs
    ADD CONSTRAINT disposition_destruction_runs_job_id_run_number_key UNIQUE (job_id, run_number);

ALTER TABLE ONLY public.disposition_destruction_runs
    ADD CONSTRAINT disposition_destruction_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_destruction_runs
    ADD CONSTRAINT disposition_destruction_runs_request_id_key UNIQUE (request_id);

ALTER TABLE ONLY public.disposition_email_attempts
    ADD CONSTRAINT disposition_email_attempts_command_id_key UNIQUE (command_id);

ALTER TABLE ONLY public.disposition_email_attempts
    ADD CONSTRAINT disposition_email_attempts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_approval_letter_document_id_key UNIQUE (approval_letter_document_id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_rejection_letter_document_id_key UNIQUE (rejection_letter_document_id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_request_document_id_key UNIQUE (request_document_id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_task_id_key UNIQUE (task_id);

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_supersedes_document_id_key UNIQUE (supersedes_document_id);

ALTER TABLE ONLY public.disposition_job_memberships
    ADD CONSTRAINT disposition_job_memberships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_destruction_number_key UNIQUE (destruction_number);

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_job_number_key UNIQUE (job_number);

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_transfer_number_key UNIQUE (transfer_number);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_certificate_document_id_key UNIQUE (certificate_document_id);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_certificate_reference_key UNIQUE (certificate_reference);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_job_id_key UNIQUE (job_id);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_task_id_key UNIQUE (task_id);

ALTER TABLE ONLY public.disposition_proposal_effects
    ADD CONSTRAINT disposition_proposal_effects_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_proposal_holds
    ADD CONSTRAINT disposition_proposal_holds_pkey PRIMARY KEY (proposal_id, hold_id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_pkey PRIMARY KEY (resource_kind, resource_id);

ALTER TABLE ONLY public.disposition_review_decisions
    ADD CONSTRAINT disposition_review_decisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_review_decisions
    ADD CONSTRAINT disposition_review_decisions_task_id_key UNIQUE (task_id);

ALTER TABLE ONLY public.disposition_review_notes
    ADD CONSTRAINT disposition_review_notes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_review_notes
    ADD CONSTRAINT disposition_review_notes_task_id_author_user_id_key UNIQUE (task_id, author_user_id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_review_rounds
    ADD CONSTRAINT disposition_review_rounds_id_job_id_key UNIQUE (id, job_id);

ALTER TABLE ONLY public.disposition_review_rounds
    ADD CONSTRAINT disposition_review_rounds_job_id_round_number_key UNIQUE (job_id, round_number);

ALTER TABLE ONLY public.disposition_review_rounds
    ADD CONSTRAINT disposition_review_rounds_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.disposition_template_revisions
    ADD CONSTRAINT disposition_template_revision_document_type_revision_number_key UNIQUE (document_type, revision_number);

ALTER TABLE ONLY public.disposition_template_revisions
    ADD CONSTRAINT disposition_template_revisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.event_history
    ADD CONSTRAINT event_history_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.hold_aggregation_assignments
    ADD CONSTRAINT hold_aggregation_assignments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.hold_aggregation_assignments
    ADD CONSTRAINT hold_aggregation_assignments_unique UNIQUE (hold_id, aggregation_id);

ALTER TABLE ONLY public.hold_contributors
    ADD CONSTRAINT hold_contributors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.hold_contributors
    ADD CONSTRAINT hold_contributors_unique UNIQUE (hold_id, user_id);

ALTER TABLE ONLY public.hold_notification_reminders
    ADD CONSTRAINT hold_notification_reminders_pkey PRIMARY KEY (hold_id, end_at);

ALTER TABLE ONLY public.hold_record_assignments
    ADD CONSTRAINT hold_record_assignments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.hold_record_assignments
    ADD CONSTRAINT hold_record_assignments_unique UNIQUE (hold_id, record_id);

ALTER TABLE ONLY public.holds
    ADD CONSTRAINT holds_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_session_token_hash_key UNIQUE (session_token_hash);

ALTER TABLE ONLY public.message_action_amendments
    ADD CONSTRAINT message_action_amendments_created_by_user_id_request_id_key UNIQUE (created_by_user_id, request_id);

ALTER TABLE ONLY public.message_action_amendments
    ADD CONSTRAINT message_action_amendments_original_envelope_id_sequence_key UNIQUE (original_envelope_id, sequence);

ALTER TABLE ONLY public.message_action_amendments
    ADD CONSTRAINT message_action_amendments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_action_completions
    ADD CONSTRAINT message_action_completions_pkey PRIMARY KEY (original_delivery_id);

ALTER TABLE ONLY public.message_action_completions
    ADD CONSTRAINT message_action_completions_reply_envelope_id_key UNIQUE (reply_envelope_id);

ALTER TABLE ONLY public.message_addressees
    ADD CONSTRAINT message_addressees_envelope_id_recipient_type_ordinal_key UNIQUE (envelope_id, recipient_type, ordinal);

ALTER TABLE ONLY public.message_addressees
    ADD CONSTRAINT message_addressees_envelope_id_user_id_recipient_type_key UNIQUE (envelope_id, user_id, recipient_type);

ALTER TABLE ONLY public.message_addressees
    ADD CONSTRAINT message_addressees_pkey PRIMARY KEY (envelope_id, user_id);

ALTER TABLE ONLY public.message_capture_drafts
    ADD CONSTRAINT message_capture_drafts_capture_id_key UNIQUE (capture_id);

ALTER TABLE ONLY public.message_capture_drafts
    ADD CONSTRAINT message_capture_drafts_pkey PRIMARY KEY (draft_id);

ALTER TABLE ONLY public.message_deliveries
    ADD CONSTRAINT message_deliveries_envelope_id_recipient_user_id_key UNIQUE (envelope_id, recipient_user_id);

ALTER TABLE ONLY public.message_deliveries
    ADD CONSTRAINT message_deliveries_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_deliveries
    ADD CONSTRAINT message_deliveries_recipient_user_id_mailbox_sequence_key UNIQUE (recipient_user_id, mailbox_sequence);

ALTER TABLE ONLY public.message_draft_recipient_selectors
    ADD CONSTRAINT message_draft_recipient_selec_draft_id_recipient_type_ordin_key UNIQUE (draft_id, recipient_type, ordinal);

ALTER TABLE ONLY public.message_draft_recipient_selectors
    ADD CONSTRAINT message_draft_recipient_selectors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_draft_resource_links
    ADD CONSTRAINT message_draft_resource_links_draft_id_link_token_key UNIQUE (draft_id, link_token);

ALTER TABLE ONLY public.message_draft_resource_links
    ADD CONSTRAINT message_draft_resource_links_draft_id_ordinal_key UNIQUE (draft_id, ordinal);

ALTER TABLE ONLY public.message_draft_resource_links
    ADD CONSTRAINT message_draft_resource_links_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_drafts
    ADD CONSTRAINT message_drafts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_envelope_localizations
    ADD CONSTRAINT message_envelope_localizations_pkey PRIMARY KEY (envelope_id, language_tag);

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_action_amendment_id_key UNIQUE (action_amendment_id);

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_test_run_id_key UNIQUE (test_run_id);

ALTER TABLE ONLY public.message_mailboxes
    ADD CONSTRAINT message_mailboxes_pkey PRIMARY KEY (user_id);

ALTER TABLE ONLY public.message_recipient_selectors
    ADD CONSTRAINT message_recipient_selectors_envelope_id_recipient_type_ordi_key UNIQUE (envelope_id, recipient_type, ordinal);

ALTER TABLE ONLY public.message_recipient_selectors
    ADD CONSTRAINT message_recipient_selectors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_record_capture_components
    ADD CONSTRAINT message_record_capture_compon_digital_component_id_at_captu_key UNIQUE (digital_component_id_at_capture);

ALTER TABLE ONLY public.message_record_capture_components
    ADD CONSTRAINT message_record_capture_component_capture_id_component_order_key UNIQUE (capture_id, component_order);

ALTER TABLE ONLY public.message_record_capture_components
    ADD CONSTRAINT message_record_capture_components_digital_component_id_key UNIQUE (digital_component_id);

ALTER TABLE ONLY public.message_record_capture_components
    ADD CONSTRAINT message_record_capture_components_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_record_captures
    ADD CONSTRAINT message_record_captures_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_record_captures
    ADD CONSTRAINT message_record_captures_record_id_at_capture_key UNIQUE (record_id_at_capture);

ALTER TABLE ONLY public.message_record_captures
    ADD CONSTRAINT message_record_captures_record_id_key UNIQUE (record_id);

ALTER TABLE ONLY public.message_request_receipts
    ADD CONSTRAINT message_request_receipts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.message_resource_links
    ADD CONSTRAINT message_resource_links_envelope_id_link_token_key UNIQUE (envelope_id, link_token);

ALTER TABLE ONLY public.message_resource_links
    ADD CONSTRAINT message_resource_links_envelope_id_ordinal_key UNIQUE (envelope_id, ordinal);

ALTER TABLE ONLY public.message_resource_links
    ADD CONSTRAINT message_resource_links_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.messaging_cleanup_groups
    ADD CONSTRAINT messaging_cleanup_groups_pkey PRIMARY KEY (group_key);

ALTER TABLE ONLY public.messaging_gateway_health
    ADD CONSTRAINT messaging_gateway_health_pkey PRIMARY KEY (instance_id);

ALTER TABLE ONLY public.messaging_notification_configuration_guard
    ADD CONSTRAINT messaging_notification_configuration_guard_pkey PRIMARY KEY (singleton);

ALTER TABLE ONLY public.messaging_operational_metrics
    ADD CONSTRAINT messaging_operational_metrics_pkey PRIMARY KEY (metric, instance_id, producer_code);

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.organizational_ownership_assignment_runs
    ADD CONSTRAINT organizational_ownership_assignment_runs_migration_version_key UNIQUE (migration_version);

ALTER TABLE ONLY public.organizational_ownership_assignment_runs
    ADD CONSTRAINT organizational_ownership_assignment_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.organizational_ownership_root_assignments
    ADD CONSTRAINT organizational_ownership_root_assignments_pkey PRIMARY KEY (root_aggregation_id);

ALTER TABLE ONLY public.permission_dependencies
    ADD CONSTRAINT permission_dependencies_pkey PRIMARY KEY (permission_id, required_permission_id);

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.privilege_dependencies
    ADD CONSTRAINT privilege_dependencies_pkey PRIMARY KEY (privilege_id, required_privilege_id);

ALTER TABLE ONLY public.privileges
    ADD CONSTRAINT privileges_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.profile_privileges
    ADD CONSTRAINT profile_privileges_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.profile_privileges
    ADD CONSTRAINT profile_privileges_unique UNIQUE (profile_id, privilege_id);

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.record_acl_grants
    ADD CONSTRAINT record_acl_grants_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.record_draft_component_blobs
    ADD CONSTRAINT record_draft_component_blobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.record_draft_component_blobs
    ADD CONSTRAINT record_draft_component_blobs_record_draft_component_id_segm_key UNIQUE (record_draft_component_id, segment_no);

ALTER TABLE ONLY public.record_draft_components
    ADD CONSTRAINT record_draft_components_draft_order_unique UNIQUE (draft_id, component_order) DEFERRABLE;

ALTER TABLE ONLY public.record_draft_components
    ADD CONSTRAINT record_draft_components_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.record_drafts
    ADD CONSTRAINT record_drafts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.record_relationships
    ADD CONSTRAINT record_relationships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.record_relationships
    ADD CONSTRAINT record_relationships_relationship_type_id_source_id_target__key UNIQUE (relationship_type_id, source_id, target_id);

ALTER TABLE ONLY public.record_search_documents
    ADD CONSTRAINT record_search_documents_pkey PRIMARY KEY (record_id);

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_record_number_key UNIQUE (record_number);

ALTER TABLE ONLY public.relationship_types
    ADD CONSTRAINT relationship_types_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.relationship_types
    ADD CONSTRAINT relationship_types_resource_kind_code_key UNIQUE (resource_kind, code);

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.saved_search_org_unit_grants
    ADD CONSTRAINT saved_search_org_unit_grants_pkey PRIMARY KEY (saved_search_id, org_unit_id);

ALTER TABLE ONLY public.saved_search_role_grants
    ADD CONSTRAINT saved_search_role_grants_pkey PRIMARY KEY (saved_search_id, role_id);

ALTER TABLE ONLY public.saved_searches
    ADD CONSTRAINT saved_searches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_version_key UNIQUE (version);

ALTER TABLE ONLY public.security_levels
    ADD CONSTRAINT security_levels_level_number_unique UNIQUE (level_number);

ALTER TABLE ONLY public.security_levels
    ADD CONSTRAINT security_levels_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.service_account_credentials
    ADD CONSTRAINT service_account_credentials_identifier_unique UNIQUE (credential_identifier);

ALTER TABLE ONLY public.service_account_credentials
    ADD CONSTRAINT service_account_credentials_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.supported_languages
    ADD CONSTRAINT supported_languages_language_tag_key UNIQUE (language_tag);

ALTER TABLE ONLY public.supported_languages
    ADD CONSTRAINT supported_languages_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.system_notification_configuration_audiences
    ADD CONSTRAINT system_notification_configura_configuration_version_id_reci_key UNIQUE (configuration_version_id, recipient_type, ordinal);

ALTER TABLE ONLY public.system_notification_configuration_audiences
    ADD CONSTRAINT system_notification_configuration_audiences_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.system_notification_configuration_translations
    ADD CONSTRAINT system_notification_configuration_translations_pkey PRIMARY KEY (configuration_version_id, language_tag);

ALTER TABLE ONLY public.system_notification_configuration_versions
    ADD CONSTRAINT system_notification_configuration_ver_producer_code_version_key UNIQUE (producer_code, version);

ALTER TABLE ONLY public.system_notification_configuration_versions
    ADD CONSTRAINT system_notification_configuration_versions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.system_notification_configuration_versions
    ADD CONSTRAINT system_notification_configuration_versions_producer_code_id_key UNIQUE (producer_code, id);

ALTER TABLE ONLY public.system_notification_producers
    ADD CONSTRAINT system_notification_producers_pkey PRIMARY KEY (producer_code);

ALTER TABLE ONLY public.text_indexing_workers
    ADD CONSTRAINT text_indexing_workers_pkey PRIMARY KEY (service_user_id, worker_id);

ALTER TABLE ONLY public.ui_message_definitions
    ADD CONSTRAINT ui_message_definitions_pkey PRIMARY KEY (message_key);

ALTER TABLE ONLY public.ui_message_translations
    ADD CONSTRAINT ui_message_translations_pkey PRIMARY KEY (message_key, language_tag);

ALTER TABLE ONLY public.user_classification_selections
    ADD CONSTRAINT user_classification_selections_pkey PRIMARY KEY (user_id, classification_id);

ALTER TABLE ONLY public.user_credentials
    ADD CONSTRAINT user_credentials_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_credentials
    ADD CONSTRAINT user_credentials_user_id_key UNIQUE (user_id);

ALTER TABLE ONLY public.user_favourite_aggregations
    ADD CONSTRAINT user_favourite_aggregations_pkey PRIMARY KEY (user_id, aggregation_id);

ALTER TABLE ONLY public.user_favourite_records
    ADD CONSTRAINT user_favourite_records_pkey PRIMARY KEY (user_id, record_id);

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (user_id);

ALTER TABLE ONLY public.user_role_assignments
    ADD CONSTRAINT user_role_assignments_period_unique UNIQUE (user_id, role_id, valid_from);

ALTER TABLE ONLY public.user_role_assignments
    ADD CONSTRAINT user_role_assignments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

CREATE INDEX disposition_completion_pending ON disposition_private.completion_work USING btree (job_id) WHERE (state = ANY (ARRAY['queued'::text, 'running'::text]));

CREATE INDEX disposition_processing_copies_component ON disposition_private.processing_copies USING btree (component_id);

CREATE UNIQUE INDEX aggregation_acl_everyone_grant_unique ON public.aggregation_acl_grants USING btree (aggregation_id, permission_id) WHERE (principal_type = 'everyone'::text);

CREATE UNIQUE INDEX aggregation_acl_grants_oversight_unique ON public.aggregation_acl_grants USING btree (aggregation_id, principal_type, permission_id) WHERE (principal_type = ANY (ARRAY['owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text]));

CREATE UNIQUE INDEX aggregation_acl_org_unit_members_grant_unique ON public.aggregation_acl_grants USING btree (aggregation_id, permission_id) WHERE (principal_type = 'org_unit_members'::text);

CREATE UNIQUE INDEX aggregation_acl_role_grant_unique ON public.aggregation_acl_grants USING btree (aggregation_id, role_id, permission_id) WHERE (principal_type = 'role'::text);

CREATE INDEX aggregation_acl_role_idx ON public.aggregation_acl_grants USING btree (role_id, aggregation_id, permission_id);

CREATE UNIQUE INDEX aggregation_child_aggregation_acl_defaults_oversight_unique ON public.aggregation_child_aggregation_acl_defaults USING btree (aggregation_id, principal_type, permission_id) WHERE (principal_type = ANY (ARRAY['owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text]));

CREATE UNIQUE INDEX aggregation_child_record_acl_defaults_oversight_unique ON public.aggregation_child_record_acl_defaults USING btree (aggregation_id, principal_type, permission_id) WHERE (principal_type = ANY (ARRAY['owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text]));

CREATE INDEX aggregation_relationships_source_idx ON public.aggregation_relationships USING btree (source_id, id);

CREATE INDEX aggregation_relationships_target_idx ON public.aggregation_relationships USING btree (target_id, id);

CREATE INDEX aggregation_search_documents_vector_gin ON public.aggregation_search_documents USING gin (search_vector);

CREATE INDEX aggregations_classification_id_idx ON public.aggregations USING btree (classification_id);

CREATE INDEX aggregations_classification_number_browse_idx ON public.aggregations USING btree (classification_id, aggregation_number COLLATE "C", id);

CREATE INDEX aggregations_medium_idx ON public.aggregations USING btree (medium, id);

CREATE INDEX aggregations_next_review_idx ON public.aggregations USING btree (date_of_next_review, id) WHERE (date_of_next_review IS NOT NULL);

CREATE INDEX aggregations_owner_parent_number_browse_idx ON public.aggregations USING btree (owning_org_unit_id, parent_aggregation_id, aggregation_number COLLATE "C", id);

CREATE INDEX aggregations_owner_review_due_idx ON public.aggregations USING btree (owning_org_unit_id, date_of_next_review, id) WHERE (date_of_next_review IS NOT NULL);

CREATE INDEX aggregations_parent_aggregation_id_idx ON public.aggregations USING btree (parent_aggregation_id);

CREATE INDEX aggregations_parent_number_browse_idx ON public.aggregations USING btree (parent_aggregation_id, aggregation_number COLLATE "C", id);

CREATE INDEX aggregations_review_due_idx ON public.aggregations USING btree (date_of_next_review, id) WHERE (date_of_next_review IS NOT NULL);

CREATE INDEX aggregations_security_level_id_idx ON public.aggregations USING btree (security_level_id);

CREATE INDEX aggregations_vital_idx ON public.aggregations USING btree (is_vital, id);

CREATE UNIQUE INDEX child_aggregation_acl_everyone_grant_unique ON public.aggregation_child_aggregation_acl_defaults USING btree (aggregation_id, permission_id) WHERE (principal_type = 'everyone'::text);

CREATE UNIQUE INDEX child_aggregation_acl_org_unit_members_grant_unique ON public.aggregation_child_aggregation_acl_defaults USING btree (aggregation_id, permission_id) WHERE (principal_type = 'org_unit_members'::text);

CREATE UNIQUE INDEX child_aggregation_acl_role_grant_unique ON public.aggregation_child_aggregation_acl_defaults USING btree (aggregation_id, role_id, permission_id) WHERE (principal_type = 'role'::text);

CREATE INDEX child_aggregation_acl_role_idx ON public.aggregation_child_aggregation_acl_defaults USING btree (role_id, aggregation_id, permission_id);

CREATE UNIQUE INDEX child_record_acl_everyone_grant_unique ON public.aggregation_child_record_acl_defaults USING btree (aggregation_id, permission_id) WHERE (principal_type = 'everyone'::text);

CREATE UNIQUE INDEX child_record_acl_org_unit_members_grant_unique ON public.aggregation_child_record_acl_defaults USING btree (aggregation_id, permission_id) WHERE (principal_type = 'org_unit_members'::text);

CREATE UNIQUE INDEX child_record_acl_role_grant_unique ON public.aggregation_child_record_acl_defaults USING btree (aggregation_id, role_id, permission_id) WHERE (principal_type = 'role'::text);

CREATE INDEX child_record_acl_role_idx ON public.aggregation_child_record_acl_defaults USING btree (role_id, aggregation_id, permission_id);

CREATE UNIQUE INDEX classification_schemes_code_ci_unique ON public.classification_schemes USING btree (lower(code));

CREATE INDEX classification_schemes_translation_text_trgm_idx ON public.classification_schemes USING gin (((translations)::text) public.gin_trgm_ops);

CREATE INDEX classification_schemes_translations_gin ON public.classification_schemes USING gin (translations jsonb_path_ops);

CREATE INDEX classifications_parent_code_browse_idx ON public.classifications USING btree (classification_scheme_id, parent_classification_id, code COLLATE "C", id);

CREATE UNIQUE INDEX classifications_scheme_code_ci_unique ON public.classifications USING btree (classification_scheme_id, lower(code));

CREATE INDEX classifications_scheme_parent_idx ON public.classifications USING btree (classification_scheme_id, parent_classification_id);

CREATE INDEX classifications_translation_text_trgm_idx ON public.classifications USING gin (((translations)::text) public.gin_trgm_ops);

CREATE INDEX classifications_translations_gin ON public.classifications USING gin (translations jsonb_path_ops);

CREATE INDEX component_search_chunks_vector_gin ON public.digital_component_search_chunks USING gin (search_vector);

CREATE INDEX component_search_record_idx ON public.digital_component_search_documents USING btree (record_id, digital_component_id);

CREATE INDEX component_search_status_reconcile_idx ON public.digital_component_search_documents USING btree (status, date_updated, digital_component_id);

CREATE INDEX content_indexing_attempts_completed_idx ON public.content_indexing_attempts USING btree (completed_at, id) WHERE (status <> 'processing'::text);

CREATE INDEX content_indexing_batch_items_job_idx ON public.content_indexing_batch_items USING btree (job_id) WHERE (job_id IS NOT NULL);

CREATE UNIQUE INDEX content_indexing_jobs_active_unique ON public.content_indexing_jobs USING btree (digital_component_id, content_set_id, extraction_config_version, index_config_version, extractor_version) WHERE (status = ANY (ARRAY['queued'::text, 'leased'::text]));

CREATE INDEX content_indexing_jobs_claim_idx ON public.content_indexing_jobs USING btree (priority DESC, not_before, id) WHERE (status = ANY (ARRAY['queued'::text, 'leased'::text]));

CREATE INDEX content_indexing_jobs_expired_lease_idx ON public.content_indexing_jobs USING btree (lease_expires_at, id) WHERE (status = 'leased'::text);

CREATE INDEX content_upload_sessions_cleanup_idx ON public.content_upload_sessions USING btree (status, expires_at);

CREATE UNIQUE INDEX content_upload_sessions_open_component_idx ON public.content_upload_sessions USING btree (digital_component_id) WHERE (status = ANY (ARRAY['uploading'::text, 'interrupted'::text, 'finalizing'::text]));

CREATE UNIQUE INDEX content_upload_sessions_open_draft_component_idx ON public.content_upload_sessions USING btree (draft_component_id) WHERE (status = ANY (ARRAY['uploading'::text, 'interrupted'::text, 'finalizing'::text]));

CREATE INDEX digital_component_blobs_content_set_order_idx ON public.digital_component_blobs USING btree (content_set_id, segment_no);

CREATE UNIQUE INDEX digital_component_one_active_content_set_idx ON public.digital_component_content_sets USING btree (digital_component_id) WHERE (status = 'active'::text);

CREATE INDEX digital_components_record_id_idx ON public.digital_components USING btree (record_id);

CREATE INDEX disposition_destruction_claim ON public.disposition_destruction_runs USING btree (id) WHERE (state = ANY (ARRAY['queued'::text, 'running'::text]));

CREATE UNIQUE INDEX disposition_destruction_manifest_identity ON public.disposition_destruction_manifest_items USING btree (job_id, resource_kind, resource_id, COALESCE(source_content_set_id, (0)::bigint));

CREATE INDEX disposition_destruction_manifest_root ON public.disposition_destruction_manifest_items USING btree (job_id, root_id, id);

CREATE UNIQUE INDEX disposition_destruction_one_active ON public.disposition_destruction_runs USING btree (job_id) WHERE (state = ANY (ARRAY['queued'::text, 'running'::text]));

CREATE INDEX disposition_destruction_units_claim ON public.disposition_destruction_run_units USING btree (run_id, state, id);

CREATE INDEX disposition_documents_component ON public.disposition_job_documents USING btree (digital_component_id);

CREATE INDEX disposition_documents_job_page ON public.disposition_job_documents USING btree (job_id, id DESC);

CREATE INDEX disposition_documents_record ON public.disposition_job_documents USING btree (record_id);

CREATE INDEX disposition_effects_proposal ON public.disposition_proposal_effects USING btree (proposal_id, id);

CREATE INDEX disposition_eligibility_scan ON public.aggregations USING btree (id) WHERE ((parent_aggregation_id IS NULL) AND (disposition_status = 1) AND (date_closed IS NOT NULL));

CREATE INDEX disposition_email_job_page ON public.disposition_email_attempts USING btree (job_id, id DESC);

CREATE INDEX disposition_email_pending ON public.disposition_email_attempts USING btree (id) WHERE (status = 'sending'::text);

CREATE UNIQUE INDEX disposition_execution_report_round ON public.disposition_job_documents USING btree (job_id, review_round) WHERE ((document_type = 'proposal_execution_report'::text) AND (provenance ? 'approval_round_id'::text));

CREATE INDEX disposition_external_approvals_job ON public.disposition_external_approvals USING btree (job_id, id);

CREATE INDEX disposition_memberships_job ON public.disposition_job_memberships USING btree (job_id, id);

CREATE INDEX disposition_notes_job_round ON public.disposition_review_notes USING btree (job_id, review_round, id);

CREATE UNIQUE INDEX disposition_one_active_job_per_root ON public.disposition_job_memberships USING btree (root_aggregation_id) WHERE (membership_state = 'active'::text);

CREATE UNIQUE INDEX disposition_one_certificate_download ON public.disposition_tasks USING btree (job_id) WHERE (task_type = 'certificate_download'::text);

CREATE UNIQUE INDEX disposition_one_digital_certificate ON public.disposition_job_documents USING btree (job_id) WHERE (document_type = 'digital_destruction_certificate'::text);

CREATE INDEX disposition_physical_scope_lookup ON public.disposition_physical_confirmations USING gin (physical_scope jsonb_path_ops);

CREATE INDEX disposition_proposal_active_round ON public.disposition_review_proposals USING btree (job_id, review_round) WHERE (proposal_state = 'active'::text);

CREATE INDEX disposition_proposals_job_round ON public.disposition_review_proposals USING btree (job_id, review_round, id);

CREATE UNIQUE INDEX disposition_request_approval_round ON public.disposition_job_documents USING btree (job_id, review_round) WHERE ((document_type = 'destruction_request'::text) AND (provenance ? 'approval_round_id'::text));

CREATE INDEX disposition_retained_job_root ON public.disposition_retained_records USING btree (job_id, root_id, resource_kind, resource_id);

CREATE INDEX disposition_tasks_current_stage ON public.disposition_tasks USING btree (job_id, workflow_stage, task_state, id);

CREATE INDEX disposition_tasks_inbox_role ON public.disposition_tasks USING btree (destination_role_id, task_state, id);

CREATE INDEX disposition_tasks_inbox_user ON public.disposition_tasks USING btree (destination_user_id, task_state, id);

CREATE INDEX event_history_actor_email_trgm_idx ON public.event_history USING gin (actor_email public.gin_trgm_ops);

CREATE INDEX event_history_actor_identity_idx ON public.event_history USING btree (actor_user_id, md5(actor_name), md5(actor_email), actor_type);

CREATE INDEX event_history_actor_name_trgm_idx ON public.event_history USING gin (actor_name public.gin_trgm_ops);

CREATE INDEX event_history_actor_timeline_idx ON public.event_history USING btree (actor_user_id, occurred_at DESC, id DESC) WHERE (actor_user_id IS NOT NULL);

CREATE INDEX event_history_correlation_id_idx ON public.event_history USING btree (correlation_id) WHERE (correlation_id IS NOT NULL);

CREATE INDEX event_history_entity_timeline_idx ON public.event_history USING btree (entity_type, entity_id, occurred_at DESC, id DESC);

CREATE INDEX event_history_occurred_at_idx ON public.event_history USING btree (occurred_at DESC, id DESC);

CREATE INDEX event_history_request_id_idx ON public.event_history USING btree (request_id) WHERE (request_id IS NOT NULL);

CREATE INDEX event_history_security_operation_timeline_idx ON public.event_history USING btree (operation, occurred_at DESC) WHERE (operation = ANY (ARRAY['AUTHORIZATION_DENIED'::text, 'AUTHENTICATION_FAILED'::text, 'ACCOUNT_LOCKED'::text, 'INFORMATION_GOVERNANCE_BYPASS_USED'::text, 'ACCESS_EXPLANATION_VIEWED'::text, 'SECURITY_LEVEL_CHANGED'::text, 'SECURITY_LEVEL_UPGRADED'::text, 'SECURITY_LEVEL_DOWNGRADED'::text, 'ACL_REPLACED'::text, 'DEFAULT_CHILD_AGGREGATION_ACL_REPLACED'::text, 'DEFAULT_CHILD_RECORD_ACL_REPLACED'::text, 'PROFILE_PRIVILEGES_REPLACED'::text, 'PROFILE_ASSIGNED'::text, 'GOVERNANCE_ROLE_CHANGED'::text]));

CREATE INDEX hold_aggregation_assignments_resource_idx ON public.hold_aggregation_assignments USING btree (aggregation_id, hold_id);

CREATE INDEX hold_contributors_user_idx ON public.hold_contributors USING btree (user_id, hold_id);

CREATE INDEX hold_record_assignments_resource_idx ON public.hold_record_assignments USING btree (record_id, hold_id);

CREATE UNIQUE INDEX holds_code_ci_unique ON public.holds USING btree (lower(code));

CREATE INDEX holds_effective_period_idx ON public.holds USING btree (valid_from, valid_to, id);

CREATE INDEX holds_notification_due_idx ON public.holds USING btree (valid_to, id) WHERE (valid_to IS NOT NULL);

CREATE INDEX holds_owner_idx ON public.holds USING btree (owner_user_id, id);

CREATE INDEX login_sessions_active_idx ON public.login_sessions USING btree (expires_at, absolute_expires_at) WHERE (revoked_at IS NULL);

CREATE INDEX login_sessions_revoked_cleanup_idx ON public.login_sessions USING btree (revoked_at, id) WHERE (revoked_at IS NOT NULL);

CREATE INDEX login_sessions_user_id_idx ON public.login_sessions USING btree (user_id);

CREATE INDEX message_action_completions_user_idx ON public.message_action_completions USING btree (completed_by_user_id, completed_at DESC);

CREATE UNIQUE INDEX message_capture_envelope_idx ON public.message_record_capture_components USING btree (capture_id, envelope_id_at_capture) WHERE (component_kind = 'message'::text);

CREATE UNIQUE INDEX message_capture_provenance_idx ON public.message_record_capture_components USING btree (capture_id) WHERE (component_kind = 'provenance'::text);

CREATE INDEX message_deliveries_inbox_idx ON public.message_deliveries USING btree (recipient_user_id, deleted_at, read_at, created_at DESC, id);

CREATE INDEX message_deliveries_page_idx ON public.message_deliveries USING btree (recipient_user_id, mailbox_sequence DESC) WHERE (deleted_at IS NULL);

CREATE INDEX message_delivery_cleanup_idx ON public.message_deliveries USING btree (purge_after, envelope_id);

CREATE INDEX message_delivery_sent_page_idx ON public.message_deliveries USING btree (recipient_user_id, created_at DESC, id DESC) WHERE (deleted_at IS NULL);

CREATE INDEX message_draft_cleanup_idx ON public.message_drafts USING btree (expires_at, purge_after, id);

CREATE UNIQUE INDEX message_draft_recipient_selectors_everyone_unique ON public.message_draft_recipient_selectors USING btree (draft_id, recipient_type) WHERE (selector_kind = 'everyone'::text);

CREATE UNIQUE INDEX message_draft_recipient_selectors_org_unit_id_unique ON public.message_draft_recipient_selectors USING btree (draft_id, recipient_type, org_unit_id) WHERE (org_unit_id IS NOT NULL);

CREATE UNIQUE INDEX message_draft_recipient_selectors_role_id_unique ON public.message_draft_recipient_selectors USING btree (draft_id, recipient_type, role_id) WHERE (role_id IS NOT NULL);

CREATE UNIQUE INDEX message_draft_recipient_selectors_user_id_unique ON public.message_draft_recipient_selectors USING btree (draft_id, recipient_type, user_id) WHERE (user_id IS NOT NULL);

CREATE INDEX message_draft_resource_links_aggregation_id_idx ON public.message_draft_resource_links USING btree (aggregation_id) WHERE (aggregation_id IS NOT NULL);

CREATE INDEX message_draft_resource_links_record_id_idx ON public.message_draft_resource_links USING btree (record_id) WHERE (record_id IS NOT NULL);

CREATE INDEX message_drafts_expiry_idx ON public.message_drafts USING btree (expires_at, id);

CREATE INDEX message_drafts_owner_idx ON public.message_drafts USING btree (owner_user_id, date_updated DESC, id);

CREATE INDEX message_envelope_related_delivery_idx ON public.message_envelopes USING btree (related_delivery_id) WHERE (related_delivery_id IS NOT NULL);

CREATE INDEX message_envelope_related_envelope_idx ON public.message_envelopes USING btree (related_envelope_id) WHERE (related_envelope_id IS NOT NULL);

CREATE INDEX message_envelopes_expiry_idx ON public.message_envelopes USING btree (expires_at, id);

CREATE INDEX message_envelopes_outbox_idx ON public.message_envelopes USING btree (sender_user_id, sent_at DESC, id DESC) WHERE ((sender_deleted_at IS NULL) AND (message_kind = 'user_message'::text));

CREATE UNIQUE INDEX message_envelopes_system_event_idx ON public.message_envelopes USING btree (system_producer_code, source_event_type, source_event_id) WHERE ((sender_kind = 'system'::text) AND (NOT is_test));

CREATE UNIQUE INDEX message_envelopes_system_request_idx ON public.message_envelopes USING btree (system_producer_code, request_id) WHERE (sender_kind = 'system'::text);

CREATE UNIQUE INDEX message_envelopes_user_request_idx ON public.message_envelopes USING btree (sender_user_id, request_id) WHERE (sender_kind = 'user'::text);

CREATE UNIQUE INDEX message_recipient_selectors_everyone_unique ON public.message_recipient_selectors USING btree (envelope_id, recipient_type) WHERE (selector_kind = 'everyone'::text);

CREATE UNIQUE INDEX message_recipient_selectors_org_unit_id_unique ON public.message_recipient_selectors USING btree (envelope_id, recipient_type, org_unit_id) WHERE (org_unit_id IS NOT NULL);

CREATE UNIQUE INDEX message_recipient_selectors_role_id_unique ON public.message_recipient_selectors USING btree (envelope_id, recipient_type, role_id) WHERE (role_id IS NOT NULL);

CREATE UNIQUE INDEX message_recipient_selectors_user_id_unique ON public.message_recipient_selectors USING btree (envelope_id, recipient_type, user_id) WHERE (user_id IS NOT NULL);

CREATE UNIQUE INDEX message_request_receipts_event_key ON public.message_request_receipts USING btree (producer_code, source_event_type, source_event_id) WHERE (source_event_id IS NOT NULL);

CREATE UNIQUE INDEX message_request_receipts_producer_key ON public.message_request_receipts USING btree (operation_kind, producer_code, request_id) WHERE (producer_code IS NOT NULL);

CREATE INDEX message_request_receipts_result_idx ON public.message_request_receipts USING btree (result_envelope_id);

CREATE UNIQUE INDEX message_request_receipts_user_key ON public.message_request_receipts USING btree (operation_kind, principal_user_id, request_id) WHERE (principal_user_id IS NOT NULL);

CREATE INDEX message_resource_links_aggregation_id_idx ON public.message_resource_links USING btree (aggregation_id) WHERE (aggregation_id IS NOT NULL);

CREATE INDEX message_resource_links_record_id_idx ON public.message_resource_links USING btree (record_id) WHERE (record_id IS NOT NULL);

CREATE INDEX notification_test_history_idx ON public.event_history USING btree (((metadata ->> 'producer_code'::text)), id DESC) WHERE ((entity_type = 'system_notification'::text) AND (operation = ANY (ARRAY['NOTIFICATION_TEST_SENT'::text, 'NOTIFICATION_TEST_FAILED'::text])));

CREATE INDEX notification_test_rate_idx ON public.event_history USING btree (actor_user_id, occurred_at) WHERE (operation = 'NOTIFICATION_TEST_SENT'::text);

CREATE UNIQUE INDEX org_units_code_ci_unique ON public.org_units USING btree (lower(code));

CREATE INDEX org_units_file_administrator_role_idx ON public.org_units USING btree (file_administrator_role_id);

CREATE INDEX org_units_managing_role_idx ON public.org_units USING btree (managing_role_id);

CREATE UNIQUE INDEX org_units_name_ci_unique ON public.org_units USING btree (lower(name));

CREATE INDEX org_units_parent_org_unit_id_idx ON public.org_units USING btree (parent_org_unit_id);

CREATE INDEX org_units_translation_text_trgm_idx ON public.org_units USING gin (((translations)::text) public.gin_trgm_ops);

CREATE INDEX org_units_translations_gin ON public.org_units USING gin (translations jsonb_path_ops);

CREATE INDEX organizational_ownership_root_assignments_role_idx ON public.organizational_ownership_root_assignments USING btree (selected_role_id, root_aggregation_id);

CREATE INDEX organizational_ownership_root_assignments_unit_idx ON public.organizational_ownership_root_assignments USING btree (owning_org_unit_id, root_aggregation_id);

CREATE UNIQUE INDEX permissions_code_ci_unique ON public.permissions USING btree (lower(code));

CREATE UNIQUE INDEX privileges_code_ci_unique ON public.privileges USING btree (lower(code));

CREATE INDEX profile_privileges_privilege_id_idx ON public.profile_privileges USING btree (privilege_id, profile_id);

CREATE UNIQUE INDEX profiles_code_ci_unique ON public.profiles USING btree (lower(code));

CREATE UNIQUE INDEX profiles_name_ci_unique ON public.profiles USING btree (lower(name));

CREATE INDEX profiles_translation_text_trgm_idx ON public.profiles USING gin (((translations)::text) public.gin_trgm_ops);

CREATE INDEX profiles_translations_gin ON public.profiles USING gin (translations jsonb_path_ops);

CREATE UNIQUE INDEX record_acl_everyone_grant_unique ON public.record_acl_grants USING btree (record_id, permission_id) WHERE (principal_type = 'everyone'::text);

CREATE UNIQUE INDEX record_acl_grants_oversight_unique ON public.record_acl_grants USING btree (record_id, principal_type, permission_id) WHERE (principal_type = ANY (ARRAY['owning_and_higher_level_unit_managers'::text, 'effective_file_administrator'::text]));

CREATE UNIQUE INDEX record_acl_org_unit_members_grant_unique ON public.record_acl_grants USING btree (record_id, permission_id) WHERE (principal_type = 'org_unit_members'::text);

CREATE UNIQUE INDEX record_acl_role_grant_unique ON public.record_acl_grants USING btree (record_id, role_id, permission_id) WHERE (principal_type = 'role'::text);

CREATE INDEX record_acl_role_idx ON public.record_acl_grants USING btree (role_id, record_id, permission_id);

CREATE INDEX record_draft_component_blobs_component_order_idx ON public.record_draft_component_blobs USING btree (record_draft_component_id, segment_no);

CREATE INDEX record_draft_components_draft_id_idx ON public.record_draft_components USING btree (draft_id);

CREATE INDEX record_drafts_expires_at_idx ON public.record_drafts USING btree (expires_at);

CREATE INDEX record_drafts_owner_user_id_idx ON public.record_drafts USING btree (owner_user_id);

CREATE INDEX record_drafts_security_level_id_idx ON public.record_drafts USING btree (security_level_id);

CREATE INDEX record_relationships_source_idx ON public.record_relationships USING btree (source_id, id);

CREATE INDEX record_relationships_target_idx ON public.record_relationships USING btree (target_id, id);

CREATE INDEX record_search_documents_vector_gin ON public.record_search_documents USING gin (search_vector);

CREATE INDEX records_aggregation_id_idx ON public.records USING btree (aggregation_id);

CREATE INDEX records_aggregation_number_browse_idx ON public.records USING btree (aggregation_id, record_number COLLATE "C", id);

CREATE INDEX records_medium_idx ON public.records USING btree (medium, id);

CREATE INDEX records_next_review_idx ON public.records USING btree (date_of_next_review, id) WHERE (date_of_next_review IS NOT NULL);

CREATE INDEX records_owner_aggregation_number_browse_idx ON public.records USING btree (owning_org_unit_id, aggregation_id, record_number COLLATE "C", id);

CREATE INDEX records_owner_review_due_idx ON public.records USING btree (owning_org_unit_id, date_of_next_review, id) WHERE (date_of_next_review IS NOT NULL);

CREATE INDEX records_review_due_idx ON public.records USING btree (date_of_next_review, id) WHERE (date_of_next_review IS NOT NULL);

CREATE INDEX records_security_level_id_idx ON public.records USING btree (security_level_id);

CREATE INDEX records_vital_idx ON public.records USING btree (is_vital, id);

CREATE INDEX result_chunks_cleanup_idx ON public.content_indexing_result_chunks USING btree (date_staged, job_id, lease_generation);

CREATE UNIQUE INDEX roles_code_ci_unique ON public.roles USING btree (lower(code));

CREATE INDEX roles_governance_clearance_idx ON public.roles USING btree (is_information_governance, security_level_id) WHERE is_information_governance;

CREATE UNIQUE INDEX roles_name_ci_unique ON public.roles USING btree (lower(name));

CREATE INDEX roles_org_unit_id_idx ON public.roles USING btree (org_unit_id);

CREATE INDEX roles_profile_id_idx ON public.roles USING btree (profile_id);

CREATE INDEX roles_security_level_id_idx ON public.roles USING btree (security_level_id);

CREATE INDEX roles_supervisor_role_id_idx ON public.roles USING btree (supervisor_role_id);

CREATE INDEX roles_translation_text_trgm_idx ON public.roles USING gin (((translations)::text) public.gin_trgm_ops);

CREATE INDEX roles_translations_gin ON public.roles USING gin (translations jsonb_path_ops);

CREATE INDEX saved_search_org_unit_grants_unit_idx ON public.saved_search_org_unit_grants USING btree (org_unit_id, saved_search_id);

CREATE INDEX saved_search_role_grants_role_idx ON public.saved_search_role_grants USING btree (role_id, saved_search_id);

CREATE INDEX saved_searches_category_ci_idx ON public.saved_searches USING btree (lower(category), date_updated DESC, id DESC) WHERE (category IS NOT NULL);

CREATE UNIQUE INDEX saved_searches_owner_name_ci_unique ON public.saved_searches USING btree (owner_user_id, lower(name));

CREATE INDEX saved_searches_owner_updated_idx ON public.saved_searches USING btree (owner_user_id, date_updated DESC, id DESC);

CREATE INDEX saved_searches_resource_updated_idx ON public.saved_searches USING btree (resource_type, date_updated DESC, id DESC);

CREATE UNIQUE INDEX security_levels_code_ci_unique ON public.security_levels USING btree (lower(code));

CREATE UNIQUE INDEX security_levels_name_ci_unique ON public.security_levels USING btree (lower(name));

CREATE INDEX security_levels_translation_text_trgm_idx ON public.security_levels USING gin (((translations)::text) public.gin_trgm_ops);

CREATE INDEX security_levels_translations_gin ON public.security_levels USING gin (translations jsonb_path_ops);

CREATE INDEX service_account_credentials_active_expiry_idx ON public.service_account_credentials USING btree (expires_at, id) WHERE (status = 'active'::text);

CREATE INDEX service_account_credentials_history_cleanup_idx ON public.service_account_credentials USING btree (COALESCE(date_revoked, expires_at), id);

CREATE INDEX service_account_credentials_service_user_idx ON public.service_account_credentials USING btree (service_user_id, date_created DESC, id DESC);

CREATE UNIQUE INDEX supported_languages_one_default_idx ON public.supported_languages USING btree (is_default) WHERE is_default;

CREATE UNIQUE INDEX supported_languages_tag_ci_unique ON public.supported_languages USING btree (lower(language_tag));

CREATE UNIQUE INDEX system_notification_configuration_audiences_org_unit_id_unique ON public.system_notification_configuration_audiences USING btree (configuration_version_id, recipient_type, org_unit_id) WHERE (org_unit_id IS NOT NULL);

CREATE UNIQUE INDEX system_notification_configuration_audiences_role_id_unique ON public.system_notification_configuration_audiences USING btree (configuration_version_id, recipient_type, role_id) WHERE (role_id IS NOT NULL);

CREATE UNIQUE INDEX system_notification_configuration_audiences_user_id_unique ON public.system_notification_configuration_audiences USING btree (configuration_version_id, recipient_type, user_id) WHERE (user_id IS NOT NULL);

CREATE INDEX text_indexing_workers_active_idx ON public.text_indexing_workers USING btree (active_until, service_user_id, worker_id);

CREATE INDEX ui_message_definitions_context_key_idx ON public.ui_message_definitions USING btree (context_group, message_key);

CREATE INDEX ui_message_translations_attention_idx ON public.ui_message_translations USING btree (language_tag, needs_review, message_key);

CREATE INDEX ui_message_translations_language_origin_idx ON public.ui_message_translations USING btree (language_tag, origin, message_key);

CREATE INDEX ui_message_translations_language_status_idx ON public.ui_message_translations USING btree (language_tag, status, message_key);

CREATE INDEX user_classification_selections_recent_idx ON public.user_classification_selections USING btree (user_id, last_selected_at DESC);

CREATE INDEX user_favourite_aggregations_aggregation_id_idx ON public.user_favourite_aggregations USING btree (aggregation_id);

CREATE INDEX user_favourite_aggregations_user_created_idx ON public.user_favourite_aggregations USING btree (user_id, date_created DESC, aggregation_id);

CREATE INDEX user_favourite_records_record_id_idx ON public.user_favourite_records USING btree (record_id);

CREATE INDEX user_favourite_records_user_created_idx ON public.user_favourite_records USING btree (user_id, date_created DESC, record_id);

CREATE INDEX user_role_assignments_effective_lookup_idx ON public.user_role_assignments USING btree (user_id, role_id, valid_from, valid_until);

CREATE INDEX user_role_assignments_role_id_idx ON public.user_role_assignments USING btree (role_id);

CREATE INDEX user_role_assignments_user_id_idx ON public.user_role_assignments USING btree (user_id);

CREATE UNIQUE INDEX users_email_ci_unique ON public.users USING btree (lower(email)) WHERE (email IS NOT NULL);

CREATE UNIQUE INDEX users_external_id_unique ON public.users USING btree (external_id) WHERE (external_id IS NOT NULL);

CREATE INDEX users_translation_text_trgm_idx ON public.users USING gin (((translations)::text) public.gin_trgm_ops);

CREATE INDEX users_translations_gin ON public.users USING gin (translations jsonb_path_ops);

CREATE CONSTRAINT TRIGGER disposition_command_complete AFTER INSERT ON disposition_private.command_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.command_complete_check();

CREATE TRIGGER disposition_command_immutable BEFORE DELETE OR UPDATE ON disposition_private.command_receipts FOR EACH ROW EXECUTE FUNCTION disposition_private.command_immutable();

CREATE TRIGGER disposition_number_guard BEFORE INSERT OR DELETE OR UPDATE ON disposition_private.destruction_numbers FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_destruction_number();

CREATE TRIGGER payload_guard BEFORE INSERT OR DELETE OR UPDATE ON disposition_private.email_payloads FOR EACH ROW EXECUTE FUNCTION disposition_private.communication_guard();

CREATE TRIGGER a_disposition_recovery_guard BEFORE UPDATE ON public.aggregations FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_recovery_resource();

CREATE TRIGGER a_disposition_recovery_guard BEFORE UPDATE ON public.records FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_recovery_resource();

CREATE TRIGGER aggregation_acl_clearance BEFORE INSERT OR UPDATE ON public.aggregation_acl_grants FOR EACH ROW EXECUTE FUNCTION public.validate_acl_role_clearance();

CREATE CONSTRAINT TRIGGER aggregation_acl_dependencies AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_acl_grants DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_acl_dependencies('aggregation_id');

CREATE TRIGGER aggregation_acl_history AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_acl_grants FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('aggregation_acl_grant');

CREATE TRIGGER aggregation_acl_type BEFORE INSERT OR UPDATE ON public.aggregation_acl_grants FOR EACH ROW EXECUTE FUNCTION public.validate_acl_permission_type();

CREATE TRIGGER aggregation_relationships_guard BEFORE INSERT OR DELETE OR UPDATE ON public.aggregation_relationships FOR EACH ROW EXECUTE FUNCTION public.guard_resource_relationship('aggregation');

CREATE TRIGGER aggregation_relationships_history AFTER INSERT OR DELETE ON public.aggregation_relationships FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('aggregation_relationship');

CREATE TRIGGER aggregation_retention_rules_bump_version BEFORE UPDATE ON public.aggregation_retention_rules FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER aggregation_retention_rules_record_history AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_retention_rules FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('aggregation_retention_rule');

CREATE TRIGGER aggregation_retention_rules_touch BEFORE UPDATE ON public.aggregation_retention_rules FOR EACH ROW EXECUTE FUNCTION public.touch_classification_date_updated();

CREATE CONSTRAINT TRIGGER aggregation_rules_validate_root AFTER INSERT OR UPDATE ON public.aggregation_retention_rules DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_root_aggregation_retention_rules();

CREATE TRIGGER aggregations_bump_version BEFORE UPDATE ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER aggregations_default_security_level BEFORE INSERT ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.default_entity_security_level();

CREATE CONSTRAINT TRIGGER aggregations_disposition_consistency AFTER UPDATE ON public.aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN ((((((((old.disposition_status IS DISTINCT FROM new.disposition_status) OR (old.final_disposition_at IS DISTINCT FROM new.final_disposition_at)) OR (old.final_disposition_by_user_id IS DISTINCT FROM new.final_disposition_by_user_id)) OR (old.disposition_job_id IS DISTINCT FROM new.disposition_job_id)) OR (old.destruction_number IS DISTINCT FROM new.destruction_number)) OR (old.transfer_number IS DISTINCT FROM new.transfer_number)) OR (old.final_disposition_event_id IS DISTINCT FROM new.final_disposition_event_id))) EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE TRIGGER aggregations_disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.aggregations FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_resource();

CREATE CONSTRAINT TRIGGER aggregations_disposition_hierarchy_consistency AFTER UPDATE ON public.aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN ((old.parent_aggregation_id IS DISTINCT FROM new.parent_aggregation_id)) EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE CONSTRAINT TRIGGER aggregations_disposition_insert_consistency AFTER INSERT ON public.aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE TRIGGER aggregations_enforce_future_review_date BEFORE INSERT OR UPDATE OF date_of_next_review ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.enforce_future_review_date();

CREATE TRIGGER aggregations_enforce_medium_hierarchy BEFORE INSERT OR UPDATE OF parent_aggregation_id, medium ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.enforce_aggregation_medium_hierarchy();

CREATE TRIGGER aggregations_enforce_ownership BEFORE INSERT OR UPDATE OF parent_aggregation_id, owning_org_unit_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.enforce_aggregation_ownership();

CREATE TRIGGER aggregations_enforce_security_hierarchy BEFORE INSERT OR UPDATE OF parent_aggregation_id, security_level_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.enforce_resource_security_hierarchy();

CREATE TRIGGER aggregations_future_next_review BEFORE INSERT OR UPDATE OF date_of_next_review ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.enforce_future_next_review_date();

CREATE TRIGGER aggregations_govern_location_change BEFORE UPDATE OF assigned_location, current_location ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.allow_governed_aggregation_location_change();

CREATE TRIGGER aggregations_govern_review_date BEFORE UPDATE OF date_of_next_review ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.allow_governed_review_date_change();

CREATE TRIGGER aggregations_govern_vital_status BEFORE UPDATE OF is_vital ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.allow_governed_vital_status_change();

CREATE TRIGGER aggregations_initialize_acls AFTER INSERT ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.initialize_resource_acls();

CREATE TRIGGER aggregations_normalize_acl_inheritance BEFORE INSERT OR UPDATE OF parent_aggregation_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.normalize_aggregation_acl_inheritance();

CREATE TRIGGER aggregations_prevent_cycle BEFORE INSERT OR UPDATE OF parent_aggregation_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.prevent_aggregation_cycle();

CREATE TRIGGER aggregations_propagate_ownership AFTER UPDATE OF parent_aggregation_id, owning_org_unit_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.propagate_aggregation_ownership();

CREATE TRIGGER aggregations_protect_closed_hierarchy BEFORE INSERT OR DELETE OR UPDATE ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.protect_closed_aggregation_hierarchy();

CREATE TRIGGER aggregations_protect_effective_holds BEFORE DELETE OR UPDATE ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.protect_held_resource();

CREATE TRIGGER aggregations_protect_vital_deletion BEFORE DELETE ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.protect_vital_resource_deletion();

CREATE TRIGGER aggregations_record_classification_governance_first_use AFTER INSERT OR UPDATE OF classification_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.record_classification_governance_first_use();

CREATE TRIGGER aggregations_record_classification_selection AFTER INSERT OR UPDATE OF classification_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.record_classification_selection();

CREATE TRIGGER aggregations_record_history AFTER INSERT OR DELETE OR UPDATE ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('aggregation');

CREATE TRIGGER aggregations_refresh_metadata_search AFTER INSERT OR UPDATE OF aggregation_number, title, description ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.refresh_aggregation_metadata_search_document();

CREATE TRIGGER aggregations_set_default_dates BEFORE INSERT ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.set_aggregation_default_dates();

CREATE TRIGGER aggregations_validate_classification BEFORE INSERT OR UPDATE OF parent_aggregation_id, classification_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.validate_aggregation_classification();

CREATE TRIGGER aggregations_validate_closure_date BEFORE INSERT OR UPDATE OF date_closed ON public.aggregations FOR EACH ROW EXECUTE FUNCTION public.validate_aggregation_closure_date();

CREATE CONSTRAINT TRIGGER aggregations_validate_local_rule_root AFTER UPDATE ON public.aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_root_aggregation_retention_rules();

CREATE TRIGGER application_settings_audit AFTER INSERT OR UPDATE ON public.application_settings FOR EACH ROW EXECUTE FUNCTION public.audit_application_setting();

CREATE TRIGGER application_settings_guard BEFORE INSERT OR DELETE OR UPDATE ON public.application_settings FOR EACH ROW EXECUTE FUNCTION public.guard_application_setting();

CREATE TRIGGER application_settings_migration_guard BEFORE INSERT OR DELETE OR UPDATE ON public.application_settings_migration_keys FOR EACH ROW EXECUTE FUNCTION public.guard_settings_migration_completion();

CREATE TRIGGER application_settings_migration_reject_truncate BEFORE TRUNCATE ON public.application_settings_migration_keys FOR EACH STATEMENT EXECUTE FUNCTION public.reject_application_settings_removal();

CREATE TRIGGER application_settings_reject_truncate BEFORE TRUNCATE ON public.application_settings FOR EACH STATEMENT EXECUTE FUNCTION public.reject_application_settings_removal();

CREATE CONSTRAINT TRIGGER application_settings_set_constraint AFTER INSERT OR UPDATE ON public.application_settings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.check_application_settings_set();

CREATE TRIGGER application_settings_state_immutable BEFORE DELETE OR UPDATE OR TRUNCATE ON public.application_settings_state FOR EACH STATEMENT EXECUTE FUNCTION public.reject_application_settings_removal();

CREATE TRIGGER child_aggregation_acl_clearance BEFORE INSERT OR UPDATE ON public.aggregation_child_aggregation_acl_defaults FOR EACH ROW EXECUTE FUNCTION public.validate_acl_role_clearance();

CREATE CONSTRAINT TRIGGER child_aggregation_acl_dependencies AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_child_aggregation_acl_defaults DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_acl_dependencies('aggregation_id');

CREATE TRIGGER child_aggregation_acl_history AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_child_aggregation_acl_defaults FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('aggregation_child_aggregation_acl_default');

CREATE TRIGGER child_aggregation_acl_type BEFORE INSERT OR UPDATE ON public.aggregation_child_aggregation_acl_defaults FOR EACH ROW EXECUTE FUNCTION public.validate_acl_permission_type();

CREATE TRIGGER child_record_acl_clearance BEFORE INSERT OR UPDATE ON public.aggregation_child_record_acl_defaults FOR EACH ROW EXECUTE FUNCTION public.validate_acl_role_clearance();

CREATE CONSTRAINT TRIGGER child_record_acl_dependencies AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_child_record_acl_defaults DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_acl_dependencies('aggregation_id');

CREATE TRIGGER child_record_acl_history AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_child_record_acl_defaults FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('aggregation_child_record_acl_default');

CREATE TRIGGER child_record_acl_type BEFORE INSERT OR UPDATE ON public.aggregation_child_record_acl_defaults FOR EACH ROW EXECUTE FUNCTION public.validate_acl_permission_type();

CREATE TRIGGER classification_retention_rules_bump_version BEFORE UPDATE ON public.classification_retention_rules FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER classification_retention_rules_record_history AFTER INSERT OR DELETE OR UPDATE ON public.classification_retention_rules FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('classification_retention_rule');

CREATE TRIGGER classification_retention_rules_touch BEFORE UPDATE ON public.classification_retention_rules FOR EACH ROW EXECUTE FUNCTION public.touch_classification_date_updated();

CREATE CONSTRAINT TRIGGER classification_rules_validate_effective_rule AFTER INSERT OR DELETE OR UPDATE ON public.classification_retention_rules DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_terminal_classification_rules();

CREATE TRIGGER classification_schemes_bump_version BEFORE UPDATE ON public.classification_schemes FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER classification_schemes_delete_unused BEFORE DELETE ON public.classification_schemes FOR EACH ROW EXECUTE FUNCTION public.delete_unused_classification_scheme();

CREATE TRIGGER classification_schemes_record_history AFTER INSERT OR DELETE OR UPDATE ON public.classification_schemes FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('classification_scheme');

CREATE TRIGGER classification_schemes_touch BEFORE UPDATE ON public.classification_schemes FOR EACH ROW EXECUTE FUNCTION public.touch_classification_date_updated();

CREATE TRIGGER classification_schemes_validate_dates BEFORE INSERT OR UPDATE OF date_created, date_published, date_deactivated, date_first_used ON public.classification_schemes FOR EACH ROW EXECUTE FUNCTION public.validate_classification_scheme_dates();

CREATE TRIGGER classification_schemes_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.classification_schemes FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

CREATE TRIGGER classifications_bump_version BEFORE UPDATE ON public.classifications FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER classifications_protect_deletion BEFORE DELETE ON public.classifications FOR EACH ROW EXECUTE FUNCTION public.protect_classification_deletion();

CREATE TRIGGER classifications_record_history AFTER INSERT OR DELETE OR UPDATE ON public.classifications FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('classification');

CREATE CONSTRAINT TRIGGER classifications_settings_destination_constraint AFTER UPDATE ON public.classifications DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.check_application_settings_set();

CREATE TRIGGER classifications_touch BEFORE UPDATE ON public.classifications FOR EACH ROW EXECUTE FUNCTION public.touch_classification_date_updated();

CREATE TRIGGER classifications_validate_dates BEFORE INSERT OR UPDATE OF date_created, date_deactivated, date_first_used ON public.classifications FOR EACH ROW EXECUTE FUNCTION public.validate_classification_dates();

CREATE CONSTRAINT TRIGGER classifications_validate_effective_rule AFTER INSERT OR UPDATE ON public.classifications DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_terminal_classification_rules();

CREATE TRIGGER classifications_validate_structure BEFORE INSERT OR UPDATE OF classification_scheme_id, parent_classification_id, is_terminal ON public.classifications FOR EACH ROW EXECUTE FUNCTION public.validate_classification_structure();

CREATE TRIGGER classifications_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.classifications FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

CREATE TRIGGER component_search_validate_identity BEFORE INSERT OR UPDATE ON public.digital_component_search_documents FOR EACH ROW EXECUTE FUNCTION public.validate_component_search_identity();

CREATE TRIGGER content_upload_sessions_protect_effective_holds BEFORE INSERT OR DELETE OR UPDATE ON public.content_upload_sessions FOR EACH ROW EXECUTE FUNCTION public.protect_held_component_mutation();

CREATE TRIGGER digital_component_blobs_protect_closed_aggregation BEFORE INSERT OR DELETE OR UPDATE ON public.digital_component_blobs FOR EACH ROW EXECUTE FUNCTION public.protect_blob_in_closed_aggregation();

CREATE TRIGGER digital_component_blobs_protect_effective_holds BEFORE INSERT OR DELETE OR UPDATE ON public.digital_component_blobs FOR EACH ROW EXECUTE FUNCTION public.protect_held_component_mutation();

CREATE TRIGGER digital_component_content_sets_protect_closed_aggregation BEFORE INSERT OR DELETE OR UPDATE ON public.digital_component_content_sets FOR EACH ROW EXECUTE FUNCTION public.protect_content_set_in_closed_aggregation();

CREATE TRIGGER digital_component_content_sets_protect_effective_holds BEFORE INSERT OR DELETE OR UPDATE ON public.digital_component_content_sets FOR EACH ROW EXECUTE FUNCTION public.protect_held_component_mutation();

CREATE TRIGGER digital_components_bump_version BEFORE UPDATE ON public.digital_components FOR EACH ROW EXECUTE FUNCTION public.bump_digital_component_version();

CREATE TRIGGER digital_components_enforce_record_medium BEFORE INSERT OR UPDATE OF record_id ON public.digital_components FOR EACH ROW EXECUTE FUNCTION public.enforce_digital_component_record_medium();

CREATE TRIGGER digital_components_protect_closed_aggregation BEFORE INSERT OR DELETE OR UPDATE ON public.digital_components FOR EACH ROW EXECUTE FUNCTION public.protect_component_in_closed_aggregation();

CREATE TRIGGER digital_components_protect_effective_holds BEFORE INSERT OR DELETE OR UPDATE ON public.digital_components FOR EACH ROW EXECUTE FUNCTION public.protect_held_component_mutation();

CREATE TRIGGER digital_components_record_history AFTER INSERT OR DELETE OR UPDATE ON public.digital_components FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('digital_component');

CREATE TRIGGER digital_components_schedule_content_indexing AFTER INSERT OR UPDATE OF active_content_set_id, content_status ON public.digital_components FOR EACH ROW EXECUTE FUNCTION public.schedule_component_content_indexing();

CREATE TRIGGER digital_components_set_default_dates BEFORE INSERT ON public.digital_components FOR EACH ROW EXECUTE FUNCTION public.set_originated_default_dates();

CREATE TRIGGER disposition_audit AFTER INSERT OR UPDATE ON public.disposition_job_documents FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_workflow();

CREATE TRIGGER disposition_audit AFTER INSERT OR UPDATE ON public.disposition_job_memberships FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_workflow();

CREATE TRIGGER disposition_audit AFTER INSERT OR UPDATE ON public.disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_workflow();

CREATE TRIGGER disposition_audit AFTER INSERT OR UPDATE ON public.disposition_review_decisions FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_workflow();

CREATE TRIGGER disposition_audit AFTER INSERT OR UPDATE ON public.disposition_review_rounds FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_workflow();

CREATE TRIGGER disposition_audit AFTER INSERT OR UPDATE ON public.disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_workflow();

CREATE TRIGGER disposition_destruction_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_destruction_manifest_items FOR EACH ROW EXECUTE FUNCTION disposition_private.destruction_guard();

CREATE TRIGGER disposition_destruction_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_destruction_run_units FOR EACH ROW EXECUTE FUNCTION disposition_private.destruction_guard();

CREATE TRIGGER disposition_destruction_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_destruction_runs FOR EACH ROW EXECUTE FUNCTION disposition_private.destruction_guard();

CREATE TRIGGER disposition_effect_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_proposal_effects FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_proposal_effect();

CREATE CONSTRAINT TRIGGER disposition_evidence_outside_job AFTER UPDATE ON public.aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN ((old.parent_aggregation_id IS DISTINCT FROM new.parent_aggregation_id)) EXECUTE FUNCTION disposition_private.artifact_outside_job();

CREATE CONSTRAINT TRIGGER disposition_evidence_outside_job AFTER INSERT OR UPDATE ON public.disposition_job_memberships DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.artifact_outside_job();

CREATE CONSTRAINT TRIGGER disposition_evidence_outside_job AFTER UPDATE ON public.records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN ((old.aggregation_id IS DISTINCT FROM new.aggregation_id)) EXECUTE FUNCTION disposition_private.artifact_outside_job();

CREATE TRIGGER disposition_external_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_external_approvals FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_external_approval();

CREATE TRIGGER disposition_external_task BEFORE INSERT OR UPDATE ON public.disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_external_task();

CREATE TRIGGER disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_job_documents FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_workflow();

CREATE TRIGGER disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_job_memberships FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_workflow();

CREATE TRIGGER disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_workflow();

CREATE TRIGGER disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_review_decisions FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_workflow();

CREATE TRIGGER disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_review_rounds FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_workflow();

CREATE TRIGGER disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_workflow();

CREATE CONSTRAINT TRIGGER disposition_job_consistency AFTER INSERT OR UPDATE ON public.disposition_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE CONSTRAINT TRIGGER disposition_membership_consistency AFTER INSERT OR UPDATE ON public.disposition_job_memberships DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE TRIGGER disposition_physical_confirmation_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_physical_confirmations FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_physical_confirmation();

CREATE TRIGGER disposition_physical_task_guard BEFORE INSERT OR UPDATE ON public.disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_physical_task();

CREATE TRIGGER disposition_policy_coordination BEFORE INSERT OR DELETE OR UPDATE ON public.aggregation_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();

CREATE TRIGGER disposition_policy_coordination BEFORE UPDATE OF date_closed, classification_id, parent_aggregation_id ON public.aggregations FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();

CREATE TRIGGER disposition_policy_coordination BEFORE INSERT OR DELETE OR UPDATE ON public.classification_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();

CREATE TRIGGER disposition_policy_coordination BEFORE UPDATE ON public.classifications FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_policy_change();

CREATE TRIGGER disposition_preparation_task AFTER INSERT OR UPDATE OF assigned_user_id ON public.disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.preparation_task();

CREATE TRIGGER disposition_preserve_content BEFORE INSERT OR DELETE OR UPDATE ON public.digital_component_blobs FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_artifact_content();

CREATE TRIGGER disposition_preserve_content BEFORE INSERT OR DELETE OR UPDATE ON public.digital_component_content_sets FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_artifact_content();

CREATE TRIGGER disposition_preserve_content BEFORE DELETE OR UPDATE ON public.digital_components FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_artifact_content();

CREATE TRIGGER disposition_preserve_physical BEFORE UPDATE ON public.disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_physical_outcome();

CREATE TRIGGER disposition_proposal_audit AFTER INSERT OR UPDATE ON public.disposition_review_proposals FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_review_work();

CREATE TRIGGER disposition_proposal_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_review_proposals FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_proposal();

CREATE TRIGGER disposition_proposal_hold_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_proposal_holds FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_proposal_hold();

CREATE CONSTRAINT TRIGGER disposition_proposal_holds_consistency AFTER INSERT OR DELETE OR UPDATE ON public.disposition_proposal_holds DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_proposal_holds();

CREATE CONSTRAINT TRIGGER disposition_proposal_holds_consistency AFTER INSERT OR UPDATE ON public.disposition_review_proposals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_proposal_holds();

CREATE TRIGGER disposition_proposal_unique BEFORE INSERT OR UPDATE ON public.disposition_review_proposals FOR EACH ROW EXECUTE FUNCTION disposition_private.reject_duplicate_proposal();

CREATE TRIGGER disposition_recalculation_apply AFTER INSERT OR DELETE OR UPDATE ON public.aggregation_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();

CREATE TRIGGER disposition_recalculation_apply AFTER UPDATE OF date_closed, classification_id, parent_aggregation_id ON public.aggregations FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();

CREATE TRIGGER disposition_recalculation_apply AFTER INSERT OR DELETE OR UPDATE ON public.classification_retention_rules FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();

CREATE TRIGGER disposition_recalculation_apply AFTER UPDATE ON public.classifications FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.finish_policy_change();

CREATE TRIGGER disposition_recalculation_capture BEFORE INSERT OR DELETE OR UPDATE ON public.aggregation_retention_rules FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();

CREATE TRIGGER disposition_recalculation_capture BEFORE UPDATE OF date_closed, classification_id, parent_aggregation_id ON public.aggregations FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();

CREATE TRIGGER disposition_recalculation_capture BEFORE INSERT OR DELETE OR UPDATE ON public.classification_retention_rules FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();

CREATE TRIGGER disposition_recalculation_capture BEFORE UPDATE ON public.classifications FOR EACH ROW EXECUTE FUNCTION disposition_private.capture_policy_change();

CREATE TRIGGER disposition_relationship_coordination BEFORE INSERT OR DELETE OR UPDATE ON public.aggregation_relationships FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_relationship_change();

CREATE TRIGGER disposition_relationship_coordination BEFORE INSERT OR DELETE OR UPDATE ON public.record_relationships FOR EACH STATEMENT EXECUTE FUNCTION disposition_private.coordinate_relationship_change();

CREATE TRIGGER disposition_retained_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_retained_records FOR EACH ROW EXECUTE FUNCTION disposition_private.retained_guard();

CREATE TRIGGER disposition_review_comments BEFORE INSERT ON public.disposition_review_decisions FOR EACH ROW EXECUTE FUNCTION disposition_private.review_decision_comments();

CREATE TRIGGER disposition_review_draft_fields BEFORE UPDATE ON public.disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_review_draft_fields();

CREATE TRIGGER disposition_review_draft_fields BEFORE UPDATE ON public.disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_review_draft_fields();

CREATE TRIGGER disposition_review_note_audit AFTER INSERT OR UPDATE ON public.disposition_review_notes FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_review_work();

CREATE TRIGGER disposition_review_note_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_review_notes FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_review_note();

CREATE TRIGGER disposition_single_reviewer BEFORE INSERT ON public.disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.assign_single_reviewer();

CREATE TRIGGER disposition_template_audit AFTER INSERT ON public.disposition_template_revisions FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_template_revision();

CREATE TRIGGER disposition_template_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_template_revisions FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_template_revision();

CREATE TRIGGER disposition_z_artifact_gate BEFORE INSERT OR UPDATE ON public.disposition_job_documents FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_artifact();

CREATE TRIGGER email_guard BEFORE INSERT OR DELETE OR UPDATE ON public.disposition_email_attempts FOR EACH ROW EXECUTE FUNCTION disposition_private.communication_guard();

CREATE TRIGGER event_history_disposition_execution BEFORE INSERT ON public.event_history FOR EACH ROW EXECUTE FUNCTION disposition_private.approval_event_metadata();

CREATE TRIGGER event_history_populate_actor_snapshot BEFORE INSERT ON public.event_history FOR EACH ROW EXECUTE FUNCTION public.populate_event_actor_snapshot();

CREATE TRIGGER event_history_populate_reference_snapshots BEFORE INSERT ON public.event_history FOR EACH ROW EXECUTE FUNCTION public.populate_event_reference_snapshots();

CREATE TRIGGER event_history_populate_relationship_snapshot BEFORE INSERT ON public.event_history FOR EACH ROW EXECUTE FUNCTION public.populate_event_relationship_snapshot();

CREATE TRIGGER event_history_reject_truncate BEFORE TRUNCATE ON public.event_history FOR EACH STATEMENT EXECUTE FUNCTION public.reject_event_history_mutation();

CREATE TRIGGER event_history_reject_update_delete BEFORE DELETE OR UPDATE ON public.event_history FOR EACH ROW EXECUTE FUNCTION public.reject_event_history_mutation();

CREATE TRIGGER event_history_remove_internal_fields BEFORE INSERT ON public.event_history FOR EACH ROW EXECUTE FUNCTION public.remove_internal_audit_fields();

CREATE TRIGGER event_history_z_hold_reference_snapshots BEFORE INSERT ON public.event_history FOR EACH ROW EXECUTE FUNCTION public.populate_hold_event_reference_snapshots();

CREATE TRIGGER hold_aggregation_assignments_bump_version BEFORE UPDATE ON public.hold_aggregation_assignments FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER hold_aggregation_assignments_domain_events AFTER INSERT OR DELETE ON public.hold_aggregation_assignments FOR EACH ROW EXECUTE FUNCTION public.append_hold_assignment_domain_events();

CREATE TRIGGER hold_aggregation_assignments_policy BEFORE INSERT OR DELETE OR UPDATE ON public.hold_aggregation_assignments FOR EACH ROW EXECUTE FUNCTION public.enforce_hold_assignment_policy();

CREATE TRIGGER hold_aggregation_assignments_record_history AFTER INSERT OR DELETE OR UPDATE ON public.hold_aggregation_assignments FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('hold_aggregation_assignment');

CREATE TRIGGER hold_contributors_bump_version BEFORE UPDATE ON public.hold_contributors FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER hold_contributors_record_history AFTER INSERT OR DELETE OR UPDATE ON public.hold_contributors FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('hold_contributor');

CREATE TRIGGER hold_contributors_require_change_reason BEFORE INSERT OR DELETE OR UPDATE ON public.hold_contributors FOR EACH ROW EXECUTE FUNCTION public.enforce_hold_change_reason();

CREATE TRIGGER hold_contributors_validate_user BEFORE INSERT OR UPDATE OF hold_id, user_id ON public.hold_contributors FOR EACH ROW EXECUTE FUNCTION public.validate_hold_person_reference();

CREATE TRIGGER hold_record_assignments_bump_version BEFORE UPDATE ON public.hold_record_assignments FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER hold_record_assignments_domain_events AFTER INSERT OR DELETE ON public.hold_record_assignments FOR EACH ROW EXECUTE FUNCTION public.append_hold_assignment_domain_events();

CREATE TRIGGER hold_record_assignments_policy BEFORE INSERT OR DELETE OR UPDATE ON public.hold_record_assignments FOR EACH ROW EXECUTE FUNCTION public.enforce_hold_assignment_policy();

CREATE TRIGGER hold_record_assignments_record_history AFTER INSERT OR DELETE OR UPDATE ON public.hold_record_assignments FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('hold_record_assignment');

CREATE TRIGGER holds_bump_version BEFORE UPDATE ON public.holds FOR EACH ROW EXECUTE FUNCTION public.touch_hold();

CREATE TRIGGER holds_domain_events AFTER INSERT OR DELETE OR UPDATE ON public.holds FOR EACH ROW EXECUTE FUNCTION public.append_hold_definition_domain_event();

CREATE TRIGGER holds_prevent_nonempty_deletion BEFORE DELETE ON public.holds FOR EACH ROW EXECUTE FUNCTION public.prevent_nonempty_hold_deletion();

CREATE TRIGGER holds_record_history AFTER INSERT OR DELETE OR UPDATE ON public.holds FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('hold');

CREATE TRIGGER holds_require_change_reason BEFORE DELETE OR UPDATE ON public.holds FOR EACH ROW EXECUTE FUNCTION public.enforce_hold_change_reason();

CREATE TRIGGER holds_validate_owner BEFORE INSERT OR UPDATE OF owner_user_id ON public.holds FOR EACH ROW EXECUTE FUNCTION public.validate_hold_person_reference();

CREATE TRIGGER message_action_amendments_immutable BEFORE DELETE OR UPDATE ON public.message_action_amendments FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_action_completions_immutable BEFORE DELETE OR UPDATE ON public.message_action_completions FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_addressee_insert BEFORE INSERT ON public.message_addressees FOR EACH ROW EXECUTE FUNCTION public.messaging_snapshot_insert();

CREATE TRIGGER message_addressees_immutable BEFORE DELETE OR UPDATE ON public.message_addressees FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE CONSTRAINT TRIGGER message_amendment_valid AFTER INSERT ON public.message_action_amendments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.messaging_validate_amendment();

CREATE TRIGGER message_capture_component_insert BEFORE INSERT ON public.message_record_capture_components FOR EACH ROW EXECUTE FUNCTION public.messaging_capture_component_insert();

CREATE TRIGGER message_capture_component_no_delete BEFORE DELETE ON public.message_record_capture_components FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_capture_component_update BEFORE UPDATE ON public.message_record_capture_components FOR EACH ROW EXECUTE FUNCTION public.messaging_capture_update();

CREATE TRIGGER message_capture_no_delete BEFORE DELETE ON public.message_record_captures FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_capture_update BEFORE UPDATE ON public.message_record_captures FOR EACH ROW EXECUTE FUNCTION public.messaging_capture_update();

CREATE CONSTRAINT TRIGGER message_capture_valid AFTER INSERT ON public.message_record_captures DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.messaging_validate_capture();

CREATE CONSTRAINT TRIGGER message_completion_valid AFTER INSERT ON public.message_action_completions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.messaging_validate_completion();

CREATE TRIGGER message_deliveries_no_delete BEFORE DELETE ON public.message_deliveries FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_deliveries_read_once BEFORE UPDATE ON public.message_deliveries FOR EACH ROW EXECUTE FUNCTION public.messaging_delivery_update();

CREATE TRIGGER message_delivery_insert BEFORE INSERT ON public.message_deliveries FOR EACH ROW EXECUTE FUNCTION public.messaging_snapshot_insert();

CREATE TRIGGER message_delivery_metric AFTER INSERT ON public.message_deliveries FOR EACH ROW EXECUTE FUNCTION public.messaging_count_delivery();

CREATE TRIGGER message_delivery_notify AFTER INSERT ON public.message_deliveries FOR EACH ROW EXECUTE FUNCTION public.messaging_notify_delivery();

CREATE TRIGGER message_delivery_sequence BEFORE INSERT ON public.message_deliveries FOR EACH ROW EXECUTE FUNCTION public.messaging_validate_delivery();

CREATE TRIGGER message_delivery_timestamp BEFORE INSERT ON public.message_deliveries FOR EACH ROW EXECUTE FUNCTION public.messaging_delivery_timestamp();

CREATE TRIGGER message_draft_default_level BEFORE INSERT ON public.message_drafts FOR EACH ROW EXECUTE FUNCTION public.messaging_default_level();

CREATE TRIGGER message_draft_resource_target BEFORE INSERT ON public.message_draft_resource_links FOR EACH ROW EXECUTE FUNCTION public.messaging_resource_link_insert();

CREATE TRIGGER message_draft_update BEFORE UPDATE ON public.message_drafts FOR EACH ROW EXECUTE FUNCTION public.messaging_draft_update();

CREATE CONSTRAINT TRIGGER message_envelope_complete AFTER INSERT ON public.message_envelopes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.messaging_validate_envelope();

CREATE TRIGGER message_envelope_default_level BEFORE INSERT ON public.message_envelopes FOR EACH ROW EXECUTE FUNCTION public.messaging_default_level();

CREATE TRIGGER message_envelope_localizations_immutable BEFORE DELETE OR UPDATE ON public.message_envelope_localizations FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_envelopes_immutable BEFORE UPDATE ON public.message_envelopes FOR EACH ROW EXECUTE FUNCTION public.messaging_mailbox_envelope_update();

CREATE TRIGGER message_envelopes_no_delete BEFORE DELETE ON public.message_envelopes FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_link_snapshot_insert BEFORE INSERT ON public.message_resource_links FOR EACH ROW EXECUTE FUNCTION public.messaging_snapshot_insert();

CREATE TRIGGER message_localization_insert BEFORE INSERT ON public.message_envelope_localizations FOR EACH ROW EXECUTE FUNCTION public.messaging_snapshot_insert();

CREATE TRIGGER message_mailbox_no_delete BEFORE DELETE ON public.message_mailboxes FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_mailbox_update BEFORE UPDATE ON public.message_mailboxes FOR EACH ROW EXECUTE FUNCTION public.messaging_mailbox_update();

CREATE CONSTRAINT TRIGGER message_receipt_valid AFTER INSERT ON public.message_request_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.messaging_validate_receipt();

CREATE TRIGGER message_recipient_selectors_immutable BEFORE DELETE OR UPDATE ON public.message_recipient_selectors FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_request_receipts_immutable BEFORE UPDATE ON public.message_request_receipts FOR EACH ROW EXECUTE FUNCTION public.messaging_receipt_purge_update();

CREATE TRIGGER message_request_receipts_no_delete BEFORE DELETE ON public.message_request_receipts FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_resource_links_insert BEFORE INSERT ON public.message_resource_links FOR EACH ROW EXECUTE FUNCTION public.messaging_resource_link_insert();

CREATE TRIGGER message_resource_links_no_delete BEFORE DELETE ON public.message_resource_links FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER message_resource_links_update BEFORE UPDATE ON public.message_resource_links FOR EACH ROW EXECUTE FUNCTION public.messaging_resource_link_update();

CREATE TRIGGER message_selector_insert BEFORE INSERT ON public.message_recipient_selectors FOR EACH ROW EXECUTE FUNCTION public.messaging_snapshot_insert();

CREATE TRIGGER notification_active_coverage BEFORE INSERT OR UPDATE ON public.system_notification_producers FOR EACH ROW EXECUTE FUNCTION public.messaging_guard_notification_coverage();

CREATE TRIGGER notification_language_coverage BEFORE INSERT OR UPDATE OF is_enabled ON public.supported_languages FOR EACH ROW EXECUTE FUNCTION public.messaging_guard_notification_coverage();

CREATE TRIGGER org_units_bump_version BEFORE UPDATE ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER org_units_prevent_cycle BEFORE INSERT OR UPDATE OF parent_org_unit_id ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.prevent_org_unit_cycle();

CREATE TRIGGER org_units_record_history AFTER INSERT OR DELETE OR UPDATE ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('org_unit');

CREATE TRIGGER org_units_set_default_dates BEFORE INSERT ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.set_user_management_default_dates();

CREATE TRIGGER org_units_validate_designated_roles BEFORE INSERT OR UPDATE ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.validate_org_unit_designated_roles();

CREATE TRIGGER org_units_validate_lifecycle_dates BEFORE INSERT OR UPDATE OF date_deactivated ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.validate_user_management_lifecycle_dates();

CREATE TRIGGER org_units_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

CREATE TRIGGER privileges_record_history AFTER INSERT OR DELETE OR UPDATE ON public.privileges FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('privilege');

CREATE TRIGGER privileges_touch BEFORE UPDATE ON public.privileges FOR EACH ROW EXECUTE FUNCTION public.touch_authorization_catalogue();

CREATE TRIGGER profile_privileges_protect_text_indexer BEFORE INSERT OR DELETE OR UPDATE ON public.profile_privileges FOR EACH ROW EXECUTE FUNCTION public.protect_text_indexer_profile_membership();

CREATE TRIGGER profile_privileges_record_history AFTER INSERT OR DELETE OR UPDATE ON public.profile_privileges FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('profile_privilege');

CREATE TRIGGER profiles_protect_text_indexer BEFORE DELETE OR UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.protect_text_indexer_profile();

CREATE TRIGGER profiles_record_history AFTER INSERT OR DELETE OR UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('profile');

CREATE TRIGGER profiles_touch BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.touch_authorization_catalogue();

CREATE TRIGGER profiles_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

CREATE TRIGGER record_acl_clearance BEFORE INSERT OR UPDATE ON public.record_acl_grants FOR EACH ROW EXECUTE FUNCTION public.validate_acl_role_clearance();

CREATE CONSTRAINT TRIGGER record_acl_dependencies AFTER INSERT OR DELETE OR UPDATE ON public.record_acl_grants DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_acl_dependencies('record_id');

CREATE TRIGGER record_acl_history AFTER INSERT OR DELETE OR UPDATE ON public.record_acl_grants FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('record_acl_grant');

CREATE TRIGGER record_acl_type BEFORE INSERT OR UPDATE ON public.record_acl_grants FOR EACH ROW EXECUTE FUNCTION public.validate_acl_permission_type();

CREATE TRIGGER record_draft_components_enforce_record_medium BEFORE INSERT OR UPDATE OF draft_id ON public.record_draft_components FOR EACH ROW EXECUTE FUNCTION public.enforce_draft_component_record_medium();

CREATE TRIGGER record_drafts_enforce_future_review_date BEFORE INSERT OR UPDATE OF date_of_next_review ON public.record_drafts FOR EACH ROW EXECUTE FUNCTION public.enforce_future_review_date();

CREATE TRIGGER record_drafts_enforce_medium_hierarchy BEFORE INSERT OR UPDATE OF aggregation_id, medium ON public.record_drafts FOR EACH ROW EXECUTE FUNCTION public.enforce_record_draft_medium_hierarchy();

CREATE TRIGGER record_drafts_touch BEFORE UPDATE ON public.record_drafts FOR EACH ROW EXECUTE FUNCTION public.touch_record_draft();

CREATE TRIGGER record_relationships_guard BEFORE INSERT OR DELETE OR UPDATE ON public.record_relationships FOR EACH ROW EXECUTE FUNCTION public.guard_resource_relationship('record');

CREATE TRIGGER record_relationships_history AFTER INSERT OR DELETE ON public.record_relationships FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('record_relationship');

CREATE TRIGGER records_bump_version BEFORE UPDATE ON public.records FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER records_default_security_level BEFORE INSERT ON public.records FOR EACH ROW EXECUTE FUNCTION public.default_entity_security_level();

CREATE CONSTRAINT TRIGGER records_disposition_consistency AFTER UPDATE ON public.records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN ((((((((old.disposition_status IS DISTINCT FROM new.disposition_status) OR (old.final_disposition_at IS DISTINCT FROM new.final_disposition_at)) OR (old.final_disposition_by_user_id IS DISTINCT FROM new.final_disposition_by_user_id)) OR (old.disposition_job_id IS DISTINCT FROM new.disposition_job_id)) OR (old.destruction_number IS DISTINCT FROM new.destruction_number)) OR (old.transfer_number IS DISTINCT FROM new.transfer_number)) OR (old.final_disposition_event_id IS DISTINCT FROM new.final_disposition_event_id))) EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE TRIGGER records_disposition_guard BEFORE INSERT OR DELETE OR UPDATE ON public.records FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_resource();

CREATE CONSTRAINT TRIGGER records_disposition_insert_consistency AFTER INSERT ON public.records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE TRIGGER records_enforce_future_review_date BEFORE INSERT OR UPDATE OF date_of_next_review ON public.records FOR EACH ROW EXECUTE FUNCTION public.enforce_future_review_date();

CREATE TRIGGER records_enforce_medium_hierarchy BEFORE INSERT OR UPDATE OF aggregation_id, medium ON public.records FOR EACH ROW EXECUTE FUNCTION public.enforce_record_medium_hierarchy();

CREATE TRIGGER records_enforce_ownership BEFORE INSERT OR UPDATE OF aggregation_id, owning_org_unit_id ON public.records FOR EACH ROW EXECUTE FUNCTION public.enforce_record_ownership();

CREATE TRIGGER records_enforce_security_hierarchy BEFORE INSERT OR UPDATE OF aggregation_id, security_level_id ON public.records FOR EACH ROW EXECUTE FUNCTION public.enforce_resource_security_hierarchy();

CREATE TRIGGER records_future_next_review BEFORE INSERT OR UPDATE OF date_of_next_review ON public.records FOR EACH ROW EXECUTE FUNCTION public.enforce_future_next_review_date();

CREATE TRIGGER records_govern_review_date BEFORE UPDATE OF date_of_next_review ON public.records FOR EACH ROW EXECUTE FUNCTION public.allow_governed_review_date_change();

CREATE TRIGGER records_govern_vital_status BEFORE UPDATE OF is_vital ON public.records FOR EACH ROW EXECUTE FUNCTION public.allow_governed_vital_status_change();

CREATE TRIGGER records_initialize_acls AFTER INSERT ON public.records FOR EACH ROW EXECUTE FUNCTION public.initialize_resource_acls();

CREATE TRIGGER records_protect_closed_aggregation BEFORE INSERT OR DELETE OR UPDATE ON public.records FOR EACH ROW EXECUTE FUNCTION public.protect_record_in_closed_aggregation();

CREATE TRIGGER records_protect_effective_holds BEFORE DELETE OR UPDATE ON public.records FOR EACH ROW EXECUTE FUNCTION public.protect_held_resource();

CREATE TRIGGER records_protect_vital_deletion BEFORE DELETE ON public.records FOR EACH ROW EXECUTE FUNCTION public.protect_vital_resource_deletion();

CREATE TRIGGER records_record_history AFTER INSERT OR DELETE OR UPDATE ON public.records FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('record');

CREATE TRIGGER records_refresh_metadata_search AFTER INSERT OR UPDATE OF record_number, title, description ON public.records FOR EACH ROW EXECUTE FUNCTION public.refresh_record_metadata_search_document();

CREATE TRIGGER records_set_default_dates BEFORE INSERT ON public.records FOR EACH ROW EXECUTE FUNCTION public.set_originated_default_dates();

CREATE TRIGGER relationship_types_guard BEFORE INSERT OR DELETE OR UPDATE ON public.relationship_types FOR EACH ROW EXECUTE FUNCTION public.guard_relationship_type();

CREATE TRIGGER relationship_types_history AFTER INSERT OR DELETE OR UPDATE ON public.relationship_types FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('relationship_type');

CREATE TRIGGER relationship_types_version BEFORE UPDATE ON public.relationship_types FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER roles_bump_version BEFORE UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER roles_default_profile BEFORE INSERT ON public.roles FOR EACH ROW EXECUTE FUNCTION public.default_role_profile();

CREATE TRIGGER roles_default_security_level BEFORE INSERT ON public.roles FOR EACH ROW EXECUTE FUNCTION public.default_entity_security_level();

CREATE TRIGGER roles_prevent_supervision_cycle BEFORE INSERT OR UPDATE OF supervisor_role_id ON public.roles FOR EACH ROW EXECUTE FUNCTION public.prevent_role_supervision_cycle();

CREATE TRIGGER roles_protect_designation BEFORE UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.protect_designated_role_unit();

CREATE TRIGGER roles_protect_text_indexer BEFORE DELETE OR UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.protect_text_indexer_role();

CREATE TRIGGER roles_record_history AFTER INSERT OR DELETE OR UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('role');

CREATE TRIGGER roles_set_default_dates BEFORE INSERT ON public.roles FOR EACH ROW EXECUTE FUNCTION public.set_user_management_default_dates();

CREATE TRIGGER roles_validate_lifecycle_dates BEFORE INSERT OR UPDATE OF date_deactivated ON public.roles FOR EACH ROW EXECUTE FUNCTION public.validate_user_management_lifecycle_dates();

CREATE TRIGGER roles_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.roles FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

CREATE TRIGGER saved_searches_record_history AFTER INSERT OR DELETE OR UPDATE ON public.saved_searches FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('saved_search');

CREATE TRIGGER saved_searches_require_change_reason BEFORE DELETE OR UPDATE ON public.saved_searches FOR EACH ROW EXECUTE FUNCTION public.enforce_saved_search_change_reason();

CREATE TRIGGER saved_searches_touch BEFORE UPDATE ON public.saved_searches FOR EACH ROW EXECUTE FUNCTION public.touch_saved_search();

CREATE TRIGGER saved_searches_validate_owner BEFORE INSERT OR UPDATE OF owner_user_id ON public.saved_searches FOR EACH ROW EXECUTE FUNCTION public.validate_saved_search_owner();

CREATE TRIGGER security_levels_bump_version BEFORE UPDATE ON public.security_levels FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER security_levels_record_history AFTER INSERT OR DELETE OR UPDATE ON public.security_levels FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('security_level');

CREATE TRIGGER security_levels_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.security_levels FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

CREATE TRIGGER security_levels_validate_update BEFORE UPDATE ON public.security_levels FOR EACH ROW EXECUTE FUNCTION public.enforce_security_level_catalogue_change();

CREATE TRIGGER service_account_credentials_validate BEFORE INSERT OR UPDATE ON public.service_account_credentials FOR EACH ROW EXECUTE FUNCTION public.validate_service_account_credential();

CREATE TRIGGER supported_languages_record_history AFTER INSERT OR DELETE OR UPDATE ON public.supported_languages FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('supported_language');

CREATE CONSTRAINT TRIGGER supported_languages_require_one_default AFTER INSERT OR DELETE OR UPDATE ON public.supported_languages DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.enforce_one_enabled_default_language();

CREATE TRIGGER supported_languages_require_reason BEFORE INSERT OR DELETE OR UPDATE ON public.supported_languages FOR EACH ROW EXECUTE FUNCTION public.require_localization_change_reason();

CREATE TRIGGER supported_languages_touch BEFORE UPDATE ON public.supported_languages FOR EACH ROW EXECUTE FUNCTION public.touch_localization_row();

CREATE TRIGGER system_notification_configuration_audiences_immutable BEFORE DELETE OR UPDATE ON public.system_notification_configuration_audiences FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER system_notification_configuration_translations_immutable BEFORE DELETE OR UPDATE ON public.system_notification_configuration_translations FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER system_notification_configuration_versions_immutable BEFORE DELETE OR UPDATE ON public.system_notification_configuration_versions FOR EACH ROW EXECUTE FUNCTION public.messaging_reject_mutation();

CREATE TRIGGER system_notification_producers_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.system_notification_producers FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

CREATE TRIGGER ui_message_definitions_history AFTER INSERT OR DELETE OR UPDATE ON public.ui_message_definitions FOR EACH ROW EXECUTE FUNCTION public.record_localization_catalogue_history('ui_message_definition');

CREATE TRIGGER ui_message_definitions_require_reason BEFORE INSERT OR DELETE OR UPDATE ON public.ui_message_definitions FOR EACH ROW EXECUTE FUNCTION public.require_localization_change_reason();

CREATE TRIGGER ui_message_definitions_touch BEFORE UPDATE ON public.ui_message_definitions FOR EACH ROW EXECUTE FUNCTION public.touch_localization_row();

CREATE TRIGGER ui_message_translations_history AFTER INSERT OR DELETE OR UPDATE ON public.ui_message_translations FOR EACH ROW EXECUTE FUNCTION public.record_localization_catalogue_history('ui_message_translation');

CREATE TRIGGER ui_message_translations_require_reason BEFORE INSERT OR DELETE OR UPDATE ON public.ui_message_translations FOR EACH ROW EXECUTE FUNCTION public.require_localization_change_reason();

CREATE TRIGGER ui_message_translations_touch BEFORE UPDATE ON public.ui_message_translations FOR EACH ROW EXECUTE FUNCTION public.touch_localization_row();

CREATE TRIGGER user_credentials_reject_service_account BEFORE INSERT OR UPDATE OF user_id ON public.user_credentials FOR EACH ROW EXECUTE FUNCTION public.reject_service_account_password();

CREATE TRIGGER user_preferences_record_history AFTER INSERT OR DELETE OR UPDATE ON public.user_preferences FOR EACH ROW EXECUTE FUNCTION public.record_user_preference_history();

CREATE TRIGGER user_preferences_touch BEFORE UPDATE ON public.user_preferences FOR EACH ROW EXECUTE FUNCTION public.touch_localization_row();

CREATE TRIGGER user_role_assignments_bump_version BEFORE UPDATE ON public.user_role_assignments FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER user_role_assignments_record_history AFTER INSERT OR DELETE OR UPDATE ON public.user_role_assignments FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('user_role_assignment');

CREATE TRIGGER user_role_assignments_set_default_dates BEFORE INSERT ON public.user_role_assignments FOR EACH ROW EXECUTE FUNCTION public.set_assignment_default_dates();

CREATE TRIGGER user_role_assignments_validate_active BEFORE INSERT OR UPDATE OF user_id, role_id ON public.user_role_assignments FOR EACH ROW EXECUTE FUNCTION public.validate_active_role_assignment();

CREATE TRIGGER users_bump_version BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TRIGGER users_record_history AFTER INSERT OR DELETE OR UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('user');

CREATE TRIGGER users_set_default_dates BEFORE INSERT ON public.users FOR EACH ROW EXECUTE FUNCTION public.set_user_management_default_dates();

CREATE TRIGGER users_validate_lifecycle_dates BEFORE INSERT OR UPDATE OF date_deactivated, date_suspended ON public.users FOR EACH ROW EXECUTE FUNCTION public.validate_user_management_lifecycle_dates();

CREATE TRIGGER users_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.users FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();

ALTER TABLE ONLY disposition_private.command_context
    ADD CONSTRAINT command_context_command_id_fkey FOREIGN KEY (command_id) REFERENCES disposition_private.command_receipts(command_id) ON DELETE RESTRICT;

ALTER TABLE ONLY disposition_private.command_receipts
    ADD CONSTRAINT command_receipts_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY disposition_private.command_receipts
    ADD CONSTRAINT command_receipts_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.disposition_job_documents(id);

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY disposition_private.completion_work
    ADD CONSTRAINT completion_work_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.disposition_tasks(id);

ALTER TABLE ONLY disposition_private.destruction_numbers
    ADD CONSTRAINT destruction_numbers_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY disposition_private.destruction_scopes
    ADD CONSTRAINT destruction_scopes_root_id_fkey FOREIGN KEY (root_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY disposition_private.destruction_scopes
    ADD CONSTRAINT destruction_scopes_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.disposition_destruction_runs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY disposition_private.email_payloads
    ADD CONSTRAINT email_payloads_attempt_id_fkey FOREIGN KEY (attempt_id) REFERENCES public.disposition_email_attempts(id);

ALTER TABLE ONLY disposition_private.processing_copies
    ADD CONSTRAINT processing_copies_component_id_fkey FOREIGN KEY (component_id) REFERENCES public.digital_components(id) ON DELETE RESTRICT;

ALTER TABLE ONLY disposition_private.processing_copies
    ADD CONSTRAINT processing_copies_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY disposition_private.reminder_checkpoints
    ADD CONSTRAINT reminder_checkpoints_recipient_user_id_fkey FOREIGN KEY (recipient_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.aggregation_acl_grants
    ADD CONSTRAINT aggregation_acl_grants_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.aggregation_acl_grants
    ADD CONSTRAINT aggregation_acl_grants_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregation_acl_grants
    ADD CONSTRAINT aggregation_acl_grants_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregation_child_aggregation_acl_defaults
    ADD CONSTRAINT aggregation_child_aggregation_acl_defaults_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.aggregation_child_aggregation_acl_defaults
    ADD CONSTRAINT aggregation_child_aggregation_acl_defaults_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregation_child_aggregation_acl_defaults
    ADD CONSTRAINT aggregation_child_aggregation_acl_defaults_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregation_child_record_acl_defaults
    ADD CONSTRAINT aggregation_child_record_acl_defaults_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.aggregation_child_record_acl_defaults
    ADD CONSTRAINT aggregation_child_record_acl_defaults_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregation_child_record_acl_defaults
    ADD CONSTRAINT aggregation_child_record_acl_defaults_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregation_relationships
    ADD CONSTRAINT aggregation_relationships_relationship_type_id_fkey FOREIGN KEY (relationship_type_id) REFERENCES public.relationship_types(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregation_relationships
    ADD CONSTRAINT aggregation_relationships_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.aggregation_relationships
    ADD CONSTRAINT aggregation_relationships_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.aggregation_retention_rules
    ADD CONSTRAINT aggregation_retention_rules_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.aggregation_search_documents
    ADD CONSTRAINT aggregation_search_documents_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_classification_id_fkey FOREIGN KEY (classification_id) REFERENCES public.classifications(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_disposition_job_id_fkey FOREIGN KEY (disposition_job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_final_disposition_by_user_id_fkey FOREIGN KEY (final_disposition_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_final_disposition_event_id_fkey FOREIGN KEY (final_disposition_event_id) REFERENCES public.event_history(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_owning_org_unit_fk FOREIGN KEY (owning_org_unit_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_parent_aggregation_id_fkey FOREIGN KEY (parent_aggregation_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.aggregations
    ADD CONSTRAINT aggregations_security_level_fk FOREIGN KEY (security_level_id) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.application_settings
    ADD CONSTRAINT application_settings_classification_reference_id_fkey FOREIGN KEY (classification_reference_id) REFERENCES public.classifications(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.application_settings_migration_keys
    ADD CONSTRAINT application_settings_migration_keys_key_fkey FOREIGN KEY (key) REFERENCES public.application_settings(key) ON DELETE RESTRICT;

ALTER TABLE ONLY public.application_settings
    ADD CONSTRAINT application_settings_scheme_reference_id_fkey FOREIGN KEY (scheme_reference_id) REFERENCES public.classification_schemes(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.classification_retention_rules
    ADD CONSTRAINT classification_retention_rules_classification_id_fkey FOREIGN KEY (classification_id) REFERENCES public.classifications(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.classifications
    ADD CONSTRAINT classifications_classification_scheme_id_fkey FOREIGN KEY (classification_scheme_id) REFERENCES public.classification_schemes(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.classifications
    ADD CONSTRAINT classifications_parent_classification_id_fkey FOREIGN KEY (parent_classification_id) REFERENCES public.classifications(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.content_indexing_attempts
    ADD CONSTRAINT content_indexing_attempts_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.digital_component_content_sets(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_attempts
    ADD CONSTRAINT content_indexing_attempts_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_attempts
    ADD CONSTRAINT content_indexing_attempts_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.content_indexing_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_attempts
    ADD CONSTRAINT content_indexing_attempts_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_attempts
    ADD CONSTRAINT content_indexing_attempts_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_batch_items
    ADD CONSTRAINT content_indexing_batch_items_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.content_indexing_batches(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_indexing_batch_items
    ADD CONSTRAINT content_indexing_batch_items_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_batch_items
    ADD CONSTRAINT content_indexing_batch_items_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.content_indexing_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_batches
    ADD CONSTRAINT content_indexing_batches_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_batches
    ADD CONSTRAINT content_indexing_batches_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.content_indexing_jobs
    ADD CONSTRAINT content_indexing_jobs_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.digital_component_content_sets(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_indexing_jobs
    ADD CONSTRAINT content_indexing_jobs_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_indexing_jobs
    ADD CONSTRAINT content_indexing_jobs_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_indexing_operations
    ADD CONSTRAINT content_indexing_operations_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.content_indexing_jobs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_indexing_result_chunks
    ADD CONSTRAINT content_indexing_result_chunks_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.content_indexing_jobs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_upload_sessions
    ADD CONSTRAINT content_upload_sessions_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.digital_component_content_sets(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_upload_sessions
    ADD CONSTRAINT content_upload_sessions_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.content_upload_sessions
    ADD CONSTRAINT content_upload_sessions_draft_component_id_fkey FOREIGN KEY (draft_component_id) REFERENCES public.record_draft_components(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.digital_component_blobs
    ADD CONSTRAINT digital_component_blobs_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.digital_component_content_sets(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.digital_component_content_sets
    ADD CONSTRAINT digital_component_content_sets_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.digital_component_search_chunks
    ADD CONSTRAINT digital_component_search_chunks_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_component_search_documents(digital_component_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.digital_component_search_documents
    ADD CONSTRAINT digital_component_search_documents_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.digital_component_content_sets(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.digital_component_search_documents
    ADD CONSTRAINT digital_component_search_documents_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.digital_component_search_documents
    ADD CONSTRAINT digital_component_search_documents_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.digital_components
    ADD CONSTRAINT digital_components_active_content_set_fk FOREIGN KEY (id, active_content_set_id) REFERENCES public.digital_component_content_sets(digital_component_id, id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.digital_components
    ADD CONSTRAINT digital_components_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.disposition_destruction_manifest_items
    ADD CONSTRAINT disposition_destruction_manifest_items_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_manifest_items
    ADD CONSTRAINT disposition_destruction_manifest_items_root_id_fkey FOREIGN KEY (root_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_manifest_items
    ADD CONSTRAINT disposition_destruction_manifest_items_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.disposition_destruction_runs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_run_units
    ADD CONSTRAINT disposition_destruction_run_units_root_id_fkey FOREIGN KEY (root_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_run_units
    ADD CONSTRAINT disposition_destruction_run_units_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.disposition_destruction_runs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_runs
    ADD CONSTRAINT disposition_destruction_runs_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_runs
    ADD CONSTRAINT disposition_destruction_runs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_runs
    ADD CONSTRAINT disposition_destruction_runs_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_destruction_runs
    ADD CONSTRAINT disposition_destruction_runs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.disposition_tasks(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_email_attempts
    ADD CONSTRAINT disposition_email_attempts_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_email_attempts
    ADD CONSTRAINT disposition_email_attempts_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_email_attempts
    ADD CONSTRAINT disposition_email_attempts_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.disposition_job_documents(id);

ALTER TABLE ONLY public.disposition_email_attempts
    ADD CONSTRAINT disposition_email_attempts_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approval_rejection_letter_document_id_fkey FOREIGN KEY (rejection_letter_document_id) REFERENCES public.disposition_job_documents(id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_approval_letter_document_id_fkey FOREIGN KEY (approval_letter_document_id) REFERENCES public.disposition_job_documents(id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_recorded_by_user_id_fkey FOREIGN KEY (recorded_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_request_document_id_fkey FOREIGN KEY (request_document_id) REFERENCES public.disposition_job_documents(id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_round_id_job_id_fkey FOREIGN KEY (round_id, job_id) REFERENCES public.disposition_review_rounds(id, job_id);

ALTER TABLE ONLY public.disposition_external_approvals
    ADD CONSTRAINT disposition_external_approvals_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.disposition_tasks(id);

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_classification_id_fkey FOREIGN KEY (classification_id) REFERENCES public.classifications(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_classification_scheme_id_fkey FOREIGN KEY (classification_scheme_id) REFERENCES public.classification_schemes(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_documents
    ADD CONSTRAINT disposition_job_documents_supersedes_document_id_fkey FOREIGN KEY (supersedes_document_id) REFERENCES public.disposition_job_documents(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_memberships
    ADD CONSTRAINT disposition_job_memberships_added_by_user_id_fkey FOREIGN KEY (added_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_memberships
    ADD CONSTRAINT disposition_job_memberships_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_memberships
    ADD CONSTRAINT disposition_job_memberships_removed_by_user_id_fkey FOREIGN KEY (removed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_job_memberships
    ADD CONSTRAINT disposition_job_memberships_root_aggregation_id_fkey FOREIGN KEY (root_aggregation_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_assigned_user_id_fkey FOREIGN KEY (assigned_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_completed_by_user_id_fkey FOREIGN KEY (completed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_final_event_id_fkey FOREIGN KEY (final_event_id) REFERENCES public.event_history(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_owning_org_unit_id_fkey FOREIGN KEY (owning_org_unit_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_terminated_by_user_id_fkey FOREIGN KEY (terminated_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_jobs
    ADD CONSTRAINT disposition_jobs_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_certificate_document_id_fkey FOREIGN KEY (certificate_document_id) REFERENCES public.disposition_job_documents(id);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_confirmed_by_user_id_fkey FOREIGN KEY (confirmed_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY public.disposition_physical_confirmations
    ADD CONSTRAINT disposition_physical_confirmations_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.disposition_tasks(id);

ALTER TABLE ONLY public.disposition_proposal_effects
    ADD CONSTRAINT disposition_proposal_effects_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_proposal_effects
    ADD CONSTRAINT disposition_proposal_effects_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_proposal_effects
    ADD CONSTRAINT disposition_proposal_effects_membership_id_fkey FOREIGN KEY (membership_id) REFERENCES public.disposition_job_memberships(id);

ALTER TABLE ONLY public.disposition_proposal_effects
    ADD CONSTRAINT disposition_proposal_effects_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.disposition_review_proposals(id);

ALTER TABLE ONLY public.disposition_proposal_holds
    ADD CONSTRAINT disposition_proposal_holds_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.disposition_review_proposals(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_classification_id_fkey FOREIGN KEY (classification_id) REFERENCES public.classifications(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_digital_confirmation_event_id_fkey FOREIGN KEY (digital_confirmation_event_id) REFERENCES public.event_history(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_executor_user_id_fkey FOREIGN KEY (executor_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_final_event_id_fkey FOREIGN KEY (final_event_id) REFERENCES public.event_history(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_owning_org_unit_id_fkey FOREIGN KEY (owning_org_unit_id) REFERENCES public.org_units(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_physical_confirmation_id_fkey FOREIGN KEY (physical_confirmation_id) REFERENCES public.disposition_physical_confirmations(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_root_id_fkey FOREIGN KEY (root_id) REFERENCES public.aggregations(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.disposition_destruction_runs(id);

ALTER TABLE ONLY public.disposition_retained_records
    ADD CONSTRAINT disposition_retained_records_security_level_id_fkey FOREIGN KEY (security_level_id) REFERENCES public.security_levels(id);

ALTER TABLE ONLY public.disposition_review_decisions
    ADD CONSTRAINT disposition_review_decisions_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_review_decisions
    ADD CONSTRAINT disposition_review_decisions_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_review_decisions
    ADD CONSTRAINT disposition_review_decisions_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_review_decisions
    ADD CONSTRAINT disposition_review_decisions_round_id_job_id_fkey FOREIGN KEY (round_id, job_id) REFERENCES public.disposition_review_rounds(id, job_id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_review_decisions
    ADD CONSTRAINT disposition_review_decisions_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.disposition_tasks(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_review_notes
    ADD CONSTRAINT disposition_review_notes_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_review_notes
    ADD CONSTRAINT disposition_review_notes_author_user_id_fkey FOREIGN KEY (author_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_review_notes
    ADD CONSTRAINT disposition_review_notes_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY public.disposition_review_notes
    ADD CONSTRAINT disposition_review_notes_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.disposition_tasks(id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_carried_from_proposal_id_fkey FOREIGN KEY (carried_from_proposal_id) REFERENCES public.disposition_review_proposals(id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_executed_by_user_id_fkey FOREIGN KEY (executed_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_last_revised_by_user_id_fkey FOREIGN KEY (last_revised_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_last_revised_role_id_fkey FOREIGN KEY (last_revised_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_proposer_role_id_fkey FOREIGN KEY (proposer_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_proposer_user_id_fkey FOREIGN KEY (proposer_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_review_proposals
    ADD CONSTRAINT disposition_review_proposals_withdrawn_by_user_id_fkey FOREIGN KEY (withdrawn_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_review_rounds
    ADD CONSTRAINT disposition_review_rounds_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_review_rounds
    ADD CONSTRAINT disposition_review_rounds_started_by_user_id_fkey FOREIGN KEY (started_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_claimed_by_user_id_fkey FOREIGN KEY (claimed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_completed_by_user_id_fkey FOREIGN KEY (completed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_destination_role_id_fkey FOREIGN KEY (destination_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_destination_user_id_fkey FOREIGN KEY (destination_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_reassigned_by_user_id_fkey FOREIGN KEY (reassigned_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_released_by_user_id_fkey FOREIGN KEY (released_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_request_document_id_fkey FOREIGN KEY (request_document_id) REFERENCES public.disposition_job_documents(id);

ALTER TABLE ONLY public.disposition_tasks
    ADD CONSTRAINT disposition_tasks_routing_org_unit_id_fkey FOREIGN KEY (routing_org_unit_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.disposition_template_revisions
    ADD CONSTRAINT disposition_template_revisions_acting_role_id_fkey FOREIGN KEY (acting_role_id) REFERENCES public.roles(id);

ALTER TABLE ONLY public.disposition_template_revisions
    ADD CONSTRAINT disposition_template_revisions_uploaded_by_user_id_fkey FOREIGN KEY (uploaded_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.disposition_template_revisions
    ADD CONSTRAINT disposition_template_revisions_uploaded_from_job_id_fkey FOREIGN KEY (uploaded_from_job_id) REFERENCES public.disposition_jobs(id);

ALTER TABLE ONLY public.hold_aggregation_assignments
    ADD CONSTRAINT hold_aggregation_assignments_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.hold_aggregation_assignments
    ADD CONSTRAINT hold_aggregation_assignments_assigned_by_user_id_fkey FOREIGN KEY (assigned_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.hold_aggregation_assignments
    ADD CONSTRAINT hold_aggregation_assignments_hold_id_fkey FOREIGN KEY (hold_id) REFERENCES public.holds(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.hold_contributors
    ADD CONSTRAINT hold_contributors_hold_id_fkey FOREIGN KEY (hold_id) REFERENCES public.holds(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.hold_contributors
    ADD CONSTRAINT hold_contributors_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.hold_notification_reminders
    ADD CONSTRAINT hold_notification_reminders_hold_id_fkey FOREIGN KEY (hold_id) REFERENCES public.holds(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.hold_record_assignments
    ADD CONSTRAINT hold_record_assignments_assigned_by_user_id_fkey FOREIGN KEY (assigned_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.hold_record_assignments
    ADD CONSTRAINT hold_record_assignments_hold_id_fkey FOREIGN KEY (hold_id) REFERENCES public.holds(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.hold_record_assignments
    ADD CONSTRAINT hold_record_assignments_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.holds
    ADD CONSTRAINT holds_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.message_action_amendments
    ADD CONSTRAINT message_action_amendments_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_action_amendments
    ADD CONSTRAINT message_action_amendments_original_envelope_id_fkey FOREIGN KEY (original_envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_action_completions
    ADD CONSTRAINT message_action_completions_completed_by_user_id_fkey FOREIGN KEY (completed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_action_completions
    ADD CONSTRAINT message_action_completions_original_delivery_id_fkey FOREIGN KEY (original_delivery_id) REFERENCES public.message_deliveries(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_action_completions
    ADD CONSTRAINT message_action_completions_reply_envelope_id_fkey FOREIGN KEY (reply_envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_addressees
    ADD CONSTRAINT message_addressees_envelope_id_fkey FOREIGN KEY (envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_addressees
    ADD CONSTRAINT message_addressees_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_capture_drafts
    ADD CONSTRAINT message_capture_drafts_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES public.record_drafts(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.message_deliveries
    ADD CONSTRAINT message_deliveries_envelope_id_fkey FOREIGN KEY (envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_deliveries
    ADD CONSTRAINT message_deliveries_envelope_id_recipient_user_id_recipient_fkey FOREIGN KEY (envelope_id, recipient_user_id, recipient_type) REFERENCES public.message_addressees(envelope_id, user_id, recipient_type);

ALTER TABLE ONLY public.message_deliveries
    ADD CONSTRAINT message_deliveries_recipient_user_id_fkey FOREIGN KEY (recipient_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_draft_recipient_selectors
    ADD CONSTRAINT message_draft_recipient_selectors_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES public.message_drafts(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_draft_recipient_selectors
    ADD CONSTRAINT message_draft_recipient_selectors_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_draft_recipient_selectors
    ADD CONSTRAINT message_draft_recipient_selectors_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_draft_recipient_selectors
    ADD CONSTRAINT message_draft_recipient_selectors_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_draft_resource_links
    ADD CONSTRAINT message_draft_resource_links_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_draft_resource_links
    ADD CONSTRAINT message_draft_resource_links_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES public.message_drafts(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_draft_resource_links
    ADD CONSTRAINT message_draft_resource_links_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_draft_resource_links
    ADD CONSTRAINT message_draft_resource_links_security_level_id_at_send_fkey FOREIGN KEY (security_level_id_at_send) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_drafts
    ADD CONSTRAINT message_drafts_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_drafts
    ADD CONSTRAINT message_drafts_security_level_id_fkey FOREIGN KEY (security_level_id) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_envelope_localizations
    ADD CONSTRAINT message_envelope_localizations_envelope_id_fkey FOREIGN KEY (envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_envelope_localizations
    ADD CONSTRAINT message_envelope_localizations_language_tag_fkey FOREIGN KEY (language_tag) REFERENCES public.supported_languages(language_tag) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_action_amendment_id_fkey FOREIGN KEY (action_amendment_id) REFERENCES public.message_action_amendments(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_related_delivery_id_fkey FOREIGN KEY (related_delivery_id) REFERENCES public.message_deliveries(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_related_envelope_id_fkey FOREIGN KEY (related_envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_security_level_id_fkey FOREIGN KEY (security_level_id) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_sender_user_id_fkey FOREIGN KEY (sender_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_system_configuration_version_id_fkey FOREIGN KEY (system_configuration_version_id) REFERENCES public.system_notification_configuration_versions(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_system_producer_code_fkey FOREIGN KEY (system_producer_code) REFERENCES public.system_notification_producers(producer_code) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_system_producer_code_system_configuratio_fkey FOREIGN KEY (system_producer_code, system_configuration_version_id) REFERENCES public.system_notification_configuration_versions(producer_code, id);

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_test_initiated_by_user_id_fkey FOREIGN KEY (test_initiated_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_envelopes
    ADD CONSTRAINT message_envelopes_triggered_by_user_id_fkey FOREIGN KEY (triggered_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_mailboxes
    ADD CONSTRAINT message_mailboxes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_recipient_selectors
    ADD CONSTRAINT message_recipient_selectors_envelope_id_fkey FOREIGN KEY (envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_recipient_selectors
    ADD CONSTRAINT message_recipient_selectors_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_recipient_selectors
    ADD CONSTRAINT message_recipient_selectors_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_recipient_selectors
    ADD CONSTRAINT message_recipient_selectors_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_record_capture_components
    ADD CONSTRAINT message_record_capture_components_capture_id_fkey FOREIGN KEY (capture_id) REFERENCES public.message_record_captures(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_record_capture_components
    ADD CONSTRAINT message_record_capture_components_digital_component_id_fkey FOREIGN KEY (digital_component_id) REFERENCES public.digital_components(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_record_capture_components
    ADD CONSTRAINT message_record_capture_components_envelope_id_fkey FOREIGN KEY (envelope_id) REFERENCES public.message_envelopes(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_record_captures
    ADD CONSTRAINT message_record_captures_captured_by_user_id_fkey FOREIGN KEY (captured_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_record_captures
    ADD CONSTRAINT message_record_captures_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_record_captures
    ADD CONSTRAINT message_record_captures_selected_envelope_id_fkey FOREIGN KEY (selected_envelope_id) REFERENCES public.message_envelopes(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_request_receipts
    ADD CONSTRAINT message_request_receipts_principal_user_id_fkey FOREIGN KEY (principal_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.message_request_receipts
    ADD CONSTRAINT message_request_receipts_producer_code_fkey FOREIGN KEY (producer_code) REFERENCES public.system_notification_producers(producer_code) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_resource_links
    ADD CONSTRAINT message_resource_links_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_resource_links
    ADD CONSTRAINT message_resource_links_envelope_id_fkey FOREIGN KEY (envelope_id) REFERENCES public.message_envelopes(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_resource_links
    ADD CONSTRAINT message_resource_links_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.message_resource_links
    ADD CONSTRAINT message_resource_links_security_level_id_at_send_fkey FOREIGN KEY (security_level_id_at_send) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_file_administrator_role_id_fkey FOREIGN KEY (file_administrator_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_managing_role_id_fkey FOREIGN KEY (managing_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_parent_org_unit_id_fkey FOREIGN KEY (parent_org_unit_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.organizational_ownership_root_assignments
    ADD CONSTRAINT organizational_ownership_root_assignments_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.organizational_ownership_assignment_runs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.permission_dependencies
    ADD CONSTRAINT permission_dependencies_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.permission_dependencies
    ADD CONSTRAINT permission_dependencies_required_permission_id_fkey FOREIGN KEY (required_permission_id) REFERENCES public.permissions(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.privilege_dependencies
    ADD CONSTRAINT privilege_dependencies_privilege_id_fkey FOREIGN KEY (privilege_id) REFERENCES public.privileges(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.privilege_dependencies
    ADD CONSTRAINT privilege_dependencies_required_privilege_id_fkey FOREIGN KEY (required_privilege_id) REFERENCES public.privileges(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.profile_privileges
    ADD CONSTRAINT profile_privileges_privilege_id_fkey FOREIGN KEY (privilege_id) REFERENCES public.privileges(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.profile_privileges
    ADD CONSTRAINT profile_privileges_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.record_acl_grants
    ADD CONSTRAINT record_acl_grants_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.record_acl_grants
    ADD CONSTRAINT record_acl_grants_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.record_acl_grants
    ADD CONSTRAINT record_acl_grants_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.record_draft_component_blobs
    ADD CONSTRAINT record_draft_component_blobs_record_draft_component_id_fkey FOREIGN KEY (record_draft_component_id) REFERENCES public.record_draft_components(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.record_draft_components
    ADD CONSTRAINT record_draft_components_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES public.record_drafts(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.record_drafts
    ADD CONSTRAINT record_drafts_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.record_drafts
    ADD CONSTRAINT record_drafts_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.record_drafts
    ADD CONSTRAINT record_drafts_security_level_id_fkey FOREIGN KEY (security_level_id) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.record_relationships
    ADD CONSTRAINT record_relationships_relationship_type_id_fkey FOREIGN KEY (relationship_type_id) REFERENCES public.relationship_types(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.record_relationships
    ADD CONSTRAINT record_relationships_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.record_relationships
    ADD CONSTRAINT record_relationships_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.record_search_documents
    ADD CONSTRAINT record_search_documents_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_disposition_job_id_fkey FOREIGN KEY (disposition_job_id) REFERENCES public.disposition_jobs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_final_disposition_by_user_id_fkey FOREIGN KEY (final_disposition_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_final_disposition_event_id_fkey FOREIGN KEY (final_disposition_event_id) REFERENCES public.event_history(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_owning_org_unit_fk FOREIGN KEY (owning_org_unit_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.records
    ADD CONSTRAINT records_security_level_fk FOREIGN KEY (security_level_id) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_profile_fk FOREIGN KEY (profile_id) REFERENCES public.profiles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_security_level_fk FOREIGN KEY (security_level_id) REFERENCES public.security_levels(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_supervisor_role_id_fkey FOREIGN KEY (supervisor_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.saved_search_org_unit_grants
    ADD CONSTRAINT saved_search_org_unit_grants_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.saved_search_org_unit_grants
    ADD CONSTRAINT saved_search_org_unit_grants_saved_search_id_fkey FOREIGN KEY (saved_search_id) REFERENCES public.saved_searches(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.saved_search_role_grants
    ADD CONSTRAINT saved_search_role_grants_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.saved_search_role_grants
    ADD CONSTRAINT saved_search_role_grants_saved_search_id_fkey FOREIGN KEY (saved_search_id) REFERENCES public.saved_searches(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.saved_searches
    ADD CONSTRAINT saved_searches_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.service_account_credentials
    ADD CONSTRAINT service_account_credentials_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.service_account_credentials
    ADD CONSTRAINT service_account_credentials_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.service_account_credentials
    ADD CONSTRAINT service_account_credentials_service_user_id_fkey FOREIGN KEY (service_user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.system_notification_configuration_audiences
    ADD CONSTRAINT system_notification_configuratio_configuration_version_id_fkey1 FOREIGN KEY (configuration_version_id) REFERENCES public.system_notification_configuration_versions(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.system_notification_configuration_audiences
    ADD CONSTRAINT system_notification_configuration_audiences_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.system_notification_configuration_audiences
    ADD CONSTRAINT system_notification_configuration_audiences_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.system_notification_configuration_audiences
    ADD CONSTRAINT system_notification_configuration_audiences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.system_notification_configuration_translations
    ADD CONSTRAINT system_notification_configuration_configuration_version_id_fkey FOREIGN KEY (configuration_version_id) REFERENCES public.system_notification_configuration_versions(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.system_notification_configuration_translations
    ADD CONSTRAINT system_notification_configuration_tran_reviewed_by_user_id_fkey FOREIGN KEY (reviewed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.system_notification_configuration_translations
    ADD CONSTRAINT system_notification_configuration_translation_language_tag_fkey FOREIGN KEY (language_tag) REFERENCES public.supported_languages(language_tag) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.system_notification_configuration_versions
    ADD CONSTRAINT system_notification_configuration_versi_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.system_notification_configuration_versions
    ADD CONSTRAINT system_notification_configuration_versions_producer_code_fkey FOREIGN KEY (producer_code) REFERENCES public.system_notification_producers(producer_code) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.system_notification_producers
    ADD CONSTRAINT system_notification_producers_active_configuration_version_fkey FOREIGN KEY (active_configuration_version_id) REFERENCES public.system_notification_configuration_versions(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.system_notification_producers
    ADD CONSTRAINT system_notification_producers_producer_code_active_configu_fkey FOREIGN KEY (producer_code, active_configuration_version_id) REFERENCES public.system_notification_configuration_versions(producer_code, id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.text_indexing_workers
    ADD CONSTRAINT text_indexing_workers_current_job_id_fkey FOREIGN KEY (current_job_id) REFERENCES public.content_indexing_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.text_indexing_workers
    ADD CONSTRAINT text_indexing_workers_service_user_id_fkey FOREIGN KEY (service_user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.ui_message_translations
    ADD CONSTRAINT ui_message_translations_language_tag_fkey FOREIGN KEY (language_tag) REFERENCES public.supported_languages(language_tag) ON DELETE RESTRICT;

ALTER TABLE ONLY public.ui_message_translations
    ADD CONSTRAINT ui_message_translations_message_key_fkey FOREIGN KEY (message_key) REFERENCES public.ui_message_definitions(message_key) ON DELETE RESTRICT;

ALTER TABLE ONLY public.ui_message_translations
    ADD CONSTRAINT ui_message_translations_published_by_user_id_fkey FOREIGN KEY (published_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.ui_message_translations
    ADD CONSTRAINT ui_message_translations_reviewed_by_user_id_fkey FOREIGN KEY (reviewed_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.ui_message_translations
    ADD CONSTRAINT ui_message_translations_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.user_classification_selections
    ADD CONSTRAINT user_classification_selections_classification_id_fkey FOREIGN KEY (classification_id) REFERENCES public.classifications(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_classification_selections
    ADD CONSTRAINT user_classification_selections_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_credentials
    ADD CONSTRAINT user_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_favourite_aggregations
    ADD CONSTRAINT user_favourite_aggregations_aggregation_id_fkey FOREIGN KEY (aggregation_id) REFERENCES public.aggregations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_favourite_aggregations
    ADD CONSTRAINT user_favourite_aggregations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_favourite_records
    ADD CONSTRAINT user_favourite_records_record_id_fkey FOREIGN KEY (record_id) REFERENCES public.records(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_favourite_records
    ADD CONSTRAINT user_favourite_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_language_tag_fkey FOREIGN KEY (language_tag) REFERENCES public.supported_languages(language_tag) ON DELETE RESTRICT;

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_role_assignments
    ADD CONSTRAINT user_role_assignments_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_role_assignments
    ADD CONSTRAINT user_role_assignments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

REVOKE ALL ON FUNCTION disposition_private.accelerate(p_root bigint, p_version bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.activate_certificate(p_job bigint, p_request uuid, p_token uuid) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.activate_request(p_job bigint, p_round bigint, p_document bigint, p_version integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.add_items(p_job bigint, p_version integer, p_items jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.allowed_stage(old_stage text, new_stage text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.allowed_transition(old_status integer, new_status integer, cause text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.apply_recalculation(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.approval_active(p_job bigint, p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.approval_event_metadata() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.approval_preview(p_task bigint, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.approve_proposals(p_task bigint, p_job_version integer, p_task_version integer, p_membership_token text, p_proposals_token text, p_overall_reason text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.artifact_destination(p_type text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.artifact_outside_job() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.assert_admission(p_job bigint, p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.assert_unit(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.assign_job(p_job bigint, p_version integer, p_assignee bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.assign_single_reviewer() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.audit_review_work() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.audit_template_revision() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.audit_workflow() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.begin_command(p_id uuid, p_operation text, p_payload jsonb, p_role bigint, p_reason text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.can_correct_evidence(p_job bigint, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.can_email(p_user bigint, p_job bigint, p_document bigint, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.can_manage() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.can_review_content(p_user bigint, p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.can_revise_template(p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.canonical_review_json(p_value jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.capture_policy_change() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.capture_recalculation(p_root bigint, p_cause text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.capture_retiring_identities(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.change_job_owner(p_job bigint, p_version integer, p_owner bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.check_completion(p_job bigint, p_task bigint, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.check_digital_job(p_job bigint, p_role bigint, p_initial boolean) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.check_physical_work(p_task bigint, p_job_version integer, p_task_version integer, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.check_proposal_holds() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.check_unit_trigger() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.claim_email(p_token uuid) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.claim_task(p_task bigint, p_version integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.command_complete_check() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.command_immutable() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.communication_guard() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.complete_certificate_task(p_job bigint, p_task bigint, p_version bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.completion_active(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.confirm_physical(p_task bigint, p_job_version integer, p_task_version integer, p_success boolean, p_reference text, p_document bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.content_reserved(p_record bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.context_operation() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.coordinate_policy_change() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.coordinate_relationship_change() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.create_email_attempt(p_command uuid, p_job bigint, p_document bigint, p_role bigint, p_config jsonb, p_database text, p_secret bytea, p_message text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.create_job(p_number text, p_type text, p_owner bigint, p_assignee bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.decide_review_work(p_task bigint, p_job_version integer, p_task_version integer, p_decision text, p_reason text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.destruction_active(p_mode text, p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.destruction_guard() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.destruction_scope(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.eligibility(p_root bigint, p_at timestamp with time zone) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.email_event(p_id bigint, p_operation text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.erase_unit_content(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.evaluate_root(p_root bigint, p_command uuid) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.external_active(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.finish_command(p_result jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.finish_destruction_job(p_job bigint, p_document bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.finish_digital_unit(p_run bigint, p_root bigint, p_token uuid) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.finish_email(p_id bigint, p_token uuid, p_status text, p_error text, p_code integer, p_server_id text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.finish_policy_change() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.governance_person(p_user bigint, p_profile text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_artifact() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_destruction_number() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_external_approval() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_external_task() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_physical_confirmation() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_physical_task() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_proposal() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_proposal_effect() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_proposal_hold() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_recovery_resource() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_resource() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_review_draft_fields() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_review_note() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_template_revision() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.guard_workflow() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.has_digital_material(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.history_resource_access(p_user bigint, p_kind text, p_id bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.hold_visible(p_hold bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.hook_applying(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.lock_current_blockers(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.lock_request_facts(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.membership_snapshot(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.minimize_unit_history(p_job bigint, p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.original_aggregation_access(p_user_id bigint, p_aggregation_id bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.original_record_access(p_user_id bigint, p_record_id bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.original_request_approval_current(p_job bigint, p_round bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.person_role(p_user bigint, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.physical_active(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.physical_confirmation_retry(p_id uuid, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.physical_covered(p_job bigint, p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.physical_item_remaining(p_kind text, p_id bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.physical_scope(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.positive_id(p_value jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.preparation_task() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.preserve_artifact_content() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.preserve_physical_outcome() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.proposal_duplicate_key(p jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.proposal_facts(p_job bigint, p_root bigint, p_target bigint, p_record bigint, p_type text, p_values jsonb, p_reason text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.proposal_relationship_key(p_relationship jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.proposal_snapshot(p_job bigint, p_round integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.proposal_visible(p_data jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.protection_blockers(p_root bigint, p_at timestamp with time zone) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.reassign_task(p_task bigint, p_version integer, p_user bigint, p_queue bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.reconcile_task(p_task bigint, p_command uuid) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.record_external_decision(p_task bigint, p_job_version integer, p_task_version integer, p_request bigint, p_decision text, p_notes text, p_number text, p_letter bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.recovery_active(p_job bigint, p_root bigint, p_status integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.recovery_facts(p_job bigint, p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.recovery_preview(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.recovery_roots(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.recovery_unit_visible(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.register_processing_copy(p_token uuid, p_component bigint, p_owner bigint, p_kind text, p_worker text, p_job bigint, p_generation bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.reject_duplicate_proposal() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.relationship_scope(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.release_task(p_task bigint, p_version integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.remove_member(p_member bigint, p_version integer, p_root_version bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.renew_external_review(p_job bigint, p_round bigint, p_version integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.request_approval_current(p_job bigint, p_round bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.request_digital(p_task bigint, p_job_version bigint, p_task_version bigint, p_confirm boolean) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.request_facts(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_actor(p_role_id bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_command() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_job_access(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_job_person(p_user bigint, p_type text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_membership_stage(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_preparer(p_user bigint, p_route text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_progress(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_task_actor(p_task bigint, p_role bigint, p_work boolean) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.require_task_command(p_task bigint, p_role bigint, p_operation text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.resolve_partial(p_job bigint, p_root bigint, p_root_version bigint, p_status integer, p_confirm boolean, p_count integer, p_token text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.retain_physical_outcome(p_job bigint, p_root bigint, p_event bigint, p_at timestamp with time zone, p_executor bigint, p_name text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.retain_unit(p_job bigint, p_root bigint, p_run bigint, p_event bigint, p_at timestamp with time zone, p_executor bigint, p_name text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.retained_access(p_kind text, p_id bigint, p_audit boolean) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.retained_command_payload(p_data jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.retained_guard() FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.retained_history_json(p_data jsonb, p_root bigint, p_ids jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.retained_json(p_data jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.review_actor(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.review_context(p_task bigint, p_job_version integer, p_task_version integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.review_fingerprint(p_value jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.review_keys(p_value jsonb, p_keys text[]) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.review_role(p_job bigint, p_stage text, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.review_round_for_work(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.root_id(p_id bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.route_after_external(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.route_correction(p_job bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.route_review(p_job bigint, p_stage text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.rule_identity(p_evaluation jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.save_review_work(p_task bigint, p_job_version integer, p_task_version integer, p_changes jsonb, p_notes text, p_note_version integer, p_overall_reason text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.start_manager_round(p_job bigint, p_version integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.start_review(p_job bigint, p_version integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.submit_review_work(p_task bigint, p_job_version integer, p_task_version integer, p_reason text) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.task_eligible(p_user bigint, p_task bigint, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.task_manager(p_task bigint, p_role bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.terminate_job(p_job bigint, p_version integer, p_confirm boolean) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.transition_unit(p_root bigint, p_version bigint, p_status integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.unit_has_digital(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.unit_ids(p_root bigint) FROM PUBLIC;

REVOKE ALL ON FUNCTION disposition_private.validate_active_proposals(p_job bigint, p_round integer) FROM PUBLIC;

COMMIT;
