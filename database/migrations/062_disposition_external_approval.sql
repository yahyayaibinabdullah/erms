BEGIN;
SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),
 set_config('app.event_source','migration',true),set_config('app.actor_name','Database migration 062',true);

CREATE TABLE disposition_external_approvals (
 id bigserial PRIMARY KEY,job_id bigint NOT NULL REFERENCES disposition_jobs(id),
 round_id bigint NOT NULL,request_document_id bigint NOT NULL UNIQUE REFERENCES disposition_job_documents(id),
 task_id bigint NOT NULL UNIQUE REFERENCES disposition_tasks(id),
 decision text NOT NULL CHECK(decision IN ('approved','rejected')),
 correction_notes text,destruction_number text,
 approval_letter_document_id bigint UNIQUE REFERENCES disposition_job_documents(id),
 rejection_letter_document_id bigint UNIQUE REFERENCES disposition_job_documents(id),
 recorded_by_user_id bigint NOT NULL REFERENCES users(id),acting_role_id bigint NOT NULL REFERENCES roles(id),
 recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 version integer NOT NULL DEFAULT 1 CHECK(version=1),
 FOREIGN KEY(round_id,job_id) REFERENCES disposition_review_rounds(id,job_id),
 CHECK((decision='approved' AND destruction_number IS NOT NULL AND btrim(destruction_number)<>'' AND char_length(destruction_number)<=20 AND approval_letter_document_id IS NOT NULL AND rejection_letter_document_id IS NULL)
 OR (decision='rejected' AND correction_notes IS NOT NULL AND correction_notes !~ '^[[:space:]]*$' AND destruction_number IS NULL AND approval_letter_document_id IS NULL AND rejection_letter_document_id IS NOT NULL))
);
CREATE INDEX disposition_external_approvals_job ON disposition_external_approvals(job_id,id);
-- Permanent reservation: another job can never reuse an authority's number.
-- A renewed decision on the same job may retain its previously supplied number.
CREATE TABLE disposition_private.destruction_numbers (
 number text PRIMARY KEY CHECK(btrim(number)<>'' AND char_length(number)<=20),
 job_id bigint NOT NULL REFERENCES disposition_jobs(id)
);
INSERT INTO disposition_private.destruction_numbers SELECT destruction_number,id FROM disposition_jobs WHERE destruction_number IS NOT NULL;
CREATE TABLE disposition_private.external_context (
 transaction_id bigint PRIMARY KEY,backend_id integer NOT NULL,command_id uuid NOT NULL,
 job_id bigint NOT NULL,phase text NOT NULL CHECK(phase IN ('request','decision','invalidate'))
);
REVOKE ALL ON disposition_private.external_context,disposition_private.destruction_numbers FROM PUBLIC;
CREATE UNIQUE INDEX disposition_request_approval_round ON disposition_job_documents(job_id,review_round)
 WHERE document_type='destruction_request' AND provenance ? 'approval_round_id';

CREATE FUNCTION disposition_private.external_active(p_job bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.external_context x JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE x.transaction_id=txid_current() AND x.backend_id=pg_backend_pid() AND x.job_id=p_job)
$$;
CREATE FUNCTION disposition_private.request_facts(p_job bigint) RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH members AS (SELECT id,root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active'),
 units AS (SELECT m.root_aggregation_id root_id,disposition_private.unit_ids(m.root_aggregation_id) id FROM members m)
 SELECT disposition_private.canonical_review_json(jsonb_build_object(
 'job',(SELECT jsonb_build_object('id',j.id,'job_number',j.job_number,'job_type',j.job_type,'owning_org_unit_id',j.owning_org_unit_id,'owner',o.name,'assigned_user_id',j.assigned_user_id,'assignee',u.name,'date_created',j.date_created,'review_route',j.review_route) FROM disposition_jobs j JOIN org_units o ON o.id=j.owning_org_unit_id LEFT JOIN users u ON u.id=j.assigned_user_id WHERE j.id=p_job),
 'source',jsonb_build_object(
 'roots',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',m.root_aggregation_id,'membership_id',m.id,'rule_snapshot',e.rule_snapshot) ORDER BY m.root_aggregation_id),'[]') FROM members m CROSS JOIN LATERAL disposition_private.eligibility(m.root_aggregation_id) e),
 'aggregations',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',a.id,'parent_aggregation_id',a.parent_aggregation_id,'aggregation_number',a.aggregation_number,'title',a.title,'medium',a.medium,'date_closed',a.date_closed,'root_id',units.root_id,'classification_id',cl.id,'classification_code',cl.code,'classification_title',cl.title,'owner',o.name,'disposition_status',a.disposition_status) ORDER BY a.id),'[]') FROM units JOIN aggregations a ON a.id=units.id JOIN aggregations root ON root.id=units.root_id JOIN classifications cl ON cl.id=root.classification_id JOIN org_units o ON o.id=a.owning_org_unit_id),
 'records',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',r.id,'aggregation_id',r.aggregation_id,'record_number',r.record_number,'title',r.title,'medium',r.medium,'disposition_status',r.disposition_status) ORDER BY r.id),'[]') FROM units JOIN records r ON r.aggregation_id=units.id))))
$$;
CREATE FUNCTION disposition_private.request_approval_current(p_job bigint,p_round bigint) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
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
CREATE FUNCTION disposition_private.lock_request_facts(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 PERFORM 1 FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 LOCK TABLE classifications,classification_retention_rules,aggregation_retention_rules,org_units,users IN SHARE MODE;
 PERFORM 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' ORDER BY id FOR UPDATE;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(root_aggregation_id) FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(root_aggregation_id) FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') ORDER BY id FOR UPDATE;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.approve_proposals(p_task bigint,p_job_version integer,p_task_version integer,p_membership_token text,p_proposals_token text,p_overall_reason text) RETURNS jsonb LANGUAGE plpgsql AS $$
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
END $$;
CREATE OR REPLACE FUNCTION disposition_private.guard_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; prior jsonb; following jsonb; op text; uid bigint:=current_user_id(); expected_status integer;
BEGIN
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
   IF NEW.job_type='destruction' THEN PERFORM disposition_private.require_preparer(uid,NEW.review_route); ELSE PERFORM disposition_private.require_job_person(uid,NEW.job_type); END IF;
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
 IF NOT disposition_private.hook_applying() AND NOT disposition_private.approval_active(job.id) AND NOT (op='task_release' AND current_setting('app.actor_type',true)='automated_process') THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF NOT disposition_private.approval_active(job.id) AND TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') AND NOT (op='review_decide' AND COALESCE((SELECT r.payload->>'decision' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())='rejected',false)) THEN PERFORM disposition_private.require_progress(job.id); END IF;
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) AND NOT (TG_TABLE_NAME='disposition_job_documents' AND op='document_save' AND following->>'document_type'='proposal_execution_report' AND EXISTS(SELECT 1 FROM disposition_review_rounds approved WHERE approved.job_id=job.id AND approved.round_number=(following->>'review_round')::integer AND approved.approval_execution IS NOT NULL)) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
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
   (op IN ('task_complete','review_submit','review_decide') AND OLD.task_state IN ('open','claimed') AND NEW.task_state='completed') OR
   (op IN ('job_assign','job_terminate','review_submit','review_decide') AND NEW.task_state='cancelled')) THEN RAISE EXCEPTION 'disposition_invalid_task_transition'; END IF;
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

ALTER TABLE disposition_tasks ADD COLUMN request_document_id bigint REFERENCES disposition_job_documents(id);
ALTER TABLE disposition_tasks ADD CONSTRAINT disposition_external_task_request CHECK((task_type='external_approval')=(request_document_id IS NOT NULL));
CREATE FUNCTION disposition_private.guard_external_task() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.request_document_id IS DISTINCT FROM OLD.request_document_id THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
 IF TG_OP='UPDATE' AND NEW.task_type='external_approval' AND NEW.task_state='completed' AND OLD.task_state<>NEW.task_state AND (NOT disposition_private.external_active(NEW.job_id) OR NOT EXISTS(SELECT 1 FROM disposition_external_approvals WHERE task_id=NEW.id)) THEN RAISE EXCEPTION 'disposition_external_command_required'; END IF;
 IF TG_OP='INSERT' AND NEW.task_type='external_approval' THEN
  IF NOT disposition_private.external_active(NEW.job_id) OR NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=NEW.request_document_id AND d.job_id=NEW.job_id AND d.document_type='destruction_request' AND d.review_round=NEW.review_round AND d.document_state='available') THEN RAISE EXCEPTION 'disposition_request_required'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_external_task BEFORE INSERT OR UPDATE ON disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_external_task();

CREATE FUNCTION disposition_private.activate_request(p_job bigint,p_round bigint,p_document bigint,p_version integer) RETURNS jsonb LANGUAGE plpgsql AS $$
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

CREATE FUNCTION disposition_private.guard_external_approval() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER disposition_external_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_external_approvals FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_external_approval();
CREATE FUNCTION disposition_private.guard_destruction_number() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM disposition_private.require_command();
 IF TG_OP<>'INSERT' OR NOT disposition_private.external_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_number_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_number_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_private.destruction_numbers FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_destruction_number();

CREATE FUNCTION disposition_private.record_external_decision(p_task bigint,p_job_version integer,p_task_version integer,p_request bigint,p_decision text,p_notes text,p_number text,p_letter bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
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
 ELSE UPDATE disposition_jobs SET destruction_number=p_number WHERE id=j.id; END IF;
 PERFORM append_domain_event('disposition_job',j.id,CASE p_decision WHEN 'approved' THEN 'EXTERNAL_APPROVAL_RECORDED' ELSE 'EXTERNAL_REJECTION_RECORDED' END,jsonb_build_object('after',(SELECT to_jsonb(a) FROM disposition_external_approvals a WHERE a.id=result_id),'acting_role_id',acting));
 DELETE FROM disposition_private.external_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('id',result_id,'job_id',j.id,'decision',p_decision,'request_document_id',p_request,'letter_document_id',p_letter,'job_version',(SELECT version FROM disposition_jobs WHERE id=j.id),'workflow_stage',(SELECT workflow_stage FROM disposition_jobs WHERE id=j.id));
END $$;

CREATE FUNCTION disposition_private.renew_external_review(p_job bigint,p_round bigint,p_version integer) RETURNS jsonb LANGUAGE plpgsql AS $$
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

CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
DECLARE proposal_data jsonb;
BEGIN
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
      WHERE m.job_id=disposition_job AND (NOT current_user_can_view_aggregation(unit.id)
        OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=unit.id AND NOT current_user_can_view_record(r.id))));
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
    RETURN record_id IS NOT NULL AND current_user_can_view_record(record_id);
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
END $$;


REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('062_disposition_external_approval');
COMMIT;
