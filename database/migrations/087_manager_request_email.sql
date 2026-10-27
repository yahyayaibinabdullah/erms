-- Request delivery: authorized Records Managers and the assigned Records Officer.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.can_email(p_user bigint,p_job bigint,p_document bigint,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
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
INSERT INTO schema_migrations(version) VALUES('087_manager_request_email') ON CONFLICT DO NOTHING;
COMMIT;
