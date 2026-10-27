BEGIN;

SELECT set_config('app.actor_type','automated_process',true),
       set_config('app.event_source','migration',true),
       set_config('app.change_reason','Use identity.users.administer for ordinary and localized user details; retire the duplicate metadata privilege',true);

-- Do not promote holders of the old narrow privilege to user administrators.
-- Existing user administrators already hold the sole required right.
DELETE FROM privilege_dependencies
 WHERE privilege_id IN (SELECT id FROM privileges WHERE code='user.modify_metadata')
    OR required_privilege_id IN (SELECT id FROM privileges WHERE code='user.modify_metadata');
DELETE FROM profile_privileges
 WHERE privilege_id IN (SELECT id FROM privileges WHERE code='user.modify_metadata');
DELETE FROM privileges WHERE code='user.modify_metadata';

-- Preserve translations and immutable history while removing obsolete labels
-- from active catalogues. Startup synchronization uses the same deprecation path.
UPDATE ui_message_definitions SET is_deprecated=true
 WHERE message_key IN ('privilege.user.modify_metadata.name','privilege.user.modify_metadata.description')
   AND NOT is_deprecated;

INSERT INTO schema_migrations(version)
 VALUES('090_unify_user_translation_authorization') ON CONFLICT DO NOTHING;
COMMIT;
