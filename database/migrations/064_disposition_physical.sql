BEGIN;
-- Physical preparation and immutable offline confirmation. Operational release
-- remains closed until the recovery AND completion implementations pass.
CREATE FUNCTION disposition_private.physical_execution_released() RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT false $$;
CREATE TABLE disposition_physical_confirmations (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job_id bigint NOT NULL UNIQUE REFERENCES disposition_jobs(id),
 task_id bigint NOT NULL UNIQUE REFERENCES disposition_tasks(id),
 successful boolean NOT NULL CHECK(successful),
 certificate_reference text NOT NULL UNIQUE CHECK(btrim(certificate_reference)<>''),
 certificate_document_id bigint NOT NULL UNIQUE REFERENCES disposition_job_documents(id),
 confirmed_by_user_id bigint NOT NULL REFERENCES users(id),
 acting_role_id bigint NOT NULL REFERENCES roles(id),
 confirmed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 confirmation_text text NOT NULL,
 confirmation_version integer NOT NULL CHECK(confirmation_version=1),
 physical_scope jsonb NOT NULL CHECK(jsonb_typeof(physical_scope)='object')
);
CREATE TABLE disposition_private.physical_context (
 transaction_id bigint PRIMARY KEY, backend_id integer NOT NULL,command_id uuid NOT NULL,job_id bigint NOT NULL
);
CREATE FUNCTION disposition_private.physical_active(p_job bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.physical_context p JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE p.transaction_id=txid_current() AND p.backend_id=pg_backend_pid() AND p.job_id=p_job)
$$;
CREATE FUNCTION disposition_private.physical_scope(p_job bigint) RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH units AS (SELECT m.root_aggregation_id,unit.id FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id) WHERE m.job_id=p_job AND m.membership_state='active')
 SELECT jsonb_build_object('aggregations',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',a.id,'root_id',u.root_aggregation_id,'medium',a.medium) ORDER BY a.id),'[]') FROM units u JOIN aggregations a ON a.id=u.id WHERE a.medium IN ('physical','mixed')),
 'records',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',r.id,'aggregation_id',r.aggregation_id,'root_id',u.root_aggregation_id,'medium',r.medium) ORDER BY r.id),'[]') FROM units u JOIN records r ON r.aggregation_id=u.id WHERE r.medium IN ('physical','mixed')))
$$;
CREATE FUNCTION disposition_private.has_digital_material(p_job bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) u(id) JOIN aggregations a ON a.id=u.id WHERE m.job_id=p_job AND m.membership_state='active' AND a.medium IN ('digital','mixed')) OR
 EXISTS(SELECT 1 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) u(id) JOIN records r ON r.aggregation_id=u.id WHERE m.job_id=p_job AND m.membership_state='active' AND r.medium IN ('digital','mixed'))
$$;
CREATE FUNCTION disposition_private.route_after_external(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
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
CREATE FUNCTION disposition_private.check_physical_work(p_task bigint,p_job_version integer,p_task_version integer,p_role bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;t disposition_tasks%ROWTYPE;root bigint;
BEGIN
 -- A code release boundary, deliberately not an operator-controlled setting.
 IF NOT disposition_private.physical_execution_released() THEN RAISE EXCEPTION 'disposition_physical_release_pending'; END IF;
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
CREATE FUNCTION disposition_private.guard_physical_confirmation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE acting bigint;key uuid;t disposition_tasks%ROWTYPE;doc disposition_job_documents%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'disposition_physical_immutable'; END IF;
 IF NOT disposition_private.physical_execution_released() OR NOT disposition_private.physical_active(NEW.job_id) OR disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_physical_release_pending'; END IF;
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
CREATE TRIGGER disposition_physical_confirmation_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_physical_confirmations FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_physical_confirmation();
CREATE FUNCTION disposition_private.confirm_physical(p_task bigint,p_job_version integer,p_task_version integer,p_success boolean,p_reference text,p_document bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
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
CREATE FUNCTION disposition_private.preserve_physical_outcome() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE job_id=OLD.id) AND NOT disposition_private.physical_active(OLD.id) AND (NEW.lifecycle_state IS DISTINCT FROM OLD.lifecycle_state OR NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage OR NEW.disposition_status IS DISTINCT FROM OLD.disposition_status) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_preserve_physical BEFORE UPDATE ON disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_physical_outcome();

CREATE OR REPLACE FUNCTION disposition_private.review_role(p_job bigint,p_stage text,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 WITH RECURSIVE chain AS (
 SELECT id,parent_org_unit_id,file_administrator_role_id,0 depth FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job)
 UNION ALL SELECT p.id,p.parent_org_unit_id,p.file_administrator_role_id,c.depth+1 FROM org_units p JOIN chain c ON p.id=c.parent_org_unit_id)
 SELECT CASE (CASE WHEN p_stage IN ('physical_destruction','digital_destruction') THEN 'records_manager_review' ELSE p_stage END)
 WHEN 'file_administrator_review' THEN p_role=(SELECT file_administrator_role_id FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1)
 WHEN 'unit_manager_review' THEN p_role=(SELECT managing_role_id FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job))
 WHEN 'records_manager_review' THEN EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE r.id=p_role AND p.code='INFO_GOV_MGR' AND r.is_information_governance AND v.code='disposition.jobs.manage')
 ELSE false END
$$;
CREATE OR REPLACE FUNCTION disposition_private.record_external_decision(p_task bigint,p_job_version integer,p_task_version integer,p_request bigint,p_decision text,p_notes text,p_number text,p_letter bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
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
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;

CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
DECLARE proposal_data jsonb;
BEGIN
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
CREATE FUNCTION disposition_private.guard_physical_task() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' AND NEW.task_type='physical_destruction' AND NOT disposition_private.external_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_external_command_required'; END IF;
 IF TG_OP='UPDATE' AND OLD.task_type='physical_destruction' AND NEW.task_state='completed' AND OLD.task_state IS DISTINCT FROM NEW.task_state AND NOT disposition_private.physical_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_physical_required'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_physical_task_guard BEFORE INSERT OR UPDATE ON disposition_tasks FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_physical_task();
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('064_disposition_physical') ON CONFLICT DO NOTHING;
COMMIT;
