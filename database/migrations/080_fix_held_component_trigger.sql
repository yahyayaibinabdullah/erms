BEGIN;

CREATE OR REPLACE FUNCTION protect_held_component_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE component_id bigint;
DECLARE held_record_id bigint;
DECLARE failure_code text;
BEGIN
    PERFORM lock_hold_policy_shared();
    IF TG_TABLE_NAME='digital_components' THEN
        held_record_id:=CASE WHEN TG_OP='DELETE' THEN OLD.record_id ELSE NEW.record_id END;
    ELSIF TG_TABLE_NAME='digital_component_content_sets' THEN
        component_id:=CASE WHEN TG_OP='DELETE' THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
        SELECT record_id INTO held_record_id FROM digital_components WHERE id=component_id;
    ELSIF TG_TABLE_NAME='digital_component_blobs' THEN
        SELECT component.digital_component_id INTO component_id
        FROM digital_component_content_sets component
        WHERE component.id=CASE WHEN TG_OP='DELETE' THEN OLD.content_set_id ELSE NEW.content_set_id END;
        SELECT record_id INTO held_record_id FROM digital_components WHERE id=component_id;
    ELSE
        component_id:=CASE WHEN TG_OP='DELETE' THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
        IF component_id IS NOT NULL THEN SELECT record_id INTO held_record_id FROM digital_components WHERE id=component_id; END IF;
    END IF;
    IF held_record_id IS NOT NULL AND resource_has_effective_hold('record',held_record_id) THEN
        failure_code:=CASE TG_OP WHEN 'INSERT' THEN 'effective_hold_prevents_component_addition'
          WHEN 'DELETE' THEN 'effective_hold_prevents_component_deletion'
          ELSE 'effective_hold_prevents_component_replacement' END;
        -- Resolve table-specific fields only after selecting their row type.
        IF TG_TABLE_NAME='digital_components' AND TG_OP='UPDATE' THEN
            IF NEW.component_order IS DISTINCT FROM OLD.component_order THEN
                failure_code:='effective_hold_prevents_component_reordering';
            END IF;
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE=failure_code;
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;

INSERT INTO schema_migrations(version) VALUES ('080_fix_held_component_trigger') ON CONFLICT DO NOTHING;

COMMIT;
