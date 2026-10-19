BEGIN;
SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),
 set_config('app.actor_name','Database migration 059',true),set_config('app.event_source','migration',true),
 set_config('app.change_reason','Install destruction review proposals, notes and decisions',true);

ALTER TABLE disposition_private.command_receipts DROP CONSTRAINT command_receipts_operation_check,
 ADD CONSTRAINT command_receipts_operation_check CHECK (operation IN ('job_create','job_assign','membership_add','membership_remove','eligibility_evaluate','eligibility_accelerate','job_terminate','resolve_partial','task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide','document_save','selective_decide','final_complete','recalculate','job_owner_change'));
ALTER TABLE disposition_tasks ADD COLUMN draft_overall_reason text NOT NULL DEFAULT '';
ALTER TABLE disposition_review_rounds ADD COLUMN submission_reason text,
 ADD COLUMN proposal_snapshot jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(proposal_snapshot)='array');
ALTER TABLE disposition_review_decisions ADD COLUMN proposal_snapshot jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(proposal_snapshot)='array');

-- Resource/hold identifiers below are historical identifiers, deliberately not
-- new deletion blockers. Save validates existence/scope/access; execution will
-- independently recheck. Merely proposing protection never protects a resource.
CREATE TABLE disposition_review_proposals (
 id bigserial PRIMARY KEY, job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 review_round integer NOT NULL CHECK(review_round>0),
 governing_root_id bigint NOT NULL, target_aggregation_id bigint NOT NULL, target_record_id bigint,
 proposal_type text NOT NULL CHECK(proposal_type IN ('remove_from_job','make_vital','blocking_security','add_to_holds','create_aggregation_relationship','remove_aggregation_relationship','remove_record_relationship','local_retention_override')),
 proposal_state text NOT NULL DEFAULT 'active' CHECK(proposal_state IN ('active','withdrawn','executed','failed')),
 proposed_values jsonb NOT NULL CHECK(jsonb_typeof(proposed_values)='object'),
 current_values jsonb NOT NULL CHECK(jsonb_typeof(current_values)='object'),
 reason text,
 proposer_user_id bigint NOT NULL REFERENCES users(id), proposer_role_id bigint NOT NULL REFERENCES roles(id),
 proposer_stage text NOT NULL, proposed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 original_review_round integer NOT NULL CHECK(original_review_round>0),
 carried_from_proposal_id bigint REFERENCES disposition_review_proposals(id),
 last_revised_by_user_id bigint REFERENCES users(id), last_revised_role_id bigint REFERENCES roles(id),
 last_revised_stage text, last_revised_round integer, last_revised_at timestamptz,
 withdrawn_by_user_id bigint REFERENCES users(id), withdrawn_at timestamptz, withdrawal_reason text,
 executed_by_user_id bigint REFERENCES users(id), executed_at timestamptz, execution_message jsonb,
 version integer NOT NULL DEFAULT 1 CHECK(version>0), date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK(proposal_type<>'remove_from_job' OR (target_record_id IS NULL AND target_aggregation_id=governing_root_id AND reason IS NOT NULL AND reason !~ '^[[:space:]]*$')),
 CHECK((target_record_id IS NOT NULL)=(proposal_type='remove_record_relationship')),
 CHECK((proposal_state='withdrawn')=(withdrawn_by_user_id IS NOT NULL AND withdrawn_at IS NOT NULL)),
 CHECK(proposal_state NOT IN ('executed','failed') OR executed_at IS NOT NULL)
);
CREATE TABLE disposition_proposal_holds (
 proposal_id bigint NOT NULL REFERENCES disposition_review_proposals(id) ON DELETE RESTRICT,
 hold_id bigint NOT NULL CHECK(hold_id>0), hold_snapshot jsonb NOT NULL,
 PRIMARY KEY(proposal_id,hold_id)
);
CREATE TABLE disposition_review_notes (
 id bigserial PRIMARY KEY, job_id bigint NOT NULL REFERENCES disposition_jobs(id),
 task_id bigint NOT NULL REFERENCES disposition_tasks(id), review_round integer NOT NULL CHECK(review_round>0),
 workflow_stage text NOT NULL, author_user_id bigint NOT NULL REFERENCES users(id),
 acting_role_id bigint NOT NULL REFERENCES roles(id), review_notes text NOT NULL,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP, version integer NOT NULL DEFAULT 1 CHECK(version>0),
 UNIQUE(task_id,author_user_id)
);
CREATE INDEX disposition_proposals_job_round ON disposition_review_proposals(job_id,review_round,id);
CREATE INDEX disposition_notes_job_round ON disposition_review_notes(job_id,review_round,id);

CREATE FUNCTION disposition_private.hold_visible(p_hold bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM holds h WHERE h.id=p_hold AND (
 user_has_global_privilege(current_user_id(),'holds.administer') OR user_has_global_privilege(current_user_id(),'holds.held_items.manage_all')
 OR h.owner_user_id=current_user_id() OR EXISTS(SELECT 1 FROM hold_contributors hc JOIN users u ON u.id=hc.user_id
 WHERE hc.hold_id=h.id AND hc.user_id=current_user_id() AND u.status='active')
 OR EXISTS(SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id WHERE a.user_id=current_user_id()
 AND r.is_information_governance AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))))
$$;
CREATE FUNCTION disposition_private.review_round_for_work(p_job bigint) RETURNS integer LANGUAGE sql STABLE AS $$
 SELECT greatest(1,current_review_round) FROM disposition_jobs WHERE id=p_job
$$;
CREATE FUNCTION disposition_private.review_context(p_task bigint,p_job_version integer,p_task_version integer) RETURNS disposition_tasks LANGUAGE plpgsql AS $$
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
CREATE FUNCTION disposition_private.review_keys(p_value jsonb,p_keys text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT jsonb_typeof(p_value)='object' AND COALESCE((SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_value) k),ARRAY[]::text[])=p_keys
$$;
CREATE FUNCTION disposition_private.positive_id(p_value jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF jsonb_typeof(p_value) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
 RETURN COALESCE(jsonb_typeof(p_value)='number' AND p_value::text ~ '^[1-9][0-9]*$' AND p_value::numeric<=9223372036854775807,false);
END $$;

CREATE FUNCTION disposition_private.proposal_facts(p_job bigint,p_root bigint,p_target bigint,p_record bigint,p_type text,p_values jsonb,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
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
END $$;

CREATE FUNCTION disposition_private.proposal_visible(p_data jsonb) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE rel jsonb; selected_id bigint;
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
 RETURN true;
END $$;
CREATE FUNCTION disposition_private.proposal_snapshot(p_job bigint,p_round integer DEFAULT NULL) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.id),'[]'::jsonb) FROM disposition_review_proposals p
 WHERE p.job_id=p_job AND p.review_round=COALESCE(p_round,disposition_private.review_round_for_work(p_job)) AND p.proposal_state='active'
 AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=p_job AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active')
$$;
CREATE FUNCTION disposition_private.review_actor(p_job bigint) RETURNS disposition_tasks LANGUAGE plpgsql AS $$
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
CREATE FUNCTION disposition_private.guard_proposal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE; acting bigint; old_proposal disposition_review_proposals%ROWTYPE; facts jsonb; op text;
BEGIN
 PERFORM disposition_private.require_command();op:=disposition_private.context_operation();
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
 IF op NOT IN ('review_save','review_submit') THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
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
  IF op='review_submit' THEN
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
CREATE TRIGGER disposition_proposal_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_review_proposals FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_proposal();
CREATE FUNCTION disposition_private.guard_proposal_hold() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p disposition_review_proposals%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT * INTO p FROM disposition_review_proposals WHERE id=CASE WHEN TG_OP='DELETE' THEN OLD.proposal_id ELSE NEW.proposal_id END;
 PERFORM disposition_private.review_actor(p.job_id);
 IF disposition_private.context_operation() NOT IN ('review_save','review_submit') OR p.proposal_type<>'add_to_holds' OR p.proposal_state<>'active' OR TG_OP='UPDATE' OR NOT (p.review_round=disposition_private.review_round_for_work(p.job_id) OR (disposition_private.context_operation()='review_submit' AND p.review_round=(SELECT current_review_round+1 FROM disposition_jobs WHERE id=p.job_id))) THEN RAISE EXCEPTION 'disposition_proposal_hold_scope_invalid'; END IF;
 IF TG_OP='INSERT' THEN
  IF NOT disposition_private.hold_visible(NEW.hold_id) OR NOT (p.proposed_values->'hold_ids' @> to_jsonb(NEW.hold_id)) THEN RAISE EXCEPTION 'disposition_proposal_hold_scope_invalid'; END IF;
  NEW.hold_snapshot:=(SELECT to_jsonb(h) FROM holds h WHERE id=NEW.hold_id);
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER disposition_proposal_hold_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_proposal_holds FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_proposal_hold();
CREATE FUNCTION disposition_private.check_proposal_holds() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE CONSTRAINT TRIGGER disposition_proposal_holds_consistency AFTER INSERT OR UPDATE ON disposition_review_proposals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_proposal_holds();
CREATE CONSTRAINT TRIGGER disposition_proposal_holds_consistency AFTER INSERT OR UPDATE OR DELETE ON disposition_proposal_holds DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_proposal_holds();
CREATE FUNCTION disposition_private.guard_review_note() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER disposition_review_note_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_review_notes FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_review_note();
CREATE FUNCTION disposition_private.audit_review_work() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE operation text;
BEGIN
 operation:=CASE WHEN TG_TABLE_NAME='disposition_review_notes' THEN 'REVIEW_NOTES_SAVED'
 WHEN TG_OP='INSERT' AND to_jsonb(NEW)->>'carried_from_proposal_id' IS NOT NULL THEN 'REVIEW_PROPOSAL_CARRIED'
 WHEN TG_OP='INSERT' THEN 'REVIEW_PROPOSAL_CREATED'
 WHEN to_jsonb(NEW)->>'proposal_state'='withdrawn' THEN 'REVIEW_PROPOSAL_WITHDRAWN' ELSE 'REVIEW_PROPOSAL_REVISED' END;
 PERFORM append_domain_event(CASE WHEN TG_TABLE_NAME='disposition_review_notes' THEN 'disposition_review_note' ELSE 'disposition_review_proposal' END,NEW.id,operation,
 jsonb_build_object('before',CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) END,'after',to_jsonb(NEW),
 'acting_role_id',(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())));
 RETURN NULL;
END $$;
CREATE TRIGGER disposition_proposal_audit AFTER INSERT OR UPDATE ON disposition_review_proposals FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_review_work();
CREATE TRIGGER disposition_review_note_audit AFTER INSERT OR UPDATE ON disposition_review_notes FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_review_work();

CREATE OR REPLACE FUNCTION disposition_private.begin_command(p_id uuid,p_operation text,p_payload jsonb,p_role bigint,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE previous disposition_private.command_receipts%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 IF p_operation IN ('task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide') AND p_payload ? 'task_id' THEN
  PERFORM disposition_private.require_task_command((p_payload->>'task_id')::bigint,p_role,p_operation);
 ELSE PERFORM disposition_private.require_actor(p_role); END IF;
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
  IF command.operation NOT IN ('eligibility_evaluate','task_release') OR command.actor_user_id IS NOT NULL OR command.acting_role_id IS NOT NULL THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 ELSE
  IF command.operation IN ('task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide') AND command.payload ? 'task_id' THEN
   PERFORM disposition_private.require_task_command((command.payload->>'task_id')::bigint,command.acting_role_id,command.operation);
  ELSE PERFORM disposition_private.require_actor(command.acting_role_id); END IF;
 END IF;
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
  IF TG_OP='UPDATE' AND NOT disposition_private.hook_applying() THEN PERFORM disposition_private.require_job_access(NEW.id); END IF;
  IF TG_OP='UPDATE' AND ((NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND NEW.workflow_stage NOT IN ('officer_correction','manager_correction')) OR NEW.disposition_status<>OLD.disposition_status) AND op<>'job_terminate' THEN PERFORM disposition_private.require_progress(NEW.id); END IF;
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
 IF NOT disposition_private.hook_applying() AND NOT (op='task_release' AND current_setting('app.actor_type',true)='automated_process') THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') AND NOT (op='review_decide' AND COALESCE((SELECT r.payload->>'decision' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())='rejected',false)) THEN PERFORM disposition_private.require_progress(job.id); END IF;
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
   NEW.claimed_at:=CURRENT_TIMESTAMP;
  END IF;
 ELSIF TG_TABLE_NAME='disposition_review_rounds' THEN
  IF TG_OP='INSERT' THEN
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
  IF NEW.decision='approved' AND NEW.review_stage IN ('records_manager_review','manager_preparation','manager_correction') THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
  IF NEW.decision='approved' AND NEW.review_stage='unit_manager_review' AND EXISTS(SELECT 1 FROM disposition_review_proposals p JOIN disposition_job_memberships m ON m.job_id=p.job_id AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active' WHERE p.job_id=job.id AND p.review_round=job.current_review_round AND p.proposal_state='active' AND p.proposal_type='remove_from_job') THEN RAISE EXCEPTION 'disposition_marked_removals_require_rejection'; END IF;
  IF TG_OP<>'INSERT' OR NEW.actor_user_id<>uid OR NEW.acting_role_id<>(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()) OR NOT EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.id=NEW.task_id AND t.job_id=NEW.job_id AND t.workflow_stage=NEW.review_stage AND (t.claimed_by_user_id=uid OR (t.destination_user_id=uid AND t.task_state='open')) AND (t.destination_role_id IS NULL OR EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=t.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)))) THEN RAISE EXCEPTION 'disposition_decision_context_invalid'; END IF;
  IF NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id) THEN RAISE EXCEPTION 'disposition_review_snapshot_stale'; END IF;
  IF NEW.decision='approved' AND NEW.membership_snapshot IS DISTINCT FROM (SELECT membership_snapshot FROM disposition_review_rounds WHERE id=NEW.round_id) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
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

CREATE FUNCTION disposition_private.guard_review_draft_fields() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER disposition_review_draft_fields BEFORE UPDATE ON disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_review_draft_fields();
CREATE TRIGGER disposition_review_draft_fields BEFORE UPDATE ON disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_review_draft_fields();

CREATE FUNCTION disposition_private.save_review_work(p_task bigint,p_job_version integer,p_task_version integer,p_changes jsonb,p_notes text,p_note_version integer,p_overall_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
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

CREATE FUNCTION disposition_private.validate_active_proposals(p_job bigint,p_round integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p disposition_review_proposals%ROWTYPE;
BEGIN
 FOR p IN SELECT p1.* FROM disposition_review_proposals p1 JOIN disposition_job_memberships m ON m.job_id=p1.job_id AND m.root_aggregation_id=p1.governing_root_id AND m.membership_state='active'
 WHERE p1.job_id=p_job AND p1.review_round=p_round AND p1.proposal_state='active' ORDER BY p1.id LOOP
  PERFORM disposition_private.proposal_facts(p.job_id,p.governing_root_id,p.target_aggregation_id,p.target_record_id,p.proposal_type,p.proposed_values,p.reason);
 END LOOP;
END $$;
CREATE FUNCTION disposition_private.submit_review_work(p_task bigint,p_job_version integer,p_task_version integer,p_reason text) RETURNS jsonb LANGUAGE plpgsql AS $$
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
END $$;
CREATE FUNCTION disposition_private.decide_review_work(p_task bigint,p_job_version integer,p_task_version integer,p_decision text,p_reason text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE; j disposition_jobs%ROWTYPE; round_id bigint; acting bigint; identity bigint; reason text;
BEGIN
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_context(p_task,p_job_version,p_task_version);
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id;
 IF t.workflow_stage NOT IN ('file_administrator_review','unit_manager_review','records_manager_review') OR p_decision NOT IN ('approved','rejected') OR (t.workflow_stage='file_administrator_review' AND p_decision<>'approved') THEN RAISE EXCEPTION 'disposition_review_decision_invalid'; END IF;
 IF t.workflow_stage='records_manager_review' AND p_decision='approved' THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
 IF p_decision='rejected' AND (p_reason IS NULL OR p_reason ~ '^[[:space:]]*$') AND NOT EXISTS(SELECT 1 FROM disposition_review_proposals p JOIN disposition_job_memberships m ON m.job_id=p.job_id AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active' WHERE p.job_id=j.id AND p.review_round=j.current_review_round AND p.proposal_state='active' AND p.proposal_type='remove_from_job') THEN RAISE EXCEPTION 'disposition_decision_reason_required'; END IF;
 IF p_decision='approved' THEN PERFORM disposition_private.validate_active_proposals(j.id,j.current_review_round); END IF;
 reason:=COALESCE(NULLIF(btrim(p_reason),''),CASE WHEN p_decision='rejected' THEN 'Return marked aggregations for correction' ELSE 'Complete authorized review' END);
 SELECT id INTO round_id FROM disposition_review_rounds WHERE job_id=j.id AND round_number=j.current_review_round;
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 INSERT INTO disposition_review_decisions(job_id,round_id,review_stage,decision,task_id,actor_user_id,acting_role_id,reason,membership_snapshot)
 VALUES(j.id,round_id,t.workflow_stage,p_decision,t.id,current_user_id(),acting,reason,disposition_private.membership_snapshot(j.id)) RETURNING id INTO identity;
 UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
 IF p_decision='rejected' THEN PERFORM disposition_private.route_correction(j.id);
 ELSE PERFORM disposition_private.route_review(j.id,CASE WHEN t.workflow_stage='file_administrator_review' THEN 'unit_manager_review' ELSE 'records_manager_review' END); END IF;
 RETURN jsonb_build_object('decision_id',identity,'job_id',j.id,'workflow_stage',(SELECT workflow_stage FROM disposition_jobs WHERE id=j.id),'job_version',(SELECT version FROM disposition_jobs WHERE id=j.id));
END $$;

CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
DECLARE proposal_data jsonb;
BEGIN
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

-- Domain workflow events preserve row snapshots in metadata. Feed those
-- immutable snapshots to the existing shared redaction gate as well.
CREATE OR REPLACE VIEW authorized_event_history AS
SELECT event.id,event.occurred_at,event.transaction_id,event.entity_type,event.entity_id,
       event.operation,
       CASE WHEN visible.allowed THEN event.actor_user_id END AS actor_user_id,
       CASE WHEN visible.allowed THEN event.actor_name END AS actor_name,
       CASE WHEN visible.allowed THEN event.actor_email END AS actor_email,
       event.actor_type,
       event.source,event.request_id,event.correlation_id,
       CASE WHEN visible.allowed THEN event.before_state ELSE NULL END AS before_state,
       CASE WHEN visible.allowed THEN event.after_state ELSE NULL END AS after_state,
       CASE WHEN visible.allowed THEN event.changed_fields ELSE ARRAY[]::text[] END AS changed_fields,
       CASE WHEN visible.allowed THEN event.reason ELSE NULL END AS reason,
       CASE WHEN visible.allowed THEN event.metadata
            ELSE jsonb_build_object('redacted',true,'reason','resource_access_denied') END AS metadata
FROM event_history event
CROSS JOIN LATERAL (
  SELECT current_user_can_view_event_resource(
    event.entity_type,event.entity_id,
    COALESCE(event.before_state,CASE WHEN event.entity_type LIKE 'disposition_%' THEN event.metadata->'before' END),
    COALESCE(event.after_state,CASE WHEN event.entity_type LIKE 'disposition_%' THEN event.metadata->'after' END)
  ) AS allowed
) visible;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('059_disposition_review');
COMMIT;
