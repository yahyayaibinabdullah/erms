-- Require configured and currently staffed Standard review roles for new destruction jobs.
BEGIN;
CREATE FUNCTION disposition_private.owner_review_setup(p_owner bigint)
RETURNS TABLE(has_file_administrator boolean,has_managing_role boolean,
              has_file_administrator_assignment boolean,has_managing_role_assignment boolean)
LANGUAGE sql STABLE AS $$
 WITH RECURSIVE chain AS (
  SELECT id,parent_org_unit_id,file_administrator_role_id,0 depth,ARRAY[id] path
  FROM public.org_units WHERE id=p_owner
  UNION ALL
  SELECT o.id,o.parent_org_unit_id,o.file_administrator_role_id,c.depth+1,c.path||o.id
  FROM chain c JOIN public.org_units o ON o.id=c.parent_org_unit_id WHERE NOT o.id=ANY(c.path)
 ), designated AS (
  SELECT (SELECT file_administrator_role_id FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1) fa,
         (SELECT managing_role_id FROM public.org_units WHERE id=p_owner) manager
 ) SELECT fa IS NOT NULL,manager IS NOT NULL,
   EXISTS(SELECT 1 FROM public.user_role_assignments a WHERE a.role_id=fa AND disposition_private.person_role(a.user_id,fa)),
   EXISTS(SELECT 1 FROM public.user_role_assignments a WHERE a.role_id=manager AND disposition_private.person_role(a.user_id,manager))
 FROM designated
$$;

CREATE FUNCTION disposition_private.require_standard_owner_roles() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE setup record;
BEGIN
 -- disposition_guard sets the saved route first. Existing jobs retain their lifecycle.
 IF NEW.job_type='destruction' AND NEW.review_route='standard' AND NEW.owning_org_unit_id IS NOT NULL THEN
  SELECT * INTO setup FROM disposition_private.owner_review_setup(NEW.owning_org_unit_id);
  IF NOT setup.has_file_administrator OR NOT setup.has_managing_role
     OR NOT setup.has_file_administrator_assignment OR NOT setup.has_managing_role_assignment THEN
   RAISE EXCEPTION 'disposition_standard_owner_roles_required';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_standard_owner_roles BEFORE INSERT ON public.disposition_jobs
 FOR EACH ROW EXECUTE FUNCTION disposition_private.require_standard_owner_roles();
REVOKE ALL ON FUNCTION disposition_private.owner_review_setup(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION disposition_private.require_standard_owner_roles() FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES ('103_standard_destruction_owner_roles') ON CONFLICT (version) DO NOTHING;
COMMIT;
