-- Promote the approved demo FILE_ADMIN profile without changing existing assignments.
BEGIN;
SELECT set_config('app.actor_type','automated_process',true),
       set_config('app.change_reason','Provision built-in File Administrator profile',true);
SELECT set_config('app.event_source','migration',true);
-- This existing messaging privilege must be available without optional seeds.
INSERT INTO privileges(code,name,description,category,is_reserved,account_type_restriction)
VALUES('messaging.user_messages.exchange','Exchange messages','Send and receive human-authored messages.','administration',false,'person')
ON CONFLICT DO NOTHING;
DO $$
DECLARE
 expected_codes text[] := ARRAY['aggregation.acl.manage','aggregation.close','aggregation.create_child','aggregation.create_root','aggregation.location.change','aggregation.modify','aggregation.move','aggregation.reclassify','aggregation.review_date.change','aggregation.security_level.change','aggregation.view','aggregation.vital_status.change','closure.correct_record_placement','messaging.user_messages.exchange','organization.browse','record.acl.manage','record.component.add','record.component.download','record.component.print','record.component.reindex','record.component.reorder','record.component.share','record.component.view','record.create','record.modify','record.move','record.review_date.change','record.security_level.change','record.view','record.vital_status.change','relationships.link','search.saved_search.delete','search.saved_search.save','security.resource.downgrade']::text[];
 existing_profile profiles%ROWTYPE;
 actual_codes text[];
 target_id bigint;
BEGIN
 -- Never silently omit privileges when applied to an incompatible schema.
 IF (SELECT count(*) FROM privileges WHERE code=ANY(expected_codes)) <> cardinality(expected_codes) THEN
  RAISE EXCEPTION 'FILE_ADMIN requires all 34 canonical privileges; apply preceding migrations first';
 END IF;
 SELECT * INTO existing_profile FROM profiles WHERE lower(code)='file_admin' FOR UPDATE;
 IF FOUND THEN
  SELECT array_agg(v.code ORDER BY v.code) INTO actual_codes
   FROM profile_privileges pp JOIN privileges v ON v.id=pp.privilege_id
   WHERE pp.profile_id=existing_profile.id;
  IF existing_profile.code <> 'FILE_ADMIN' OR existing_profile.name <> 'File Administrator'
     OR actual_codes IS DISTINCT FROM expected_codes THEN
   RAISE EXCEPTION 'Existing FILE_ADMIN differs from the approved built-in profile; review and reconcile explicitly before retrying';
  END IF;
  UPDATE profiles SET is_system=true,version=version+1,date_updated=CURRENT_TIMESTAMP
   WHERE id=existing_profile.id AND NOT is_system;
 ELSE
  IF EXISTS(SELECT 1 FROM profiles WHERE lower(name)='file administrator') THEN
   RAISE EXCEPTION 'File Administrator name belongs to another profile code; review before retrying';
  END IF;
  INSERT INTO profiles(code,name,is_system) VALUES('FILE_ADMIN','File Administrator',true) RETURNING id INTO target_id;
  INSERT INTO profile_privileges(profile_id,privilege_id)
   SELECT target_id,id FROM privileges WHERE code=ANY(expected_codes);
 END IF;
END $$;
-- Default entity metadata translation; preserve administrator wording and other fields.
UPDATE profiles
 SET translations = coalesce(translations,'{}'::jsonb) || jsonb_build_object(
       'ar',coalesce(translations->'ar','{}'::jsonb) || jsonb_build_object('name','مسؤول الملفات')),
     version=version+1,date_updated=CURRENT_TIMESTAMP
 WHERE code='FILE_ADMIN' AND nullif(btrim(translations->'ar'->>'name'),'') IS NULL;
INSERT INTO schema_migrations(version) VALUES('073_file_administrator_profile') ON CONFLICT DO NOTHING;
COMMIT;
