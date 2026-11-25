
BEGIN;

-- Exercise truncation before fixture writes queue deferred constraint triggers.
DO $$
BEGIN
    BEGIN
        -- Include FK dependents so PostgreSQL reaches the immutability trigger.
        TRUNCATE event_history CASCADE;
        RAISE EXCEPTION 'event history TRUNCATE was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'event history is immutable' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO org_units(code,name)
VALUES ('PHASE2-SEGMENT','Event history test unit');

INSERT INTO classification_schemes (code, title, date_published)
VALUES ('AUDIT-TEST', 'Audit test scheme', CURRENT_TIMESTAMP)
RETURNING id AS audit_scheme_id \gset
INSERT INTO classifications (classification_scheme_id, code, title, is_terminal)
VALUES (:audit_scheme_id, 'AUDIT-01', 'Audit test classification', true)
RETURNING id AS audit_classification_id \gset
INSERT INTO classification_retention_rules
    (classification_id, current_period_years, intermediate_period_years, final_disposition)
VALUES (:audit_classification_id, 5, 0, 'destruction');

INSERT INTO aggregations (aggregation_number, title, classification_id, owning_org_unit_id)
SELECT 'AUDIT-AGG-001', 'Audited aggregation', :audit_classification_id, id
FROM org_units WHERE code='PHASE2-SEGMENT'
RETURNING id AS audited_aggregation_id \gset

UPDATE aggregations
SET title = 'Updated audited aggregation'
WHERE id = :audited_aggregation_id;

DO $$
DECLARE
    create_event event_history%ROWTYPE;
    update_event event_history%ROWTYPE;
BEGIN
    SELECT * INTO STRICT create_event
    FROM event_history
    WHERE entity_type = 'aggregation' AND operation = 'CREATE'
      AND after_state ->> 'aggregation_number' = 'AUDIT-AGG-001';

    IF create_event.before_state IS NOT NULL
       OR create_event.after_state ->> 'title' <> 'Audited aggregation'
       OR create_event.source <> 'database'
       OR create_event.actor_type <> 'automated_process'
       OR create_event.metadata #>> '{reference_snapshots,after,classification_id,code}' <> 'AUDIT-01'
       OR create_event.metadata #>> '{reference_snapshots,entity,code}' <> 'AUDIT-AGG-001' THEN
        RAISE EXCEPTION 'CREATE history event is incorrect';
    END IF;

    SELECT * INTO STRICT update_event
    FROM event_history
    WHERE entity_type = 'aggregation' AND operation = 'UPDATE'
      AND after_state ->> 'aggregation_number' = 'AUDIT-AGG-001';

    IF update_event.before_state ->> 'title' <> 'Audited aggregation'
       OR update_event.after_state ->> 'title' <> 'Updated audited aggregation'
       OR update_event.changed_fields <> ARRAY['title'] THEN
        RAISE EXCEPTION 'UPDATE history event is incorrect';
    END IF;
END;
$$;

SAVEPOINT before_rolled_back_change;
INSERT INTO aggregations (aggregation_number, title, classification_id, owning_org_unit_id)
SELECT 'AUDIT-ROLLBACK', 'This change will roll back', :audit_classification_id, id
FROM org_units WHERE code='PHASE2-SEGMENT';
ROLLBACK TO SAVEPOINT before_rolled_back_change;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM event_history
        WHERE after_state ->> 'aggregation_number' = 'AUDIT-ROLLBACK'
    ) THEN
        RAISE EXCEPTION 'history survived a rolled-back entity change';
    END IF;

    BEGIN
        UPDATE event_history
        SET reason = 'tampered'
        WHERE id = (SELECT min(id) FROM event_history);
        RAISE EXCEPTION 'event history UPDATE was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'event history is immutable' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        DELETE FROM event_history
        WHERE id = (SELECT min(id) FROM event_history);
        RAISE EXCEPTION 'event history DELETE was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'event history is immutable' THEN
                RAISE;
            END IF;
    END;

END;
$$;

DELETE FROM aggregations WHERE id = :audited_aggregation_id;

DO $$
DECLARE
    delete_event event_history%ROWTYPE;
BEGIN
    SELECT * INTO STRICT delete_event
    FROM event_history
    WHERE entity_type = 'aggregation' AND operation = 'DELETE'
      AND before_state ->> 'aggregation_number' = 'AUDIT-AGG-001';

    IF delete_event.before_state ->> 'title' <> 'Updated audited aggregation'
       OR delete_event.after_state IS NOT NULL THEN
        RAISE EXCEPTION 'DELETE history event is incorrect';
    END IF;
END;
$$;

ROLLBACK;
