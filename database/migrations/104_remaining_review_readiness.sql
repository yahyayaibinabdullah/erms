-- Read/refresh-time reviewer warnings and authoritative Standard review progression gates.
BEGIN;
CREATE FUNCTION disposition_private.job_review_setup(p_job bigint)
RETURNS TABLE(file_administrator_missing boolean,unit_manager_missing boolean)
LANGUAGE sql STABLE AS $$
 SELECT j.lifecycle_state='active' AND j.job_type='destruction' AND j.review_route='standard'
   AND ((j.workflow_stage IN ('officer_preparation','officer_correction','manager_preparation','manager_correction')
         AND s.has_file_administrator AND NOT s.has_file_administrator_assignment)
        OR (j.workflow_stage='file_administrator_review' AND NOT (s.has_file_administrator AND s.has_file_administrator_assignment))),
   j.lifecycle_state='active' AND j.job_type='destruction' AND j.review_route='standard'
   AND j.workflow_stage IN ('officer_preparation','officer_correction','manager_preparation','manager_correction','file_administrator_review','unit_manager_review')
   AND NOT (s.has_managing_role AND s.has_managing_role_assignment)
 FROM public.disposition_jobs j CROSS JOIN LATERAL disposition_private.owner_review_setup(j.owning_org_unit_id) s
 WHERE j.id=p_job
$$;

CREATE OR REPLACE FUNCTION disposition_private.require_standard_owner_roles() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE setup record;
BEGIN
 -- disposition_guard sets the saved route first. Existing jobs retain their lifecycle.
 IF NEW.job_type='destruction' AND NEW.review_route='standard' AND NEW.owning_org_unit_id IS NOT NULL THEN
  SELECT * INTO setup FROM disposition_private.owner_review_setup(NEW.owning_org_unit_id);
  IF NOT setup.has_file_administrator OR NOT setup.has_managing_role
     OR NOT setup.has_file_administrator_assignment OR NOT setup.has_managing_role_assignment THEN
   IF NOT (setup.has_file_administrator AND setup.has_file_administrator_assignment) AND NOT (setup.has_managing_role AND setup.has_managing_role_assignment) THEN RAISE EXCEPTION 'disposition_reviewers_required';
   ELSIF NOT (setup.has_file_administrator AND setup.has_file_administrator_assignment) THEN RAISE EXCEPTION 'disposition_file_administrator_required';
   ELSE RAISE EXCEPTION 'disposition_unit_manager_required'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.require_progress(p_job bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE setup record;
BEGIN
 SELECT * INTO setup FROM disposition_private.job_review_setup(p_job);
 IF setup.file_administrator_missing AND setup.unit_manager_missing THEN RAISE EXCEPTION 'disposition_reviewers_required';
 ELSIF setup.file_administrator_missing THEN RAISE EXCEPTION 'disposition_file_administrator_required';
 ELSIF setup.unit_manager_missing THEN RAISE EXCEPTION 'disposition_unit_manager_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' AND removal_required) THEN
 RAISE EXCEPTION 'disposition_removal_required'; END IF;
END $$;

REVOKE ALL ON FUNCTION disposition_private.job_review_setup(bigint) FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES ('104_remaining_review_readiness') ON CONFLICT (version) DO NOTHING;
COMMIT;
