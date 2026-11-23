BEGIN;
ALTER TABLE public.resource_type_role_grants
    DROP CONSTRAINT resource_type_role_grants_pkey,
    ALTER COLUMN role_id DROP NOT NULL,
    ADD CONSTRAINT resource_type_principal_unique UNIQUE NULLS NOT DISTINCT (kind, type_id, role_id);

CREATE OR REPLACE FUNCTION public.user_has_type_grant(p_user bigint, p_kind text, p_type bigint, p_use boolean)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT p_type IS NULL OR EXISTS (
        SELECT FROM resource_type_role_grants g
        WHERE (g.kind, g.type_id) = (p_kind, p_type) AND (NOT p_use OR g.can_use)
          AND EXISTS (SELECT FROM user_role_assignments a WHERE a.user_id=p_user
              AND (g.role_id IS NULL OR a.role_id=g.role_id)
              AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(a.role_id))
    )
$$;

CREATE OR REPLACE FUNCTION public.resource_type_history_access() RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN (WITH effective AS MATERIALIZED (
        SELECT r.id,level.level_number,r.is_information_governance FROM user_role_assignments a
          JOIN roles r ON r.id=a.role_id JOIN security_levels level ON level.id=r.security_level_id
         WHERE a.user_id=current_user_id() AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(r.id)
    ), clearance AS (
        SELECT max(level_number) AS ordinary,
               max(level_number) FILTER (WHERE is_information_governance) AS governance FROM effective
    )
    SELECT jsonb_build_object(
        'types', (SELECT jsonb_object_agg(g.kind || '/' || g.type_id,true) FROM resource_type_role_grants g
                   WHERE g.role_id IN (SELECT id FROM effective)
                      OR (g.role_id IS NULL AND EXISTS (SELECT FROM effective))),
        'levels', (SELECT jsonb_object_agg(id,true) FROM security_levels WHERE level_number<=clearance.ordinary),
        'governance', (SELECT jsonb_object_agg(id,true) FROM security_levels WHERE level_number<=clearance.governance))
      FROM clearance);
END $$;

INSERT INTO public.schema_migrations(version) VALUES ('123_resource_type_everyone');
COMMIT;
