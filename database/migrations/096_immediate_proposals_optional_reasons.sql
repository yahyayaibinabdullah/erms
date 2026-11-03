-- Immediate proposal persistence; optional proposal and routine review comments.
BEGIN;
SET LOCAL check_function_bodies=false;
CREATE OR REPLACE FUNCTION disposition_private.proposal_facts(p_job bigint, p_root bigint, p_target bigint, p_record bigint, p_type text, p_values jsonb, p_reason text) RETURNS jsonb
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
  IF p_target<>p_root OR NOT disposition_private.review_keys(p_values,ARRAY[]::text[]) THEN RAISE EXCEPTION 'disposition_proposal_payload_invalid'; END IF;
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

CREATE OR REPLACE FUNCTION disposition_private.submit_review_work(p_task bigint, p_job_version integer, p_task_version integer, p_reason text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $_$
DECLARE t disposition_tasks%ROWTYPE; p disposition_review_proposals%ROWTYPE; next_id bigint; next_round integer; result jsonb;
BEGIN
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_submit' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_context(p_task,p_job_version,p_task_version);
 IF t.workflow_stage NOT IN ('officer_preparation','officer_correction') THEN RAISE EXCEPTION 'disposition_combined_approval_required'; END IF;
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

CREATE OR REPLACE FUNCTION disposition_private.start_review(p_job bigint, p_version integer) RETURNS jsonb
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
 INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot,submission_reason)
 VALUES(p_job,j.current_review_round+1,current_user_id(),disposition_private.membership_snapshot(p_job),
 COALESCE((SELECT r.payload->>'overall_reason' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()),''));
 result:=disposition_private.route_review(p_job,CASE WHEN j.review_route='standard' THEN 'file_administrator_review' ELSE 'records_manager_review' END);
 RETURN result||jsonb_build_object('review_round',j.current_review_round+1);
END $$;

CREATE OR REPLACE FUNCTION disposition_private.approve_proposals(p_task bigint, p_job_version integer, p_task_version integer, p_membership_token text, p_proposals_token text, p_overall_reason text) RETURNS jsonb
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
  IF NOT FOUND OR rr.completed_at IS NOT NULL OR rr.invalidated_at IS NOT NULL OR
   (rr.membership_snapshot IS DISTINCT FROM before_members AND NOT (j.review_route='simplified' AND NOT EXISTS(
    SELECT value FROM jsonb_array_elements(rr.membership_snapshot)
    EXCEPT SELECT value FROM jsonb_array_elements(before_members)))) THEN RAISE EXCEPTION 'disposition_review_snapshot_stale'; END IF;
  total_reason:=rr.submission_reason;
 END IF;
 total_reason:=COALESCE(total_reason,'');
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
  current_reason:=CASE WHEN p.reason IS NOT NULL AND p.reason !~ '^[[:space:]]*$' THEN btrim(p.reason) WHEN total_reason !~ '^[[:space:]]*$' THEN btrim(total_reason) ELSE 'Apply approved disposition proposals' END;source:=CASE WHEN p.reason IS NOT NULL AND p.reason !~ '^[[:space:]]*$' THEN 'proposal' WHEN total_reason !~ '^[[:space:]]*$' THEN 'submission' ELSE 'approval' END;
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
 UPDATE disposition_private.approval_context SET current_proposal_id=NULL,reason_used=CASE WHEN total_reason ~ '^[[:space:]]*$' THEN 'Apply approved disposition proposals' ELSE total_reason END,reason_source=CASE WHEN total_reason ~ '^[[:space:]]*$' THEN 'approval' ELSE 'submission' END,phase='removing' WHERE transaction_id=txid_current();
 PERFORM set_config('app.change_reason',CASE WHEN total_reason ~ '^[[:space:]]*$' THEN 'Apply approved disposition proposals' ELSE total_reason END,true);
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
  SELECT jsonb_build_object('approving_user_id',current_user_id(),'acting_role_id',acting,'decision_id',decision_id,'reason_used',CASE WHEN p.reason IS NOT NULL AND p.reason !~ '^[[:space:]]*$' THEN btrim(p.reason) WHEN total_reason !~ '^[[:space:]]*$' THEN btrim(total_reason) ELSE 'Apply approved disposition proposals' END,'reason_source',CASE WHEN p.reason IS NOT NULL AND p.reason !~ '^[[:space:]]*$' THEN 'proposal' WHEN total_reason !~ '^[[:space:]]*$' THEN 'submission' ELSE 'approval' END,
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
ALTER TABLE public.disposition_review_decisions DROP CONSTRAINT disposition_review_decisions_reason_check;
ALTER TABLE public.disposition_review_decisions ADD CONSTRAINT disposition_review_decisions_reason_check CHECK (decision<>'rejected' OR reason !~ '^[[:space:]]*$');
ALTER TABLE public.disposition_review_proposals DROP CONSTRAINT disposition_review_proposals_check;
ALTER TABLE public.disposition_review_proposals ADD CONSTRAINT disposition_review_proposals_check CHECK (proposal_type<>'remove_from_job' OR (target_record_id IS NULL AND target_aggregation_id=governing_root_id));
INSERT INTO schema_migrations(version) VALUES ('096_immediate_proposals_optional_reasons') ON CONFLICT DO NOTHING;
COMMIT;
