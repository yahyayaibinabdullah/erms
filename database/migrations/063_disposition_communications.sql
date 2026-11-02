-- Durable external-document attempts and purge-independent reminder checkpoints.
BEGIN;
CREATE TABLE disposition_email_attempts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 command_id uuid NOT NULL UNIQUE,
 job_id bigint NOT NULL REFERENCES disposition_jobs(id),
 document_id bigint NOT NULL REFERENCES disposition_job_documents(id),
 review_round integer,
 actor_user_id bigint NOT NULL REFERENCES users(id),
 actor_type text NOT NULL DEFAULT 'user' CHECK(actor_type='user'),
 acting_role_id bigint NOT NULL REFERENCES roles(id),
 recipient text NOT NULL,
 sender text NOT NULL,
 configuration jsonb NOT NULL CHECK(NOT configuration ? 'password'),
 requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 status text NOT NULL DEFAULT 'sending' CHECK(status IN ('sending','smtp_accepted','failed','unknown')),
 outcome_at timestamptz,
 message_id text,
 server_message_id text,
 error_code text,
 smtp_code integer,
 CHECK((status='sending')=(outcome_at IS NULL))
);
CREATE INDEX disposition_email_job_page ON disposition_email_attempts(job_id,id DESC);
CREATE INDEX disposition_email_pending ON disposition_email_attempts(id) WHERE status='sending';
CREATE TABLE disposition_private.email_payloads (
 attempt_id bigint PRIMARY KEY REFERENCES disposition_email_attempts(id),
 content_set_id bigint NOT NULL,
 checksum text NOT NULL,
 database_id text NOT NULL,
 encrypted_password bytea,
 worker_token uuid,
 lease_expires_at timestamptz
);
CREATE TABLE disposition_private.communication_context(transaction_id bigint PRIMARY KEY);
CREATE FUNCTION disposition_private.communication_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM disposition_private.communication_context WHERE transaction_id=txid_current()) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_communication_protected';
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER email_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_email_attempts FOR EACH ROW EXECUTE FUNCTION disposition_private.communication_guard();
CREATE TRIGGER payload_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_private.email_payloads FOR EACH ROW EXECUTE FUNCTION disposition_private.communication_guard();

CREATE FUNCTION disposition_private.can_email(p_user bigint,p_job bigint,p_document bigint,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_jobs j JOIN disposition_job_documents d ON d.job_id=j.id
 JOIN digital_components dc ON dc.id=d.digital_component_id
 WHERE j.id=p_job AND d.id=p_document AND d.document_state='available'
 AND disposition_private.person_role(p_user,p_role)
 AND user_can_view_record(p_user,d.record_id) AND user_can_record_operation(p_user,d.record_id,'record.component.download','record.component.download')
 AND disposition_private.can_review_content(p_user,j.id)
 AND CASE WHEN d.document_type='digital_destruction_certificate' THEN
   j.lifecycle_state IN ('active','completed') AND disposition_private.review_role(j.id,'records_manager_review',p_role)
 WHEN d.document_type='destruction_request' THEN
   j.lifecycle_state='active' AND j.workflow_stage='external_approval_pending' AND j.assigned_user_id=p_user
   AND EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.job_id=j.id AND t.task_type='external_approval'
      AND t.request_document_id=d.id AND j.current_review_round=d.review_round
      AND disposition_private.request_approval_current(j.id,(d.provenance->>'approval_round_id')::bigint) AND t.task_state IN ('open','claimed') AND disposition_private.task_eligible(p_user,t.id,p_role))
 ELSE false END)
$$;
CREATE FUNCTION disposition_private.email_event(p_id bigint,p_operation text) RETURNS void LANGUAGE plpgsql AS $$
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
CREATE FUNCTION disposition_private.create_email_attempt(p_command uuid,p_job bigint,p_document bigint,p_role bigint,p_config jsonb,p_database text,p_secret bytea,p_message text) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
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
CREATE FUNCTION disposition_private.claim_email(p_token uuid) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
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
CREATE FUNCTION disposition_private.finish_email(p_id bigint,p_token uuid,p_status text,p_error text,p_code integer,p_server_id text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
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
CREATE TABLE disposition_private.reminder_schedule (
 producer_code text PRIMARY KEY,
 anchor_at timestamptz NOT NULL,
 months integer NOT NULL CHECK(months>0),
 setting_version integer NOT NULL,
 interval_index integer NOT NULL DEFAULT 1,
 recipient_after bigint NOT NULL DEFAULT 0
);
CREATE TABLE disposition_private.reminder_checkpoints (
 producer_code text NOT NULL,
 scheduled_at timestamptz NOT NULL,
 recipient_user_id bigint NOT NULL REFERENCES users(id),
 sent_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(producer_code,scheduled_at,recipient_user_id)
);
-- Technical schedule/checkpoint writes are private worker operations, not CRUD.
REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('063_disposition_communications');
COMMIT;
