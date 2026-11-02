BEGIN;
SELECT set_config('app.user_id','',true),
       set_config('app.actor_type','automated_process',true),
       set_config('app.actor_name','Database migration 053',true),
       set_config('app.event_source','migration',true),
       set_config('app.change_reason','Install approved common disposition foundation',true);

-- Phase 7 common persistence. Action-specific entry points remain closed until
-- their own phases supply current blocker, routing, evidence and approval gates.
CREATE SCHEMA disposition_private;
REVOKE ALL ON SCHEMA disposition_private FROM PUBLIC;

-- The single privilege required by Disposition section 15. Platform
-- administrators receive no implicit disposition authority.
INSERT INTO privileges(code,name,description,category)
 VALUES('disposition.jobs.manage','Manage Disposition Jobs','Perform authorized disposition work without granting resource access or bypassing protection.','administration') ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id)
 SELECT profile.id,privilege.id FROM profiles profile CROSS JOIN privileges privilege
 WHERE profile.code IN ('ALL_PRIVS','INFO_GOV_MGR','INFO_GOV_OFFICER') AND privilege.code='disposition.jobs.manage' ON CONFLICT DO NOTHING;

CREATE TABLE disposition_jobs (
 id bigserial PRIMARY KEY,
 job_number text NOT NULL UNIQUE CHECK (btrim(job_number)<>''),
 job_type text NOT NULL CHECK (job_type IN ('destruction','permanent_transfer','selective_transfer','local_archives')),
 lifecycle_state text NOT NULL DEFAULT 'active' CHECK (lifecycle_state IN ('active','completed','terminated')),
 workflow_stage text,
 disposition_status smallint NOT NULL CHECK (disposition_status BETWEEN 1 AND 13),
 owning_org_unit_id bigint REFERENCES org_units(id) ON DELETE RESTRICT,
 assigned_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 current_review_round integer NOT NULL DEFAULT 0 CHECK (current_review_round>=0),
 created_by_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 completed_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 completed_by_name text,
 completed_at timestamptz,
 terminated_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 terminated_at timestamptz,
 termination_reason text,
 destruction_number text UNIQUE CHECK (destruction_number IS NULL OR (btrim(destruction_number)<>'' AND char_length(destruction_number)<=20)),
 transfer_number text UNIQUE CHECK (transfer_number IS NULL OR (btrim(transfer_number)<>'' AND char_length(transfer_number)<=20)),
 final_event_id bigint REFERENCES event_history(id) ON DELETE RESTRICT,
 version integer NOT NULL DEFAULT 1 CHECK (version>0),
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 CONSTRAINT disposition_jobs_completion CHECK (
  (lifecycle_state='completed' AND disposition_status IN (10,11,12)
   AND completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL AND completed_by_name IS NOT NULL AND final_event_id IS NOT NULL)
  OR (lifecycle_state<>'completed' AND disposition_status NOT IN (10,11,12)
   AND completed_at IS NULL AND completed_by_user_id IS NULL AND completed_by_name IS NULL AND final_event_id IS NULL)),
 CONSTRAINT disposition_jobs_termination CHECK (
  (lifecycle_state='terminated' AND terminated_at IS NOT NULL AND terminated_by_user_id IS NOT NULL AND NULLIF(btrim(termination_reason),'') IS NOT NULL)
  OR (lifecycle_state<>'terminated' AND terminated_at IS NULL AND terminated_by_user_id IS NULL AND termination_reason IS NULL)),
 CONSTRAINT disposition_jobs_numbers CHECK (
  (destruction_number IS NULL OR job_type='destruction') AND (transfer_number IS NULL OR job_type='permanent_transfer')
  AND (disposition_status<>10 OR destruction_number IS NOT NULL) AND (disposition_status<>11 OR transfer_number IS NOT NULL)),
 CONSTRAINT disposition_jobs_stage CHECK (
  (job_type='destruction' AND owning_org_unit_id IS NOT NULL AND workflow_stage IS NOT NULL AND workflow_stage IN (
   'officer_preparation','officer_correction','manager_preparation','manager_correction',
   'file_administrator_review','unit_manager_review','records_manager_review',
   'external_approval_pending','physical_destruction','digital_destruction','certificate_generation'))
  OR (job_type<>'destruction' AND workflow_stage IS NULL))
);

CREATE TABLE disposition_job_memberships (
 id bigserial PRIMARY KEY,
 job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 root_aggregation_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE RESTRICT,
 membership_state text NOT NULL DEFAULT 'active' CHECK (membership_state IN ('active','removed','terminated_history','completed_history')),
 added_by_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 added_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 removed_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 removed_at timestamptz,
 removal_reason text,
 version integer NOT NULL DEFAULT 1 CHECK (version>0),
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT disposition_membership_removal CHECK (
  (membership_state='removed' AND removed_by_user_id IS NOT NULL AND removed_at IS NOT NULL AND NULLIF(btrim(removal_reason),'') IS NOT NULL)
  OR (membership_state<>'removed' AND removed_by_user_id IS NULL AND removed_at IS NULL AND removal_reason IS NULL))
);
CREATE UNIQUE INDEX disposition_one_active_job_per_root ON disposition_job_memberships(root_aggregation_id) WHERE membership_state='active';
CREATE INDEX disposition_memberships_job ON disposition_job_memberships(job_id,id);

CREATE TABLE disposition_tasks (
 id bigserial PRIMARY KEY,
 job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 task_type text NOT NULL CHECK (task_type IN ('preparation','correction','file_administrator_review','unit_manager_review','records_manager_review','external_approval','physical_destruction','digital_destruction','certificate_download')),
 workflow_stage text NOT NULL CHECK (workflow_stage IN ('officer_preparation','officer_correction','manager_preparation','manager_correction','file_administrator_review','unit_manager_review','records_manager_review','external_approval_pending','physical_destruction','digital_destruction','certificate_generation')),
 review_round integer CHECK (review_round>0),
 task_state text NOT NULL DEFAULT 'open' CHECK (task_state IN ('open','claimed','completed','cancelled')),
 destination_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 destination_role_id bigint REFERENCES roles(id) ON DELETE RESTRICT,
 claimed_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 claimed_at timestamptz,
 completed_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 completed_at timestamptz,
 released_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 released_at timestamptz,
 reassigned_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 reassigned_at timestamptz,
 priority integer NOT NULL DEFAULT 0,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 version integer NOT NULL DEFAULT 1 CHECK (version>0),
 CHECK ((destination_user_id IS NULL)<>(destination_role_id IS NULL)),
 CHECK ((claimed_by_user_id IS NULL)=(claimed_at IS NULL)),
 CHECK ((task_state='claimed')=(claimed_by_user_id IS NOT NULL) OR task_state IN ('completed','cancelled')),
 CHECK ((task_state='completed')=(completed_by_user_id IS NOT NULL AND completed_at IS NOT NULL)),
 CHECK ((completed_by_user_id IS NULL)=(completed_at IS NULL)),
 CHECK ((released_by_user_id IS NULL)=(released_at IS NULL)),
 CHECK ((reassigned_by_user_id IS NULL)=(reassigned_at IS NULL))
);
CREATE INDEX disposition_tasks_inbox_user ON disposition_tasks(destination_user_id,task_state,id);
CREATE INDEX disposition_tasks_inbox_role ON disposition_tasks(destination_role_id,task_state,id);

CREATE TABLE disposition_review_rounds (
 id bigserial PRIMARY KEY,
 job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 round_number integer NOT NULL CHECK (round_number>0),
 started_by_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 membership_snapshot jsonb NOT NULL CHECK (jsonb_typeof(membership_snapshot)='array'),
 completed_at timestamptz,
 invalidated_at timestamptz,
 invalidation_reason text,
 version integer NOT NULL DEFAULT 1 CHECK (version>0),
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(job_id,round_number), UNIQUE(id,job_id),
 CHECK ((invalidated_at IS NOT NULL)=(NULLIF(btrim(invalidation_reason),'') IS NOT NULL))
);
CREATE TABLE disposition_review_decisions (
 id bigserial PRIMARY KEY,
 job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 round_id bigint NOT NULL,
 review_stage text NOT NULL CHECK (review_stage IN ('file_administrator_review','unit_manager_review','records_manager_review','manager_preparation','manager_correction')),
 decision text NOT NULL CHECK (decision IN ('approved','rejected')),
 task_id bigint NOT NULL UNIQUE REFERENCES disposition_tasks(id) ON DELETE RESTRICT,
 actor_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 acting_role_id bigint NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
 reason text NOT NULL CHECK (btrim(reason)<>''),
 decided_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 membership_snapshot jsonb NOT NULL CHECK (jsonb_typeof(membership_snapshot)='array'),
 FOREIGN KEY(round_id,job_id) REFERENCES disposition_review_rounds(id,job_id) ON DELETE RESTRICT
);
CREATE TABLE disposition_job_documents (
 id bigserial PRIMARY KEY,
 job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 document_type text NOT NULL CHECK (document_type IN ('destruction_request','external_rejection_letter','external_approval_letter','physical_destruction_certificate','digital_destruction_certificate','proposal_execution_report','physical_preparation_report')),
 document_state text NOT NULL CHECK (document_state IN ('generating','available','failed')),
 review_round integer CHECK (review_round>0),
 record_id bigint REFERENCES records(id) ON DELETE RESTRICT,
 digital_component_id bigint REFERENCES digital_components(id) ON DELETE RESTRICT,
 created_by_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 checksum_algo text,
 checksum text,
 template_version text,
 version integer NOT NULL DEFAULT 1 CHECK (version>0),
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK (document_state<>'available' OR (record_id IS NOT NULL AND digital_component_id IS NOT NULL AND NULLIF(btrim(checksum),'') IS NOT NULL AND NULLIF(btrim(checksum_algo),'') IS NOT NULL))
);

ALTER TABLE aggregations ADD COLUMN disposition_status smallint NOT NULL DEFAULT 1 CHECK (disposition_status BETWEEN 1 AND 13),
 ADD COLUMN final_disposition_at timestamptz,
 ADD COLUMN final_disposition_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 ADD COLUMN disposition_job_id bigint REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 ADD COLUMN destruction_number text,
 ADD COLUMN transfer_number text,
 ADD COLUMN final_disposition_event_id bigint REFERENCES event_history(id) ON DELETE RESTRICT;
ALTER TABLE records ADD COLUMN disposition_status smallint NOT NULL DEFAULT 1 CHECK (disposition_status BETWEEN 1 AND 13),
 ADD COLUMN final_disposition_at timestamptz,
 ADD COLUMN final_disposition_by_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
 ADD COLUMN disposition_job_id bigint REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 ADD COLUMN destruction_number text,
 ADD COLUMN transfer_number text,
 ADD COLUMN final_disposition_event_id bigint REFERENCES event_history(id) ON DELETE RESTRICT;

-- Durable command receipts are technical retry infrastructure, not workflow
-- definitions. No scripts, arbitrary state graphs or administrator processes.
CREATE TABLE disposition_private.command_receipts (
 command_id uuid PRIMARY KEY,
 actor_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 acting_role_id bigint NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
 operation text NOT NULL CHECK (operation IN ('job_create','job_assign','membership_add','membership_remove','eligibility_evaluate','eligibility_accelerate','job_terminate','resolve_partial','task_claim','task_release','task_reassign','task_complete','review_submit','review_decide','document_save','selective_decide','final_complete','recalculate')),
 payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
 reason text NOT NULL CHECK (btrim(reason)<>''),
 result jsonb,
 started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 completed_at timestamptz,
 CHECK ((result IS NULL)=(completed_at IS NULL))
);
CREATE TABLE disposition_private.command_context (
 transaction_id bigint PRIMARY KEY,
 backend_id integer NOT NULL,
 command_id uuid NOT NULL REFERENCES disposition_private.command_receipts(command_id) ON DELETE RESTRICT
);
REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;

CREATE FUNCTION disposition_private.context_operation() RETURNS text LANGUAGE sql STABLE AS $$
 SELECT r.operation FROM disposition_private.command_context c
 JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid()
   AND r.actor_user_id=current_user_id() AND r.completed_at IS NULL
$$;

CREATE FUNCTION disposition_private.require_actor(p_role_id bigint) RETURNS void LANGUAGE plpgsql AS $$
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

CREATE FUNCTION disposition_private.begin_command(p_id uuid,p_operation text,p_payload jsonb,p_role bigint,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE previous disposition_private.command_receipts%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 PERFORM disposition_private.require_actor(p_role);
 IF NULLIF(btrim(p_reason),'') IS NULL THEN RAISE EXCEPTION 'disposition_reason_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.command_context WHERE transaction_id=txid_current()) THEN RAISE EXCEPTION 'disposition_nested_command'; END IF;
 SELECT * INTO previous FROM disposition_private.command_receipts WHERE command_id=p_id FOR UPDATE;
 IF FOUND THEN
  IF previous.actor_user_id<>current_user_id() OR previous.acting_role_id<>p_role OR previous.operation<>p_operation
    OR previous.payload IS DISTINCT FROM p_payload OR previous.reason IS DISTINCT FROM p_reason THEN
    RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='disposition_command_conflict'; END IF;
  IF previous.completed_at IS NULL THEN RAISE EXCEPTION 'disposition_incomplete_command'; END IF;
  RETURN previous.result;
 END IF;
 INSERT INTO disposition_private.command_receipts(command_id,actor_user_id,acting_role_id,operation,payload,reason)
 VALUES(p_id,current_user_id(),p_role,p_operation,p_payload,p_reason);
 INSERT INTO disposition_private.command_context VALUES(txid_current(),pg_backend_pid(),p_id);
 PERFORM set_config('app.change_reason',p_reason,true);
 RETURN NULL;
END $$;

CREATE FUNCTION disposition_private.finish_command(p_result jsonb) RETURNS void LANGUAGE plpgsql AS $$
DECLARE command uuid;
BEGIN
 SELECT command_id INTO command FROM disposition_private.command_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid();
 IF command IS NULL OR p_result IS NULL THEN RAISE EXCEPTION 'disposition_command_required'; END IF;
 UPDATE disposition_private.command_receipts SET result=p_result,completed_at=CURRENT_TIMESTAMP WHERE command_id=command;
 DELETE FROM disposition_private.command_context WHERE transaction_id=txid_current();
END $$;

CREATE FUNCTION disposition_private.require_command() RETURNS void LANGUAGE plpgsql AS $$
DECLARE command disposition_private.command_receipts%ROWTYPE;
BEGIN
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid() AND r.completed_at IS NULL;
 IF NOT FOUND OR command.actor_user_id IS DISTINCT FROM current_user_id() THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 PERFORM disposition_private.require_actor(command.acting_role_id);
END $$;

CREATE FUNCTION disposition_private.allowed_transition(old_status integer,new_status integer,cause text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT old_status=new_status OR CASE cause
 WHEN 'eligibility_evaluate' THEN old_status=1 AND new_status BETWEEN 2 AND 5
 WHEN 'eligibility_accelerate' THEN old_status=1 AND new_status BETWEEN 2 AND 5
 WHEN 'membership_add' THEN (old_status,new_status) IN ((2,6),(3,7),(4,8),(5,9))
 WHEN 'membership_remove' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5))
 WHEN 'job_terminate' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5),(6,13))
 WHEN 'resolve_partial' THEN old_status=13 AND new_status BETWEEN 2 AND 5
 WHEN 'selective_decide' THEN old_status=8 AND new_status IN (2,3,5)
 WHEN 'final_complete' THEN (old_status,new_status) IN ((6,10),(7,11),(9,12))
 WHEN 'recalculate' THEN old_status NOT IN (10,11,12,13) AND new_status BETWEEN 1 AND 9
 ELSE false END
$$;

CREATE FUNCTION disposition_private.root_id(p_id bigint) RETURNS bigint LANGUAGE sql STABLE AS $$
 WITH RECURSIVE a AS (SELECT id,parent_aggregation_id FROM aggregations WHERE id=p_id
 UNION ALL SELECT p.id,p.parent_aggregation_id FROM aggregations p JOIN a ON p.id=a.parent_aggregation_id)
 SELECT id FROM a WHERE parent_aggregation_id IS NULL
$$;
CREATE FUNCTION disposition_private.unit_ids(p_root bigint) RETURNS SETOF bigint LANGUAGE sql STABLE AS $$
 WITH RECURSIVE a AS (SELECT id FROM aggregations WHERE id=p_root UNION ALL
 SELECT child.id FROM aggregations child JOIN a ON child.parent_aggregation_id=a.id) SELECT id FROM a
$$;

CREATE FUNCTION disposition_private.guard_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous jsonb; following jsonb; fields text[] := ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id']; operation text;
BEGIN
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
CREATE TRIGGER aggregations_disposition_guard BEFORE INSERT OR UPDATE OR DELETE ON aggregations FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_resource();
CREATE TRIGGER records_disposition_guard BEFORE INSERT OR UPDATE OR DELETE ON records FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_resource();

-- Only protected disposition-field updates may pass existing closure guards.
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

CREATE OR REPLACE FUNCTION protect_record_in_closed_aggregation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
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

CREATE FUNCTION disposition_private.assert_unit(p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
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
  -- Non-pending members are retained only by the later reopening/rule-change
  -- operation. Their required-removal flag is an explicit blocker on the job.
  IF root.disposition_status NOT BETWEEN 6 AND 9 THEN
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

CREATE FUNCTION disposition_private.check_unit_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root bigint;
BEGIN
 IF TG_TABLE_NAME='disposition_job_memberships' THEN
  PERFORM disposition_private.assert_unit(NEW.root_aggregation_id);
 ELSIF TG_TABLE_NAME='disposition_jobs' THEN
  IF NEW.current_review_round>0 AND NOT EXISTS(SELECT 1 FROM disposition_review_rounds WHERE job_id=NEW.id AND round_number=NEW.current_review_round) THEN RAISE EXCEPTION 'disposition_review_round_missing'; END IF;
  FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=NEW.id LOOP
   PERFORM disposition_private.assert_unit(root);
  END LOOP;
 ELSE
  root:=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN NEW.id ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END);
  PERFORM disposition_private.assert_unit(root);
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER aggregations_disposition_consistency AFTER UPDATE ON aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 WHEN ((OLD.disposition_status,OLD.final_disposition_at,OLD.final_disposition_by_user_id,OLD.disposition_job_id,OLD.destruction_number,OLD.transfer_number,OLD.final_disposition_event_id)
 IS DISTINCT FROM (NEW.disposition_status,NEW.final_disposition_at,NEW.final_disposition_by_user_id,NEW.disposition_job_id,NEW.destruction_number,NEW.transfer_number,NEW.final_disposition_event_id)) EXECUTE FUNCTION disposition_private.check_unit_trigger();
CREATE CONSTRAINT TRIGGER records_disposition_consistency AFTER UPDATE ON records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 WHEN ((OLD.disposition_status,OLD.final_disposition_at,OLD.final_disposition_by_user_id,OLD.disposition_job_id,OLD.destruction_number,OLD.transfer_number,OLD.final_disposition_event_id)
 IS DISTINCT FROM (NEW.disposition_status,NEW.final_disposition_at,NEW.final_disposition_by_user_id,NEW.disposition_job_id,NEW.destruction_number,NEW.transfer_number,NEW.final_disposition_event_id)) EXECUTE FUNCTION disposition_private.check_unit_trigger();
CREATE CONSTRAINT TRIGGER disposition_membership_consistency AFTER INSERT OR UPDATE ON disposition_job_memberships DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();
CREATE CONSTRAINT TRIGGER disposition_job_consistency AFTER INSERT OR UPDATE ON disposition_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.check_unit_trigger();

CREATE FUNCTION disposition_private.membership_snapshot(p_job bigint) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT COALESCE(jsonb_agg(jsonb_build_object('membership_id',m.id,'membership_version',m.version,
  'root_id',m.root_aggregation_id,
  'aggregations',(SELECT jsonb_agg(jsonb_build_object('id',a.id,'version',a.version) ORDER BY a.id) FROM aggregations a WHERE a.id IN (SELECT disposition_private.unit_ids(m.root_aggregation_id))),
  'records',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',r.id,'version',r.version) ORDER BY r.id),'[]'::jsonb) FROM records r WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(m.root_aggregation_id)))) ORDER BY m.id),'[]'::jsonb)
 FROM disposition_job_memberships m WHERE m.job_id=p_job AND m.membership_state='active'
$$;
CREATE FUNCTION disposition_private.allowed_stage(old_stage text,new_stage text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
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

CREATE FUNCTION disposition_private.require_job_access(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' AND NOT current_user_can_view_aggregation(root_aggregation_id)) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
END $$;

CREATE FUNCTION disposition_private.guard_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; prior jsonb; following jsonb; op text; uid bigint:=current_user_id(); expected_status integer;
BEGIN
 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 IF NOT (CASE TG_TABLE_NAME
 WHEN 'disposition_jobs' THEN op IN ('job_create','job_assign','membership_add','membership_remove','job_terminate','final_complete','review_submit','review_decide','recalculate','selective_decide')
 WHEN 'disposition_job_memberships' THEN op IN ('membership_add','membership_remove','job_terminate','final_complete')
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
  IF TG_OP='UPDATE' THEN PERFORM disposition_private.require_job_access(NEW.id); END IF;
  IF TG_OP='INSERT' THEN
   IF op<>'job_create' OR NEW.lifecycle_state<>'active' OR NEW.created_by_user_id<>uid OR (NEW.job_type='destruction' AND NEW.workflow_stage NOT IN ('officer_preparation','manager_preparation')) THEN RAISE EXCEPTION 'disposition_invalid_job_creation'; END IF;
   NEW.date_created:=CURRENT_TIMESTAMP;
  ELSE
   IF NEW.job_number<>OLD.job_number OR NEW.job_type<>OLD.job_type OR NEW.created_by_user_id<>OLD.created_by_user_id OR NEW.date_created<>OLD.date_created THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF NEW.lifecycle_state<>OLD.lifecycle_state AND NOT ((op='job_terminate' AND NEW.lifecycle_state='terminated') OR (op='final_complete' AND NEW.lifecycle_state='completed')) THEN RAISE EXCEPTION 'disposition_invalid_lifecycle_transition'; END IF;
   IF NEW.disposition_status<>OLD.disposition_status AND NOT disposition_private.allowed_transition(OLD.disposition_status,NEW.disposition_status,op) THEN RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
   IF NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND (op NOT IN ('review_submit','review_decide','final_complete') OR NOT disposition_private.allowed_stage(OLD.workflow_stage,NEW.workflow_stage)) THEN RAISE EXCEPTION 'disposition_invalid_stage_transition'; END IF;
  END IF;
  expected_status:=CASE NEW.job_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 ELSE 9 END;
  IF NEW.lifecycle_state='active' AND NEW.disposition_status<>expected_status THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
  IF NEW.assigned_user_id IS NOT NULL AND NOT EXISTS(
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
 PERFORM disposition_private.require_job_access(job.id);
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF TG_TABLE_NAME='disposition_job_memberships' THEN
  IF disposition_private.root_id(NEW.root_aggregation_id)<>NEW.root_aggregation_id THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
  IF TG_OP='INSERT' THEN
   IF op<>'membership_add' OR NEW.membership_state<>'active' OR NEW.added_by_user_id<>uid OR job.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_membership_add_invalid'; END IF;
   IF NOT current_user_can_view_aggregation(NEW.root_aggregation_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=NEW.root_aggregation_id AND membership_state='completed_history') THEN RAISE EXCEPTION 'disposition_already_completed'; END IF;
   NEW.added_at:=CURRENT_TIMESTAMP;
  ELSE
   IF NOT current_user_can_view_aggregation(NEW.root_aggregation_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF NEW.root_aggregation_id<>OLD.root_aggregation_id OR NEW.added_at<>OLD.added_at OR NEW.added_by_user_id<>OLD.added_by_user_id THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF NOT ((op='membership_remove' AND NEW.membership_state='removed') OR (op='job_terminate' AND NEW.membership_state='terminated_history') OR (op='final_complete' AND NEW.membership_state='completed_history')) THEN RAISE EXCEPTION 'disposition_invalid_membership_transition'; END IF;
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

CREATE FUNCTION disposition_private.audit_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE before_state jsonb; after_state jsonb; command disposition_private.command_receipts%ROWTYPE;
BEGIN
 before_state:=CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) END;
 after_state:=to_jsonb(NEW);
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM append_domain_event(CASE TG_TABLE_NAME WHEN 'disposition_jobs' THEN 'disposition_job' WHEN 'disposition_job_memberships' THEN 'disposition_job_membership' WHEN 'disposition_tasks' THEN 'disposition_task' WHEN 'disposition_review_rounds' THEN 'disposition_review_round' WHEN 'disposition_review_decisions' THEN 'disposition_review_decision' ELSE 'disposition_job_document' END,
 NEW.id, upper(command.operation), jsonb_build_object('command_id',command.command_id,'acting_role_id',command.acting_role_id,'before',before_state,'after',after_state),command.reason);
 RETURN NULL;
END $$;
DO $$
DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['disposition_jobs','disposition_job_memberships','disposition_tasks','disposition_review_rounds','disposition_review_decisions','disposition_job_documents'] LOOP
  EXECUTE format('CREATE TRIGGER disposition_guard BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_workflow()',name);
  EXECUTE format('CREATE TRIGGER disposition_audit AFTER INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_workflow()',name);
 END LOOP;
END $$;

CREATE FUNCTION disposition_private.command_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR OLD.completed_at IS NOT NULL OR (to_jsonb(NEW)-ARRAY['result','completed_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['result','completed_at']) THEN RAISE EXCEPTION 'disposition_command_history_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_command_immutable BEFORE UPDATE OR DELETE ON disposition_private.command_receipts FOR EACH ROW EXECUTE FUNCTION disposition_private.command_immutable();
CREATE FUNCTION disposition_private.command_complete_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_private.command_receipts WHERE command_id=NEW.command_id AND completed_at IS NULL)
 OR EXISTS(SELECT 1 FROM disposition_private.command_context WHERE command_id=NEW.command_id) THEN RAISE EXCEPTION 'disposition_command_not_finished'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER disposition_command_complete AFTER INSERT ON disposition_private.command_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.command_complete_check();

CREATE FUNCTION disposition_private.transition_unit(p_root bigint,p_version integer,p_status integer)
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
 IF NOT user_can_view_aggregation(uid,p_root) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.disposition_status=p_status THEN RETURN; END IF;
 event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_STATUS_CHANGED',jsonb_build_object(
  'old_status',root.disposition_status,'new_status',p_status,'operation',op,
  'command_id',(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())));
 UPDATE aggregations SET disposition_status=p_status WHERE id IN (SELECT disposition_private.unit_ids(p_root));
 UPDATE records SET disposition_status=p_status WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
END $$;

CREATE FUNCTION disposition_private.claim_task(p_task bigint,p_version integer) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE task disposition_tasks%ROWTYPE; next_version integer;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_claim' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO task FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR task.version<>p_version OR task.task_state<>'open' THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 UPDATE disposition_tasks SET task_state='claimed',claimed_by_user_id=current_user_id() WHERE id=p_task RETURNING version INTO next_version;
 RETURN next_version;
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
       aggregation_effective_assigned_location(resource.id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.id) AS effective_current_location,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.id))
            THEN aggregation_effective_assigned_location_source_id(resource.id) END AS effective_assigned_location_source_aggregation_id,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.id))
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
) hold_state;

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
) hold_state;

CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
BEGIN
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
INSERT INTO schema_migrations(version) VALUES('053_disposition_foundation');
COMMIT;
