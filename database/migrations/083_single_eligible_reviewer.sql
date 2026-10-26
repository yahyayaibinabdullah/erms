BEGIN;
-- Keep the role destination so release/reconciliation can return work to its queue.
-- This BEFORE INSERT trigger follows disposition_guard alphabetically: the
-- original routing command is authorized before this narrowly scoped default.
CREATE FUNCTION disposition_private.assign_single_reviewer() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER disposition_single_reviewer BEFORE INSERT ON disposition_tasks
 FOR EACH ROW EXECUTE FUNCTION disposition_private.assign_single_reviewer();
REVOKE ALL ON FUNCTION disposition_private.assign_single_reviewer() FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('083_single_eligible_reviewer') ON CONFLICT DO NOTHING;
COMMIT;
