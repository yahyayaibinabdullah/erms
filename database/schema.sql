BEGIN;

-- Natural numeric ordering for organization-unit and role codes.
CREATE COLLATION erms_code_natural (provider = icu, locale = 'und-u-kn-true');

CREATE TABLE security_levels (
    id                   bigserial PRIMARY KEY,
    code                 text NOT NULL,
    name                 text NOT NULL,
    level_number         integer NOT NULL,
    prevents_disposition boolean NOT NULL DEFAULT false,
    date_created         timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated         timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version              integer NOT NULL DEFAULT 1,
    CONSTRAINT security_levels_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT security_levels_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT security_levels_number_nonnegative CHECK (level_number >= 0),
    CONSTRAINT security_levels_version_positive CHECK (version > 0),
    CONSTRAINT security_levels_level_number_unique UNIQUE (level_number)
);

CREATE UNIQUE INDEX security_levels_code_ci_unique ON security_levels (lower(code));
CREATE UNIQUE INDEX security_levels_name_ci_unique ON security_levels (lower(name));

INSERT INTO security_levels (code, name, level_number, prevents_disposition)
VALUES ('G','General',0,false), ('R','Restricted',50,false),
       ('S','Secret',75,false), ('TS','Top Secret',100,true);

CREATE TABLE aggregations (
    id                    bigserial PRIMARY KEY,
    parent_aggregation_id bigint REFERENCES aggregations (id) ON DELETE RESTRICT,
    aggregation_number    text NOT NULL UNIQUE,
    title                 text NOT NULL,
    description           text,
    date_created          timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_opened           timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_closed           timestamptz,

    CONSTRAINT aggregations_number_not_blank
        CHECK (btrim(aggregation_number) <> ''),
    CONSTRAINT aggregations_title_not_blank
        CHECK (btrim(title) <> ''),
    CONSTRAINT aggregations_not_own_parent
        CHECK (parent_aggregation_id IS NULL OR parent_aggregation_id <> id),
    CONSTRAINT aggregations_dates_in_order
        CHECK (date_closed IS NULL OR date_closed >= date_opened)
);

CREATE INDEX aggregations_parent_aggregation_id_idx
    ON aggregations (parent_aggregation_id);
CREATE INDEX aggregations_parent_number_browse_idx
    ON aggregations (parent_aggregation_id, aggregation_number COLLATE "C", id);

CREATE TABLE records (
    id              bigserial PRIMARY KEY,
    aggregation_id  bigint NOT NULL REFERENCES aggregations (id) ON DELETE RESTRICT,
    record_number   text NOT NULL UNIQUE,
    title           text NOT NULL,
    description     text,
    date_created    timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_originated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT records_number_not_blank
        CHECK (btrim(record_number) <> ''),
    CONSTRAINT records_title_not_blank
        CHECK (btrim(title) <> '')
);

CREATE INDEX records_aggregation_id_idx
    ON records (aggregation_id);
CREATE INDEX records_aggregation_number_browse_idx
    ON records (aggregation_id, record_number COLLATE "C", id);

CREATE TABLE digital_components (
    id              bigserial PRIMARY KEY,
    record_id       bigint NOT NULL REFERENCES records (id) ON DELETE CASCADE,
    component_order integer NOT NULL,
    file_name       text NOT NULL,
    date_created    timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_originated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mime_type       text NOT NULL,
    size_in_bytes   bigint NOT NULL,
    checksum_algo   text NOT NULL,
    checksum_value  text NOT NULL,

    CONSTRAINT digital_components_file_name_not_blank
        CHECK (btrim(file_name) <> ''),
    CONSTRAINT digital_components_order_positive
        CHECK (component_order > 0),
    CONSTRAINT digital_components_mime_type_not_blank
        CHECK (btrim(mime_type) <> ''),
    CONSTRAINT digital_components_size_nonnegative
        CHECK (size_in_bytes >= 0),
    CONSTRAINT digital_components_checksum_algo_not_blank
        CHECK (btrim(checksum_algo) <> ''),
    CONSTRAINT digital_components_checksum_value_not_blank
        CHECK (btrim(checksum_value) <> ''),
    CONSTRAINT digital_components_record_order_unique
        UNIQUE (record_id, component_order)
        DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX digital_components_record_id_idx
    ON digital_components (record_id);

-- DEFAULT applies when a column is omitted, while this trigger also handles an
-- explicitly supplied NULL as requested by the domain rules.
CREATE FUNCTION set_aggregation_default_dates()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.date_created IS NULL THEN
        NEW.date_created := CURRENT_TIMESTAMP;
    END IF;

    IF NEW.date_opened IS NULL THEN
        NEW.date_opened := NEW.date_created;
    END IF;

    RETURN NEW;
END;
$$;

CREATE FUNCTION set_originated_default_dates()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.date_created IS NULL THEN
        NEW.date_created := CURRENT_TIMESTAMP;
    END IF;

    IF NEW.date_originated IS NULL THEN
        NEW.date_originated := NEW.date_created;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER aggregations_set_default_dates
BEFORE INSERT ON aggregations
FOR EACH ROW EXECUTE FUNCTION set_aggregation_default_dates();

CREATE TRIGGER records_set_default_dates
BEFORE INSERT ON records
FOR EACH ROW EXECUTE FUNCTION set_originated_default_dates();

CREATE TRIGGER digital_components_set_default_dates
BEFORE INSERT ON digital_components
FOR EACH ROW EXECUTE FUNCTION set_originated_default_dates();

-- A self-referencing foreign key prevents missing parents but not longer
-- cycles. This trigger preserves a genuine containment hierarchy.
CREATE FUNCTION prevent_aggregation_cycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.parent_aggregation_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF EXISTS (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_aggregation_id
            FROM aggregations
            WHERE id = NEW.parent_aggregation_id

            UNION ALL

            SELECT aggregation.id, aggregation.parent_aggregation_id
            FROM aggregations AS aggregation
            JOIN ancestors ON aggregation.id = ancestors.parent_aggregation_id
        )
        SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'aggregation hierarchy cannot contain a cycle';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER aggregations_prevent_cycle
BEFORE INSERT OR UPDATE OF parent_aggregation_id ON aggregations
FOR EACH ROW EXECUTE FUNCTION prevent_aggregation_cycle();

-- The current event-history schema is repeated here intentionally. New
-- databases need only this standard SQL file; existing databases use the
-- numbered migration containing the equivalent upgrade.
CREATE TABLE schema_migrations (
    id         bigserial PRIMARY KEY,
    version    text NOT NULL UNIQUE,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT schema_migrations_version_not_blank
        CHECK (btrim(version) <> '')
);

CREATE TABLE event_history (
    id              bigserial PRIMARY KEY,
    occurred_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    transaction_id  bigint NOT NULL DEFAULT (pg_current_xact_id()::text::bigint),
    entity_type     text NOT NULL,
    entity_id       bigint NOT NULL,
    operation       text NOT NULL,
    actor_user_id   bigint,
    actor_name      text,
    actor_email     text,
    actor_type      text NOT NULL DEFAULT 'automated_process',
    source          text NOT NULL DEFAULT 'database',
    request_id      uuid,
    correlation_id  uuid,
    before_state    jsonb,
    after_state     jsonb,
    changed_fields  text[] NOT NULL DEFAULT ARRAY[]::text[],
    reason          text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT event_history_entity_type_not_blank
        CHECK (btrim(entity_type) <> ''),
    CONSTRAINT event_history_operation_not_blank
        CHECK (btrim(operation) <> ''),
    CONSTRAINT event_history_actor_type_not_blank
        CHECK (btrim(actor_type) <> ''),
    CONSTRAINT event_history_actor_type_valid
        CHECK (actor_type IN ('user', 'anonymous', 'automated_process')),
    CONSTRAINT event_history_source_not_blank
        CHECK (btrim(source) <> ''),
    CONSTRAINT event_history_metadata_is_object
        CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT event_history_row_change_states_valid
        CHECK (
            (operation = 'CREATE' AND before_state IS NULL AND after_state IS NOT NULL)
            OR (operation = 'UPDATE' AND before_state IS NOT NULL AND after_state IS NOT NULL)
            OR (operation = 'DELETE' AND before_state IS NOT NULL AND after_state IS NULL)
            OR operation NOT IN ('CREATE', 'UPDATE', 'DELETE')
        )
);

CREATE INDEX event_history_entity_timeline_idx
    ON event_history (entity_type, entity_id, occurred_at DESC, id DESC);

CREATE INDEX event_history_actor_timeline_idx
    ON event_history (actor_user_id, occurred_at DESC, id DESC)
    WHERE actor_user_id IS NOT NULL;

CREATE INDEX event_history_request_id_idx
    ON event_history (request_id)
    WHERE request_id IS NOT NULL;

CREATE INDEX event_history_correlation_id_idx
    ON event_history (correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE INDEX event_history_occurred_at_idx
    ON event_history (occurred_at DESC, id DESC);

CREATE INDEX event_history_security_operation_timeline_idx
    ON event_history (operation, occurred_at DESC)
    WHERE operation IN (
        'AUTHORIZATION_DENIED','AUTHENTICATION_FAILED','ACCOUNT_LOCKED',
        'INFORMATION_GOVERNANCE_BYPASS_USED','ACCESS_EXPLANATION_VIEWED',
        'SECURITY_LEVEL_CHANGED','SECURITY_LEVEL_UPGRADED','SECURITY_LEVEL_DOWNGRADED',
        'ACL_REPLACED','DEFAULT_CHILD_AGGREGATION_ACL_REPLACED',
        'DEFAULT_CHILD_RECORD_ACL_REPLACED','PROFILE_PRIVILEGES_REPLACED',
        'PROFILE_ASSIGNED','GOVERNANCE_ROLE_CHANGED'
    );

CREATE FUNCTION populate_event_actor_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    stored_name  text;
    stored_email text;
BEGIN
    IF NEW.actor_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.actor_name IS NULL OR NEW.actor_email IS NULL THEN
        SELECT name, email INTO stored_name, stored_email
        FROM users
        WHERE id = NEW.actor_user_id;
    END IF;

    NEW.actor_name := COALESCE(
        NEW.actor_name,
        NULLIF(current_setting('app.actor_name', true), ''),
        stored_name
    );
    NEW.actor_email := COALESCE(
        NEW.actor_email,
        NULLIF(current_setting('app.actor_email', true), ''),
        stored_email
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER event_history_populate_actor_snapshot
BEFORE INSERT ON event_history
FOR EACH ROW EXECUTE FUNCTION populate_event_actor_snapshot();

CREATE FUNCTION populate_event_relationship_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    assignment_state jsonb;
    user_snapshot     jsonb;
    role_snapshot     jsonb;
BEGIN
    IF NEW.entity_type <> 'user_role_assignment' THEN
        RETURN NEW;
    END IF;

    assignment_state := COALESCE(NEW.after_state, NEW.before_state);
    SELECT jsonb_build_object('id', id, 'name', name, 'email', email)
    INTO user_snapshot
    FROM users
    WHERE id = (assignment_state ->> 'user_id')::bigint;

    SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
    INTO role_snapshot
    FROM roles
    WHERE id = (assignment_state ->> 'role_id')::bigint;

    NEW.metadata := NEW.metadata || jsonb_build_object(
        'assignment_parties',
        jsonb_build_object('user', user_snapshot, 'role', role_snapshot)
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER event_history_populate_relationship_snapshot
BEFORE INSERT ON event_history
FOR EACH ROW EXECUTE FUNCTION populate_event_relationship_snapshot();

-- Preserve readable identities for entities referenced by newly-created audit
-- events.  These snapshots deliberately live alongside the numeric keys: the
-- key remains useful to developers while the snapshot remains meaningful to
-- auditors after the referenced row is renamed or deleted.
CREATE FUNCTION event_reference_identity(reference_field text, reference_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    snapshot jsonb;
BEGIN
    CASE reference_field
        WHEN 'profile_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM profiles WHERE id = reference_id;
        WHEN 'old_profile_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM profiles WHERE id = reference_id;
        WHEN 'new_profile_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM profiles WHERE id = reference_id;
        WHEN 'security_level_id' THEN
            SELECT jsonb_build_object(
                'id', id, 'code', code, 'name', name, 'level_number', level_number
            ) INTO snapshot FROM security_levels WHERE id = reference_id;
        WHEN 'classification_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'title', title)
            INTO snapshot FROM classifications WHERE id = reference_id;
        WHEN 'parent_classification_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'title', title)
            INTO snapshot FROM classifications WHERE id = reference_id;
        WHEN 'classification_scheme_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'title', title)
            INTO snapshot FROM classification_schemes WHERE id = reference_id;
        WHEN 'aggregation_id' THEN
            SELECT jsonb_build_object(
                'id', id, 'code', aggregation_number, 'title', title
            ) INTO snapshot FROM aggregations WHERE id = reference_id;
        WHEN 'parent_aggregation_id' THEN
            SELECT jsonb_build_object(
                'id', id, 'code', aggregation_number, 'title', title
            ) INTO snapshot FROM aggregations WHERE id = reference_id;
        WHEN 'destination_aggregation_id' THEN
            SELECT jsonb_build_object(
                'id', id, 'code', aggregation_number, 'title', title
            ) INTO snapshot FROM aggregations WHERE id = reference_id;
        WHEN 'record_id' THEN
            SELECT jsonb_build_object('id', id, 'code', record_number, 'title', title)
            INTO snapshot FROM records WHERE id = reference_id;
        WHEN 'role_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM roles WHERE id = reference_id;
        WHEN 'supervisor_role_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM roles WHERE id = reference_id;
        WHEN 'user_id' THEN
            SELECT jsonb_build_object('id', id, 'name', name, 'email', email)
            INTO snapshot FROM users WHERE id = reference_id;
        WHEN 'owner_user_id' THEN
            SELECT jsonb_build_object('id', id, 'name', name, 'email', email)
            INTO snapshot FROM users WHERE id = reference_id;
        WHEN 'org_unit_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM org_units WHERE id = reference_id;
        WHEN 'parent_org_unit_id' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM org_units WHERE id = reference_id;
        ELSE
            snapshot := NULL;
    END CASE;
    RETURN snapshot;
END;
$$;

CREATE FUNCTION event_state_reference_snapshots(event_state jsonb)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    reference_field text;
    reference_value text;
    snapshot        jsonb;
    snapshots       jsonb := '{}'::jsonb;
BEGIN
    IF event_state IS NULL OR jsonb_typeof(event_state) <> 'object' THEN
        RETURN snapshots;
    END IF;

    FOREACH reference_field IN ARRAY ARRAY[
        'profile_id', 'old_profile_id', 'new_profile_id', 'security_level_id',
        'classification_id', 'parent_classification_id', 'classification_scheme_id',
        'aggregation_id', 'parent_aggregation_id', 'destination_aggregation_id',
        'record_id', 'role_id', 'supervisor_role_id', 'user_id', 'owner_user_id',
        'org_unit_id', 'parent_org_unit_id'
    ] LOOP
        reference_value := event_state ->> reference_field;
        IF reference_value IS NOT NULL AND reference_value ~ '^[0-9]+$' THEN
            snapshot := event_reference_identity(reference_field, reference_value::bigint);
            IF snapshot IS NOT NULL THEN
                snapshots := snapshots || jsonb_build_object(reference_field, snapshot);
            END IF;
        END IF;
    END LOOP;
    RETURN snapshots;
END;
$$;

CREATE FUNCTION event_entity_identity_snapshot(event_entity_type text, event_entity_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    snapshot jsonb;
BEGIN
    CASE event_entity_type
        WHEN 'aggregation' THEN
            SELECT jsonb_build_object('id', id, 'code', aggregation_number, 'title', title)
            INTO snapshot FROM aggregations WHERE id = event_entity_id;
        WHEN 'record' THEN
            SELECT jsonb_build_object('id', id, 'code', record_number, 'title', title)
            INTO snapshot FROM records WHERE id = event_entity_id;
        WHEN 'digital_component' THEN
            SELECT jsonb_build_object('id', id, 'name', file_name)
            INTO snapshot FROM digital_components WHERE id = event_entity_id;
        WHEN 'classification_scheme' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'title', title)
            INTO snapshot FROM classification_schemes WHERE id = event_entity_id;
        WHEN 'classification' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'title', title)
            INTO snapshot FROM classifications WHERE id = event_entity_id;
        WHEN 'org_unit' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM org_units WHERE id = event_entity_id;
        WHEN 'role' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM roles WHERE id = event_entity_id;
        WHEN 'user' THEN
            SELECT jsonb_build_object('id', id, 'name', name, 'email', email)
            INTO snapshot FROM users WHERE id = event_entity_id;
        WHEN 'profile' THEN
            SELECT jsonb_build_object('id', id, 'code', code, 'name', name)
            INTO snapshot FROM profiles WHERE id = event_entity_id;
        WHEN 'security_level' THEN
            SELECT jsonb_build_object(
                'id', id, 'code', code, 'name', name, 'level_number', level_number
            ) INTO snapshot FROM security_levels WHERE id = event_entity_id;
        ELSE
            snapshot := NULL;
    END CASE;
    RETURN snapshot;
END;
$$;

CREATE FUNCTION populate_event_reference_snapshots()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    snapshots      jsonb := '{}'::jsonb;
    state_snapshot jsonb;
BEGIN
    state_snapshot := event_state_reference_snapshots(NEW.before_state);
    IF state_snapshot <> '{}'::jsonb THEN
        snapshots := snapshots || jsonb_build_object('before', state_snapshot);
    END IF;

    state_snapshot := event_state_reference_snapshots(NEW.after_state);
    IF state_snapshot <> '{}'::jsonb THEN
        snapshots := snapshots || jsonb_build_object('after', state_snapshot);
    END IF;

    state_snapshot := event_state_reference_snapshots(NEW.metadata);
    IF state_snapshot <> '{}'::jsonb THEN
        snapshots := snapshots || jsonb_build_object('metadata', state_snapshot);
    END IF;

    state_snapshot := event_entity_identity_snapshot(NEW.entity_type, NEW.entity_id);
    IF state_snapshot IS NOT NULL THEN
        snapshots := snapshots || jsonb_build_object('entity', state_snapshot);
    END IF;

    IF snapshots <> '{}'::jsonb THEN
        NEW.metadata := NEW.metadata || jsonb_build_object('reference_snapshots', snapshots);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER event_history_populate_reference_snapshots
BEFORE INSERT ON event_history
FOR EACH ROW EXECUTE FUNCTION populate_event_reference_snapshots();

CREATE FUNCTION record_entity_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    old_state        jsonb;
    new_state        jsonb;
    entity_key       bigint;
    changed          text[];
    context_user_id  text;
    context_metadata text;
BEGIN
    IF TG_OP = 'UPDATE'
       AND current_setting('app.suppress_ordinary_history', true) = 'authorized' THEN
        RETURN NEW;
    END IF;
    old_state := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
    new_state := CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END;
    entity_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;

    SELECT COALESCE(array_agg(key ORDER BY key), ARRAY[]::text[])
    INTO changed
    FROM (
        SELECT key
        FROM jsonb_object_keys(COALESCE(old_state, '{}'::jsonb) || COALESCE(new_state, '{}'::jsonb)) AS key
        WHERE old_state -> key IS DISTINCT FROM new_state -> key
    ) AS differences;

    context_user_id := NULLIF(current_setting('app.user_id', true), '');
    context_metadata := NULLIF(current_setting('app.event_metadata', true), '');

    INSERT INTO event_history (
        entity_type,
        entity_id,
        operation,
        actor_user_id,
        actor_type,
        source,
        request_id,
        correlation_id,
        before_state,
        after_state,
        changed_fields,
        reason,
        metadata
    )
    VALUES (
        TG_ARGV[0],
        entity_key,
        CASE TG_OP WHEN 'INSERT' THEN 'CREATE' ELSE TG_OP END,
        context_user_id::bigint,
        COALESCE(NULLIF(current_setting('app.actor_type', true), ''), 'automated_process'),
        COALESCE(NULLIF(current_setting('app.event_source', true), ''), 'database'),
        NULLIF(current_setting('app.request_id', true), '')::uuid,
        NULLIF(current_setting('app.correlation_id', true), '')::uuid,
        old_state,
        new_state,
        changed,
        NULLIF(current_setting('app.change_reason', true), ''),
        COALESCE(context_metadata::jsonb, '{}'::jsonb)
    );

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER aggregations_record_history
AFTER INSERT OR UPDATE OR DELETE ON aggregations
FOR EACH ROW EXECUTE FUNCTION record_entity_history('aggregation');

CREATE TRIGGER records_record_history
AFTER INSERT OR UPDATE OR DELETE ON records
FOR EACH ROW EXECUTE FUNCTION record_entity_history('record');

CREATE TRIGGER digital_components_record_history
AFTER INSERT OR UPDATE OR DELETE ON digital_components
FOR EACH ROW EXECUTE FUNCTION record_entity_history('digital_component');

CREATE FUNCTION reject_event_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'event history is immutable';
END;
$$;

CREATE TRIGGER event_history_reject_update_delete
BEFORE UPDATE OR DELETE ON event_history
FOR EACH ROW EXECUTE FUNCTION reject_event_history_mutation();

CREATE TRIGGER event_history_reject_truncate
BEFORE TRUNCATE ON event_history
FOR EACH STATEMENT EXECUTE FUNCTION reject_event_history_mutation();


-- User management subsystem. The equivalent upgrade for existing databases is
-- database/migrations/002_add_user_management.sql.
CREATE TABLE org_units (
    id                 bigserial PRIMARY KEY,
    parent_org_unit_id bigint REFERENCES org_units (id) ON DELETE RESTRICT,
    code               text NOT NULL,
    name               text NOT NULL,
    description        text,
    date_created       timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_deactivated   timestamptz,
    status             text GENERATED ALWAYS AS (
        CASE WHEN date_deactivated IS NULL THEN 'active' ELSE 'inactive' END
    ) STORED,

    CONSTRAINT org_units_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT org_units_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT org_units_not_own_parent
        CHECK (parent_org_unit_id IS NULL OR parent_org_unit_id <> id),
    CONSTRAINT org_units_dates_in_order
        CHECK (date_deactivated IS NULL OR date_deactivated >= date_created)
);

CREATE UNIQUE INDEX org_units_code_ci_unique
    ON org_units (lower(code));
CREATE UNIQUE INDEX org_units_name_ci_unique
    ON org_units (lower(name));
CREATE INDEX org_units_parent_org_unit_id_idx
    ON org_units (parent_org_unit_id);

CREATE TABLE users (
    id               bigserial PRIMARY KEY,
    name             text NOT NULL,
    email            text,
    external_id      text,
    account_type     text NOT NULL DEFAULT 'person',
    date_created     timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_deactivated timestamptz,
    date_suspended   timestamptz,
    status           text GENERATED ALWAYS AS (
        CASE
            WHEN date_deactivated IS NOT NULL THEN 'inactive'
            WHEN date_suspended IS NOT NULL THEN 'suspended'
            ELSE 'active'
        END
    ) STORED,

    CONSTRAINT users_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT users_email_not_blank CHECK (email IS NULL OR btrim(email) <> ''),
    CONSTRAINT users_external_id_not_blank
        CHECK (external_id IS NULL OR btrim(external_id) <> ''),
    CONSTRAINT users_account_type_valid
        CHECK (account_type IN ('person', 'service')),
    CONSTRAINT users_dates_in_order
        CHECK (
            (date_deactivated IS NULL OR date_deactivated >= date_created)
            AND (date_suspended IS NULL OR date_suspended >= date_created)
        ),
    CONSTRAINT users_lifecycle_dates_exclusive
        CHECK (date_deactivated IS NULL OR date_suspended IS NULL)
);

CREATE UNIQUE INDEX users_email_ci_unique
    ON users (lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX users_external_id_unique
    ON users (external_id) WHERE external_id IS NOT NULL;

CREATE TABLE roles (
    id                 bigserial PRIMARY KEY,
    org_unit_id        bigint NOT NULL REFERENCES org_units (id) ON DELETE RESTRICT,
    supervisor_role_id bigint REFERENCES roles (id) ON DELETE RESTRICT,
    code               text NOT NULL,
    name               text NOT NULL,
    description        text,
    date_created       timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_deactivated   timestamptz,
    status             text GENERATED ALWAYS AS (
        CASE WHEN date_deactivated IS NULL THEN 'active' ELSE 'inactive' END
    ) STORED,

    CONSTRAINT roles_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT roles_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT roles_not_own_supervisor
        CHECK (supervisor_role_id IS NULL OR supervisor_role_id <> id),
    CONSTRAINT roles_dates_in_order
        CHECK (date_deactivated IS NULL OR date_deactivated >= date_created)
);

CREATE UNIQUE INDEX roles_code_ci_unique ON roles (lower(code));
CREATE UNIQUE INDEX roles_name_ci_unique ON roles (lower(name));
CREATE INDEX roles_org_unit_id_idx ON roles (org_unit_id);
CREATE INDEX roles_supervisor_role_id_idx ON roles (supervisor_role_id);

CREATE TABLE user_role_assignments (
    id            bigserial PRIMARY KEY,
    user_id       bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role_id       bigint NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
    date_assigned timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_from    timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_until   timestamptz,

    CONSTRAINT user_role_assignments_dates_in_order
        CHECK (valid_until IS NULL OR valid_until >= valid_from),
    CONSTRAINT user_role_assignments_period_unique
        UNIQUE (user_id, role_id, valid_from)
);

CREATE INDEX user_role_assignments_user_id_idx
    ON user_role_assignments (user_id);
CREATE INDEX user_role_assignments_role_id_idx
    ON user_role_assignments (role_id);

CREATE TABLE user_credentials (
    id                   bigserial PRIMARY KEY,
    user_id              bigint NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    password_hash        text NOT NULL,
    must_change_password boolean NOT NULL DEFAULT true,
    temporary_expires_at timestamptz,
    password_changed_at  timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    failed_attempt_count integer NOT NULL DEFAULT 0,
    last_failed_at       timestamptz,
    locked_until         timestamptz,
    last_authenticated_at timestamptz,
    date_created         timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated         timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT user_credentials_password_hash_not_blank CHECK (btrim(password_hash) <> ''),
    CONSTRAINT user_credentials_failed_attempts_nonnegative CHECK (failed_attempt_count >= 0)
);

CREATE TABLE login_sessions (
    id                  bigserial PRIMARY KEY,
    user_id             bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    session_token_hash  bytea NOT NULL UNIQUE,
    csrf_token_hash     bytea NOT NULL,
    date_created        timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at        timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at          timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    revoked_at          timestamptz,
    revoked_by          bigint REFERENCES users (id) ON DELETE SET NULL,
    client_ip           inet,
    user_agent          text,

    CONSTRAINT login_sessions_expiry_valid CHECK (expires_at > date_created),
    CONSTRAINT login_sessions_absolute_expiry_valid CHECK (absolute_expires_at >= expires_at)
);

CREATE INDEX login_sessions_user_id_idx ON login_sessions (user_id);
CREATE INDEX login_sessions_active_idx
    ON login_sessions (expires_at, absolute_expires_at) WHERE revoked_at IS NULL;
CREATE INDEX login_sessions_revoked_cleanup_idx
    ON login_sessions (revoked_at, id) WHERE revoked_at IS NOT NULL;

CREATE TABLE user_favourite_aggregations (
    user_id         bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    aggregation_id  bigint NOT NULL REFERENCES aggregations (id) ON DELETE CASCADE,
    date_created    timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, aggregation_id)
);

CREATE INDEX user_favourite_aggregations_aggregation_id_idx
    ON user_favourite_aggregations (aggregation_id);
CREATE INDEX user_favourite_aggregations_user_created_idx
    ON user_favourite_aggregations (user_id, date_created DESC, aggregation_id);

CREATE TABLE user_favourite_records (
    user_id      bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    record_id    bigint NOT NULL REFERENCES records (id) ON DELETE CASCADE,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, record_id)
);

CREATE INDEX user_favourite_records_record_id_idx
    ON user_favourite_records (record_id);
CREATE INDEX user_favourite_records_user_created_idx
    ON user_favourite_records (user_id, date_created DESC, record_id);

CREATE FUNCTION set_user_management_default_dates()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.date_created IS NULL THEN
        NEW.date_created := CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION set_assignment_default_dates()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.date_assigned IS NULL THEN
        NEW.date_assigned := CURRENT_TIMESTAMP;
    END IF;
    IF NEW.valid_from IS NULL THEN
        NEW.valid_from := NEW.date_assigned;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION prevent_org_unit_cycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.parent_org_unit_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_org_unit_id
            FROM org_units WHERE id = NEW.parent_org_unit_id
            UNION ALL
            SELECT parent.id, parent.parent_org_unit_id
            FROM org_units AS parent
            JOIN ancestors ON parent.id = ancestors.parent_org_unit_id
        )
        SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'organizational unit hierarchy cannot contain a cycle';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION prevent_role_supervision_cycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.supervisor_role_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        WITH RECURSIVE supervisors AS (
            SELECT id, supervisor_role_id
            FROM roles WHERE id = NEW.supervisor_role_id
            UNION ALL
            SELECT supervisor.id, supervisor.supervisor_role_id
            FROM roles AS supervisor
            JOIN supervisors ON supervisor.id = supervisors.supervisor_role_id
        )
        SELECT 1 FROM supervisors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'role supervision hierarchy cannot contain a cycle';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER org_units_set_default_dates
BEFORE INSERT ON org_units
FOR EACH ROW EXECUTE FUNCTION set_user_management_default_dates();

CREATE TRIGGER users_set_default_dates
BEFORE INSERT ON users
FOR EACH ROW EXECUTE FUNCTION set_user_management_default_dates();

CREATE TRIGGER roles_set_default_dates
BEFORE INSERT ON roles
FOR EACH ROW EXECUTE FUNCTION set_user_management_default_dates();

CREATE TRIGGER user_role_assignments_set_default_dates
BEFORE INSERT ON user_role_assignments
FOR EACH ROW EXECUTE FUNCTION set_assignment_default_dates();

CREATE TRIGGER org_units_prevent_cycle
BEFORE INSERT OR UPDATE OF parent_org_unit_id ON org_units
FOR EACH ROW EXECUTE FUNCTION prevent_org_unit_cycle();

CREATE TRIGGER roles_prevent_supervision_cycle
BEFORE INSERT OR UPDATE OF supervisor_role_id ON roles
FOR EACH ROW EXECUTE FUNCTION prevent_role_supervision_cycle();

CREATE TRIGGER org_units_record_history
AFTER INSERT OR UPDATE OR DELETE ON org_units
FOR EACH ROW EXECUTE FUNCTION record_entity_history('org_unit');

CREATE TRIGGER users_record_history
AFTER INSERT OR UPDATE OR DELETE ON users
FOR EACH ROW EXECUTE FUNCTION record_entity_history('user');

CREATE TRIGGER roles_record_history
AFTER INSERT OR UPDATE OR DELETE ON roles
FOR EACH ROW EXECUTE FUNCTION record_entity_history('role');

CREATE TRIGGER user_role_assignments_record_history
AFTER INSERT OR UPDATE OR DELETE ON user_role_assignments
FOR EACH ROW EXECUTE FUNCTION record_entity_history('user_role_assignment');


-- Open record drafts stage metadata and binary content until the user commits
-- the complete record package. The equivalent upgrade is migration 004.
CREATE TABLE IF NOT EXISTS record_drafts (
    id bigserial PRIMARY KEY,
    owner_user_id bigint REFERENCES users (id) ON DELETE CASCADE,
    aggregation_id bigint REFERENCES aggregations (id) ON DELETE RESTRICT,
    record_number text,
    title text,
    description text,
    date_originated timestamptz,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL DEFAULT (CURRENT_TIMESTAMP + interval '7 days'),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE INDEX IF NOT EXISTS record_drafts_owner_user_id_idx ON record_drafts (owner_user_id);
CREATE INDEX IF NOT EXISTS record_drafts_expires_at_idx ON record_drafts (expires_at);

CREATE TABLE IF NOT EXISTS record_draft_components (
    id bigserial PRIMARY KEY,
    draft_id bigint NOT NULL REFERENCES record_drafts (id) ON DELETE CASCADE,
    component_order integer NOT NULL CHECK (component_order > 0),
    file_name text NOT NULL CHECK (btrim(file_name) <> ''),
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_originated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mime_type text NOT NULL,
    size_in_bytes bigint NOT NULL CHECK (size_in_bytes >= 0),
    checksum_algo text NOT NULL,
    checksum_value text NOT NULL,
    content_status text NOT NULL DEFAULT 'uploading'
        CHECK (content_status IN ('uploading', 'interrupted', 'finalizing', 'available', 'failed', 'cancelled', 'expired')),
    segment_count integer CHECK (segment_count IS NULL OR segment_count >= 0),
    upload_completed_at timestamptz,
    CONSTRAINT record_draft_components_draft_order_unique
        UNIQUE (draft_id, component_order) DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX IF NOT EXISTS record_draft_components_draft_id_idx ON record_draft_components (draft_id);

CREATE TABLE IF NOT EXISTS record_draft_component_blobs (
    id bigserial PRIMARY KEY,
    record_draft_component_id bigint NOT NULL
        REFERENCES record_draft_components (id) ON DELETE CASCADE,
    segment_no integer NOT NULL CHECK (segment_no >= 0),
    segment_size integer NOT NULL CHECK (segment_size > 0),
    segment_checksum_algo text,
    segment_checksum_value text,
    content bytea NOT NULL,
    date_stored timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (record_draft_component_id, segment_no),
    CHECK (segment_size = octet_length(content))
);
CREATE INDEX IF NOT EXISTS record_draft_component_blobs_component_order_idx
    ON record_draft_component_blobs (record_draft_component_id, segment_no);

CREATE OR REPLACE FUNCTION touch_record_draft() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.date_updated := CURRENT_TIMESTAMP;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS record_drafts_touch ON record_drafts;
CREATE TRIGGER record_drafts_touch BEFORE UPDATE ON record_drafts
FOR EACH ROW EXECUTE FUNCTION touch_record_draft();


-- Binary content storage and optimistic concurrency. The equivalent upgrade
-- for existing databases is migration 003.
ALTER TABLE aggregations ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;
ALTER TABLE records ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;
ALTER TABLE digital_components ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;
ALTER TABLE org_units ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;
ALTER TABLE roles ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;
ALTER TABLE user_role_assignments ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;

ALTER TABLE aggregations DROP CONSTRAINT IF EXISTS aggregations_version_positive;
ALTER TABLE aggregations ADD CONSTRAINT aggregations_version_positive CHECK (version > 0);
ALTER TABLE records DROP CONSTRAINT IF EXISTS records_version_positive;
ALTER TABLE records ADD CONSTRAINT records_version_positive CHECK (version > 0);
ALTER TABLE digital_components DROP CONSTRAINT IF EXISTS digital_components_version_positive;
ALTER TABLE digital_components ADD CONSTRAINT digital_components_version_positive CHECK (version > 0);
ALTER TABLE org_units DROP CONSTRAINT IF EXISTS org_units_version_positive;
ALTER TABLE org_units ADD CONSTRAINT org_units_version_positive CHECK (version > 0);
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_version_positive;
ALTER TABLE users ADD CONSTRAINT users_version_positive CHECK (version > 0);
ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_version_positive;
ALTER TABLE roles ADD CONSTRAINT roles_version_positive CHECK (version > 0);
ALTER TABLE user_role_assignments DROP CONSTRAINT IF EXISTS user_role_assignments_version_positive;
ALTER TABLE user_role_assignments ADD CONSTRAINT user_role_assignments_version_positive CHECK (version > 0);

ALTER TABLE digital_components
    ADD COLUMN IF NOT EXISTS storage_backend text NOT NULL DEFAULT 'postgresql',
    ADD COLUMN IF NOT EXISTS storage_key text,
    ADD COLUMN IF NOT EXISTS content_status text NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS active_content_set_id bigint,
    ADD COLUMN IF NOT EXISTS upload_completed_at timestamptz;

ALTER TABLE digital_components DROP CONSTRAINT IF EXISTS digital_components_storage_backend_valid;
ALTER TABLE digital_components ADD CONSTRAINT digital_components_storage_backend_valid
    CHECK (storage_backend IN ('postgresql', 's3'));
ALTER TABLE digital_components DROP CONSTRAINT IF EXISTS digital_components_content_status_valid;
ALTER TABLE digital_components ADD CONSTRAINT digital_components_content_status_valid
    CHECK (content_status IN ('pending', 'uploading', 'available', 'failed', 'quarantined', 'deleted'));
ALTER TABLE digital_components DROP CONSTRAINT IF EXISTS digital_components_storage_location_valid;
ALTER TABLE digital_components ADD CONSTRAINT digital_components_storage_location_valid
    CHECK (
        (storage_backend = 'postgresql' AND storage_key IS NULL)
        OR (storage_backend = 's3' AND storage_key IS NOT NULL AND btrim(storage_key) <> '')
    );

CREATE TABLE IF NOT EXISTS digital_component_content_sets (
    id bigserial PRIMARY KEY,
    digital_component_id bigint NOT NULL REFERENCES digital_components (id) ON DELETE CASCADE,
    status text NOT NULL CHECK (status IN ('staged', 'active', 'superseded', 'failed')),
    size_in_bytes bigint CHECK (size_in_bytes IS NULL OR size_in_bytes >= 0),
    segment_count integer CHECK (segment_count IS NULL OR segment_count >= 0),
    checksum_algo text,
    checksum_value text,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_completed timestamptz,
    UNIQUE (digital_component_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS digital_component_one_active_content_set_idx
    ON digital_component_content_sets (digital_component_id) WHERE status = 'active';

ALTER TABLE digital_components DROP CONSTRAINT IF EXISTS digital_components_active_content_set_fk;
ALTER TABLE digital_components ADD CONSTRAINT digital_components_active_content_set_fk
    FOREIGN KEY (id, active_content_set_id)
    REFERENCES digital_component_content_sets (digital_component_id, id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS digital_component_blobs (
    id bigserial PRIMARY KEY,
    content_set_id bigint NOT NULL REFERENCES digital_component_content_sets (id) ON DELETE CASCADE,
    segment_no integer NOT NULL CHECK (segment_no >= 0),
    segment_size integer NOT NULL CHECK (segment_size > 0),
    segment_checksum_algo text,
    segment_checksum_value text,
    content bytea NOT NULL,
    date_stored timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (content_set_id, segment_no),
    CHECK (segment_size = octet_length(content))
);
CREATE INDEX IF NOT EXISTS digital_component_blobs_content_set_order_idx
    ON digital_component_blobs (content_set_id, segment_no);

CREATE TABLE IF NOT EXISTS content_upload_sessions (
    id bigserial PRIMARY KEY,
    digital_component_id bigint REFERENCES digital_components (id) ON DELETE CASCADE,
    draft_component_id bigint REFERENCES record_draft_components (id) ON DELETE CASCADE,
    content_set_id bigint REFERENCES digital_component_content_sets (id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'uploading'
        CHECK (status IN ('uploading', 'interrupted', 'finalizing', 'completed', 'failed', 'cancelled', 'expired')),
    next_segment_no integer NOT NULL DEFAULT 0 CHECK (next_segment_no >= 0),
    bytes_received bigint NOT NULL DEFAULT 0 CHECK (bytes_received >= 0),
    expected_size bigint CHECK (expected_size IS NULL OR expected_size >= 0),
    checksum_algo text NOT NULL DEFAULT 'sha256',
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL DEFAULT (CURRENT_TIMESTAMP + interval '1 day'),
    CHECK (((digital_component_id IS NOT NULL)::integer + (draft_component_id IS NOT NULL)::integer) = 1),
    CHECK ((digital_component_id IS NOT NULL AND content_set_id IS NOT NULL)
        OR (draft_component_id IS NOT NULL AND content_set_id IS NULL))
);
CREATE INDEX IF NOT EXISTS content_upload_sessions_cleanup_idx
    ON content_upload_sessions (status, expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS content_upload_sessions_open_component_idx
    ON content_upload_sessions (digital_component_id)
    WHERE status IN ('uploading', 'interrupted', 'finalizing');
CREATE UNIQUE INDEX IF NOT EXISTS content_upload_sessions_open_draft_component_idx
    ON content_upload_sessions (draft_component_id)
    WHERE status IN ('uploading', 'interrupted', 'finalizing');

CREATE OR REPLACE FUNCTION bump_entity_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS aggregations_bump_version ON aggregations;
CREATE TRIGGER aggregations_bump_version
BEFORE UPDATE ON aggregations
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

DROP TRIGGER IF EXISTS records_bump_version ON records;
CREATE TRIGGER records_bump_version
BEFORE UPDATE ON records
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

DROP TRIGGER IF EXISTS digital_components_bump_version ON digital_components;
CREATE OR REPLACE FUNCTION bump_digital_component_version()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['active_content_set_id', 'upload_completed_at'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['active_content_set_id', 'upload_completed_at']) THEN
        NEW.version := OLD.version + 1;
    ELSE
        NEW.version := OLD.version;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER digital_components_bump_version
BEFORE UPDATE ON digital_components
FOR EACH ROW EXECUTE FUNCTION bump_digital_component_version();

DROP TRIGGER IF EXISTS org_units_bump_version ON org_units;
CREATE TRIGGER org_units_bump_version
BEFORE UPDATE ON org_units
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

DROP TRIGGER IF EXISTS users_bump_version ON users;
CREATE TRIGGER users_bump_version
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

DROP TRIGGER IF EXISTS roles_bump_version ON roles;
CREATE TRIGGER roles_bump_version
BEFORE UPDATE ON roles
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

DROP TRIGGER IF EXISTS user_role_assignments_bump_version ON user_role_assignments;
CREATE TRIGGER user_role_assignments_bump_version
BEFORE UPDATE ON user_role_assignments
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

CREATE OR REPLACE FUNCTION remove_internal_audit_fields()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.changed_fields := array_remove(NEW.changed_fields, 'version');
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS event_history_remove_internal_fields ON event_history;
CREATE TRIGGER event_history_remove_internal_fields
BEFORE INSERT ON event_history
FOR EACH ROW EXECUTE FUNCTION remove_internal_audit_fields();

CREATE OR REPLACE FUNCTION append_domain_event(
    event_entity_type text,
    event_entity_id bigint,
    event_operation text,
    event_metadata jsonb DEFAULT '{}'::jsonb,
    event_reason text DEFAULT NULL
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    event_id         bigint;
    context_user_id text;
BEGIN
    IF btrim(event_entity_type) = '' OR btrim(event_operation) = '' THEN
        RAISE EXCEPTION 'domain event entity type and operation cannot be blank';
    END IF;
    IF jsonb_typeof(event_metadata) <> 'object' THEN
        RAISE EXCEPTION 'domain event metadata must be a JSON object';
    END IF;

    context_user_id := NULLIF(current_setting('app.user_id', true), '');
    INSERT INTO event_history (
        entity_type,
        entity_id,
        operation,
        actor_user_id,
        actor_type,
        source,
        request_id,
        correlation_id,
        reason,
        metadata
    )
    VALUES (
        event_entity_type,
        event_entity_id,
        event_operation,
        context_user_id::bigint,
        COALESCE(NULLIF(current_setting('app.actor_type', true), ''), 'automated_process'),
        COALESCE(NULLIF(current_setting('app.event_source', true), ''), 'database'),
        NULLIF(current_setting('app.request_id', true), '')::uuid,
        NULLIF(current_setting('app.correlation_id', true), '')::uuid,
        COALESCE(event_reason, NULLIF(current_setting('app.change_reason', true), '')),
        event_metadata
    )
    RETURNING id INTO event_id;
    RETURN event_id;
END;
$$;



-- Enforce inherited aggregation closure across records, components and blobs.
CREATE OR REPLACE FUNCTION assert_aggregation_effectively_open(p_aggregation_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    blocker record;
BEGIN
    IF p_aggregation_id IS NULL THEN
        RETURN;
    END IF;

    -- Lock every ancestor in a stable order. Closing or reparenting an ancestor
    -- must wait for in-flight content changes, and vice versa.
    PERFORM 1
    FROM aggregations AS locked
    WHERE locked.id IN (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_aggregation_id
            FROM aggregations
            WHERE id = p_aggregation_id
            UNION ALL
            SELECT parent.id, parent.parent_aggregation_id
            FROM aggregations AS parent
            JOIN ancestors ON parent.id = ancestors.parent_aggregation_id
        )
        SELECT id FROM ancestors
    )
    ORDER BY locked.id
    FOR SHARE;

    WITH RECURSIVE ancestors AS (
        SELECT id, parent_aggregation_id, aggregation_number, title, date_closed, 0 AS depth
        FROM aggregations
        WHERE id = p_aggregation_id
        UNION ALL
        SELECT parent.id, parent.parent_aggregation_id, parent.aggregation_number,
               parent.title, parent.date_closed, child.depth + 1
        FROM aggregations AS parent
        JOIN ancestors AS child ON parent.id = child.parent_aggregation_id
    )
    SELECT id, aggregation_number, title, date_closed
    INTO blocker
    FROM ancestors
    WHERE date_closed IS NOT NULL
    ORDER BY depth
    LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = format(
                'aggregation %s (%s) is closed by aggregation %s (%s); records and digital content in this subtree are immutable',
                p_aggregation_id,
                (SELECT aggregation_number FROM aggregations WHERE id = p_aggregation_id),
                blocker.id,
                blocker.aggregation_number
            );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION validate_aggregation_closure_date()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.date_closed IS NOT NULL AND NEW.date_closed > CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'date_closed cannot be in the future';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_closed_aggregation_hierarchy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.parent_aggregation_id IS NOT NULL THEN
            PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id);
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM assert_aggregation_effectively_open(OLD.id);
        RETURN OLD;
    END IF;

    IF NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id THEN
        PERFORM assert_aggregation_effectively_open(OLD.id);
        IF NEW.parent_aggregation_id IS NOT NULL THEN
            PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id);
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_record_in_closed_aggregation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM assert_aggregation_effectively_open(NEW.aggregation_id);
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM assert_aggregation_effectively_open(OLD.aggregation_id);
        RETURN OLD;
    END IF;

    PERFORM assert_aggregation_effectively_open(OLD.aggregation_id);
    IF NEW.aggregation_id IS DISTINCT FROM OLD.aggregation_id THEN
        PERFORM assert_aggregation_effectively_open(NEW.aggregation_id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION assert_record_effectively_open(p_record_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    aggregation_key bigint;
BEGIN
    SELECT aggregation_id
    INTO aggregation_key
    FROM records
    WHERE id = p_record_id
    FOR SHARE;

    IF aggregation_key IS NOT NULL THEN
        PERFORM assert_aggregation_effectively_open(aggregation_key);
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION protect_component_in_closed_aggregation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM assert_record_effectively_open(NEW.record_id);
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM assert_record_effectively_open(OLD.record_id);
        RETURN OLD;
    END IF;

    PERFORM assert_record_effectively_open(OLD.record_id);
    IF NEW.record_id IS DISTINCT FROM OLD.record_id THEN
        PERFORM assert_record_effectively_open(NEW.record_id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_blob_in_closed_aggregation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_content_set_id bigint;
BEGIN
    target_content_set_id := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.content_set_id ELSE NEW.content_set_id END;
    PERFORM assert_record_effectively_open(
        (SELECT dc.record_id
           FROM digital_component_content_sets content_set
           JOIN digital_components dc ON dc.id = content_set.digital_component_id
          WHERE content_set.id = target_content_set_id)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE OR REPLACE FUNCTION protect_content_set_in_closed_aggregation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target_component_id bigint;
BEGIN
    target_component_id := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
    PERFORM assert_record_effectively_open(
        (SELECT record_id FROM digital_components WHERE id = target_component_id)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS aggregations_validate_closure_date ON aggregations;
CREATE TRIGGER aggregations_validate_closure_date
BEFORE INSERT OR UPDATE OF date_closed ON aggregations
FOR EACH ROW EXECUTE FUNCTION validate_aggregation_closure_date();

DROP TRIGGER IF EXISTS aggregations_protect_closed_hierarchy ON aggregations;
CREATE TRIGGER aggregations_protect_closed_hierarchy
BEFORE INSERT OR UPDATE OF parent_aggregation_id OR DELETE ON aggregations
FOR EACH ROW EXECUTE FUNCTION protect_closed_aggregation_hierarchy();

DROP TRIGGER IF EXISTS records_protect_closed_aggregation ON records;
CREATE TRIGGER records_protect_closed_aggregation
BEFORE INSERT OR UPDATE OR DELETE ON records
FOR EACH ROW EXECUTE FUNCTION protect_record_in_closed_aggregation();

DROP TRIGGER IF EXISTS digital_components_protect_closed_aggregation ON digital_components;
CREATE TRIGGER digital_components_protect_closed_aggregation
BEFORE INSERT OR UPDATE OR DELETE ON digital_components
FOR EACH ROW EXECUTE FUNCTION protect_component_in_closed_aggregation();

DROP TRIGGER IF EXISTS digital_component_blobs_protect_closed_aggregation ON digital_component_blobs;
CREATE TRIGGER digital_component_blobs_protect_closed_aggregation
BEFORE INSERT OR UPDATE OR DELETE ON digital_component_blobs
FOR EACH ROW EXECUTE FUNCTION protect_blob_in_closed_aggregation();

DROP TRIGGER IF EXISTS digital_component_content_sets_protect_closed_aggregation ON digital_component_content_sets;
CREATE TRIGGER digital_component_content_sets_protect_closed_aggregation
BEFORE INSERT OR UPDATE OR DELETE ON digital_component_content_sets
FOR EACH ROW EXECUTE FUNCTION protect_content_set_in_closed_aggregation();


-- Freeze aggregation metadata while allowing an explicit direct reopen.
CREATE OR REPLACE FUNCTION protect_closed_aggregation_hierarchy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    closure_source_id bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.parent_aggregation_id IS NOT NULL THEN
            PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id);
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM assert_aggregation_effectively_open(OLD.id);
        RETURN OLD;
    END IF;

    PERFORM 1
    FROM aggregations AS locked
    WHERE locked.id IN (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_aggregation_id FROM aggregations WHERE id = OLD.id
            UNION ALL
            SELECT parent.id, parent.parent_aggregation_id
            FROM aggregations AS parent
            JOIN ancestors ON parent.id = ancestors.parent_aggregation_id
        )
        SELECT id FROM ancestors
    )
    ORDER BY locked.id
    FOR SHARE;

    WITH RECURSIVE ancestors AS (
        SELECT id, parent_aggregation_id, date_closed, 0 AS depth
        FROM aggregations WHERE id = OLD.id
        UNION ALL
        SELECT parent.id, parent.parent_aggregation_id, parent.date_closed, child.depth + 1
        FROM aggregations AS parent
        JOIN ancestors AS child ON parent.id = child.parent_aggregation_id
    )
    SELECT id INTO closure_source_id
    FROM ancestors WHERE date_closed IS NOT NULL
    ORDER BY depth LIMIT 1;

    IF closure_source_id IS NOT NULL THEN
        IF closure_source_id = OLD.id
           AND OLD.date_closed IS NOT NULL AND NEW.date_closed IS NULL
           AND NEW.parent_aggregation_id IS NOT DISTINCT FROM OLD.parent_aggregation_id
           AND NEW.aggregation_number IS NOT DISTINCT FROM OLD.aggregation_number
           AND NEW.title IS NOT DISTINCT FROM OLD.title
           AND NEW.description IS NOT DISTINCT FROM OLD.description
           AND NEW.date_created IS NOT DISTINCT FROM OLD.date_created
           AND NEW.date_opened IS NOT DISTINCT FROM OLD.date_opened THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = format(
            'aggregation %s is closed by aggregation %s; closed aggregation metadata is immutable and only a direct closure may be cleared',
            OLD.id, closure_source_id
        );
    END IF;

    IF NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id
       AND NEW.parent_aggregation_id IS NOT NULL THEN
        PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS aggregations_protect_closed_hierarchy ON aggregations;
CREATE TRIGGER aggregations_protect_closed_hierarchy
BEFORE INSERT OR UPDATE OR DELETE ON aggregations
FOR EACH ROW EXECUTE FUNCTION protect_closed_aggregation_hierarchy();




-- Enforce user-management lifecycle semantics and inherited organization activity.
CREATE TABLE IF NOT EXISTS schema_migrations (
    id bigserial PRIMARY KEY,
    version text NOT NULL UNIQUE,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT schema_migrations_version_not_blank CHECK (btrim(version) <> '')
);

CREATE OR REPLACE FUNCTION org_unit_effectively_active(p_org_unit_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id, parent_org_unit_id, date_deactivated FROM org_units WHERE id = p_org_unit_id
        UNION ALL
        SELECT parent.id, parent.parent_org_unit_id, parent.date_deactivated
        FROM org_units parent JOIN ancestors child ON parent.id = child.parent_org_unit_id
    )
    SELECT COALESCE(bool_and(date_deactivated IS NULL), false) FROM ancestors;
$$;

CREATE OR REPLACE FUNCTION role_effectively_active(p_role_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT COALESCE(r.date_deactivated IS NULL AND org_unit_effectively_active(r.org_unit_id), false)
    FROM roles r WHERE r.id = p_role_id;
$$;

CREATE OR REPLACE FUNCTION validate_user_management_lifecycle_dates()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated > clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE=TG_TABLE_NAME || ' deactivation date cannot be in the future';
    END IF;
    IF TG_TABLE_NAME = 'users'
       AND NULLIF(to_jsonb(NEW)->>'date_suspended', '')::timestamptz > clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='user suspension date cannot be in the future';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION validate_active_role_assignment()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM users
        WHERE id=NEW.user_id
          AND date_deactivated IS NULL
          AND date_suspended IS NULL
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role assignments require an active user';
    END IF;
    IF NOT role_effectively_active(NEW.role_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role assignments require an effectively active role and organization hierarchy';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS org_units_normalize_lifecycle ON org_units;
CREATE TRIGGER org_units_validate_lifecycle_dates
BEFORE INSERT OR UPDATE OF date_deactivated ON org_units
FOR EACH ROW EXECUTE FUNCTION validate_user_management_lifecycle_dates();

DROP TRIGGER IF EXISTS users_normalize_lifecycle ON users;
CREATE TRIGGER users_validate_lifecycle_dates
BEFORE INSERT OR UPDATE OF date_deactivated, date_suspended ON users
FOR EACH ROW EXECUTE FUNCTION validate_user_management_lifecycle_dates();

DROP TRIGGER IF EXISTS roles_normalize_lifecycle ON roles;
CREATE TRIGGER roles_validate_lifecycle_dates
BEFORE INSERT OR UPDATE OF date_deactivated ON roles
FOR EACH ROW EXECUTE FUNCTION validate_user_management_lifecycle_dates();

DROP TRIGGER IF EXISTS user_role_assignments_validate_active ON user_role_assignments;
CREATE TRIGGER user_role_assignments_validate_active
BEFORE INSERT OR UPDATE OF user_id, role_id ON user_role_assignments
FOR EACH ROW EXECUTE FUNCTION validate_active_role_assignment();

CREATE TABLE classification_schemes (
    id               bigserial PRIMARY KEY,
    code             text NOT NULL,
    title            text NOT NULL,
    description      text,
    authority        text,
    scope_note       text,
    edition          text,
    date_created     timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated     timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_published   timestamptz,
    date_deactivated timestamptz,
    date_first_used  timestamptz,
    version          bigint NOT NULL DEFAULT 1,
    CONSTRAINT classification_schemes_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT classification_schemes_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT classification_schemes_dates_in_order CHECK (
        date_deactivated IS NULL OR date_deactivated >= date_created
    ),
    CONSTRAINT classification_schemes_first_use_in_order CHECK (
        date_first_used IS NULL OR date_first_used >= date_created
    ),
    CONSTRAINT classification_schemes_version_positive CHECK (version > 0)
);
CREATE UNIQUE INDEX classification_schemes_code_ci_unique
    ON classification_schemes (lower(code));

CREATE TABLE classifications (
    id                       bigserial PRIMARY KEY,
    classification_scheme_id bigint NOT NULL
        REFERENCES classification_schemes(id) ON DELETE RESTRICT,
    parent_classification_id bigint REFERENCES classifications(id) ON DELETE RESTRICT,
    code                     text NOT NULL,
    title                    text NOT NULL,
    description              text,
    authority                text,
    scope_note               text,
    keywords                 text,
    is_terminal              boolean NOT NULL DEFAULT false,
    date_created             timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated             timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_deactivated         timestamptz,
    date_first_used          timestamptz,
    version                  bigint NOT NULL DEFAULT 1,
    CONSTRAINT classifications_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT classifications_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT classifications_not_own_parent CHECK (
        parent_classification_id IS NULL OR parent_classification_id <> id
    ),
    CONSTRAINT classifications_dates_in_order CHECK (
        date_deactivated IS NULL OR date_deactivated >= date_created
    ),
    CONSTRAINT classifications_first_use_in_order CHECK (
        date_first_used IS NULL OR date_first_used >= date_created
    ),
    CONSTRAINT classifications_version_positive CHECK (version > 0)
);
CREATE UNIQUE INDEX classifications_scheme_code_ci_unique
    ON classifications (classification_scheme_id, lower(code));
CREATE INDEX classifications_scheme_parent_idx
    ON classifications (classification_scheme_id, parent_classification_id);
CREATE INDEX classifications_parent_code_browse_idx
    ON classifications (classification_scheme_id, parent_classification_id, code COLLATE "C", id);

CREATE TABLE classification_retention_rules (
    id                        bigserial PRIMARY KEY,
    classification_id         bigint NOT NULL UNIQUE
        REFERENCES classifications(id) ON DELETE CASCADE,
    current_period_years       integer NOT NULL CHECK (current_period_years >= 0),
    intermediate_period_years  integer NOT NULL CHECK (intermediate_period_years >= 0),
    final_disposition          text NOT NULL CHECK (final_disposition IN (
        'destruction', 'transfer_to_external_archive',
        'selective_preservation', 'retain_as_local_archives'
    )),
    instructions               text,
    date_created               timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated               timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version                    bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);

ALTER TABLE aggregations
    ADD COLUMN classification_id bigint
        REFERENCES classifications(id) ON DELETE RESTRICT;
CREATE INDEX aggregations_classification_id_idx
    ON aggregations (classification_id);
CREATE INDEX aggregations_classification_number_browse_idx
    ON aggregations (classification_id, aggregation_number COLLATE "C", id);
ALTER TABLE aggregations
    ADD CONSTRAINT aggregations_root_classification_consistent
    CHECK (
        (parent_aggregation_id IS NULL AND classification_id IS NOT NULL)
        OR
        (parent_aggregation_id IS NOT NULL AND classification_id IS NULL)
    );

CREATE TABLE aggregation_retention_rules (
    id                        bigserial PRIMARY KEY,
    aggregation_id            bigint NOT NULL UNIQUE
        REFERENCES aggregations(id) ON DELETE CASCADE,
    current_period_years       integer NOT NULL CHECK (current_period_years >= 0),
    intermediate_period_years  integer NOT NULL CHECK (intermediate_period_years >= 0),
    final_disposition          text NOT NULL CHECK (final_disposition IN (
        'destruction', 'transfer_to_external_archive',
        'selective_preservation', 'retain_as_local_archives'
    )),
    instructions               text,
    justification              text NOT NULL CHECK (btrim(justification) <> ''),
    date_created               timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated               timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version                    bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);

CREATE TABLE user_classification_selections (
    user_id           bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    classification_id bigint NOT NULL REFERENCES classifications(id) ON DELETE CASCADE,
    last_selected_at  timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    selection_count   bigint NOT NULL DEFAULT 1 CHECK (selection_count > 0),
    PRIMARY KEY (user_id, classification_id)
);
CREATE INDEX user_classification_selections_recent_idx
    ON user_classification_selections (user_id, last_selected_at DESC);

CREATE OR REPLACE FUNCTION touch_classification_date_updated()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.date_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION validate_classification_scheme_dates()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated > CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'classification scheme date_deactivated cannot be in the future';
    END IF;
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated < NEW.date_created THEN
        RAISE EXCEPTION 'classification scheme date_deactivated cannot precede date_created';
    END IF;
    IF TG_OP = 'UPDATE'
       AND OLD.date_first_used IS NOT NULL
       AND NEW.date_first_used IS DISTINCT FROM OLD.date_first_used THEN
        RAISE EXCEPTION 'classification scheme date_first_used is immutable once set';
    END IF;
    IF TG_OP = 'UPDATE'
       AND OLD.date_published IS NOT NULL
       AND NEW.date_published IS NULL THEN
        IF OLD.date_first_used IS NOT NULL THEN
            RAISE EXCEPTION 'a classification scheme that has governed an aggregation cannot be unpublished';
        END IF;
        IF NULLIF(current_setting('app.change_reason', true), '') IS NULL THEN
            RAISE EXCEPTION 'unpublishing a classification scheme requires a change reason';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION classification_scheme_is_eligible(p_scheme_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT COALESCE(
        date_deactivated IS NULL
        AND date_published IS NOT NULL
        AND date_published <= CURRENT_TIMESTAMP,
        false
    )
    FROM classification_schemes
    WHERE id = p_scheme_id;
$$;

CREATE OR REPLACE FUNCTION classification_is_effectively_active(p_classification_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    WITH RECURSIVE lineage AS (
        SELECT id, parent_classification_id, date_deactivated
        FROM classifications WHERE id = p_classification_id
        UNION ALL
        SELECT parent.id, parent.parent_classification_id, parent.date_deactivated
        FROM classifications AS parent
        JOIN lineage AS child ON parent.id = child.parent_classification_id
    )
    SELECT EXISTS (SELECT 1 FROM lineage)
       AND NOT EXISTS (SELECT 1 FROM lineage WHERE date_deactivated IS NOT NULL);
$$;

CREATE OR REPLACE FUNCTION validate_classification_dates()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated > CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'classification date_deactivated cannot be in the future';
    END IF;
    IF NEW.date_deactivated IS NOT NULL AND NEW.date_deactivated < NEW.date_created THEN
        RAISE EXCEPTION 'classification date_deactivated cannot precede date_created';
    END IF;
    IF TG_OP = 'UPDATE'
       AND OLD.date_first_used IS NOT NULL
       AND NEW.date_first_used IS DISTINCT FROM OLD.date_first_used THEN
        RAISE EXCEPTION 'classification date_first_used is immutable once set';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION record_classification_governance_first_use()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    scheme_id bigint;
    used_at timestamptz := CURRENT_TIMESTAMP;
BEGIN
    IF NEW.classification_id IS NULL
       OR (TG_OP = 'UPDATE' AND NEW.classification_id IS NOT DISTINCT FROM OLD.classification_id) THEN
        RETURN NEW;
    END IF;

    SELECT classification_scheme_id INTO scheme_id
    FROM classifications
    WHERE id = NEW.classification_id;

    WITH RECURSIVE lineage AS (
        SELECT id, parent_classification_id
        FROM classifications WHERE id = NEW.classification_id
        UNION ALL
        SELECT parent.id, parent.parent_classification_id
        FROM classifications AS parent
        JOIN lineage AS child ON parent.id = child.parent_classification_id
    )
    UPDATE classifications
    SET date_first_used = used_at
    WHERE id IN (SELECT id FROM lineage) AND date_first_used IS NULL;

    UPDATE classification_schemes
    SET date_first_used = used_at
    WHERE id = scheme_id AND date_first_used IS NULL;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_classification_deletion()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    scheme_row classification_schemes%ROWTYPE;
BEGIN
    SELECT * INTO scheme_row FROM classification_schemes WHERE id = OLD.classification_scheme_id;
    IF scheme_row.date_deactivated IS NOT NULL THEN
        RAISE EXCEPTION 'classifications cannot be deleted while their scheme is deactivated';
    END IF;
    IF scheme_row.date_published IS NOT NULL THEN
        RAISE EXCEPTION 'classification scheme must be unpublished before deleting classifications';
    END IF;
    IF OLD.date_first_used IS NOT NULL THEN
        RAISE EXCEPTION 'a classification that has governed an aggregation cannot be deleted; deactivate it instead';
    END IF;
    IF EXISTS (SELECT 1 FROM classifications WHERE parent_classification_id = OLD.id) THEN
        RAISE EXCEPTION 'classification has children; delete its child classifications first';
    END IF;
    IF EXISTS (SELECT 1 FROM aggregations WHERE classification_id = OLD.id) THEN
        RAISE EXCEPTION 'classification is assigned to an aggregation and cannot be deleted';
    END IF;
    IF NULLIF(current_setting('app.change_reason', true), '') IS NULL THEN
        RAISE EXCEPTION 'deleting a classification requires a change reason';
    END IF;
    RETURN OLD;
END;
$$;

CREATE OR REPLACE FUNCTION delete_unused_classification_scheme()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    deleted_count integer;
BEGIN
    IF OLD.date_published IS NOT NULL THEN
        RAISE EXCEPTION 'published classification schemes must be unpublished before deletion';
    END IF;
    IF OLD.date_first_used IS NOT NULL THEN
        RAISE EXCEPTION 'a classification scheme that has governed an aggregation cannot be deleted';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM aggregations AS a
        JOIN classifications AS c ON c.id = a.classification_id
        WHERE c.classification_scheme_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'classification scheme has classifications assigned to aggregations';
    END IF;

    LOOP
        DELETE FROM classifications AS candidate
        WHERE candidate.classification_scheme_id = OLD.id
          AND NOT EXISTS (
              SELECT 1 FROM classifications AS child
              WHERE child.parent_classification_id = candidate.id
          );
        GET DIAGNOSTICS deleted_count = ROW_COUNT;
        EXIT WHEN deleted_count = 0;
    END LOOP;

    IF EXISTS (SELECT 1 FROM classifications WHERE classification_scheme_id = OLD.id) THEN
        RAISE EXCEPTION 'classification scheme hierarchy could not be deleted safely';
    END IF;
    RETURN OLD;
END;
$$;

CREATE OR REPLACE FUNCTION validate_classification_structure()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_scheme bigint;
    parent_terminal boolean;
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.classification_scheme_id IS DISTINCT FROM OLD.classification_scheme_id THEN
        RAISE EXCEPTION 'a classification cannot be moved to another scheme';
    END IF;

    IF NEW.parent_classification_id IS NOT NULL THEN
        SELECT classification_scheme_id, is_terminal
        INTO parent_scheme, parent_terminal
        FROM classifications
        WHERE id = NEW.parent_classification_id;
        IF parent_scheme IS NULL THEN
            RAISE EXCEPTION 'parent classification does not exist';
        END IF;
        IF parent_scheme <> NEW.classification_scheme_id THEN
            RAISE EXCEPTION 'parent classification must belong to the same scheme';
        END IF;
        IF parent_terminal THEN
            RAISE EXCEPTION 'terminal classifications cannot contain child classifications';
        END IF;
        IF EXISTS (
            WITH RECURSIVE descendants AS (
                SELECT id FROM classifications WHERE parent_classification_id = NEW.id
                UNION ALL
                SELECT child.id
                FROM classifications AS child
                JOIN descendants AS parent ON child.parent_classification_id = parent.id
            )
            SELECT 1 FROM descendants WHERE id = NEW.parent_classification_id
        ) THEN
            RAISE EXCEPTION 'classification hierarchy cannot contain a cycle';
        END IF;
    END IF;

    IF NEW.is_terminal AND EXISTS (
        SELECT 1 FROM classifications WHERE parent_classification_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'a classification with children cannot be terminal';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.is_terminal AND NOT NEW.is_terminal
       AND EXISTS (SELECT 1 FROM aggregations WHERE classification_id = NEW.id) THEN
        RAISE EXCEPTION 'an assigned terminal classification cannot become a branch';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION effective_classification_retention_rule(p_classification_id bigint)
RETURNS TABLE (
    rule_id bigint,
    defined_by_classification_id bigint,
    inheritance_depth integer,
    current_period_years integer,
    intermediate_period_years integer,
    final_disposition text,
    instructions text
)
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE ancestors AS (
        SELECT c.id, c.parent_classification_id, 0 AS depth
        FROM classifications AS c
        WHERE c.id = p_classification_id
        UNION ALL
        SELECT parent.id, parent.parent_classification_id, child.depth + 1
        FROM classifications AS parent
        JOIN ancestors AS child ON parent.id = child.parent_classification_id
    )
    SELECT rule.id, rule.classification_id, ancestors.depth,
           rule.current_period_years, rule.intermediate_period_years,
           rule.final_disposition, rule.instructions
    FROM ancestors
    JOIN classification_retention_rules AS rule
      ON rule.classification_id = ancestors.id
    ORDER BY ancestors.depth
    LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION validate_terminal_classification_rules()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE missing_code text;
BEGIN
    SELECT c.code INTO missing_code
    FROM classifications AS c
    WHERE c.is_terminal
      AND NOT EXISTS (
          SELECT 1 FROM effective_classification_retention_rule(c.id)
      )
    ORDER BY c.id LIMIT 1;
    IF missing_code IS NOT NULL THEN
        RAISE EXCEPTION 'terminal classification % has no effective retention rule', missing_code;
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION validate_aggregation_classification()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    classification_terminal boolean;
    scheme_id bigint;
BEGIN
    IF NEW.parent_aggregation_id IS NULL THEN
        IF NEW.classification_id IS NULL THEN
            RAISE EXCEPTION 'root aggregations must have a classification';
        END IF;
        SELECT is_terminal, classification_scheme_id
        INTO classification_terminal, scheme_id
        FROM classifications WHERE id = NEW.classification_id;
        IF NOT COALESCE(classification_terminal, false) THEN
            RAISE EXCEPTION 'root aggregations must use a terminal classification';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM effective_classification_retention_rule(NEW.classification_id)
        ) THEN
            RAISE EXCEPTION 'selected classification has no effective retention rule';
        END IF;
        IF TG_OP = 'INSERT'
           OR NEW.classification_id IS DISTINCT FROM OLD.classification_id
           OR NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id THEN
            IF NOT classification_scheme_is_eligible(scheme_id) THEN
                RAISE EXCEPTION 'selected classification scheme is not active and published';
            END IF;
            IF NOT classification_is_effectively_active(NEW.classification_id) THEN
                RAISE EXCEPTION 'selected classification or one of its ancestors is deactivated';
            END IF;
        END IF;
    ELSIF NEW.classification_id IS NOT NULL THEN
        RAISE EXCEPTION 'child aggregations cannot have a classification';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION validate_root_aggregation_retention_rules()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE invalid_number text;
BEGIN
    SELECT a.aggregation_number INTO invalid_number
    FROM aggregation_retention_rules AS rule
    JOIN aggregations AS a ON a.id = rule.aggregation_id
    WHERE a.parent_aggregation_id IS NOT NULL
    ORDER BY a.id LIMIT 1;
    IF invalid_number IS NOT NULL THEN
        RAISE EXCEPTION 'child aggregation % cannot have a local retention rule', invalid_number;
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION aggregation_effective_retention_rule(p_aggregation_id bigint)
RETURNS TABLE (
    governing_root_aggregation_id bigint,
    classification_id bigint,
    rule_source text,
    rule_id bigint,
    defined_by_classification_id bigint,
    inheritance_depth integer,
    current_period_years integer,
    intermediate_period_years integer,
    final_disposition text,
    instructions text,
    justification text
)
LANGUAGE plpgsql STABLE AS $$
DECLARE root_row record;
BEGIN
    WITH RECURSIVE lineage AS (
        SELECT a.*, 0 AS depth FROM aggregations AS a WHERE a.id = p_aggregation_id
        UNION ALL
        SELECT parent.*, child.depth + 1
        FROM aggregations AS parent
        JOIN lineage AS child ON parent.id = child.parent_aggregation_id
    )
    SELECT lineage.*
    INTO root_row
    FROM lineage WHERE lineage.parent_aggregation_id IS NULL LIMIT 1;

    IF root_row.id IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM aggregation_retention_rules WHERE aggregation_id = root_row.id
    ) THEN
        RETURN QUERY
        SELECT root_row.id, root_row.classification_id, 'aggregation'::text,
               r.id, NULL::bigint, 0,
               r.current_period_years, r.intermediate_period_years,
               r.final_disposition, r.instructions, r.justification
        FROM aggregation_retention_rules AS r
        WHERE r.aggregation_id = root_row.id;
        RETURN;
    END IF;
    RETURN QUERY
    SELECT root_row.id, root_row.classification_id, 'classification'::text,
           r.rule_id, r.defined_by_classification_id, r.inheritance_depth,
           r.current_period_years, r.intermediate_period_years,
           r.final_disposition, r.instructions, NULL::text
    FROM effective_classification_retention_rule(root_row.classification_id) AS r;
END;
$$;

CREATE OR REPLACE FUNCTION record_classification_selection()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE context_user_id text;
BEGIN
    context_user_id := NULLIF(current_setting('app.user_id', true), '');
    IF context_user_id IS NOT NULL
       AND NEW.parent_aggregation_id IS NULL
       AND NEW.classification_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.classification_id IS DISTINCT FROM OLD.classification_id) THEN
        INSERT INTO user_classification_selections (
            user_id, classification_id, last_selected_at, selection_count
        ) VALUES (context_user_id::bigint, NEW.classification_id, CURRENT_TIMESTAMP, 1)
        ON CONFLICT (user_id, classification_id) DO UPDATE
        SET last_selected_at = EXCLUDED.last_selected_at,
            selection_count = user_classification_selections.selection_count + 1;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER classification_schemes_validate_dates
BEFORE INSERT OR UPDATE OF date_created, date_published, date_deactivated, date_first_used
ON classification_schemes
FOR EACH ROW EXECUTE FUNCTION validate_classification_scheme_dates();
CREATE TRIGGER classification_schemes_touch
BEFORE UPDATE ON classification_schemes
FOR EACH ROW EXECUTE FUNCTION touch_classification_date_updated();
CREATE TRIGGER classifications_touch
BEFORE UPDATE ON classifications
FOR EACH ROW EXECUTE FUNCTION touch_classification_date_updated();
CREATE TRIGGER classifications_validate_dates
BEFORE INSERT OR UPDATE OF date_created, date_deactivated, date_first_used ON classifications
FOR EACH ROW EXECUTE FUNCTION validate_classification_dates();
CREATE TRIGGER classification_retention_rules_touch
BEFORE UPDATE ON classification_retention_rules
FOR EACH ROW EXECUTE FUNCTION touch_classification_date_updated();
CREATE TRIGGER aggregation_retention_rules_touch
BEFORE UPDATE ON aggregation_retention_rules
FOR EACH ROW EXECUTE FUNCTION touch_classification_date_updated();

CREATE TRIGGER classifications_validate_structure
BEFORE INSERT OR UPDATE OF classification_scheme_id, parent_classification_id, is_terminal
ON classifications FOR EACH ROW EXECUTE FUNCTION validate_classification_structure();

CREATE CONSTRAINT TRIGGER classifications_validate_effective_rule
AFTER INSERT OR UPDATE ON classifications
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_terminal_classification_rules();
CREATE CONSTRAINT TRIGGER classification_rules_validate_effective_rule
AFTER INSERT OR UPDATE OR DELETE ON classification_retention_rules
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_terminal_classification_rules();

CREATE TRIGGER aggregations_validate_classification
BEFORE INSERT OR UPDATE OF parent_aggregation_id, classification_id ON aggregations
FOR EACH ROW EXECUTE FUNCTION validate_aggregation_classification();
CREATE CONSTRAINT TRIGGER aggregation_rules_validate_root
AFTER INSERT OR UPDATE ON aggregation_retention_rules
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_root_aggregation_retention_rules();
CREATE CONSTRAINT TRIGGER aggregations_validate_local_rule_root
AFTER UPDATE ON aggregations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_root_aggregation_retention_rules();
CREATE TRIGGER aggregations_record_classification_selection
AFTER INSERT OR UPDATE OF classification_id ON aggregations
FOR EACH ROW EXECUTE FUNCTION record_classification_selection();
CREATE TRIGGER aggregations_record_classification_governance_first_use
AFTER INSERT OR UPDATE OF classification_id ON aggregations
FOR EACH ROW EXECUTE FUNCTION record_classification_governance_first_use();

CREATE TRIGGER classification_schemes_delete_unused
BEFORE DELETE ON classification_schemes
FOR EACH ROW EXECUTE FUNCTION delete_unused_classification_scheme();
CREATE TRIGGER classifications_protect_deletion
BEFORE DELETE ON classifications
FOR EACH ROW EXECUTE FUNCTION protect_classification_deletion();

CREATE TRIGGER classification_schemes_bump_version
BEFORE UPDATE ON classification_schemes
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();
CREATE TRIGGER classifications_bump_version
BEFORE UPDATE ON classifications
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();
CREATE TRIGGER classification_retention_rules_bump_version
BEFORE UPDATE ON classification_retention_rules
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();
CREATE TRIGGER aggregation_retention_rules_bump_version
BEFORE UPDATE ON aggregation_retention_rules
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

CREATE TRIGGER classification_schemes_record_history
AFTER INSERT OR UPDATE OR DELETE ON classification_schemes
FOR EACH ROW EXECUTE FUNCTION record_entity_history('classification_scheme');
CREATE TRIGGER classifications_record_history
AFTER INSERT OR UPDATE OR DELETE ON classifications
FOR EACH ROW EXECUTE FUNCTION record_entity_history('classification');
CREATE TRIGGER classification_retention_rules_record_history
AFTER INSERT OR UPDATE OR DELETE ON classification_retention_rules
FOR EACH ROW EXECUTE FUNCTION record_entity_history('classification_retention_rule');
CREATE TRIGGER aggregation_retention_rules_record_history
AFTER INSERT OR UPDATE OR DELETE ON aggregation_retention_rules
FOR EACH ROW EXECUTE FUNCTION record_entity_history('aggregation_retention_rule');

ALTER TABLE aggregations ADD COLUMN security_level_id bigint NOT NULL;
ALTER TABLE aggregations ADD CONSTRAINT aggregations_security_level_fk
    FOREIGN KEY (security_level_id) REFERENCES security_levels (id) ON DELETE RESTRICT;
ALTER TABLE records ADD COLUMN security_level_id bigint NOT NULL;
ALTER TABLE records ADD CONSTRAINT records_security_level_fk
    FOREIGN KEY (security_level_id) REFERENCES security_levels (id) ON DELETE RESTRICT;
ALTER TABLE roles ADD COLUMN security_level_id bigint NOT NULL;
ALTER TABLE roles ADD CONSTRAINT roles_security_level_fk
    FOREIGN KEY (security_level_id) REFERENCES security_levels (id) ON DELETE RESTRICT;
ALTER TABLE record_drafts ADD COLUMN security_level_id bigint
    REFERENCES security_levels (id) ON DELETE RESTRICT;
CREATE INDEX aggregations_security_level_id_idx ON aggregations (security_level_id);
CREATE INDEX records_security_level_id_idx ON records (security_level_id);
CREATE INDEX roles_security_level_id_idx ON roles (security_level_id);
CREATE INDEX record_drafts_security_level_id_idx ON record_drafts (security_level_id);

CREATE FUNCTION lowest_security_level_id()
RETURNS bigint LANGUAGE sql STABLE AS $$
    SELECT id FROM security_levels ORDER BY level_number, id LIMIT 1
$$;

CREATE FUNCTION default_entity_security_level()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.security_level_id IS NOT NULL THEN RETURN NEW; END IF;
    IF TG_TABLE_NAME = 'aggregations'
       AND NULLIF(to_jsonb(NEW)->>'parent_aggregation_id', '') IS NOT NULL THEN
        SELECT security_level_id INTO NEW.security_level_id
        FROM aggregations
        WHERE id = (to_jsonb(NEW)->>'parent_aggregation_id')::bigint;
    END IF;
    NEW.security_level_id := COALESCE(NEW.security_level_id, lowest_security_level_id());
    IF NEW.security_level_id IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='no security level is configured';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER roles_default_security_level BEFORE INSERT ON roles
FOR EACH ROW EXECUTE FUNCTION default_entity_security_level();
CREATE TRIGGER aggregations_default_security_level BEFORE INSERT ON aggregations
FOR EACH ROW EXECUTE FUNCTION default_entity_security_level();
CREATE TRIGGER records_default_security_level BEFORE INSERT ON records
FOR EACH ROW EXECUTE FUNCTION default_entity_security_level();

CREATE FUNCTION enforce_resource_security_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    resource_level integer;
    parent_level integer;
    child_max integer;
BEGIN
    SELECT level_number INTO STRICT resource_level
    FROM security_levels WHERE id = NEW.security_level_id;
    IF TG_TABLE_NAME = 'records' THEN
        IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
        SELECT level.level_number INTO parent_level
        FROM aggregations parent JOIN security_levels level ON level.id=parent.security_level_id
        WHERE parent.id=NEW.aggregation_id;
        IF parent_level IS NULL THEN RETURN NEW; END IF;
        IF parent_level < resource_level THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
                DETAIL=format('record level %s exceeds parent aggregation level %s',resource_level,parent_level);
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.parent_aggregation_id IS NOT NULL THEN
        SELECT level.level_number INTO parent_level
        FROM aggregations parent JOIN security_levels level ON level.id=parent.security_level_id
        WHERE parent.id=NEW.parent_aggregation_id;
        IF parent_level IS NULL THEN RETURN NEW; END IF;
        IF parent_level < resource_level THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
                DETAIL=format('aggregation level %s exceeds parent aggregation level %s',resource_level,parent_level);
        END IF;
    END IF;
    SELECT max(level_number) INTO child_max FROM (
        SELECT level.level_number FROM aggregations child
        JOIN security_levels level ON level.id=child.security_level_id
        WHERE child.parent_aggregation_id=NEW.id
        UNION ALL
        SELECT level.level_number FROM records child
        JOIN security_levels level ON level.id=child.security_level_id
        WHERE child.aggregation_id=NEW.id
    ) children;
    IF child_max IS NOT NULL AND resource_level < child_max THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
            DETAIL=format('aggregation level %s is below contained resource level %s',resource_level,child_max);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER aggregations_enforce_security_hierarchy
BEFORE INSERT OR UPDATE OF parent_aggregation_id, security_level_id ON aggregations
FOR EACH ROW EXECUTE FUNCTION enforce_resource_security_hierarchy();
CREATE TRIGGER records_enforce_security_hierarchy
BEFORE INSERT OR UPDATE OF aggregation_id, security_level_id ON records
FOR EACH ROW EXECUTE FUNCTION enforce_resource_security_hierarchy();

CREATE FUNCTION enforce_security_level_catalogue_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.level_number IS DISTINCT FROM OLD.level_number AND EXISTS (
        SELECT 1 FROM aggregations child
        JOIN aggregations parent ON parent.id=child.parent_aggregation_id
        JOIN security_levels child_level ON child_level.id=child.security_level_id
        JOIN security_levels parent_level ON parent_level.id=parent.security_level_id
        WHERE (CASE WHEN parent_level.id=NEW.id THEN NEW.level_number ELSE parent_level.level_number END)
            < (CASE WHEN child_level.id=NEW.id THEN NEW.level_number ELSE child_level.level_number END)
        UNION ALL
        SELECT 1 FROM records child
        JOIN aggregations parent ON parent.id=child.aggregation_id
        JOIN security_levels child_level ON child_level.id=child.security_level_id
        JOIN security_levels parent_level ON parent_level.id=parent.security_level_id
        WHERE (CASE WHEN parent_level.id=NEW.id THEN NEW.level_number ELSE parent_level.level_number END)
            < (CASE WHEN child_level.id=NEW.id THEN NEW.level_number ELSE child_level.level_number END)
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='security_hierarchy_violation',
            DETAIL='changing this catalogue number would invalidate a resource hierarchy';
    END IF;
    NEW.date_updated := CURRENT_TIMESTAMP;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;

CREATE TRIGGER security_levels_validate_update BEFORE UPDATE ON security_levels
FOR EACH ROW EXECUTE FUNCTION enforce_security_level_catalogue_change();
CREATE TRIGGER security_levels_record_history
AFTER INSERT OR UPDATE OR DELETE ON security_levels
FOR EACH ROW EXECUTE FUNCTION record_entity_history('security_level');

-- The built-in levels are inserted before event-history triggers are
-- available. Record the baseline events with seed provenance so a database
-- created from this canonical schema has a complete catalogue timeline.
INSERT INTO event_history (
    occurred_at,
    entity_type,
    entity_id,
    operation,
    actor_type,
    actor_name,
    actor_email,
    source,
    after_state,
    changed_fields,
    reason,
    metadata
)
SELECT
    level.date_created,
    'security_level',
    level.id,
    'CREATE',
    'automated_process',
    'Canonical security-level seed',
    'system@erms.local',
    'seeding',
    to_jsonb(level),
    ARRAY[
        'code', 'date_created', 'date_updated', 'id', 'level_number',
        'name', 'prevents_disposition'
    ]::text[],
    'Baseline CREATE event recorded for a seeded security level.',
    jsonb_build_object('backfilled', true, 'seeded_baseline', true)
FROM security_levels level
WHERE NOT EXISTS (
    SELECT 1
    FROM event_history event
    WHERE event.entity_type = 'security_level'
      AND event.entity_id = level.id
      AND event.operation = 'CREATE'
);

















-- The canonical schema repeats upgrade DDL here so a new database is created
-- from this file alone. Migration scripts remain independent upgrade paths for
-- existing databases and are never included or invoked by this file.

-- Canonical definitions corresponding to 033_add_privileges_profiles_and_role_authorization.sql

SELECT set_config('app.actor_type', 'automated_process', true),
       set_config('app.actor_name', 'Database migration 033', true),
       set_config('app.event_source', 'migration', true),
       set_config('app.change_reason', 'Install the Phase 2 privilege and profile model', true),
       set_config('app.event_metadata', '{"migration":"033_add_privileges_profiles_and_role_authorization"}', true);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE privileges (
    id bigserial PRIMARY KEY,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    category text NOT NULL,
    is_reserved boolean NOT NULL DEFAULT false,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT privileges_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT privileges_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT privileges_category_valid CHECK (category IN ('administration','aggregation','record','component','exceptional'))
);
CREATE UNIQUE INDEX privileges_code_ci_unique ON privileges(lower(code));

CREATE TABLE profiles (
    id bigserial PRIMARY KEY,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    is_system boolean NOT NULL DEFAULT false,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT profiles_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT profiles_name_not_blank CHECK (btrim(name) <> '')
);
CREATE UNIQUE INDEX profiles_code_ci_unique ON profiles(lower(code));
CREATE UNIQUE INDEX profiles_name_ci_unique ON profiles(lower(name));

CREATE TABLE profile_privileges (
    id bigserial PRIMARY KEY,
    profile_id bigint NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    privilege_id bigint NOT NULL REFERENCES privileges(id) ON DELETE RESTRICT,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT profile_privileges_unique UNIQUE(profile_id, privilege_id)
);
CREATE INDEX profile_privileges_privilege_id_idx ON profile_privileges(privilege_id, profile_id);

CREATE TABLE privilege_dependencies (
    privilege_id bigint NOT NULL REFERENCES privileges(id) ON DELETE CASCADE,
    required_privilege_id bigint NOT NULL REFERENCES privileges(id) ON DELETE RESTRICT,
    PRIMARY KEY(privilege_id, required_privilege_id),
    CONSTRAINT privilege_dependencies_not_self CHECK (privilege_id <> required_privilege_id)
);

WITH seed(code, category, reserved) AS (VALUES
 ('authorization.administer','administration',false), ('authorization.explain','administration',false),
 ('security_levels.administer','administration',false), ('identity.users.administer','administration',false),
 ('identity.text_indexers.administer','administration',false),
 ('identity.sessions.administer','administration',false), ('organization.browse','administration',false),
 ('organization.administer','administration',false), ('organization.ownership.correct','exceptional',false),
 ('classifications.administer','administration',false), ('audit.view','administration',false),
 ('aggregation.view','aggregation',false), ('aggregation.create_root','aggregation',false),
 ('aggregation.create_child','aggregation',false), ('aggregation.modify','aggregation',false),
 ('aggregation.move','aggregation',false), ('aggregation.reclassify','aggregation',false),
 ('aggregation.close','aggregation',false), ('aggregation.reopen','aggregation',false),
 ('aggregation.delete','aggregation',false), ('aggregation.security_level.change','aggregation',false),
 ('aggregation.acl.manage','aggregation',false), ('record.view','record',false),
 ('record.create','record',false), ('record.modify','record',false), ('record.move','record',false),
 ('record.delete','record',false), ('record.security_level.change','record',false),
 ('record.acl.manage','record',false), ('record.component.view','component',false),
 ('record.component.download','component',false), ('record.component.add','component',false),
 ('record.component.replace','component',false), ('record.component.remove','component',false),
 ('record.component.reorder','component',false), ('record.component.share','component',true),
 ('record.component.print','component',true), ('security.resource.downgrade','exceptional',false),
 ('closure.correct_record_placement','exceptional',false), ('authorization.recovery','exceptional',true)
)
INSERT INTO privileges(code,name,description,category,is_reserved)
SELECT code, initcap(replace(replace(code,'.',' '),'_',' ')),
       'Global capability: ' || code, category, reserved FROM seed;

UPDATE privileges
SET name='Browse Organization Structure',
    description='Browse the organization hierarchy and view concise organization-unit, role, and user summaries.'
WHERE code='organization.browse';

INSERT INTO profiles(code,name,description,is_system) VALUES
 ('ALL_PRIVS','All privileges','Migration and controlled compatibility profile',true),
 ('SYS_ADMIN','System Administrator','Platform administration without governed-content bypass',true),
 ('INFO_GOV_MGR','Information Governance Manager','Universal governed-information custody and classification administration, subject to privilege and clearance gates',true),
 ('INFO_GOV_OFFICER','Information Governance Officer','Universal governed-information custody and classification administration, subject to privilege and clearance gates',true);

INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id, privilege.id FROM profiles profile CROSS JOIN privileges privilege
WHERE profile.code='ALL_PRIVS';

INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id, privilege.id FROM profiles profile JOIN privileges privilege ON privilege.code IN (
 'authorization.administer','authorization.explain','security_levels.administer',
 'identity.users.administer','identity.text_indexers.administer','identity.sessions.administer','organization.browse','organization.administer',
 'classifications.administer','audit.view') WHERE profile.code='SYS_ADMIN';

INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id, privilege.id FROM profiles profile JOIN privileges privilege ON
 privilege.code IN ('authorization.administer','authorization.explain','classifications.administer','security_levels.administer','audit.view','organization.browse','organization.ownership.correct',
 'aggregation.view','aggregation.create_root','aggregation.create_child','aggregation.modify',
 'aggregation.move','aggregation.reclassify','aggregation.close','aggregation.reopen',
 'aggregation.delete','aggregation.security_level.change','aggregation.acl.manage',
 'record.view','record.create','record.modify','record.move','record.delete',
 'record.security_level.change','record.acl.manage','record.component.view',
 'record.component.download','record.component.add','record.component.replace',
 'record.component.remove','record.component.reorder','record.component.share',
 'record.component.print','security.resource.downgrade','closure.correct_record_placement')
WHERE profile.code IN ('INFO_GOV_MGR','INFO_GOV_OFFICER');

INSERT INTO privilege_dependencies(privilege_id,required_privilege_id)
SELECT dependent.id, required.id FROM privileges dependent CROSS JOIN privileges required
WHERE required.code = CASE
 WHEN dependent.code LIKE 'aggregation.%' AND dependent.code <> 'aggregation.view' THEN 'aggregation.view'
 WHEN (dependent.code LIKE 'record.%' OR dependent.code LIKE 'record.component.%') AND dependent.code <> 'record.view' THEN 'record.view'
 END;

ALTER TABLE roles ADD COLUMN profile_id bigint;
ALTER TABLE roles ADD COLUMN is_information_governance boolean NOT NULL DEFAULT false;
UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='ALL_PRIVS');
ALTER TABLE roles ALTER COLUMN profile_id SET NOT NULL;
ALTER TABLE roles ADD CONSTRAINT roles_profile_fk FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE RESTRICT;
CREATE INDEX roles_profile_id_idx ON roles(profile_id);
CREATE INDEX roles_governance_clearance_idx ON roles(is_information_governance,security_level_id) WHERE is_information_governance;

CREATE OR REPLACE FUNCTION default_role_profile()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.profile_id IS NULL THEN
        SELECT id INTO NEW.profile_id FROM profiles WHERE code='ALL_PRIVS';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER roles_default_profile BEFORE INSERT ON roles
FOR EACH ROW EXECUTE FUNCTION default_role_profile();

CREATE OR REPLACE FUNCTION touch_authorization_catalogue()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.date_updated := CURRENT_TIMESTAMP;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;
CREATE TRIGGER privileges_touch BEFORE UPDATE ON privileges FOR EACH ROW EXECUTE FUNCTION touch_authorization_catalogue();
CREATE TRIGGER profiles_touch BEFORE UPDATE ON profiles FOR EACH ROW EXECUTE FUNCTION touch_authorization_catalogue();

CREATE TRIGGER privileges_record_history AFTER INSERT OR UPDATE OR DELETE ON privileges
FOR EACH ROW EXECUTE FUNCTION record_entity_history('privilege');
CREATE TRIGGER profiles_record_history AFTER INSERT OR UPDATE OR DELETE ON profiles
FOR EACH ROW EXECUTE FUNCTION record_entity_history('profile');
CREATE TRIGGER profile_privileges_record_history AFTER INSERT OR UPDATE OR DELETE ON profile_privileges
FOR EACH ROW EXECUTE FUNCTION record_entity_history('profile_privilege');

SELECT append_domain_event(
    'profile', profile.id, 'ROLE_PROFILE_BACKFILL_COMPLETED',
    jsonb_build_object(
        'profile_code', profile.code,
        'role_count', (SELECT count(*) FROM roles),
        'privilege_count', (SELECT count(*) FROM privileges),
        'unassigned_role_count', (SELECT count(*) FROM roles WHERE profile_id IS NULL)
    ),
    'Assign the compatibility profile before enforcing the non-null role profile reference'
)
FROM profiles profile WHERE profile.code='ALL_PRIVS';


-- Canonical definitions corresponding to 034_add_resource_acl_inheritance.sql

SELECT set_config('app.actor_type', 'automated_process', true),
       set_config('app.actor_name', 'Database migration 034', true),
       set_config('app.event_source', 'migration', true),
       set_config('app.change_reason', 'Install Phase 5 resource ACLs and live inheritance', true),
       set_config('app.event_metadata', '{"migration":"034_add_resource_acl_inheritance"}', true);

CREATE TABLE permissions (
    id bigserial PRIMARY KEY,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    resource_type text NOT NULL CHECK (resource_type IN ('aggregation','record')),
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT permissions_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT permissions_name_not_blank CHECK (btrim(name) <> '')
);
CREATE UNIQUE INDEX permissions_code_ci_unique ON permissions(lower(code));

CREATE TABLE permission_dependencies (
    permission_id bigint NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    required_permission_id bigint NOT NULL REFERENCES permissions(id) ON DELETE RESTRICT,
    PRIMARY KEY(permission_id, required_permission_id),
    CHECK (permission_id <> required_permission_id)
);

WITH seed(code, resource_type) AS (VALUES
 ('aggregation.view','aggregation'), ('aggregation.modify_metadata','aggregation'),
 ('aggregation.delete','aggregation'), ('aggregation.close','aggregation'),
 ('aggregation.reopen','aggregation'), ('aggregation.add_child','aggregation'),
 ('aggregation.add_record','aggregation'), ('aggregation.move','aggregation'),
 ('aggregation.receive_child','aggregation'), ('aggregation.receive_record','aggregation'),
 ('aggregation.reclassify','aggregation'), ('aggregation.security_level.change','aggregation'),
 ('aggregation.acl.manage','aggregation'), ('aggregation.history.view','aggregation'),
 ('record.view','record'), ('record.modify_metadata','record'), ('record.delete','record'),
 ('record.move','record'), ('record.security_level.change','record'),
 ('record.acl.manage','record'), ('record.history.view','record'),
 ('record.component.list','record'), ('record.component.view','record'),
 ('record.component.download','record'), ('record.component.add','record'),
 ('record.component.replace','record'), ('record.component.remove','record'),
 ('record.component.reorder','record'), ('record.component.share','record'),
 ('record.component.print','record')
)
INSERT INTO permissions(code,name,description,resource_type)
SELECT code, initcap(replace(replace(code,'.',' '),'_',' ')),
       'Resource permission: ' || code, resource_type FROM seed;

INSERT INTO permission_dependencies(permission_id,required_permission_id)
SELECT dependent.id, required.id
FROM permissions dependent
JOIN permissions required ON required.code = CASE
  WHEN dependent.resource_type='aggregation' AND dependent.code<>'aggregation.view'
    THEN 'aggregation.view'
  WHEN dependent.code IN ('record.component.view','record.component.download','record.component.add',
                           'record.component.replace','record.component.remove','record.component.reorder')
    THEN 'record.component.list'
  WHEN dependent.code IN ('record.component.share','record.component.print')
    THEN 'record.component.view'
  WHEN dependent.resource_type='record' AND dependent.code<>'record.view'
    THEN 'record.view'
END
WHERE dependent.code NOT IN ('aggregation.view','record.view');

-- Materialize transitive dependencies so every storage boundary can validate
-- a complete permission set without relying on application recursion.
INSERT INTO permission_dependencies(permission_id,required_permission_id)
SELECT dependency.permission_id, root.id
FROM permission_dependencies dependency
JOIN permissions immediate ON immediate.id=dependency.required_permission_id
JOIN permissions root ON root.code=CASE
  WHEN immediate.resource_type='record' AND immediate.code<>'record.view' THEN 'record.view'
  ELSE immediate.code
END
ON CONFLICT DO NOTHING;

ALTER TABLE aggregations
  ADD COLUMN inherit_acl_from_parent boolean,
  ADD COLUMN default_child_aggregation_acl_mode text NOT NULL DEFAULT 'mirror_resource_acl',
  ADD COLUMN resource_acl_version integer NOT NULL DEFAULT 1,
  ADD COLUMN child_aggregation_acl_version integer NOT NULL DEFAULT 1,
  ADD COLUMN child_record_acl_version integer NOT NULL DEFAULT 1,
  ADD CONSTRAINT aggregations_child_acl_mode_valid
    CHECK (default_child_aggregation_acl_mode IN ('mirror_resource_acl','custom')),
  ADD CONSTRAINT aggregations_acl_versions_positive
    CHECK (resource_acl_version>0 AND child_aggregation_acl_version>0 AND child_record_acl_version>0);
UPDATE aggregations SET inherit_acl_from_parent=(parent_aggregation_id IS NOT NULL);
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE aggregations ALTER COLUMN inherit_acl_from_parent SET NOT NULL;
ALTER TABLE aggregations ALTER COLUMN inherit_acl_from_parent SET DEFAULT true;
ALTER TABLE aggregations ADD CONSTRAINT aggregations_root_acl_inheritance_valid
  CHECK ((parent_aggregation_id IS NULL AND NOT inherit_acl_from_parent)
      OR (parent_aggregation_id IS NOT NULL));

ALTER TABLE records
  ADD COLUMN inherit_acl_from_parent boolean NOT NULL DEFAULT true,
  ADD COLUMN resource_acl_version integer NOT NULL DEFAULT 1 CHECK (resource_acl_version>0);

ALTER TABLE roles ADD CONSTRAINT roles_everyone_code_reserved CHECK (lower(btrim(code)) <> 'everyone');
ALTER TABLE roles ADD CONSTRAINT roles_everyone_name_reserved CHECK (lower(btrim(name)) <> 'everyone');
ALTER TABLE roles ADD CONSTRAINT roles_org_unit_members_code_reserved CHECK (lower(btrim(code)) <> 'org_unit_members');
ALTER TABLE roles ADD CONSTRAINT roles_org_unit_members_name_reserved CHECK (lower(btrim(name)) <> 'all org unit members');

CREATE TABLE aggregation_acl_grants (
    id bigserial PRIMARY KEY,
    aggregation_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE CASCADE,
    principal_type text NOT NULL CHECK (principal_type IN ('role','everyone','org_unit_members')),
    role_id bigint REFERENCES roles(id) ON DELETE RESTRICT,
    permission_id bigint NOT NULL REFERENCES permissions(id) ON DELETE RESTRICT,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL DEFAULT 1 CHECK (version>0),
    CHECK ((principal_type='role' AND role_id IS NOT NULL) OR
           (principal_type IN ('everyone','org_unit_members') AND role_id IS NULL))
);
CREATE UNIQUE INDEX aggregation_acl_role_grant_unique ON aggregation_acl_grants(aggregation_id,role_id,permission_id) WHERE principal_type='role';
CREATE UNIQUE INDEX aggregation_acl_everyone_grant_unique ON aggregation_acl_grants(aggregation_id,permission_id) WHERE principal_type='everyone';
CREATE UNIQUE INDEX aggregation_acl_org_unit_members_grant_unique ON aggregation_acl_grants(aggregation_id,permission_id) WHERE principal_type='org_unit_members';

CREATE TABLE aggregation_child_aggregation_acl_defaults (LIKE aggregation_acl_grants INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY);
ALTER TABLE aggregation_child_aggregation_acl_defaults DROP COLUMN aggregation_id;
ALTER TABLE aggregation_child_aggregation_acl_defaults ADD COLUMN aggregation_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE CASCADE;
ALTER TABLE aggregation_child_aggregation_acl_defaults ADD PRIMARY KEY(id);
ALTER TABLE aggregation_child_aggregation_acl_defaults ADD CHECK ((principal_type='role' AND role_id IS NOT NULL) OR (principal_type IN ('everyone','org_unit_members') AND role_id IS NULL));
ALTER TABLE aggregation_child_aggregation_acl_defaults ADD FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE RESTRICT;
ALTER TABLE aggregation_child_aggregation_acl_defaults ADD FOREIGN KEY(permission_id) REFERENCES permissions(id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX child_aggregation_acl_role_grant_unique ON aggregation_child_aggregation_acl_defaults(aggregation_id,role_id,permission_id) WHERE principal_type='role';
CREATE UNIQUE INDEX child_aggregation_acl_everyone_grant_unique ON aggregation_child_aggregation_acl_defaults(aggregation_id,permission_id) WHERE principal_type='everyone';
CREATE UNIQUE INDEX child_aggregation_acl_org_unit_members_grant_unique ON aggregation_child_aggregation_acl_defaults(aggregation_id,permission_id) WHERE principal_type='org_unit_members';

CREATE TABLE aggregation_child_record_acl_defaults (LIKE aggregation_acl_grants INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY);
ALTER TABLE aggregation_child_record_acl_defaults DROP COLUMN aggregation_id;
ALTER TABLE aggregation_child_record_acl_defaults ADD COLUMN aggregation_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE CASCADE;
ALTER TABLE aggregation_child_record_acl_defaults ADD PRIMARY KEY(id);
ALTER TABLE aggregation_child_record_acl_defaults ADD CHECK ((principal_type='role' AND role_id IS NOT NULL) OR (principal_type IN ('everyone','org_unit_members') AND role_id IS NULL));
ALTER TABLE aggregation_child_record_acl_defaults ADD FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE RESTRICT;
ALTER TABLE aggregation_child_record_acl_defaults ADD FOREIGN KEY(permission_id) REFERENCES permissions(id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX child_record_acl_role_grant_unique ON aggregation_child_record_acl_defaults(aggregation_id,role_id,permission_id) WHERE principal_type='role';
CREATE UNIQUE INDEX child_record_acl_everyone_grant_unique ON aggregation_child_record_acl_defaults(aggregation_id,permission_id) WHERE principal_type='everyone';
CREATE UNIQUE INDEX child_record_acl_org_unit_members_grant_unique ON aggregation_child_record_acl_defaults(aggregation_id,permission_id) WHERE principal_type='org_unit_members';

CREATE TABLE record_acl_grants (
    id bigserial PRIMARY KEY,
    record_id bigint NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    principal_type text NOT NULL CHECK (principal_type IN ('role','everyone','org_unit_members')),
    role_id bigint REFERENCES roles(id) ON DELETE RESTRICT,
    permission_id bigint NOT NULL REFERENCES permissions(id) ON DELETE RESTRICT,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL DEFAULT 1 CHECK (version>0),
    CHECK ((principal_type='role' AND role_id IS NOT NULL) OR
           (principal_type IN ('everyone','org_unit_members') AND role_id IS NULL))
);
CREATE UNIQUE INDEX record_acl_role_grant_unique ON record_acl_grants(record_id,role_id,permission_id) WHERE principal_type='role';
CREATE UNIQUE INDEX record_acl_everyone_grant_unique ON record_acl_grants(record_id,permission_id) WHERE principal_type='everyone';
CREATE UNIQUE INDEX record_acl_org_unit_members_grant_unique ON record_acl_grants(record_id,permission_id) WHERE principal_type='org_unit_members';

CREATE INDEX aggregation_acl_role_idx ON aggregation_acl_grants(role_id,aggregation_id,permission_id);
CREATE INDEX child_aggregation_acl_role_idx ON aggregation_child_aggregation_acl_defaults(role_id,aggregation_id,permission_id);
CREATE INDEX child_record_acl_role_idx ON aggregation_child_record_acl_defaults(role_id,aggregation_id,permission_id);
CREATE INDEX record_acl_role_idx ON record_acl_grants(role_id,record_id,permission_id);

-- Every local or custom ACL starts as Everyone/all. Inheritance determines
-- whether that local set is effective or dormant; no grants are copied later.
INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id)
SELECT aggregation.id,'everyone',permission.id FROM aggregations aggregation CROSS JOIN permissions permission WHERE permission.resource_type='aggregation';
INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,permission_id)
SELECT aggregation.id,'everyone',permission.id FROM aggregations aggregation CROSS JOIN permissions permission WHERE permission.resource_type='aggregation';
INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
SELECT aggregation.id,'everyone',permission.id FROM aggregations aggregation CROSS JOIN permissions permission WHERE permission.resource_type='record';
INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
SELECT record.id,'everyone',permission.id FROM records record CROSS JOIN permissions permission WHERE permission.resource_type='record';

CREATE FUNCTION validate_acl_permission_type() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected text;
BEGIN
  expected := CASE WHEN TG_TABLE_NAME='aggregation_child_record_acl_defaults' OR TG_TABLE_NAME='record_acl_grants' THEN 'record' ELSE 'aggregation' END;
  IF NOT EXISTS (SELECT 1 FROM permissions WHERE id=NEW.permission_id AND resource_type=expected) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='acl_permission_type_mismatch';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION validate_acl_role_clearance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id bigint; sufficient boolean;
BEGIN
  IF NEW.principal_type <> 'role' THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='record_acl_grants' THEN
    SELECT role_level.level_number>=resource_level.level_number INTO sufficient
    FROM roles role JOIN security_levels role_level ON role_level.id=role.security_level_id
    JOIN records resource ON resource.id=NEW.record_id
    JOIN security_levels resource_level ON resource_level.id=resource.security_level_id
    WHERE role.id=NEW.role_id;
  ELSE
    SELECT role_level.level_number>=resource_level.level_number INTO sufficient
    FROM roles role JOIN security_levels role_level ON role_level.id=role.security_level_id
    JOIN aggregations resource ON resource.id=NEW.aggregation_id
    JOIN security_levels resource_level ON resource_level.id=resource.security_level_id
    WHERE role.id=NEW.role_id;
  END IF;
  IF NOT coalesce(sufficient,false) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='role_clearance_below_resource';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION validate_acl_dependencies() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id bigint; owner_column text; missing boolean;
BEGIN
  owner_column := TG_ARGV[0];
  owner_id := CASE WHEN TG_OP='DELETE' THEN (to_jsonb(OLD)->>owner_column)::bigint ELSE (to_jsonb(NEW)->>owner_column)::bigint END;
  EXECUTE format($query$
    SELECT EXISTS(
      SELECT 1 FROM %I grant_row
      JOIN permission_dependencies dependency ON dependency.permission_id=grant_row.permission_id
      WHERE grant_row.%I=$1
        AND grant_row.principal_type=$2
        AND grant_row.role_id IS NOT DISTINCT FROM $3
        AND NOT EXISTS (
          SELECT 1 FROM %I required_grant
          WHERE required_grant.%I=grant_row.%I
            AND required_grant.principal_type=grant_row.principal_type
            AND required_grant.role_id IS NOT DISTINCT FROM grant_row.role_id
            AND required_grant.permission_id=dependency.required_permission_id))
  $query$,TG_TABLE_NAME,owner_column,TG_TABLE_NAME,owner_column,owner_column)
  INTO missing USING owner_id,
    CASE WHEN TG_OP='DELETE' THEN OLD.principal_type ELSE NEW.principal_type END,
    CASE WHEN TG_OP='DELETE' THEN OLD.role_id ELSE NEW.role_id END;
  IF missing THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='permission_dependency_violation';
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER aggregation_acl_type BEFORE INSERT OR UPDATE ON aggregation_acl_grants FOR EACH ROW EXECUTE FUNCTION validate_acl_permission_type();
CREATE TRIGGER child_aggregation_acl_type BEFORE INSERT OR UPDATE ON aggregation_child_aggregation_acl_defaults FOR EACH ROW EXECUTE FUNCTION validate_acl_permission_type();
CREATE TRIGGER child_record_acl_type BEFORE INSERT OR UPDATE ON aggregation_child_record_acl_defaults FOR EACH ROW EXECUTE FUNCTION validate_acl_permission_type();
CREATE TRIGGER record_acl_type BEFORE INSERT OR UPDATE ON record_acl_grants FOR EACH ROW EXECUTE FUNCTION validate_acl_permission_type();
CREATE TRIGGER aggregation_acl_clearance BEFORE INSERT OR UPDATE ON aggregation_acl_grants FOR EACH ROW EXECUTE FUNCTION validate_acl_role_clearance();
CREATE TRIGGER child_aggregation_acl_clearance BEFORE INSERT OR UPDATE ON aggregation_child_aggregation_acl_defaults FOR EACH ROW EXECUTE FUNCTION validate_acl_role_clearance();
CREATE TRIGGER child_record_acl_clearance BEFORE INSERT OR UPDATE ON aggregation_child_record_acl_defaults FOR EACH ROW EXECUTE FUNCTION validate_acl_role_clearance();
CREATE TRIGGER record_acl_clearance BEFORE INSERT OR UPDATE ON record_acl_grants FOR EACH ROW EXECUTE FUNCTION validate_acl_role_clearance();
CREATE CONSTRAINT TRIGGER aggregation_acl_dependencies AFTER INSERT OR UPDATE OR DELETE ON aggregation_acl_grants DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_acl_dependencies('aggregation_id');
CREATE CONSTRAINT TRIGGER child_aggregation_acl_dependencies AFTER INSERT OR UPDATE OR DELETE ON aggregation_child_aggregation_acl_defaults DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_acl_dependencies('aggregation_id');
CREATE CONSTRAINT TRIGGER child_record_acl_dependencies AFTER INSERT OR UPDATE OR DELETE ON aggregation_child_record_acl_defaults DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_acl_dependencies('aggregation_id');
CREATE CONSTRAINT TRIGGER record_acl_dependencies AFTER INSERT OR UPDATE OR DELETE ON record_acl_grants DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_acl_dependencies('record_id');

CREATE FUNCTION initialize_resource_acls() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE creator_role_id bigint := NULLIF(current_setting('app.creator_acl_role_id',true),'')::bigint;
BEGIN
  IF creator_role_id IS NULL THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='aggregations' THEN
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.acl.manage','aggregation.history.view']);
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.acl.manage','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.acl.manage','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  ELSE
    INSERT INTO record_acl_grants(record_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.acl.manage','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  END IF;
  RETURN NEW;
END $$;
CREATE FUNCTION normalize_aggregation_acl_inheritance() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_aggregation_id IS NULL THEN NEW.inherit_acl_from_parent := false; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER aggregations_normalize_acl_inheritance BEFORE INSERT OR UPDATE OF parent_aggregation_id ON aggregations FOR EACH ROW EXECUTE FUNCTION normalize_aggregation_acl_inheritance();
CREATE TRIGGER aggregations_initialize_acls AFTER INSERT ON aggregations FOR EACH ROW EXECUTE FUNCTION initialize_resource_acls();
CREATE TRIGGER records_initialize_acls AFTER INSERT ON records FOR EACH ROW EXECUTE FUNCTION initialize_resource_acls();

CREATE TRIGGER aggregation_acl_history AFTER INSERT OR UPDATE OR DELETE ON aggregation_acl_grants FOR EACH ROW EXECUTE FUNCTION record_entity_history('aggregation_acl_grant');
CREATE TRIGGER child_aggregation_acl_history AFTER INSERT OR UPDATE OR DELETE ON aggregation_child_aggregation_acl_defaults FOR EACH ROW EXECUTE FUNCTION record_entity_history('aggregation_child_aggregation_acl_default');
CREATE TRIGGER child_record_acl_history AFTER INSERT OR UPDATE OR DELETE ON aggregation_child_record_acl_defaults FOR EACH ROW EXECUTE FUNCTION record_entity_history('aggregation_child_record_acl_default');
CREATE TRIGGER record_acl_history AFTER INSERT OR UPDATE OR DELETE ON record_acl_grants FOR EACH ROW EXECUTE FUNCTION record_entity_history('record_acl_grant');


-- Canonical definitions corresponding to 035_enforce_resource_read_authorization.sql

SELECT set_config('app.actor_type', 'automated_process', true),
       set_config('app.actor_name', 'Database migration 035', true),
       set_config('app.event_source', 'migration', true),
       set_config('app.change_reason', 'Install Phase 6 governed-resource read predicates', true),
       set_config('app.event_metadata', '{"migration":"035_enforce_resource_read_authorization"}', true);

-- This is deliberately a database predicate: callers can compose it into the
-- query before count, sort, and pagination, avoiding both inference leaks and
-- per-row authorization queries.
CREATE FUNCTION user_has_global_privilege(p_user_id bigint, p_code text)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1
      FROM users account
      JOIN user_role_assignments assignment ON assignment.user_id=account.id
      JOIN roles role ON role.id=assignment.role_id
      JOIN profile_privileges membership ON membership.profile_id=role.profile_id
      JOIN privileges privilege ON privilege.id=membership.privilege_id
     WHERE account.id=p_user_id AND account.status='active'
       AND assignment.valid_from<=CURRENT_TIMESTAMP
       AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
       AND role_effectively_active(role.id)
       AND privilege.code=p_code
  )
$$;

CREATE FUNCTION user_has_aggregation_permission(
  p_user_id bigint, p_aggregation_id bigint, p_permission text
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE
  cursor_row aggregations%ROWTYPE;
  parent_row aggregations%ROWTYPE;
  source_id bigint;
  source_kind text;
BEGIN
  SELECT * INTO cursor_row FROM aggregations WHERE id=p_aggregation_id;
  IF NOT FOUND THEN RETURN false; END IF;
  IF NOT cursor_row.inherit_acl_from_parent OR cursor_row.parent_aggregation_id IS NULL THEN
    source_id := cursor_row.id; source_kind := 'resource';
  ELSE
    LOOP
      SELECT * INTO parent_row FROM aggregations WHERE id=cursor_row.parent_aggregation_id;
      IF NOT FOUND THEN RETURN false; END IF;
      IF parent_row.default_child_aggregation_acl_mode='custom' THEN
        source_id := parent_row.id; source_kind := 'child_default'; EXIT;
      ELSIF NOT parent_row.inherit_acl_from_parent OR parent_row.parent_aggregation_id IS NULL THEN
        source_id := parent_row.id; source_kind := 'resource'; EXIT;
      END IF;
      cursor_row := parent_row;
    END LOOP;
  END IF;

  IF source_kind='resource' THEN
    RETURN EXISTS (
      SELECT 1 FROM aggregation_acl_grants grant_row
      JOIN permissions permission ON permission.id=grant_row.permission_id
      WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
        AND (grant_row.principal_type='everyone' OR EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(assignment.role_id)))
    );
  END IF;
  RETURN EXISTS (
    SELECT 1 FROM aggregation_child_aggregation_acl_defaults grant_row
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone' OR EXISTS (
        SELECT 1 FROM user_role_assignments assignment
        WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
          AND assignment.valid_from<=CURRENT_TIMESTAMP
          AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
          AND role_effectively_active(assignment.role_id)))
  );
END $$;

CREATE FUNCTION user_can_view_aggregation(p_user_id bigint, p_aggregation_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT user_has_global_privilege(p_user_id,'aggregation.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN aggregations resource ON resource.id=p_aggregation_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     AND (
       user_has_aggregation_permission(p_user_id,p_aggregation_id,'aggregation.view')
       OR EXISTS (SELECT 1 FROM user_role_assignments a
         JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
         JOIN aggregations resource ON resource.id=p_aggregation_id
         JOIN security_levels required ON required.id=resource.security_level_id
         WHERE a.user_id=p_user_id AND r.is_information_governance
           AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     )
$$;

CREATE FUNCTION user_has_record_permission(
  p_user_id bigint, p_record_id bigint, p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN record_acl_grants grant_row ON NOT resource.inherit_acl_from_parent
      AND grant_row.record_id=resource.id AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone' OR EXISTS (
        SELECT 1 FROM user_role_assignments assignment
        WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
          AND assignment.valid_from<=CURRENT_TIMESTAMP
          AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
          AND role_effectively_active(assignment.role_id)))
  ) OR EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN aggregation_child_record_acl_defaults grant_row
      ON resource.inherit_acl_from_parent AND grant_row.aggregation_id=resource.aggregation_id
      AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone' OR EXISTS (
        SELECT 1 FROM user_role_assignments assignment
        WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
          AND assignment.valid_from<=CURRENT_TIMESTAMP
          AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
          AND role_effectively_active(assignment.role_id)))
  )
$$;

CREATE FUNCTION user_can_view_record(p_user_id bigint, p_record_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT user_has_global_privilege(p_user_id,'record.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN records resource ON resource.id=p_record_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     AND (
       user_has_record_permission(p_user_id,p_record_id,'record.view')
       OR EXISTS (SELECT 1 FROM user_role_assignments a
         JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
         JOIN records resource ON resource.id=p_record_id
         JOIN security_levels required ON required.id=resource.security_level_id
         WHERE a.user_id=p_user_id AND r.is_information_governance
           AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     )
$$;

CREATE FUNCTION current_user_id() RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.user_id',true),'')::bigint
$$;
CREATE FUNCTION current_user_can_view_aggregation(p_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_id() IS NOT NULL AND user_can_view_aggregation(current_user_id(),p_id)
$$;
CREATE FUNCTION current_user_can_view_record(p_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_id() IS NOT NULL AND user_can_view_record(current_user_id(),p_id)
$$;

CREATE FUNCTION current_user_can_list_record_components(p_record_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_can_view_record(p_record_id)
     AND user_has_global_privilege(current_user_id(),'record.component.view')
     AND (
       user_has_record_permission(current_user_id(),p_record_id,'record.component.list')
       OR EXISTS (SELECT 1 FROM user_role_assignments a
         JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
         JOIN records resource ON resource.id=p_record_id
         JOIN security_levels required ON required.id=resource.security_level_id
         WHERE a.user_id=current_user_id() AND r.is_information_governance
           AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     )
$$;

CREATE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
BEGIN
  IF p_entity_type='aggregation' THEN
    IF EXISTS (SELECT 1 FROM aggregations WHERE id=p_entity_id) THEN
      RETURN current_user_can_view_aggregation(p_entity_id);
    END IF;
    historical_level_id := COALESCE(
      CASE WHEN (p_before->>'security_level_id') ~ '^[0-9]+$' THEN (p_before->>'security_level_id')::bigint END,
      CASE WHEN (p_after->>'security_level_id') ~ '^[0-9]+$' THEN (p_after->>'security_level_id')::bigint END
    );
  ELSIF p_entity_type='record' THEN
    IF EXISTS (SELECT 1 FROM records WHERE id=p_entity_id) THEN
      RETURN current_user_can_view_record(p_entity_id);
    END IF;
    historical_level_id := COALESCE(
      CASE WHEN (p_before->>'security_level_id') ~ '^[0-9]+$' THEN (p_before->>'security_level_id')::bigint END,
      CASE WHEN (p_after->>'security_level_id') ~ '^[0-9]+$' THEN (p_after->>'security_level_id')::bigint END
    );
  ELSIF p_entity_type IN ('digital_component','record_component') THEN
    SELECT component.record_id INTO record_id FROM digital_components component WHERE component.id=p_entity_id;
    IF record_id IS NULL THEN
      record_id := COALESCE(
        CASE WHEN (p_after->>'record_id') ~ '^[0-9]+$' THEN (p_after->>'record_id')::bigint END,
        CASE WHEN (p_before->>'record_id') ~ '^[0-9]+$' THEN (p_before->>'record_id')::bigint END
      );
    END IF;
    RETURN record_id IS NOT NULL AND current_user_can_view_record(record_id);
  ELSE
    RETURN true;
  END IF;
  IF historical_level_id IS NOT NULL THEN
    RETURN user_has_global_privilege(current_user_id(),'audit.view') AND EXISTS (
      SELECT 1 FROM user_role_assignments assignment
      JOIN roles role ON role.id=assignment.role_id
      JOIN security_levels role_level ON role_level.id=role.security_level_id
      JOIN security_levels required ON required.id=historical_level_id
      WHERE assignment.user_id=current_user_id()
        AND assignment.valid_from<=CURRENT_TIMESTAMP
        AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
        AND role_effectively_active(role.id)
        AND role_level.level_number>=required.level_number
    );
  END IF;
  RETURN false;
END $$;

CREATE VIEW authorized_event_history AS
SELECT event.id,event.occurred_at,event.transaction_id,event.entity_type,event.entity_id,
       event.operation,
       CASE WHEN visible.allowed THEN event.actor_user_id END AS actor_user_id,
       CASE WHEN visible.allowed THEN event.actor_name END AS actor_name,
       CASE WHEN visible.allowed THEN event.actor_email END AS actor_email,
       event.actor_type,
       event.source,event.request_id,event.correlation_id,
       CASE WHEN visible.allowed THEN event.before_state ELSE NULL END AS before_state,
       CASE WHEN visible.allowed THEN event.after_state ELSE NULL END AS after_state,
       CASE WHEN visible.allowed THEN event.changed_fields ELSE ARRAY[]::text[] END AS changed_fields,
       CASE WHEN visible.allowed THEN event.reason ELSE NULL END AS reason,
       CASE WHEN visible.allowed THEN event.metadata
            ELSE jsonb_build_object('redacted',true,'reason','resource_access_denied') END AS metadata
FROM event_history event
CROSS JOIN LATERAL (
  SELECT current_user_can_view_event_resource(
    event.entity_type,event.entity_id,event.before_state,event.after_state
  ) AS allowed
) visible;

CREATE VIEW authorized_aggregations_for_search AS
SELECT resource.id,
       CASE WHEN resource.parent_aggregation_id IS NULL
                  OR current_user_can_view_aggregation(resource.parent_aggregation_id)
            THEN resource.parent_aggregation_id END AS parent_aggregation_id,
       resource.classification_id,resource.aggregation_number,resource.title,
       resource.description,resource.date_created,resource.date_opened,resource.date_closed,
       resource.security_level_id,resource.inherit_acl_from_parent,
       resource.default_child_aggregation_acl_mode,resource.resource_acl_version,
       resource.child_aggregation_acl_version,resource.child_record_acl_version,resource.version
FROM aggregations resource;

CREATE VIEW authorized_records_for_search AS
SELECT resource.id,
       CASE WHEN current_user_can_view_aggregation(resource.aggregation_id)
            THEN resource.aggregation_id END AS aggregation_id,
       resource.record_number,resource.title,resource.description,resource.date_created,
       resource.date_originated,resource.security_level_id,resource.inherit_acl_from_parent,
       resource.resource_acl_version,resource.version
FROM records resource;

CREATE INDEX user_role_assignments_effective_lookup_idx
  ON user_role_assignments(user_id,role_id,valid_from,valid_until);


-- Canonical definitions corresponding to 036_enforce_resource_mutation_authorization.sql

SELECT set_config('app.actor_type','automated_process',true),
       set_config('app.actor_name','Database migration 036',true),
       set_config('app.event_source','migration',true),
       set_config('app.change_reason','Install Phase 7 resource mutation predicates',true),
       set_config('app.event_metadata','{"migration":"036_enforce_resource_mutation_authorization"}',true);

CREATE FUNCTION user_has_governance_clearance(p_user_id bigint,p_security_level_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS(
    SELECT 1 FROM user_role_assignments assignment
    JOIN roles role ON role.id=assignment.role_id
    JOIN security_levels role_level ON role_level.id=role.security_level_id
    JOIN security_levels required ON required.id=p_security_level_id
    WHERE assignment.user_id=p_user_id AND role.is_information_governance
      AND assignment.valid_from<=CURRENT_TIMESTAMP
      AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
      AND role_effectively_active(role.id)
      AND role_level.level_number>=required.level_number)
$$;

CREATE FUNCTION user_can_aggregation_operation(
  p_user_id bigint,p_aggregation_id bigint,p_privilege text,p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT user_can_view_aggregation(p_user_id,p_aggregation_id)
     AND user_has_global_privilege(p_user_id,p_privilege)
     AND (user_has_aggregation_permission(p_user_id,p_aggregation_id,p_permission)
          OR EXISTS(SELECT 1 FROM aggregations resource
                    WHERE resource.id=p_aggregation_id
                      AND user_has_governance_clearance(p_user_id,resource.security_level_id)))
$$;

CREATE FUNCTION user_can_record_operation(
  p_user_id bigint,p_record_id bigint,p_privilege text,p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT user_can_view_record(p_user_id,p_record_id)
     AND user_has_global_privilege(p_user_id,p_privilege)
     AND (user_has_record_permission(p_user_id,p_record_id,p_permission)
          OR EXISTS(SELECT 1 FROM records resource
                    WHERE resource.id=p_record_id
                      AND user_has_governance_clearance(p_user_id,resource.security_level_id)))
$$;

CREATE FUNCTION current_user_can_aggregation_operation(bigint,text,text)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_id() IS NOT NULL
     AND user_can_aggregation_operation(current_user_id(),$1,$2,$3)
$$;
CREATE FUNCTION current_user_can_record_operation(bigint,text,text)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_id() IS NOT NULL
     AND user_can_record_operation(current_user_id(),$1,$2,$3)
$$;


-- Canonical definitions corresponding to 037_enforce_draft_component_authorization.sql

SELECT set_config('app.actor_type','automated_process',true),
       set_config('app.actor_name','Database migration 037',true),
       set_config('app.event_source','migration',true),
       set_config('app.change_reason','Install Phase 8 draft, component, and placement-correction policy',true),
       set_config('app.event_metadata','{"migration":"037_enforce_draft_component_authorization"}',true);

CREATE FUNCTION user_has_destination_record_permission(
  p_user_id bigint,p_aggregation_id bigint,p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS(
    SELECT 1 FROM aggregation_child_record_acl_defaults grant_row
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE grant_row.aggregation_id=p_aggregation_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone' OR EXISTS(
        SELECT 1 FROM user_role_assignments assignment
        WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
          AND assignment.valid_from<=CURRENT_TIMESTAMP
          AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
          AND role_effectively_active(assignment.role_id)))
  )
$$;

CREATE FUNCTION current_user_can_record_component_operation(
  p_record_id bigint,p_privilege text,p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_can_view_record(p_record_id)
     AND user_has_global_privilege(current_user_id(),p_privilege)
     AND (user_has_record_permission(current_user_id(),p_record_id,p_permission)
          OR EXISTS(SELECT 1 FROM records resource
                    WHERE resource.id=p_record_id
                      AND user_has_governance_clearance(current_user_id(),resource.security_level_id)))
$$;

CREATE OR REPLACE FUNCTION current_user_can_list_record_components(p_record_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_can_view_record(p_record_id)
     AND (user_has_record_permission(current_user_id(),p_record_id,'record.component.list')
          OR EXISTS(SELECT 1 FROM records resource
                    WHERE resource.id=p_record_id
                      AND user_has_governance_clearance(current_user_id(),resource.security_level_id)))
$$;

CREATE FUNCTION current_user_owns_open_draft(p_draft_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_user_id() IS NOT NULL AND EXISTS(
    SELECT 1 FROM record_drafts draft
    JOIN users owner ON owner.id=draft.owner_user_id
    WHERE draft.id=p_draft_id AND draft.owner_user_id=current_user_id()
      AND draft.expires_at>CURRENT_TIMESTAMP
      AND owner.status='active')
$$;

CREATE OR REPLACE FUNCTION protect_record_in_closed_aggregation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE correction boolean := COALESCE(current_setting('app.closed_record_placement_correction',true)='authorized',false);
BEGIN
  IF TG_OP='INSERT' THEN
    IF NOT correction THEN PERFORM assert_aggregation_effectively_open(NEW.aggregation_id); END IF;
    RETURN NEW;
  ELSIF TG_OP='DELETE' THEN
    PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN OLD;
  END IF;
  IF correction AND NEW.aggregation_id IS DISTINCT FROM OLD.aggregation_id
     AND NEW.record_number IS NOT DISTINCT FROM OLD.record_number
     AND NEW.title IS NOT DISTINCT FROM OLD.title
     AND NEW.description IS NOT DISTINCT FROM OLD.description
     AND NEW.date_originated IS NOT DISTINCT FROM OLD.date_originated
     AND NEW.security_level_id IS NOT DISTINCT FROM OLD.security_level_id THEN
    RETURN NEW;
  END IF;
  PERFORM assert_aggregation_effectively_open(OLD.aggregation_id);
  IF NEW.aggregation_id IS DISTINCT FROM OLD.aggregation_id THEN
    PERFORM assert_aggregation_effectively_open(NEW.aggregation_id);
  END IF;
  RETURN NEW;
END $$;








-- Canonical definitions corresponding to
-- 044_add_organizational_ownership_foundation.sql

SELECT set_config('app.actor_type', 'automated_process', true),
       set_config('app.actor_name', 'Database migration 044', true),
       set_config('app.event_source', 'migration', true),
       set_config('app.change_reason', 'Add the organizational ownership schema foundation', true),
       set_config('app.event_metadata', '{"migration":"044_add_organizational_ownership_foundation"}', true);

ALTER TABLE aggregations
    ADD COLUMN owning_org_unit_id bigint,
    ADD CONSTRAINT aggregations_owning_org_unit_fk
        FOREIGN KEY (owning_org_unit_id) REFERENCES org_units (id) ON DELETE RESTRICT;

ALTER TABLE records
    ADD COLUMN owning_org_unit_id bigint,
    ADD CONSTRAINT records_owning_org_unit_fk
        FOREIGN KEY (owning_org_unit_id) REFERENCES org_units (id) ON DELETE RESTRICT;

CREATE INDEX aggregations_owner_parent_number_browse_idx
    ON aggregations (
        owning_org_unit_id,
        parent_aggregation_id,
        aggregation_number COLLATE "C",
        id
    );

CREATE INDEX records_owner_aggregation_number_browse_idx
    ON records (
        owning_org_unit_id,
        aggregation_id,
        record_number COLLATE "C",
        id
    );

CREATE VIEW organizational_ownership_diagnostics AS
SELECT
    'aggregation'::text AS resource_type,
    child.id AS resource_id,
    child.parent_aggregation_id AS parent_resource_id,
    child.owning_org_unit_id,
    parent.owning_org_unit_id AS expected_owning_org_unit_id,
    CASE WHEN child.owning_org_unit_id IS NULL THEN 'missing_owner' ELSE 'owner_mismatch' END AS issue
FROM aggregations AS child
LEFT JOIN aggregations AS parent ON parent.id = child.parent_aggregation_id
WHERE child.owning_org_unit_id IS NULL
   OR (child.parent_aggregation_id IS NOT NULL
       AND child.owning_org_unit_id IS DISTINCT FROM parent.owning_org_unit_id)
UNION ALL
SELECT
    'record'::text,
    record.id,
    record.aggregation_id,
    record.owning_org_unit_id,
    parent.owning_org_unit_id,
    CASE WHEN record.owning_org_unit_id IS NULL THEN 'missing_owner' ELSE 'owner_mismatch' END
FROM records AS record
JOIN aggregations AS parent ON parent.id = record.aggregation_id
WHERE record.owning_org_unit_id IS NULL
   OR record.owning_org_unit_id IS DISTINCT FROM parent.owning_org_unit_id;

CREATE OR REPLACE FUNCTION event_reference_identity(reference_field text, reference_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE snapshot jsonb;
DECLARE existing_snapshots jsonb;
BEGIN
    CASE reference_field
        WHEN 'profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'old_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'new_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'security_level_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name,'level_number',level_number) INTO snapshot FROM security_levels WHERE id=reference_id;
        WHEN 'classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'parent_classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'classification_scheme_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classification_schemes WHERE id=reference_id;
        WHEN 'aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'parent_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'destination_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'record_id' THEN SELECT jsonb_build_object('id',id,'code',record_number,'title',title) INTO snapshot FROM records WHERE id=reference_id;
        WHEN 'role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'supervisor_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'owner_user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'parent_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'owning_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        ELSE snapshot := NULL;
    END CASE;
    RETURN snapshot;
END;
$$;

CREATE OR REPLACE FUNCTION event_state_reference_snapshots(event_state jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE reference_field text; reference_value text; snapshot jsonb; snapshots jsonb := '{}'::jsonb;
BEGIN
    IF event_state IS NULL OR jsonb_typeof(event_state) <> 'object' THEN RETURN snapshots; END IF;
    FOREACH reference_field IN ARRAY ARRAY[
        'profile_id','old_profile_id','new_profile_id','security_level_id',
        'classification_id','parent_classification_id','classification_scheme_id',
        'aggregation_id','parent_aggregation_id','destination_aggregation_id',
        'record_id','role_id','supervisor_role_id','user_id','owner_user_id',
        'org_unit_id','parent_org_unit_id','owning_org_unit_id'
    ] LOOP
        reference_value := event_state ->> reference_field;
        IF reference_value IS NOT NULL AND reference_value ~ '^[0-9]+$' THEN
            snapshot := event_reference_identity(reference_field,reference_value::bigint);
            IF snapshot IS NOT NULL THEN snapshots := snapshots || jsonb_build_object(reference_field,snapshot); END IF;
        END IF;
    END LOOP;
    RETURN snapshots;
END;
$$;


-- 045_assign_existing_organizational_ownership.sql
-- New databases contain no historical holdings to assign, but retain the
-- reporting structures used by the upgrade migration and later ACL work.
CREATE TABLE organizational_ownership_assignment_runs (
    id                    bigserial PRIMARY KEY,
    migration_version     text NOT NULL UNIQUE,
    started_at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at          timestamptz,
    root_count            bigint NOT NULL,
    aggregation_count     bigint NOT NULL,
    record_count          bigint NOT NULL,
    before_counts_by_unit jsonb NOT NULL,
    after_counts_by_unit  jsonb,
    CONSTRAINT ownership_assignment_run_version_not_blank
        CHECK (btrim(migration_version) <> ''),
    CONSTRAINT ownership_assignment_run_counts_nonnegative
        CHECK (root_count >= 0 AND aggregation_count >= 0 AND record_count >= 0),
    CONSTRAINT ownership_assignment_run_before_counts_object
        CHECK (jsonb_typeof(before_counts_by_unit) = 'object'),
    CONSTRAINT ownership_assignment_run_after_counts_object
        CHECK (after_counts_by_unit IS NULL OR jsonb_typeof(after_counts_by_unit) = 'object')
);

CREATE TABLE organizational_ownership_root_assignments (
    root_aggregation_id bigint PRIMARY KEY,
    run_id              bigint NOT NULL REFERENCES organizational_ownership_assignment_runs(id) ON DELETE RESTRICT,
    selected_role_id    bigint NOT NULL,
    selected_role_code  text NOT NULL,
    selected_role_name  text NOT NULL,
    owning_org_unit_id  bigint NOT NULL,
    owning_org_unit_code text NOT NULL,
    owning_org_unit_name text NOT NULL,
    match_score         integer NOT NULL CHECK (match_score >= 0),
    assignment_method   text NOT NULL CHECK (assignment_method IN (
        'text_match', 'score_tie_stable_distribution', 'no_text_match_stable_distribution'
    )),
    root_title          text NOT NULL,
    root_description    text,
    assigned_at         timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX organizational_ownership_root_assignments_role_idx
    ON organizational_ownership_root_assignments(selected_role_id, root_aggregation_id);
CREATE INDEX organizational_ownership_root_assignments_unit_idx
    ON organizational_ownership_root_assignments(owning_org_unit_id, root_aggregation_id);


-- 046_enforce_organizational_ownership.sql
ALTER TABLE aggregations ALTER COLUMN owning_org_unit_id SET NOT NULL;
ALTER TABLE records ALTER COLUMN owning_org_unit_id SET NOT NULL;

CREATE FUNCTION enforce_aggregation_ownership()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_owner bigint;
    target_owner bigint;
    confirmed boolean := COALESCE(NULLIF(current_setting('app.ownership_move_confirmed', true), '')::boolean, false);
    propagating boolean := current_setting('app.ownership_propagation', true) = 'authorized';
    correcting boolean := current_setting('app.ownership_correction_authorized', true) = 'authorized';
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.parent_aggregation_id IS NOT NULL THEN
            SELECT owning_org_unit_id INTO STRICT parent_owner
            FROM aggregations WHERE id = NEW.parent_aggregation_id FOR UPDATE;
            NEW.owning_org_unit_id := parent_owner;
        ELSIF NEW.owning_org_unit_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='23502', MESSAGE='root aggregation ownership is required';
        END IF;
        RETURN NEW;
    END IF;
    IF propagating THEN RETURN NEW; END IF;

    IF correcting THEN
        IF OLD.parent_aggregation_id IS NOT NULL OR NEW.parent_aggregation_id IS NOT NULL
           OR NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id
           OR NULLIF(btrim(current_setting('app.change_reason', true)), '') IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='ownership correction is restricted to root aggregations and requires a reason';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.parent_aggregation_id IS NOT DISTINCT FROM OLD.parent_aggregation_id THEN
        IF NEW.owning_org_unit_id IS DISTINCT FROM OLD.owning_org_unit_id THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='owning_org_unit_id cannot be changed directly';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.parent_aggregation_id IS NULL THEN
        target_owner := OLD.owning_org_unit_id;
    ELSE
        SELECT owning_org_unit_id INTO STRICT target_owner
        FROM aggregations WHERE id = NEW.parent_aggregation_id FOR UPDATE;
    END IF;

    IF target_owner IS DISTINCT FROM OLD.owning_org_unit_id AND (
        NOT confirmed OR NULLIF(btrim(current_setting('app.change_reason', true)), '') IS NULL
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='ownership-changing aggregation moves require a reason and explicit confirmation';
    END IF;
    NEW.owning_org_unit_id := target_owner;
    RETURN NEW;
END;
$$;

CREATE FUNCTION propagate_aggregation_ownership()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous_context text;
BEGIN
    IF NEW.owning_org_unit_id IS NOT DISTINCT FROM OLD.owning_org_unit_id
       OR current_setting('app.ownership_propagation', true) = 'authorized' THEN
        RETURN NEW;
    END IF;
    previous_context := current_setting('app.ownership_propagation', true);
    PERFORM set_config('app.ownership_propagation', 'authorized', true);
    WITH RECURSIVE descendants(id) AS (
        SELECT child.id FROM aggregations child WHERE child.parent_aggregation_id = NEW.id
        UNION ALL
        SELECT child.id FROM descendants parent
        JOIN aggregations child ON child.parent_aggregation_id = parent.id
    )
    UPDATE aggregations child SET owning_org_unit_id = NEW.owning_org_unit_id
    FROM descendants WHERE child.id = descendants.id
      AND child.owning_org_unit_id IS DISTINCT FROM NEW.owning_org_unit_id;
    WITH RECURSIVE subtree(id) AS (
        SELECT NEW.id
        UNION ALL
        SELECT child.id FROM subtree parent
        JOIN aggregations child ON child.parent_aggregation_id = parent.id
    )
    UPDATE records record SET owning_org_unit_id = NEW.owning_org_unit_id
    FROM subtree WHERE record.aggregation_id = subtree.id
      AND record.owning_org_unit_id IS DISTINCT FROM NEW.owning_org_unit_id;
    PERFORM set_config('app.ownership_propagation', COALESCE(previous_context, ''), true);
    RETURN NEW;
END;
$$;

CREATE FUNCTION enforce_record_ownership()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target_owner bigint;
    confirmed boolean := COALESCE(NULLIF(current_setting('app.ownership_move_confirmed', true), '')::boolean, false);
    propagating boolean := current_setting('app.ownership_propagation', true) = 'authorized';
BEGIN
    IF TG_OP = 'UPDATE' AND propagating THEN RETURN NEW; END IF;
    IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
    SELECT owning_org_unit_id INTO STRICT target_owner
    FROM aggregations WHERE id = NEW.aggregation_id FOR UPDATE;
    IF TG_OP = 'INSERT' THEN
        NEW.owning_org_unit_id := target_owner;
        RETURN NEW;
    END IF;
    IF NEW.aggregation_id IS NOT DISTINCT FROM OLD.aggregation_id THEN
        IF NEW.owning_org_unit_id IS DISTINCT FROM OLD.owning_org_unit_id THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='owning_org_unit_id cannot be changed directly';
        END IF;
        RETURN NEW;
    END IF;
    IF target_owner IS DISTINCT FROM OLD.owning_org_unit_id AND (
        NOT confirmed OR NULLIF(btrim(current_setting('app.change_reason', true)), '') IS NULL
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='ownership-changing record moves require a reason and explicit confirmation';
    END IF;
    NEW.owning_org_unit_id := target_owner;
    RETURN NEW;
END;
$$;

CREATE TRIGGER aggregations_enforce_ownership
BEFORE INSERT OR UPDATE OF parent_aggregation_id, owning_org_unit_id ON aggregations
FOR EACH ROW EXECUTE FUNCTION enforce_aggregation_ownership();
CREATE TRIGGER aggregations_propagate_ownership
AFTER UPDATE OF parent_aggregation_id, owning_org_unit_id ON aggregations
FOR EACH ROW EXECUTE FUNCTION propagate_aggregation_ownership();
CREATE TRIGGER records_enforce_ownership
BEFORE INSERT OR UPDATE OF aggregation_id, owning_org_unit_id ON records
FOR EACH ROW EXECUTE FUNCTION enforce_record_ownership();


-- 047_expose_organizational_ownership_in_search.sql
CREATE OR REPLACE VIEW authorized_aggregations_for_search AS
SELECT resource.id,
       CASE WHEN resource.parent_aggregation_id IS NULL
                  OR current_user_can_view_aggregation(resource.parent_aggregation_id)
            THEN resource.parent_aggregation_id END AS parent_aggregation_id,
       resource.classification_id,resource.aggregation_number,resource.title,
       resource.description,resource.date_created,resource.date_opened,resource.date_closed,
       resource.security_level_id,resource.inherit_acl_from_parent,
       resource.default_child_aggregation_acl_mode,resource.resource_acl_version,
       resource.child_aggregation_acl_version,resource.child_record_acl_version,resource.version,
       resource.owning_org_unit_id
FROM aggregations resource;

CREATE OR REPLACE VIEW authorized_records_for_search AS
SELECT resource.id,
       CASE WHEN current_user_can_view_aggregation(resource.aggregation_id)
            THEN resource.aggregation_id END AS aggregation_id,
       resource.record_number,resource.title,resource.description,resource.date_created,
       resource.date_originated,resource.security_level_id,resource.inherit_acl_from_parent,
       resource.resource_acl_version,resource.version,resource.owning_org_unit_id
FROM records resource;


-- 048_add_org_unit_members_acl_principal.sql
CREATE OR REPLACE FUNCTION user_has_aggregation_permission(
  p_user_id bigint, p_aggregation_id bigint, p_permission text
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE
  cursor_row aggregations%ROWTYPE;
  parent_row aggregations%ROWTYPE;
  source_id bigint;
  source_kind text;
  target_owner_id bigint;
BEGIN
  SELECT * INTO cursor_row FROM aggregations WHERE id=p_aggregation_id;
  IF NOT FOUND THEN RETURN false; END IF;
  target_owner_id := cursor_row.owning_org_unit_id;
  IF NOT cursor_row.inherit_acl_from_parent OR cursor_row.parent_aggregation_id IS NULL THEN
    source_id := cursor_row.id; source_kind := 'resource';
  ELSE
    LOOP
      SELECT * INTO parent_row FROM aggregations WHERE id=cursor_row.parent_aggregation_id;
      IF NOT FOUND THEN RETURN false; END IF;
      IF parent_row.default_child_aggregation_acl_mode='custom' THEN
        source_id := parent_row.id; source_kind := 'child_default'; EXIT;
      ELSIF NOT parent_row.inherit_acl_from_parent OR parent_row.parent_aggregation_id IS NULL THEN
        source_id := parent_row.id; source_kind := 'resource'; EXIT;
      END IF;
      cursor_row := parent_row;
    END LOOP;
  END IF;

  IF source_kind='resource' THEN
    RETURN EXISTS (
      SELECT 1 FROM aggregation_acl_grants grant_row
      JOIN permissions permission ON permission.id=grant_row.permission_id
      WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
        AND (grant_row.principal_type='everyone'
          OR (grant_row.principal_type='role' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(assignment.role_id)))
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            JOIN roles role ON role.id=assignment.role_id
            WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(role.id))))
    );
  END IF;
  RETURN EXISTS (
    SELECT 1 FROM aggregation_child_aggregation_acl_defaults grant_row
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
        OR (grant_row.principal_type='role' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(assignment.role_id)))
        OR (grant_row.principal_type='org_unit_members' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          JOIN roles role ON role.id=assignment.role_id
          WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(role.id))))
  );
END $$;

CREATE OR REPLACE FUNCTION user_has_record_permission(
  p_user_id bigint, p_record_id bigint, p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN record_acl_grants grant_row ON NOT resource.inherit_acl_from_parent
      AND grant_row.record_id=resource.id AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  ) OR EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN aggregation_child_record_acl_defaults grant_row
      ON resource.inherit_acl_from_parent AND grant_row.aggregation_id=resource.aggregation_id
      AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;

CREATE OR REPLACE FUNCTION user_has_destination_record_permission(
  p_user_id bigint,p_aggregation_id bigint,p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS(
    SELECT 1 FROM aggregations resource
    JOIN aggregation_child_record_acl_defaults grant_row
      ON grant_row.aggregation_id=resource.id
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE resource.id=p_aggregation_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR (grant_row.principal_type='org_unit_members' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;




ALTER TABLE aggregations
    ADD COLUMN medium text NOT NULL DEFAULT 'mixed',
    ADD COLUMN is_vital boolean NOT NULL DEFAULT false,
    ADD COLUMN date_of_next_review timestamptz,
    ADD COLUMN assigned_location text,
    ADD COLUMN current_location text,
    ADD CONSTRAINT aggregations_medium_valid CHECK (medium IN ('digital','physical','mixed')),
    ADD CONSTRAINT aggregations_assigned_location_valid CHECK (
        assigned_location IS NULL OR (
            assigned_location=btrim(assigned_location)
            AND assigned_location<>'' AND char_length(assigned_location)<=200
        )
    ),
    ADD CONSTRAINT aggregations_current_location_valid CHECK (
        current_location IS NULL OR (
            current_location=btrim(current_location)
            AND current_location<>'' AND char_length(current_location)<=200
        )
    );

ALTER TABLE records
    ADD COLUMN medium text NOT NULL DEFAULT 'mixed',
    ADD COLUMN is_vital boolean NOT NULL DEFAULT false,
    ADD COLUMN date_of_next_review timestamptz,
    ADD CONSTRAINT records_medium_valid CHECK (medium IN ('digital','physical','mixed'));

CREATE INDEX aggregations_medium_idx ON aggregations(medium,id);
CREATE INDEX aggregations_vital_idx ON aggregations(is_vital,id);
CREATE INDEX aggregations_next_review_idx
    ON aggregations(date_of_next_review,id) WHERE date_of_next_review IS NOT NULL;
CREATE INDEX records_medium_idx ON records(medium,id);
CREATE INDEX records_vital_idx ON records(is_vital,id);
CREATE INDEX records_next_review_idx
    ON records(date_of_next_review,id) WHERE date_of_next_review IS NOT NULL;

CREATE FUNCTION enforce_future_next_review_date()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.date_of_next_review IS NOT NULL
       AND (TG_OP='INSERT' OR NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review)
       AND NEW.date_of_next_review<=CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='date_of_next_review must be in the future';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER aggregations_future_next_review
BEFORE INSERT OR UPDATE OF date_of_next_review ON aggregations
FOR EACH ROW EXECUTE FUNCTION enforce_future_next_review_date();

CREATE TRIGGER records_future_next_review
BEFORE INSERT OR UPDATE OF date_of_next_review ON records
FOR EACH ROW EXECUTE FUNCTION enforce_future_next_review_date();

CREATE FUNCTION aggregation_effective_assigned_location(p_aggregation_id bigint)
RETURNS text LANGUAGE sql STABLE AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id,parent_aggregation_id,assigned_location,0 AS depth
        FROM aggregations WHERE id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,parent.assigned_location,child.depth+1
        FROM ancestors child
        JOIN aggregations parent ON parent.id=child.parent_aggregation_id
    )
    SELECT assigned_location FROM ancestors
    WHERE assigned_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE FUNCTION aggregation_effective_current_location(p_aggregation_id bigint)
RETURNS text LANGUAGE sql STABLE AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id,parent_aggregation_id,current_location,0 AS depth
        FROM aggregations WHERE id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,parent.current_location,child.depth+1
        FROM ancestors child
        JOIN aggregations parent ON parent.id=child.parent_aggregation_id
    )
    SELECT current_location FROM ancestors
    WHERE current_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE FUNCTION aggregation_effective_assigned_location_source_id(p_aggregation_id bigint)
RETURNS bigint LANGUAGE sql STABLE AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id,parent_aggregation_id,assigned_location,0 AS depth FROM aggregations WHERE id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,parent.assigned_location,child.depth+1
        FROM ancestors child JOIN aggregations parent ON parent.id=child.parent_aggregation_id
    )
    SELECT id FROM ancestors WHERE assigned_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE FUNCTION aggregation_effective_current_location_source_id(p_aggregation_id bigint)
RETURNS bigint LANGUAGE sql STABLE AS $$
    WITH RECURSIVE ancestors AS (
        SELECT id,parent_aggregation_id,current_location,0 AS depth FROM aggregations WHERE id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,parent.current_location,child.depth+1
        FROM ancestors child JOIN aggregations parent ON parent.id=child.parent_aggregation_id
    )
    SELECT id FROM ancestors WHERE current_location IS NOT NULL ORDER BY depth LIMIT 1
$$;

CREATE OR REPLACE VIEW authorized_aggregations_for_search AS
SELECT resource.id,
       CASE WHEN resource.parent_aggregation_id IS NULL
                  OR current_user_can_view_aggregation(resource.parent_aggregation_id)
            THEN resource.parent_aggregation_id END AS parent_aggregation_id,
       resource.classification_id,resource.aggregation_number,resource.title,
       resource.description,resource.date_created,resource.date_opened,resource.date_closed,
       resource.security_level_id,resource.inherit_acl_from_parent,
       resource.default_child_aggregation_acl_mode,resource.resource_acl_version,
       resource.child_aggregation_acl_version,resource.child_record_acl_version,resource.version,
       resource.owning_org_unit_id,resource.medium,resource.is_vital,
       resource.date_of_next_review,resource.assigned_location,resource.current_location,
       aggregation_effective_assigned_location(resource.id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.id) AS effective_current_location
       ,CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.id)) THEN aggregation_effective_assigned_location_source_id(resource.id) END AS effective_assigned_location_source_aggregation_id
       ,CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.id)) THEN aggregation_effective_current_location_source_id(resource.id) END AS effective_current_location_source_aggregation_id
FROM aggregations resource;

CREATE OR REPLACE VIEW authorized_records_for_search AS
SELECT resource.id,
       CASE WHEN current_user_can_view_aggregation(resource.aggregation_id)
            THEN resource.aggregation_id END AS aggregation_id,
       resource.record_number,resource.title,resource.description,resource.date_created,
       resource.date_originated,resource.security_level_id,resource.inherit_acl_from_parent,
       resource.resource_acl_version,resource.version,resource.owning_org_unit_id,
       resource.medium,resource.is_vital,resource.date_of_next_review,
       aggregation_effective_assigned_location(resource.aggregation_id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.aggregation_id) AS effective_current_location
       ,CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.aggregation_id)) THEN aggregation_effective_assigned_location_source_id(resource.aggregation_id) END AS effective_assigned_location_source_aggregation_id
       ,CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.aggregation_id)) THEN aggregation_effective_current_location_source_id(resource.aggregation_id) END AS effective_current_location_source_aggregation_id
FROM records resource;


-- Full-text content search Phase 2 begins.
DO $$ BEGIN
    IF current_setting('server_version_num')::integer < 180000 THEN
        RAISE EXCEPTION 'Full-text search requires PostgreSQL 18 or newer';
    END IF;
END $$;

CREATE TABLE digital_component_search_documents (
    digital_component_id bigint PRIMARY KEY REFERENCES digital_components(id) ON DELETE CASCADE,
    record_id bigint NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    content_set_id bigint REFERENCES digital_component_content_sets(id) ON DELETE CASCADE,
    content_checksum_algo text,
    content_checksum_value text,
    status text NOT NULL,
    detected_mime_type text,
    detected_language text,
    extractor_name text,
    extractor_version text,
    extraction_config_version text NOT NULL,
    index_config_version text NOT NULL,
    indexed_at timestamptz,
    last_attempt_at timestamptz,
    last_error_code text,
    last_error_summary text,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT component_search_status_valid CHECK (
        status IN ('pending','processing','indexed','unsupported','failed','stale')
    ),
    CONSTRAINT component_search_identity_complete CHECK (
        (content_set_id IS NULL AND content_checksum_algo IS NULL AND content_checksum_value IS NULL)
        OR (content_set_id IS NOT NULL AND btrim(content_checksum_algo)<>'' AND btrim(content_checksum_value)<>'')
    ),
    CONSTRAINT component_search_error_summary_bounded CHECK (
        last_error_summary IS NULL OR length(last_error_summary)<=500
    )
);
CREATE INDEX component_search_status_reconcile_idx ON digital_component_search_documents
    (status,date_updated,digital_component_id);
CREATE INDEX component_search_record_idx ON digital_component_search_documents
    (record_id,digital_component_id);

CREATE TABLE digital_component_search_chunks (
    id bigserial PRIMARY KEY,
    digital_component_id bigint NOT NULL REFERENCES digital_component_search_documents(digital_component_id) ON DELETE CASCADE,
    chunk_no integer NOT NULL CHECK (chunk_no>=0),
    page_from integer,
    page_to integer,
    extracted_text text NOT NULL,
    search_vector tsvector NOT NULL,
    text_search_config regconfig NOT NULL,
    CONSTRAINT component_search_chunks_unique UNIQUE(digital_component_id,chunk_no),
    CONSTRAINT component_search_chunks_text_bounded CHECK (length(extracted_text)<=20000),
    CONSTRAINT component_search_chunks_pages_valid CHECK (
        (page_from IS NULL AND page_to IS NULL)
        OR (page_from>0 AND page_to>=page_from)
    )
);
CREATE INDEX component_search_chunks_vector_gin ON digital_component_search_chunks USING gin(search_vector);

CREATE TABLE content_indexing_jobs (
    id bigserial PRIMARY KEY,
    digital_component_id bigint NOT NULL REFERENCES digital_components(id) ON DELETE CASCADE,
    record_id bigint NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    content_set_id bigint NOT NULL REFERENCES digital_component_content_sets(id) ON DELETE CASCADE,
    content_checksum_algo text NOT NULL,
    content_checksum_value text NOT NULL,
    trigger text NOT NULL,
    priority smallint NOT NULL DEFAULT 0 CHECK (priority BETWEEN -100 AND 100),
    status text NOT NULL DEFAULT 'queued',
    not_before timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    lease_generation bigint NOT NULL DEFAULT 0 CHECK (lease_generation>=0),
    attempt_no integer NOT NULL DEFAULT 0 CHECK (attempt_no>=0),
    extraction_config_version text NOT NULL,
    index_config_version text NOT NULL,
    extractor_version text NOT NULL,
    required_capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
    queued_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at timestamptz,
    completed_at timestamptz,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT content_indexing_jobs_trigger_valid CHECK (
        trigger IN ('upload','replacement','manual_component','manual_record','backfill','retry','config_change')
    ),
    CONSTRAINT content_indexing_jobs_status_valid CHECK (
        status IN ('queued','leased','succeeded','failed','unsupported','cancelled','skipped')
    ),
    CONSTRAINT content_indexing_jobs_lease_shape CHECK (
        (status='leased' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status<>'leased')
    ),
    CONSTRAINT content_indexing_jobs_capabilities_object CHECK (jsonb_typeof(required_capabilities)='object')
);
CREATE UNIQUE INDEX content_indexing_jobs_active_unique
    ON content_indexing_jobs(
        digital_component_id,content_set_id,extraction_config_version,index_config_version,extractor_version
    ) WHERE status IN ('queued','leased');
CREATE INDEX content_indexing_jobs_claim_idx
    ON content_indexing_jobs(priority DESC,not_before,id)
    WHERE status IN ('queued','leased');
CREATE INDEX content_indexing_jobs_expired_lease_idx
    ON content_indexing_jobs(lease_expires_at,id) WHERE status='leased';

CREATE TABLE content_indexing_attempts (
    id bigserial PRIMARY KEY,
    digital_component_id bigint REFERENCES digital_components(id) ON DELETE SET NULL,
    record_id bigint REFERENCES records(id) ON DELETE SET NULL,
    content_set_id bigint REFERENCES digital_component_content_sets(id) ON DELETE SET NULL,
    content_checksum_algo text NOT NULL,
    content_checksum_value text NOT NULL,
    trigger text NOT NULL,
    requested_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    job_id bigint REFERENCES content_indexing_jobs(id) ON DELETE SET NULL,
    worker_id text,
    lease_generation bigint,
    status text NOT NULL,
    attempt_no integer NOT NULL CHECK (attempt_no>0),
    queued_at timestamptz NOT NULL,
    started_at timestamptz,
    completed_at timestamptz,
    extractor_name text,
    extractor_version text,
    extraction_config_version text NOT NULL,
    index_config_version text NOT NULL,
    characters_extracted bigint CHECK (characters_extracted IS NULL OR characters_extracted>=0),
    chunks_created integer CHECK (chunks_created IS NULL OR chunks_created>=0),
    ocr_used boolean NOT NULL DEFAULT false,
    error_code text,
    error_summary text,
    request_id text,
    correlation_id text,
    CONSTRAINT content_indexing_attempts_status_valid CHECK (
        status IN ('processing','succeeded','failed','unsupported','cancelled','lease_lost','skipped')
    ),
    CONSTRAINT content_indexing_attempts_error_bounded CHECK (error_summary IS NULL OR length(error_summary)<=500),
    CONSTRAINT content_indexing_attempts_generation_unique UNIQUE(job_id,lease_generation)
);
CREATE INDEX content_indexing_attempts_completed_idx ON content_indexing_attempts(completed_at,id)
    WHERE status<>'processing';

CREATE TABLE content_indexing_result_chunks (
    job_id bigint NOT NULL REFERENCES content_indexing_jobs(id) ON DELETE CASCADE,
    lease_generation bigint NOT NULL,
    chunk_no integer NOT NULL CHECK (chunk_no>=0),
    page_from integer,
    page_to integer,
    extracted_text text NOT NULL,
    text_digest text NOT NULL,
    detected_language text,
    language_decision text NOT NULL,
    text_search_config regconfig NOT NULL,
    characters_count integer NOT NULL CHECK (characters_count>=0),
    date_staged timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(job_id,lease_generation,chunk_no),
    CONSTRAINT result_chunks_text_bounded CHECK (length(extracted_text)<=20000),
    CONSTRAINT result_chunks_digest_format CHECK (text_digest~'^[0-9a-f]{64}$'),
    CONSTRAINT result_chunks_language_decision_valid CHECK (
        language_decision IN ('english','arabic','mixed','unknown','short','low_confidence','unsupported_script','code_like')
    ),
    CONSTRAINT result_chunks_pages_valid CHECK (
        (page_from IS NULL AND page_to IS NULL) OR (page_from>0 AND page_to>=page_from)
    )
);
CREATE INDEX result_chunks_cleanup_idx ON content_indexing_result_chunks(date_staged,job_id,lease_generation);

CREATE TABLE content_indexing_operations (
    job_id bigint NOT NULL REFERENCES content_indexing_jobs(id) ON DELETE CASCADE,
    lease_generation bigint NOT NULL,
    operation text NOT NULL CHECK (operation IN ('chunk','complete','fail')),
    idempotency_key text NOT NULL,
    response jsonb NOT NULL,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(job_id,lease_generation,operation,idempotency_key),
    CONSTRAINT content_indexing_operations_key_bounded CHECK (
        btrim(idempotency_key)<>'' AND length(idempotency_key)<=200
    )
);

CREATE TABLE text_indexing_workers (
    service_user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    worker_id text NOT NULL,
    contract_version text NOT NULL,
    extractor_version text NOT NULL,
    extraction_config_version text NOT NULL,
    index_config_version text NOT NULL,
    capabilities jsonb NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_contact_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active_until timestamptz NOT NULL,
    current_job_id bigint REFERENCES content_indexing_jobs(id) ON DELETE SET NULL,
    PRIMARY KEY(service_user_id,worker_id),
    CONSTRAINT text_indexing_workers_id_bounded CHECK (btrim(worker_id)<>'' AND length(worker_id)<=200),
    CONSTRAINT text_indexing_workers_capabilities_object CHECK (jsonb_typeof(capabilities)='object')
);
CREATE INDEX text_indexing_workers_active_idx ON text_indexing_workers(active_until,service_user_id,worker_id);

CREATE FUNCTION validate_component_search_identity()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.content_set_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM digital_component_content_sets content_set
        WHERE content_set.id=NEW.content_set_id
          AND content_set.digital_component_id=NEW.digital_component_id
    ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='search content set does not belong to component'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM digital_components component
        WHERE component.id=NEW.digital_component_id AND component.record_id=NEW.record_id
    ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='search record does not match component'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER component_search_validate_identity BEFORE INSERT OR UPDATE
ON digital_component_search_documents FOR EACH ROW EXECUTE FUNCTION validate_component_search_identity();

CREATE FUNCTION schedule_component_content_indexing()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    active_set digital_component_content_sets%ROWTYPE;
    schedule_trigger text;
BEGIN
    IF NEW.content_status<>'available' OR NEW.active_content_set_id IS NULL THEN
        UPDATE digital_component_search_documents SET status='stale',date_updated=CURRENT_TIMESTAMP
         WHERE digital_component_id=NEW.id;
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT active_set FROM digital_component_content_sets
     WHERE id=NEW.active_content_set_id AND digital_component_id=NEW.id AND status='active';
    schedule_trigger:=CASE WHEN TG_OP='INSERT' OR OLD.active_content_set_id IS NULL THEN 'upload' ELSE 'replacement' END;
    UPDATE digital_component_search_documents SET status='stale',date_updated=CURRENT_TIMESTAMP
     WHERE digital_component_id=NEW.id AND content_set_id IS DISTINCT FROM active_set.id;
    INSERT INTO digital_component_search_documents(
        digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
        status,extraction_config_version,index_config_version,date_updated
    ) VALUES (NEW.id,NEW.record_id,active_set.id,active_set.checksum_algo,active_set.checksum_value,
              'pending','tika-4.0.0-ocr-eng-ara-v1','fts-content-v1',CURRENT_TIMESTAMP)
    ON CONFLICT(digital_component_id) DO UPDATE SET
        record_id=EXCLUDED.record_id,content_set_id=EXCLUDED.content_set_id,
        content_checksum_algo=EXCLUDED.content_checksum_algo,
        content_checksum_value=EXCLUDED.content_checksum_value,status='pending',
        extraction_config_version=EXCLUDED.extraction_config_version,
        index_config_version=EXCLUDED.index_config_version,indexed_at=NULL,
        last_error_code=NULL,last_error_summary=NULL,date_updated=CURRENT_TIMESTAMP;
    IF coalesce(nullif(current_setting('app.content_indexing_scheduling_enabled',true),''),'true')<>'true' THEN
        RETURN NEW;
    END IF;
    INSERT INTO content_indexing_jobs(
        digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
        trigger,extraction_config_version,index_config_version,extractor_version,required_capabilities
    ) VALUES (NEW.id,NEW.record_id,active_set.id,active_set.checksum_algo,active_set.checksum_value,
              schedule_trigger,'tika-4.0.0-ocr-eng-ara-v1','fts-content-v1','4.0.0',
              jsonb_build_object('mime_type',NEW.mime_type,'max_input_bytes',52428800))
    ON CONFLICT(digital_component_id,content_set_id,extraction_config_version,index_config_version,extractor_version)
        WHERE status IN ('queued','leased') DO NOTHING;
    RETURN NEW;
END $$;
CREATE TRIGGER digital_components_schedule_content_indexing
AFTER INSERT OR UPDATE OF active_content_set_id,content_status ON digital_components
FOR EACH ROW EXECUTE FUNCTION schedule_component_content_indexing();

-- Full-text content search Phase 2 ends.

COMMIT;

-- Legal holds: persistence and non-bypassable policy enforcement.
BEGIN;

CREATE TABLE holds (
    id                      bigserial PRIMARY KEY,
    code                    text NOT NULL,
    name                    text NOT NULL,
    description             text,
    valid_from              timestamptz NOT NULL,
    valid_to                timestamptz,
    owner_user_id           bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    preserve_resource_state boolean NOT NULL DEFAULT false,
    date_created            timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated            timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version                 bigint NOT NULL DEFAULT 1,
    CONSTRAINT holds_code_valid CHECK (code=btrim(code) AND code<>'' AND char_length(code)<=100),
    CONSTRAINT holds_name_valid CHECK (name=btrim(name) AND name<>'' AND char_length(name)<=300),
    CONSTRAINT holds_description_length CHECK (description IS NULL OR char_length(description)<=4000),
    CONSTRAINT holds_dates_in_order CHECK (valid_to IS NULL OR valid_to>valid_from),
    CONSTRAINT holds_version_positive CHECK (version>0)
);
CREATE UNIQUE INDEX holds_code_ci_unique ON holds(lower(code));
CREATE INDEX holds_effective_period_idx ON holds(valid_from,valid_to,id);
CREATE INDEX holds_owner_idx ON holds(owner_user_id,id);

CREATE TABLE hold_contributors (
    id           bigserial PRIMARY KEY,
    hold_id      bigint NOT NULL REFERENCES holds(id) ON DELETE CASCADE,
    user_id      bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version      bigint NOT NULL DEFAULT 1 CHECK (version>0),
    CONSTRAINT hold_contributors_unique UNIQUE(hold_id,user_id)
);
CREATE INDEX hold_contributors_user_idx ON hold_contributors(user_id,hold_id);

CREATE TABLE hold_aggregation_assignments (
    id                  bigserial PRIMARY KEY,
    hold_id             bigint NOT NULL REFERENCES holds(id) ON DELETE RESTRICT,
    aggregation_id      bigint NOT NULL REFERENCES aggregations(id) ON DELETE CASCADE,
    assigned_at         timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    version             bigint NOT NULL DEFAULT 1 CHECK (version>0),
    CONSTRAINT hold_aggregation_assignments_unique UNIQUE(hold_id,aggregation_id)
);
CREATE INDEX hold_aggregation_assignments_resource_idx
    ON hold_aggregation_assignments(aggregation_id,hold_id);

CREATE TABLE hold_record_assignments (
    id                  bigserial PRIMARY KEY,
    hold_id             bigint NOT NULL REFERENCES holds(id) ON DELETE RESTRICT,
    record_id           bigint NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    assigned_at         timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    version             bigint NOT NULL DEFAULT 1 CHECK (version>0),
    CONSTRAINT hold_record_assignments_unique UNIQUE(hold_id,record_id)
);
CREATE INDEX hold_record_assignments_resource_idx
    ON hold_record_assignments(record_id,hold_id);

INSERT INTO privileges(code,name,description,category,is_reserved)
VALUES ('holds.administer','Administer Legal Holds',
        'Create, update, and delete legal holds and manage their owners and contributors.',
        'administration',false),
       ('holds.held_items.manage_all','Manage All Legal Hold Items',
        'Add or remove held items from any legal hold.',
        'administration',false)
ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id
FROM profiles profile CROSS JOIN privileges privilege
WHERE (profile.code='ALL_PRIVS' AND privilege.code IN ('holds.administer','holds.held_items.manage_all'))
   OR (profile.code IN ('INFO_GOV_MGR','INFO_GOV_OFFICER')
       AND privilege.code='holds.held_items.manage_all')
ON CONFLICT DO NOTHING;

CREATE FUNCTION hold_is_effective(p_hold_id bigint,p_at_time timestamptz DEFAULT statement_timestamp())
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT COALESCE(
        (hold.valid_from<=p_at_time AND (hold.valid_to IS NULL OR p_at_time<hold.valid_to)),
        false
    ) FROM holds hold WHERE hold.id=p_hold_id
$$;

CREATE FUNCTION effective_holds_for_aggregation(
    p_aggregation_id bigint,p_at_time timestamptz DEFAULT statement_timestamp()
) RETURNS TABLE(
    hold_id bigint,code text,name text,preserve_resource_state boolean,
    is_direct boolean,is_inherited boolean,nearest_assigned_aggregation_id bigint
) LANGUAGE sql STABLE AS $$
    WITH RECURSIVE ancestry AS (
        SELECT aggregation.id,aggregation.parent_aggregation_id,0 AS depth
        FROM aggregations aggregation WHERE aggregation.id=p_aggregation_id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,child.depth+1
        FROM aggregations parent JOIN ancestry child ON child.parent_aggregation_id=parent.id
    ), matched AS (
        SELECT assignment.hold_id,ancestry.id AS assigned_aggregation_id,ancestry.depth
        FROM ancestry
        JOIN hold_aggregation_assignments assignment ON assignment.aggregation_id=ancestry.id
    )
    SELECT hold.id,hold.code,hold.name,hold.preserve_resource_state,
           bool_or(matched.depth=0),bool_or(matched.depth>0),
           (array_agg(matched.assigned_aggregation_id ORDER BY matched.depth))[1]
    FROM matched JOIN holds hold ON hold.id=matched.hold_id
    WHERE hold.valid_from<=p_at_time AND (hold.valid_to IS NULL OR p_at_time<hold.valid_to)
    GROUP BY hold.id,hold.code,hold.name,hold.preserve_resource_state
$$;

CREATE FUNCTION effective_holds_for_record(
    p_record_id bigint,p_at_time timestamptz DEFAULT statement_timestamp()
) RETURNS TABLE(
    hold_id bigint,code text,name text,preserve_resource_state boolean,
    is_direct boolean,is_inherited boolean,nearest_assigned_aggregation_id bigint
) LANGUAGE sql STABLE AS $$
    WITH RECURSIVE record_row AS (
        SELECT id,aggregation_id FROM records WHERE id=p_record_id
    ), ancestry AS (
        SELECT aggregation.id,aggregation.parent_aggregation_id,0 AS depth
        FROM aggregations aggregation JOIN record_row ON record_row.aggregation_id=aggregation.id
        UNION ALL
        SELECT parent.id,parent.parent_aggregation_id,child.depth+1
        FROM aggregations parent JOIN ancestry child ON child.parent_aggregation_id=parent.id
    ), matched AS (
        SELECT assignment.hold_id,true AS direct,false AS inherited,
               NULL::bigint AS assigned_aggregation_id,NULL::integer AS depth
        FROM record_row JOIN hold_record_assignments assignment ON assignment.record_id=record_row.id
        UNION ALL
        SELECT assignment.hold_id,false,true,ancestry.id,ancestry.depth
        FROM ancestry
        JOIN hold_aggregation_assignments assignment ON assignment.aggregation_id=ancestry.id
    )
    SELECT hold.id,hold.code,hold.name,hold.preserve_resource_state,
           bool_or(matched.direct),bool_or(matched.inherited),
           (array_agg(matched.assigned_aggregation_id ORDER BY matched.depth NULLS LAST)
             FILTER (WHERE matched.assigned_aggregation_id IS NOT NULL))[1]
    FROM matched JOIN holds hold ON hold.id=matched.hold_id
    WHERE hold.valid_from<=p_at_time AND (hold.valid_to IS NULL OR p_at_time<hold.valid_to)
    GROUP BY hold.id,hold.code,hold.name,hold.preserve_resource_state
$$;

CREATE FUNCTION resource_has_effective_hold(
    p_resource_type text,p_resource_id bigint,p_at_time timestamptz DEFAULT statement_timestamp()
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF p_resource_type='aggregation' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_aggregation(p_resource_id,p_at_time));
    ELSIF p_resource_type='record' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_record(p_resource_id,p_at_time));
    END IF;
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='unknown hold resource type';
END;
$$;

CREATE FUNCTION resource_state_changes_blocked(
    p_resource_type text,p_resource_id bigint,p_at_time timestamptz DEFAULT statement_timestamp()
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF p_resource_type='aggregation' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_aggregation(p_resource_id,p_at_time)
                      WHERE preserve_resource_state);
    ELSIF p_resource_type='record' THEN
        RETURN EXISTS(SELECT 1 FROM effective_holds_for_record(p_resource_id,p_at_time)
                      WHERE preserve_resource_state);
    END IF;
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='unknown hold resource type';
END;
$$;

CREATE FUNCTION current_hold_actor_is_manager(p_hold_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS(
        SELECT 1 FROM holds hold JOIN users actor ON actor.id=NULLIF(current_setting('app.user_id',true),'')::bigint
        WHERE hold.id=p_hold_id AND actor.account_type='person'
          AND actor.date_deactivated IS NULL AND actor.date_suspended IS NULL
          AND (user_has_global_privilege(actor.id,'holds.administer')
               OR user_has_global_privilege(actor.id,'holds.held_items.manage_all')
               OR hold.owner_user_id=actor.id OR EXISTS(
              SELECT 1 FROM hold_contributors contributor
              WHERE contributor.hold_id=hold.id AND contributor.user_id=actor.id))
    )
$$;

CREATE FUNCTION lock_hold_policy_shared() RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock_shared(7246,1); END;
$$;
CREATE FUNCTION lock_hold_policy_exclusive() RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_advisory_xact_lock(7246,1); END;
$$;

CREATE FUNCTION validate_hold_person_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_user_id bigint;
BEGIN
    IF TG_TABLE_NAME='holds' THEN
        selected_user_id:=NEW.owner_user_id;
    ELSE
        selected_user_id:=NEW.user_id;
    END IF;
    IF NOT EXISTS(SELECT 1 FROM users WHERE id=selected_user_id AND account_type='person'
                  AND date_deactivated IS NULL AND date_suspended IS NULL) THEN
        RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='hold_owner_or_contributor_must_be_active_person';
    END IF;
    IF TG_TABLE_NAME='hold_contributors' THEN
        IF EXISTS(SELECT 1 FROM holds WHERE id=NEW.hold_id AND owner_user_id=NEW.user_id) THEN
            RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='hold_owner_cannot_be_contributor';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER holds_validate_owner BEFORE INSERT OR UPDATE OF owner_user_id ON holds
FOR EACH ROW EXECUTE FUNCTION validate_hold_person_reference();
CREATE TRIGGER hold_contributors_validate_user BEFORE INSERT OR UPDATE OF hold_id,user_id ON hold_contributors
FOR EACH ROW EXECUTE FUNCTION validate_hold_person_reference();

CREATE FUNCTION enforce_hold_change_reason() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE hold_created_in_transaction boolean:=false;
BEGIN
    PERFORM lock_hold_policy_exclusive();
    IF TG_TABLE_NAME='hold_contributors' AND TG_OP='DELETE' AND pg_trigger_depth()>1 THEN
        RETURN OLD;
    END IF;
    IF TG_TABLE_NAME='hold_contributors' AND TG_OP='INSERT' THEN
        SELECT xmin::text=pg_current_xact_id()::text INTO hold_created_in_transaction
        FROM holds WHERE id=NEW.hold_id;
    END IF;
    IF NOT hold_created_in_transaction
       AND NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_change_reason_required';
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER holds_require_change_reason
BEFORE UPDATE OR DELETE ON holds FOR EACH ROW EXECUTE FUNCTION enforce_hold_change_reason();
CREATE TRIGGER hold_contributors_require_change_reason
BEFORE INSERT OR UPDATE OR DELETE ON hold_contributors FOR EACH ROW EXECUTE FUNCTION enforce_hold_change_reason();

CREATE FUNCTION enforce_hold_assignment_policy() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target_hold_id bigint:=CASE WHEN TG_OP='DELETE' THEN OLD.hold_id ELSE NEW.hold_id END;
BEGIN
    PERFORM lock_hold_policy_exclusive();
    IF NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_change_reason_required';
    END IF;
    IF NOT current_hold_actor_is_manager(target_hold_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_manager_required';
    END IF;
    IF TG_OP='INSERT' AND NEW.assigned_by_user_id IS NULL THEN
        NEW.assigned_by_user_id:=NULLIF(current_setting('app.user_id',true),'')::bigint;
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER hold_aggregation_assignments_policy
BEFORE INSERT OR UPDATE OR DELETE ON hold_aggregation_assignments
FOR EACH ROW EXECUTE FUNCTION enforce_hold_assignment_policy();
CREATE TRIGGER hold_record_assignments_policy
BEFORE INSERT OR UPDATE OR DELETE ON hold_record_assignments
FOR EACH ROW EXECUTE FUNCTION enforce_hold_assignment_policy();

CREATE FUNCTION protect_held_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE blocked boolean;
DECLARE allowed_old jsonb;
DECLARE allowed_new jsonb;
BEGIN
    PERFORM lock_hold_policy_shared();
    IF TG_OP='DELETE' THEN
        IF TG_TABLE_NAME='aggregations' THEN
            WITH RECURSIVE subtree AS (
                SELECT OLD.id AS id UNION ALL
                SELECT child.id FROM aggregations child JOIN subtree parent ON child.parent_aggregation_id=parent.id
            )
            SELECT EXISTS(
                SELECT 1 FROM subtree WHERE resource_has_effective_hold('aggregation',subtree.id)
                UNION ALL
                SELECT 1 FROM records record JOIN subtree ON subtree.id=record.aggregation_id
                WHERE resource_has_effective_hold('record',record.id)
            ) INTO blocked;
        ELSE
            blocked:=resource_has_effective_hold('record',OLD.id);
        END IF;
        IF blocked THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_deletion'; END IF;
        RETURN OLD;
    END IF;

    IF TG_TABLE_NAME='aggregations' THEN
        blocked:=resource_state_changes_blocked('aggregation',OLD.id);
        IF NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id THEN
            IF blocked OR (NEW.parent_aggregation_id IS NOT NULL AND EXISTS(
                SELECT 1 FROM effective_holds_for_aggregation(NEW.parent_aggregation_id) WHERE preserve_resource_state
            )) THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
            IF EXISTS(
                WITH old_holds AS (SELECT hold_id FROM effective_holds_for_aggregation(OLD.id)),
                     new_ancestor_holds AS (
                         SELECT hold_id FROM effective_holds_for_aggregation(NEW.parent_aggregation_id)
                         UNION SELECT hold_id FROM hold_aggregation_assignments WHERE aggregation_id=OLD.id AND hold_is_effective(hold_id)
                     ), changed AS ((SELECT * FROM old_holds EXCEPT SELECT * FROM new_ancestor_holds)
                                    UNION (SELECT * FROM new_ancestor_holds EXCEPT SELECT * FROM old_holds))
                SELECT 1 FROM changed WHERE NOT current_hold_actor_is_manager(changed.hold_id)
            ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_management_required_for_held_move'; END IF;
        END IF;
        IF blocked THEN
            allowed_old:=to_jsonb(OLD)-ARRAY['security_level_id','owning_org_unit_id','assigned_location','current_location',
                'inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','version'];
            allowed_new:=to_jsonb(NEW)-ARRAY['security_level_id','owning_org_unit_id','assigned_location','current_location',
                'inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','version'];
            IF allowed_old IS DISTINCT FROM allowed_new THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
        END IF;
    ELSE
        blocked:=resource_state_changes_blocked('record',OLD.id);
        IF NEW.aggregation_id IS DISTINCT FROM OLD.aggregation_id THEN
            IF blocked OR EXISTS(SELECT 1 FROM effective_holds_for_aggregation(NEW.aggregation_id)
                                 WHERE preserve_resource_state) THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
            IF EXISTS(
                WITH old_holds AS (SELECT hold_id FROM effective_holds_for_record(OLD.id)),
                     new_holds AS (
                         SELECT hold_id FROM effective_holds_for_aggregation(NEW.aggregation_id)
                         UNION SELECT hold_id FROM hold_record_assignments WHERE record_id=OLD.id AND hold_is_effective(hold_id)
                     ), changed AS ((SELECT * FROM old_holds EXCEPT SELECT * FROM new_holds)
                                    UNION (SELECT * FROM new_holds EXCEPT SELECT * FROM old_holds))
                SELECT 1 FROM changed WHERE NOT current_hold_actor_is_manager(changed.hold_id)
            ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_management_required_for_held_move'; END IF;
        END IF;
        IF blocked THEN
            allowed_old:=to_jsonb(OLD)-ARRAY['security_level_id','owning_org_unit_id','inherit_acl_from_parent',
                'resource_acl_version','version'];
            allowed_new:=to_jsonb(NEW)-ARRAY['security_level_id','owning_org_unit_id','inherit_acl_from_parent',
                'resource_acl_version','version'];
            IF allowed_old IS DISTINCT FROM allowed_new THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER aggregations_protect_effective_holds
BEFORE UPDATE OR DELETE ON aggregations FOR EACH ROW EXECUTE FUNCTION protect_held_resource();
CREATE TRIGGER records_protect_effective_holds
BEFORE UPDATE OR DELETE ON records FOR EACH ROW EXECUTE FUNCTION protect_held_resource();

CREATE FUNCTION protect_held_component_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
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
        IF TG_TABLE_NAME='digital_components' AND TG_OP='UPDATE'
           AND NEW.component_order IS DISTINCT FROM OLD.component_order THEN
            failure_code:='effective_hold_prevents_component_reordering';
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE=failure_code;
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER digital_components_protect_effective_holds
BEFORE INSERT OR UPDATE OR DELETE ON digital_components FOR EACH ROW EXECUTE FUNCTION protect_held_component_mutation();
CREATE TRIGGER digital_component_content_sets_protect_effective_holds
BEFORE INSERT OR UPDATE OR DELETE ON digital_component_content_sets FOR EACH ROW EXECUTE FUNCTION protect_held_component_mutation();
CREATE TRIGGER digital_component_blobs_protect_effective_holds
BEFORE INSERT OR UPDATE OR DELETE ON digital_component_blobs FOR EACH ROW EXECUTE FUNCTION protect_held_component_mutation();
CREATE TRIGGER content_upload_sessions_protect_effective_holds
BEFORE INSERT OR UPDATE OR DELETE ON content_upload_sessions FOR EACH ROW EXECUTE FUNCTION protect_held_component_mutation();

CREATE FUNCTION prevent_nonempty_hold_deletion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM hold_aggregation_assignments WHERE hold_id=OLD.id)
       OR EXISTS (SELECT 1 FROM hold_record_assignments WHERE hold_id=OLD.id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_not_empty';
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER holds_prevent_nonempty_deletion
BEFORE DELETE ON holds FOR EACH ROW EXECUTE FUNCTION prevent_nonempty_hold_deletion();

CREATE FUNCTION touch_hold() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.version:=OLD.version+1; NEW.date_updated:=CURRENT_TIMESTAMP; RETURN NEW; END;
$$;
CREATE TRIGGER holds_bump_version BEFORE UPDATE ON holds
FOR EACH ROW EXECUTE FUNCTION touch_hold();
CREATE TRIGGER hold_contributors_bump_version BEFORE UPDATE ON hold_contributors
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();
CREATE TRIGGER hold_aggregation_assignments_bump_version BEFORE UPDATE ON hold_aggregation_assignments
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();
CREATE TRIGGER hold_record_assignments_bump_version BEFORE UPDATE ON hold_record_assignments
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();

CREATE TRIGGER holds_record_history AFTER INSERT OR UPDATE OR DELETE ON holds
FOR EACH ROW EXECUTE FUNCTION record_entity_history('hold');
CREATE TRIGGER hold_contributors_record_history AFTER INSERT OR UPDATE OR DELETE ON hold_contributors
FOR EACH ROW EXECUTE FUNCTION record_entity_history('hold_contributor');
CREATE TRIGGER hold_aggregation_assignments_record_history AFTER INSERT OR UPDATE OR DELETE ON hold_aggregation_assignments
FOR EACH ROW EXECUTE FUNCTION record_entity_history('hold_aggregation_assignment');
CREATE TRIGGER hold_record_assignments_record_history AFTER INSERT OR UPDATE OR DELETE ON hold_record_assignments
FOR EACH ROW EXECUTE FUNCTION record_entity_history('hold_record_assignment');

CREATE FUNCTION populate_hold_event_reference_snapshots() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE state jsonb:=COALESCE(NEW.after_state,NEW.before_state,'{}'::jsonb);
DECLARE snapshots jsonb:='{}'::jsonb;
DECLARE reference_id bigint;
DECLARE snapshot jsonb;
DECLARE existing_snapshots jsonb;
BEGIN
    IF NEW.entity_type='hold' THEN
        snapshots:=jsonb_build_object('hold',jsonb_strip_nulls(jsonb_build_object(
            'id',NEW.entity_id,'code',state->>'code','name',state->>'name')));
    ELSIF NEW.entity_type IN ('hold_contributor','hold_aggregation_assignment','hold_record_assignment') THEN
        reference_id:=NULLIF(state->>'hold_id','')::bigint;
        SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot
        FROM holds WHERE id=reference_id;
        IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('hold',snapshot); END IF;
        IF NEW.entity_type='hold_contributor' THEN
            reference_id:=NULLIF(state->>'user_id','')::bigint;
            SELECT jsonb_strip_nulls(jsonb_build_object('id',id,'name',name,'email',email)) INTO snapshot
            FROM users WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('user',snapshot); END IF;
        ELSIF NEW.entity_type='hold_aggregation_assignment' THEN
            reference_id:=NULLIF(state->>'aggregation_id','')::bigint;
            SELECT jsonb_build_object('id',id,'number',aggregation_number,'title',title) INTO snapshot
            FROM aggregations WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('aggregation',snapshot); END IF;
        ELSE
            reference_id:=NULLIF(state->>'record_id','')::bigint;
            SELECT jsonb_build_object('id',id,'number',record_number,'title',title) INTO snapshot
            FROM records WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('record',snapshot); END IF;
        END IF;
    ELSE
        IF NEW.metadata ? 'hold_id' THEN
            reference_id:=NULLIF(NEW.metadata->>'hold_id','')::bigint;
            SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot
            FROM holds WHERE id=reference_id;
            IF snapshot IS NOT NULL THEN snapshots:=snapshots||jsonb_build_object('hold',snapshot); END IF;
        ELSE
            RETURN NEW;
        END IF;
    END IF;
    IF snapshots<>'{}'::jsonb THEN
        existing_snapshots:=COALESCE(NEW.metadata->'reference_snapshots','{}'::jsonb);
        NEW.metadata:=NEW.metadata||jsonb_build_object(
            'reference_snapshots',existing_snapshots||snapshots);
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER event_history_z_hold_reference_snapshots
BEFORE INSERT ON event_history FOR EACH ROW EXECUTE FUNCTION populate_hold_event_reference_snapshots();

CREATE FUNCTION append_hold_definition_domain_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE entity_id bigint:=CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
DECLARE operation_name text:=CASE TG_OP WHEN 'INSERT' THEN 'HOLD_CREATED' WHEN 'UPDATE' THEN 'HOLD_UPDATED' ELSE 'HOLD_DELETED' END;
DECLARE old_state jsonb:=CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) ELSE NULL END;
DECLARE new_state jsonb:=CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) ELSE NULL END;
BEGIN
    IF TG_OP='INSERT' THEN
        new_state:=new_state||jsonb_build_object(
            'contributor_user_ids',COALESCE(NULLIF(current_setting('app.hold_contributor_ids',true),'')::jsonb,'[]'::jsonb));
    END IF;
    PERFORM append_domain_event('hold',entity_id,operation_name,
        jsonb_strip_nulls(jsonb_build_object('before',old_state,'after',new_state)));
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER holds_domain_events AFTER INSERT OR UPDATE OR DELETE ON holds
FOR EACH ROW EXECUTE FUNCTION append_hold_definition_domain_event();

CREATE FUNCTION append_hold_assignment_domain_events() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE state record;
DECLARE operation_name text:=CASE WHEN TG_OP='INSERT' THEN 'RESOURCE_ADDED_TO_HOLD' ELSE 'RESOURCE_REMOVED_FROM_HOLD' END;
DECLARE resource_type text:=CASE WHEN TG_TABLE_NAME='hold_aggregation_assignments' THEN 'aggregation' ELSE 'record' END;
DECLARE resource_id bigint;
DECLARE metadata jsonb;
BEGIN
    IF TG_OP='UPDATE' THEN RETURN NEW; END IF;
    IF TG_OP='DELETE' THEN state:=OLD; ELSE state:=NEW; END IF;
    IF resource_type='aggregation' THEN resource_id:=state.aggregation_id; ELSE resource_id:=state.record_id; END IF;
    metadata:=jsonb_build_object('hold_id',state.hold_id,'resource_type',resource_type,
                                 'resource_id',resource_id,'assignment_id',state.id);
    IF TG_OP='DELETE' THEN
        IF resource_type='aggregation' THEN
            metadata:=metadata||jsonb_build_object('remaining_effective_hold_ids',
                COALESCE((SELECT jsonb_agg(hold_id ORDER BY hold_id) FROM effective_holds_for_aggregation(resource_id)),'[]'::jsonb));
        ELSE
            metadata:=metadata||jsonb_build_object('remaining_effective_hold_ids',
                COALESCE((SELECT jsonb_agg(hold_id ORDER BY hold_id) FROM effective_holds_for_record(resource_id)),'[]'::jsonb));
        END IF;
    END IF;
    PERFORM append_domain_event('hold',state.hold_id,operation_name,metadata);
    PERFORM append_domain_event(resource_type,resource_id,operation_name,metadata);
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER hold_aggregation_assignments_domain_events
AFTER INSERT OR DELETE ON hold_aggregation_assignments
FOR EACH ROW EXECUTE FUNCTION append_hold_assignment_domain_events();
CREATE TRIGGER hold_record_assignments_domain_events
AFTER INSERT OR DELETE ON hold_record_assignments
FOR EACH ROW EXECUTE FUNCTION append_hold_assignment_domain_events();

CREATE OR REPLACE VIEW authorized_aggregations_for_search AS
SELECT resource.id,
       -- Search predicates must use the true relationship. The API redacts an
       -- inaccessible parent only after filtering and adds parent_aggregation_state.
       resource.parent_aggregation_id,
       resource.classification_id,resource.aggregation_number,resource.title,resource.description,
       resource.date_created,resource.date_opened,resource.date_closed,resource.security_level_id,
       resource.inherit_acl_from_parent,resource.default_child_aggregation_acl_mode,
       resource.resource_acl_version,resource.child_aggregation_acl_version,resource.child_record_acl_version,
       resource.version,resource.owning_org_unit_id,resource.medium,resource.is_vital,
       resource.date_of_next_review,resource.assigned_location,resource.current_location,
       aggregation_effective_assigned_location(resource.id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.id) AS effective_current_location,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.id))
            THEN aggregation_effective_assigned_location_source_id(resource.id) END AS effective_assigned_location_source_aggregation_id,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.id))
            THEN aggregation_effective_current_location_source_id(resource.id) END AS effective_current_location_source_aggregation_id,
       hold_state.effective_hold_count > 0 AS on_effective_hold,
       hold_state.resource_state_changes_blocked,
       hold_state.effective_hold_ids
FROM aggregations resource
CROSS JOIN LATERAL (
    SELECT count(*)::integer effective_hold_count,
           COALESCE(bool_or(effective.preserve_resource_state),false) resource_state_changes_blocked,
           COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id),'{}'::bigint[]) effective_hold_ids
    FROM effective_holds_for_aggregation(resource.id) effective
) hold_state;

CREATE OR REPLACE VIEW authorized_records_for_search AS
SELECT resource.id,
       -- Keep the true container for filtering; API serialization performs
       -- output redaction and adds aggregation_state.
       resource.aggregation_id,
       resource.record_number,resource.title,resource.description,resource.date_created,resource.date_originated,
       resource.security_level_id,resource.inherit_acl_from_parent,resource.resource_acl_version,resource.version,
       resource.owning_org_unit_id,resource.medium,resource.is_vital,resource.date_of_next_review,
       aggregation_effective_assigned_location(resource.aggregation_id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.aggregation_id) AS effective_current_location,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.aggregation_id))
            THEN aggregation_effective_assigned_location_source_id(resource.aggregation_id) END AS effective_assigned_location_source_aggregation_id,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.aggregation_id))
            THEN aggregation_effective_current_location_source_id(resource.aggregation_id) END AS effective_current_location_source_aggregation_id,
       hold_state.effective_hold_count > 0 AS on_effective_hold,
       hold_state.resource_state_changes_blocked,
       hold_state.effective_hold_ids
FROM records resource
CROSS JOIN LATERAL (
    SELECT count(*)::integer effective_hold_count,
           COALESCE(bool_or(effective.preserve_resource_state),false) resource_state_changes_blocked,
           COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id),'{}'::bigint[]) effective_hold_ids
    FROM effective_holds_for_record(resource.id) effective
) hold_state;

COMMIT;

-- Resource-medium hierarchy enforcement. Equivalent upgrade: migration 052.
BEGIN;
ALTER TABLE record_drafts ADD COLUMN IF NOT EXISTS medium text;
ALTER TABLE record_drafts ADD COLUMN IF NOT EXISTS is_vital boolean NOT NULL DEFAULT false;
ALTER TABLE record_drafts ADD COLUMN IF NOT EXISTS date_of_next_review timestamptz;
ALTER TABLE record_drafts
    DROP CONSTRAINT IF EXISTS record_drafts_medium_valid,
    ADD CONSTRAINT record_drafts_medium_valid
        CHECK (medium IS NULL OR medium IN ('digital','physical','mixed'));

CREATE OR REPLACE FUNCTION enforce_aggregation_medium_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.parent_aggregation_id IS NOT NULL THEN
        SELECT medium INTO parent_medium FROM aggregations
         WHERE id=NEW.parent_aggregation_id FOR UPDATE;
        IF parent_medium IS NULL OR NEW.medium IS DISTINCT FROM parent_medium THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='aggregation_medium_mismatch',
                MESSAGE='aggregation_medium_mismatch: a child aggregation must use its parent medium';
        END IF;
    END IF;
    IF TG_OP='UPDATE' AND NEW.medium IS DISTINCT FROM OLD.medium AND (
        EXISTS (SELECT 1 FROM aggregations WHERE parent_aggregation_id=OLD.id)
        OR EXISTS (SELECT 1 FROM records WHERE aggregation_id=OLD.id)) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='medium_change_requires_empty_aggregation',
            MESSAGE='medium_change_requires_empty_aggregation: an aggregation must be empty before changing medium';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS aggregations_enforce_medium_hierarchy ON aggregations;
CREATE TRIGGER aggregations_enforce_medium_hierarchy
BEFORE INSERT OR UPDATE OF parent_aggregation_id,medium ON aggregations
FOR EACH ROW EXECUTE FUNCTION enforce_aggregation_medium_hierarchy();

CREATE OR REPLACE FUNCTION enforce_record_medium_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
    SELECT medium INTO parent_medium FROM aggregations WHERE id=NEW.aggregation_id FOR UPDATE;
    IF parent_medium IS NULL OR (parent_medium<>'mixed' AND NEW.medium IS DISTINCT FROM parent_medium) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='record_medium_not_allowed_by_parent',
            MESSAGE='record_medium_not_allowed_by_parent: record medium is incompatible with its parent aggregation';
    END IF;
    IF TG_OP='UPDATE' AND NEW.medium='physical' AND NEW.medium IS DISTINCT FROM OLD.medium
       AND EXISTS (SELECT 1 FROM digital_components WHERE record_id=OLD.id) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='physical_record_has_digital_components',
            MESSAGE='physical_record_has_digital_components: a record with digital components cannot become physical';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS records_enforce_medium_hierarchy ON records;
CREATE TRIGGER records_enforce_medium_hierarchy
BEFORE INSERT OR UPDATE OF aggregation_id,medium ON records
FOR EACH ROW EXECUTE FUNCTION enforce_record_medium_hierarchy();

CREATE OR REPLACE FUNCTION enforce_record_draft_medium_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
    SELECT medium INTO parent_medium FROM aggregations WHERE id=NEW.aggregation_id FOR UPDATE;
    IF NEW.medium IS NULL THEN
        NEW.medium:=parent_medium;
    ELSIF parent_medium IS NULL OR (parent_medium<>'mixed' AND NEW.medium IS DISTINCT FROM parent_medium) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='record_medium_not_allowed_by_parent',
            MESSAGE='record_medium_not_allowed_by_parent: draft medium is incompatible with its parent aggregation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS record_drafts_enforce_medium_hierarchy ON record_drafts;
CREATE TRIGGER record_drafts_enforce_medium_hierarchy
BEFORE INSERT OR UPDATE OF aggregation_id,medium ON record_drafts
FOR EACH ROW EXECUTE FUNCTION enforce_record_draft_medium_hierarchy();
COMMIT;

-- Physical records cannot carry digital components. Equivalent upgrade: migration 053.
BEGIN;
CREATE OR REPLACE FUNCTION enforce_digital_component_record_medium()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE record_medium text;
BEGIN
    SELECT medium INTO record_medium FROM records WHERE id=NEW.record_id FOR UPDATE;
    IF record_medium='physical' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            CONSTRAINT='physical_record_disallows_digital_components',
            MESSAGE='physical_record_disallows_digital_components: physical records cannot have digital components';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS digital_components_enforce_record_medium ON digital_components;
CREATE TRIGGER digital_components_enforce_record_medium
BEFORE INSERT OR UPDATE OF record_id ON digital_components
FOR EACH ROW EXECUTE FUNCTION enforce_digital_component_record_medium();

CREATE OR REPLACE FUNCTION enforce_record_draft_medium_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.aggregation_id IS NULL THEN RETURN NEW; END IF;
    SELECT medium INTO parent_medium FROM aggregations WHERE id=NEW.aggregation_id FOR UPDATE;
    IF NEW.medium IS NULL THEN
        NEW.medium:=parent_medium;
    ELSIF parent_medium IS NULL OR (parent_medium<>'mixed' AND NEW.medium IS DISTINCT FROM parent_medium) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='record_medium_not_allowed_by_parent',
            MESSAGE='record_medium_not_allowed_by_parent: draft medium is incompatible with its parent aggregation';
    END IF;
    IF NEW.medium='physical' AND (TG_OP='INSERT' OR OLD.medium IS DISTINCT FROM NEW.medium)
       AND EXISTS (SELECT 1 FROM record_draft_components WHERE draft_id=NEW.id) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='physical_record_has_staged_components',
            MESSAGE='physical_record_has_staged_components: remove staged components before changing the draft medium';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_draft_component_record_medium()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE draft_medium text;
BEGIN
    SELECT medium INTO draft_medium FROM record_drafts WHERE id=NEW.draft_id FOR UPDATE;
    IF draft_medium IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='record_medium_required_before_components',
            MESSAGE='record_medium_required_before_components: select a record medium before adding digital components';
    ELSIF draft_medium='physical' THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='physical_record_disallows_digital_components',
            MESSAGE='physical_record_disallows_digital_components: physical record drafts cannot have digital components';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS record_draft_components_enforce_record_medium ON record_draft_components;
CREATE TRIGGER record_draft_components_enforce_record_medium
BEFORE INSERT OR UPDATE OF draft_id ON record_draft_components
FOR EACH ROW EXECUTE FUNCTION enforce_draft_component_record_medium();
COMMIT;

-- Governed vital status and immutable deletion protection. Equivalent upgrade: migration 054.
BEGIN;
INSERT INTO privileges(code,name,description,category,is_reserved) VALUES
 ('aggregation.vital_status.change','Change Aggregation Vital Status','Governed change of aggregation vital status.','aggregation',false),
 ('record.vital_status.change','Change Record Vital Status','Governed change of record vital status.','record',false) ON CONFLICT DO NOTHING;
INSERT INTO permissions(code,name,description,resource_type) VALUES
 ('aggregation.vital_status.change','Change Aggregation Vital Status','Governed change of aggregation vital status.','aggregation'),
 ('record.vital_status.change','Change Record Vital Status','Governed change of record vital status.','record') ON CONFLICT DO NOTHING;
INSERT INTO privilege_dependencies(privilege_id,required_privilege_id)
SELECT dependent.id,required.id FROM privileges dependent JOIN privileges required ON required.code=CASE WHEN dependent.code LIKE 'aggregation.%' THEN 'aggregation.view' ELSE 'record.view' END WHERE dependent.code IN ('aggregation.vital_status.change','record.vital_status.change') ON CONFLICT DO NOTHING;
INSERT INTO permission_dependencies(permission_id,required_permission_id)
SELECT dependent.id,required.id FROM permissions dependent JOIN permissions required ON required.code=CASE WHEN dependent.resource_type='aggregation' THEN 'aggregation.view' ELSE 'record.view' END WHERE dependent.code IN ('aggregation.vital_status.change','record.vital_status.change') ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id FROM profiles profile CROSS JOIN privileges privilege WHERE profile.code IN ('ALL_PRIVS','INFO_GOV_MGR','INFO_GOV_OFFICER') AND privilege.code IN ('aggregation.vital_status.change','record.vital_status.change') ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION aggregation_has_vital_descendants(p_id bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 WITH RECURSIVE subtree AS (
   SELECT p_id AS id
   UNION ALL
   SELECT child.id FROM aggregations child JOIN subtree parent ON child.parent_aggregation_id=parent.id
 )
 SELECT EXISTS(SELECT 1 FROM aggregations WHERE id IN (SELECT id FROM subtree) AND id<>p_id AND is_vital)
     OR EXISTS(SELECT 1 FROM records WHERE aggregation_id IN (SELECT id FROM subtree) AND is_vital)$$;
CREATE OR REPLACE FUNCTION protect_vital_resource_deletion() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE vital_count integer;
BEGIN
 IF TG_TABLE_NAME='records' THEN IF OLD.is_vital THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='vital_resource_deletion_blocked'; END IF; RETURN OLD; END IF;
 PERFORM 1 FROM aggregations WHERE id=OLD.id FOR UPDATE;
 IF OLD.is_vital THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='vital_resource_deletion_blocked'; END IF;
 WITH RECURSIVE subtree AS (
   SELECT OLD.id AS id
   UNION ALL
   SELECT child.id FROM aggregations child JOIN subtree parent ON child.parent_aggregation_id=parent.id
 )
 SELECT count(*) INTO vital_count FROM (
   SELECT id FROM aggregations WHERE id IN (SELECT id FROM subtree) AND id<>OLD.id AND is_vital
   UNION ALL
   SELECT id FROM records WHERE aggregation_id IN (SELECT id FROM subtree) AND is_vital
 ) vital;
 IF vital_count>0 THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='vital_descendant_deletion_blocked'; END IF; RETURN OLD;
END; $$;
CREATE TRIGGER aggregations_protect_vital_deletion BEFORE DELETE ON aggregations FOR EACH ROW EXECUTE FUNCTION protect_vital_resource_deletion();
CREATE TRIGGER records_protect_vital_deletion BEFORE DELETE ON records FOR EACH ROW EXECUTE FUNCTION protect_vital_resource_deletion();
CREATE OR REPLACE FUNCTION allow_governed_vital_status_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF NEW.is_vital IS DISTINCT FROM OLD.is_vital AND (current_setting('app.vital_status_change_authorized',true)<>'authorized' OR NULLIF(btrim(current_setting('app.change_reason',true)), '') IS NULL) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='vital_status_change_requires_governed_authorization_and_reason'; END IF; RETURN NEW; END; $$;
CREATE TRIGGER aggregations_govern_vital_status BEFORE UPDATE OF is_vital ON aggregations FOR EACH ROW EXECUTE FUNCTION allow_governed_vital_status_change();
CREATE TRIGGER records_govern_vital_status BEFORE UPDATE OF is_vital ON records FOR EACH ROW EXECUTE FUNCTION allow_governed_vital_status_change();
CREATE OR REPLACE FUNCTION protect_closed_aggregation_hierarchy() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE closure_source_id bigint;
BEGIN
 IF TG_OP='INSERT' THEN IF NEW.parent_aggregation_id IS NOT NULL THEN PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id); END IF; RETURN NEW; END IF;
 IF TG_OP='DELETE' THEN PERFORM assert_aggregation_effectively_open(OLD.id); RETURN OLD; END IF;
 WITH RECURSIVE ancestors AS (SELECT id,parent_aggregation_id,date_closed,0 depth FROM aggregations WHERE id=OLD.id UNION ALL SELECT parent.id,parent.parent_aggregation_id,parent.date_closed,child.depth+1 FROM aggregations parent JOIN ancestors child ON parent.id=child.parent_aggregation_id) SELECT id INTO closure_source_id FROM ancestors WHERE date_closed IS NOT NULL ORDER BY depth LIMIT 1;
 IF closure_source_id IS NOT NULL THEN
  IF current_setting('app.vital_status_change_authorized',true)='authorized' AND NEW.is_vital IS DISTINCT FROM OLD.is_vital AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN RETURN NEW; END IF;
  IF closure_source_id=OLD.id AND OLD.date_closed IS NOT NULL AND NEW.date_closed IS NULL AND (to_jsonb(NEW)-'date_closed'-'version')=(to_jsonb(OLD)-'date_closed'-'version') THEN RETURN NEW; END IF;
  RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='closed aggregation metadata is immutable';
 END IF; RETURN NEW;
END; $$;
CREATE OR REPLACE FUNCTION protect_record_in_closed_aggregation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN PERFORM assert_aggregation_effectively_open(NEW.aggregation_id); RETURN NEW; END IF;
 IF TG_OP='DELETE' THEN PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN OLD; END IF;
 IF current_setting('app.vital_status_change_authorized',true)='authorized' AND NEW.is_vital IS DISTINCT FROM OLD.is_vital AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.review_date_change_authorized',true)='authorized' AND NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review AND (to_jsonb(NEW)-'date_of_next_review'-'version')=(to_jsonb(OLD)-'date_of_next_review'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.security_level_change_authorized',true)='authorized' AND NEW.security_level_id IS DISTINCT FROM OLD.security_level_id AND (to_jsonb(NEW)-'security_level_id'-'version')=(to_jsonb(OLD)-'security_level_id'-'version') THEN RETURN NEW; END IF;
 PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN NEW;
END; $$;
INSERT INTO privileges(code,name,description,category) VALUES ('aggregation.location.change','Change Aggregation Location','Governed change of aggregation assigned or current location.','aggregation') ON CONFLICT DO NOTHING;
INSERT INTO permissions(code,name,description,resource_type) VALUES ('aggregation.location.change','Change Aggregation Location','Governed change of aggregation assigned or current location.','aggregation') ON CONFLICT DO NOTHING;
INSERT INTO privilege_dependencies(privilege_id,required_privilege_id) SELECT dependent.id,required.id FROM privileges dependent JOIN privileges required ON required.code='aggregation.view' WHERE dependent.code='aggregation.location.change' ON CONFLICT DO NOTHING;
INSERT INTO permission_dependencies(permission_id,required_permission_id) SELECT dependent.id,required.id FROM permissions dependent JOIN permissions required ON required.code='aggregation.view' WHERE dependent.code='aggregation.location.change' ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id) SELECT profile.id,privilege.id FROM profiles profile CROSS JOIN privileges privilege WHERE profile.code IN ('ALL_PRIVS','INFO_GOV_MGR','INFO_GOV_OFFICER') AND privilege.code='aggregation.location.change' ON CONFLICT DO NOTHING;
INSERT INTO privileges(code,name,description,category,is_reserved) VALUES ('aggregation.review_date.change','Change Aggregation Review Date','Governed scheduling or clearing of an aggregation review date.','aggregation',false),('record.review_date.change','Change Record Review Date','Governed scheduling or clearing of a record review date.','record',false) ON CONFLICT DO NOTHING;
INSERT INTO permissions(code,name,description,resource_type) VALUES ('aggregation.review_date.change','Change Aggregation Review Date','Governed scheduling or clearing of an aggregation review date.','aggregation'),('record.review_date.change','Change Record Review Date','Governed scheduling or clearing of a record review date.','record') ON CONFLICT DO NOTHING;
INSERT INTO privilege_dependencies(privilege_id,required_privilege_id) SELECT d.id,r.id FROM privileges d JOIN privileges r ON r.code=CASE WHEN d.code LIKE 'aggregation.%' THEN 'aggregation.view' ELSE 'record.view' END WHERE d.code IN ('aggregation.review_date.change','record.review_date.change') ON CONFLICT DO NOTHING;
INSERT INTO permission_dependencies(permission_id,required_permission_id) SELECT d.id,r.id FROM permissions d JOIN permissions r ON r.code=CASE WHEN d.resource_type='aggregation' THEN 'aggregation.view' ELSE 'record.view' END WHERE d.code IN ('aggregation.review_date.change','record.review_date.change') ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id) SELECT p.id,v.id FROM profiles p CROSS JOIN privileges v WHERE p.code IN ('ALL_PRIVS','INFO_GOV_MGR','INFO_GOV_OFFICER') AND v.code IN ('aggregation.review_date.change','record.review_date.change') ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION enforce_future_review_date() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.date_of_next_review IS NOT NULL AND (TG_OP='INSERT' OR NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review) AND NEW.date_of_next_review <= CURRENT_TIMESTAMP THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='date_of_next_review_must_be_future'; END IF; RETURN NEW; END; $$;
CREATE TRIGGER aggregations_enforce_future_review_date BEFORE INSERT OR UPDATE OF date_of_next_review ON aggregations FOR EACH ROW EXECUTE FUNCTION enforce_future_review_date();
CREATE TRIGGER records_enforce_future_review_date BEFORE INSERT OR UPDATE OF date_of_next_review ON records FOR EACH ROW EXECUTE FUNCTION enforce_future_review_date();
CREATE TRIGGER record_drafts_enforce_future_review_date BEFORE INSERT OR UPDATE OF date_of_next_review ON record_drafts FOR EACH ROW EXECUTE FUNCTION enforce_future_review_date();
CREATE OR REPLACE FUNCTION allow_governed_review_date_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review AND (current_setting('app.review_date_change_authorized',true)<>'authorized' OR NULLIF(btrim(current_setting('app.change_reason',true)), '') IS NULL) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='review_date_change_requires_governed_authorization_and_reason'; END IF; RETURN NEW; END; $$;
CREATE TRIGGER aggregations_govern_review_date BEFORE UPDATE OF date_of_next_review ON aggregations FOR EACH ROW EXECUTE FUNCTION allow_governed_review_date_change();
CREATE TRIGGER records_govern_review_date BEFORE UPDATE OF date_of_next_review ON records FOR EACH ROW EXECUTE FUNCTION allow_governed_review_date_change();
CREATE OR REPLACE FUNCTION allow_governed_aggregation_location_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (NEW.assigned_location IS DISTINCT FROM OLD.assigned_location OR NEW.current_location IS DISTINCT FROM OLD.current_location) AND (current_setting('app.location_change_authorized',true)<>'authorized' OR NULLIF(btrim(current_setting('app.change_reason',true)), '') IS NULL) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='location_change_requires_governed_authorization_and_reason'; END IF; RETURN NEW; END; $$;
CREATE TRIGGER aggregations_govern_location_change BEFORE UPDATE OF assigned_location,current_location ON aggregations FOR EACH ROW EXECUTE FUNCTION allow_governed_aggregation_location_change();
CREATE OR REPLACE FUNCTION protect_closed_aggregation_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE closure_source_id bigint;
BEGIN
 IF TG_OP='INSERT' THEN
   IF NEW.parent_aggregation_id IS NOT NULL THEN
     PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id);
   END IF;
   RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN
   PERFORM assert_aggregation_effectively_open(OLD.id);
   RETURN OLD;
 END IF;
 WITH RECURSIVE ancestors AS (
   SELECT id,parent_aggregation_id,date_closed,0 depth FROM aggregations WHERE id=OLD.id
   UNION ALL
   SELECT parent.id,parent.parent_aggregation_id,parent.date_closed,child.depth+1
   FROM aggregations parent JOIN ancestors child ON parent.id=child.parent_aggregation_id
 )
 SELECT id INTO closure_source_id FROM ancestors
 WHERE date_closed IS NOT NULL ORDER BY depth LIMIT 1;
 IF closure_source_id IS NOT NULL THEN
   IF current_setting('app.vital_status_change_authorized',true)='authorized'
      AND NEW.is_vital IS DISTINCT FROM OLD.is_vital
      AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.location_change_authorized',true)='authorized'
      AND (NEW.assigned_location IS DISTINCT FROM OLD.assigned_location
           OR NEW.current_location IS DISTINCT FROM OLD.current_location)
      AND (to_jsonb(NEW)-'assigned_location'-'current_location'-'version')
          =(to_jsonb(OLD)-'assigned_location'-'current_location'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.review_date_change_authorized',true)='authorized'
      AND NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review
      AND (to_jsonb(NEW)-'date_of_next_review'-'version')=(to_jsonb(OLD)-'date_of_next_review'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.security_level_change_authorized',true)='authorized'
      AND NEW.security_level_id IS DISTINCT FROM OLD.security_level_id
      AND (to_jsonb(NEW)-'security_level_id'-'version')=(to_jsonb(OLD)-'security_level_id'-'version') THEN
     RETURN NEW;
   END IF;
   IF closure_source_id=OLD.id AND OLD.date_closed IS NOT NULL
      AND NEW.date_closed IS NULL
      AND (to_jsonb(NEW)-'date_closed'-'version')=(to_jsonb(OLD)-'date_closed'-'version') THEN
     RETURN NEW;
   END IF;
   RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='closed aggregation metadata is immutable';
 END IF;
 RETURN NEW;
END;
$$;
CREATE INDEX aggregations_review_due_idx ON aggregations (date_of_next_review,id) WHERE date_of_next_review IS NOT NULL;
CREATE INDEX records_review_due_idx ON records (date_of_next_review,id) WHERE date_of_next_review IS NOT NULL;
CREATE INDEX aggregations_owner_review_due_idx ON aggregations (owning_org_unit_id,date_of_next_review,id) WHERE date_of_next_review IS NOT NULL;
CREATE INDEX records_owner_review_due_idx ON records (owning_org_unit_id,date_of_next_review,id) WHERE date_of_next_review IS NOT NULL;

SELECT set_config('app.actor_type','automated_process',true),
       set_config('app.actor_name','Database migration 010',true),
       set_config('app.event_source','migration',true),
       set_config('app.change_reason','Install full-text search Phase 1 metadata and service-authentication foundation',true),
       set_config('app.event_metadata','{"migration":"010_add_full_text_search_phase1"}',true);

DO $$
BEGIN
    IF current_setting('server_version_num')::integer < 180000 THEN
        RAISE EXCEPTION 'Full-text search requires PostgreSQL 18 or newer';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_ts_config config
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid=config.cfgnamespace
        WHERE namespace.nspname='pg_catalog' AND config.cfgname='simple'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_ts_config config
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid=config.cfgnamespace
        WHERE namespace.nspname='pg_catalog' AND config.cfgname='english'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_ts_config config
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid=config.cfgnamespace
        WHERE namespace.nspname='pg_catalog' AND config.cfgname='arabic'
    ) THEN
        RAISE EXCEPTION 'Required PostgreSQL text-search configurations are unavailable';
    END IF;
END;
$$;

CREATE TABLE record_search_documents (
    record_id bigint PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
    search_vector tsvector NOT NULL,
    text_search_config regconfig NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    index_config_version text NOT NULL,
    CONSTRAINT record_search_documents_config_version_not_blank
        CHECK (btrim(index_config_version) <> '')
);

CREATE INDEX record_search_documents_vector_gin
    ON record_search_documents USING gin(search_vector);

CREATE TABLE aggregation_search_documents (
    aggregation_id bigint PRIMARY KEY REFERENCES aggregations(id) ON DELETE CASCADE,
    search_vector tsvector NOT NULL,
    text_search_config regconfig NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    index_config_version text NOT NULL,
    CONSTRAINT aggregation_search_documents_config_version_not_blank
        CHECK (btrim(index_config_version) <> '')
);

CREATE INDEX aggregation_search_documents_vector_gin
    ON aggregation_search_documents USING gin(search_vector);

CREATE FUNCTION refresh_record_metadata_search_document()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO record_search_documents(
        record_id,search_vector,text_search_config,indexed_at,index_config_version
    ) VALUES (
        NEW.id,
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.record_number,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.title,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.description,'')),'B'),
        'pg_catalog.simple'::regconfig,
        CURRENT_TIMESTAMP,
        'fts-metadata-v1'
    )
    ON CONFLICT(record_id) DO UPDATE SET
        search_vector=EXCLUDED.search_vector,
        text_search_config=EXCLUDED.text_search_config,
        indexed_at=EXCLUDED.indexed_at,
        index_config_version=EXCLUDED.index_config_version;
    RETURN NEW;
END;
$$;

CREATE FUNCTION refresh_aggregation_metadata_search_document()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO aggregation_search_documents(
        aggregation_id,search_vector,text_search_config,indexed_at,index_config_version
    ) VALUES (
        NEW.id,
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.aggregation_number,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.title,'')),'A') ||
        setweight(to_tsvector('pg_catalog.simple',coalesce(NEW.description,'')),'B'),
        'pg_catalog.simple'::regconfig,
        CURRENT_TIMESTAMP,
        'fts-metadata-v1'
    )
    ON CONFLICT(aggregation_id) DO UPDATE SET
        search_vector=EXCLUDED.search_vector,
        text_search_config=EXCLUDED.text_search_config,
        indexed_at=EXCLUDED.indexed_at,
        index_config_version=EXCLUDED.index_config_version;
    RETURN NEW;
END;
$$;

CREATE TRIGGER records_refresh_metadata_search
AFTER INSERT OR UPDATE OF record_number,title,description ON records
FOR EACH ROW EXECUTE FUNCTION refresh_record_metadata_search_document();

CREATE TRIGGER aggregations_refresh_metadata_search
AFTER INSERT OR UPDATE OF aggregation_number,title,description ON aggregations
FOR EACH ROW EXECUTE FUNCTION refresh_aggregation_metadata_search_document();

INSERT INTO record_search_documents(
    record_id,search_vector,text_search_config,indexed_at,index_config_version
)
SELECT record.id,
       setweight(to_tsvector('pg_catalog.simple',coalesce(record.record_number,'')),'A') ||
       setweight(to_tsvector('pg_catalog.simple',coalesce(record.title,'')),'A') ||
       setweight(to_tsvector('pg_catalog.simple',coalesce(record.description,'')),'B'),
       'pg_catalog.simple'::regconfig,CURRENT_TIMESTAMP,'fts-metadata-v1'
FROM records record;

INSERT INTO aggregation_search_documents(
    aggregation_id,search_vector,text_search_config,indexed_at,index_config_version
)
SELECT aggregation.id,
       setweight(to_tsvector('pg_catalog.simple',coalesce(aggregation.aggregation_number,'')),'A') ||
       setweight(to_tsvector('pg_catalog.simple',coalesce(aggregation.title,'')),'A') ||
       setweight(to_tsvector('pg_catalog.simple',coalesce(aggregation.description,'')),'B'),
       'pg_catalog.simple'::regconfig,CURRENT_TIMESTAMP,'fts-metadata-v1'
FROM aggregations aggregation;

CREATE VIEW authorized_record_search_documents AS
SELECT document.record_id,document.search_vector,document.text_search_config,
       document.indexed_at,document.index_config_version
FROM record_search_documents document
WHERE current_user_can_view_record(document.record_id);

CREATE VIEW authorized_aggregation_search_documents AS
SELECT document.aggregation_id,document.search_vector,document.text_search_config,
       document.indexed_at,document.index_config_version
FROM aggregation_search_documents document
WHERE current_user_can_view_aggregation(document.aggregation_id);

ALTER TABLE privileges
    ADD COLUMN account_type_restriction text;
ALTER TABLE privileges
    ADD CONSTRAINT privileges_account_type_restriction_valid
    CHECK (account_type_restriction IS NULL OR account_type_restriction IN ('person','service'));

UPDATE privileges
SET name='Administer Text Indexers',
    description='Create and manage non-interactive text-indexer identities and their API credentials.',
    account_type_restriction='person'
WHERE code='identity.text_indexers.administer';

INSERT INTO privileges(code,name,description,category,is_reserved,account_type_restriction)
VALUES
    ('content.index.execute','Execute Content Indexing',
     'Use the lease-scoped internal text-indexing worker contract.','administration',false,'service'),
    ('search.query.debug','Debug Search Query',
     'Request sanitized API-level diagnostics for searches performed by the current user.','administration',false,'person')
ON CONFLICT DO NOTHING;

INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id
FROM profiles profile CROSS JOIN privileges privilege
WHERE profile.code='ALL_PRIVS'
  AND privilege.code IN ('content.index.execute','search.query.debug')
ON CONFLICT DO NOTHING;

INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id
FROM profiles profile CROSS JOIN privileges privilege
WHERE profile.code IN ('SYS_ADMIN','INFO_GOV_MGR','INFO_GOV_OFFICER')
  AND privilege.code='search.query.debug'
ON CONFLICT DO NOTHING;

INSERT INTO profiles(code,name,description,is_system)
VALUES ('TEXT_INDEXER_SERVICE','Text Indexer Service',
        'Protected non-interactive profile for the internal text-indexing worker contract.',true);

INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id
FROM profiles profile CROSS JOIN privileges privilege
WHERE profile.code='TEXT_INDEXER_SERVICE' AND privilege.code='content.index.execute';

ALTER TABLE roles ADD COLUMN is_system boolean NOT NULL DEFAULT false;
ALTER TABLE roles ADD COLUMN account_type_restriction text;
ALTER TABLE roles ALTER COLUMN org_unit_id DROP NOT NULL;
ALTER TABLE roles ADD CONSTRAINT roles_account_type_restriction_valid
    CHECK (account_type_restriction IS NULL OR account_type_restriction IN ('person','service'));
ALTER TABLE roles ADD CONSTRAINT roles_system_service_shape
    CHECK (
        (is_system AND account_type_restriction='service' AND org_unit_id IS NULL
         AND supervisor_role_id IS NULL AND NOT is_information_governance)
        OR
        (NOT is_system AND account_type_restriction IS NULL AND org_unit_id IS NOT NULL)
    );

CREATE OR REPLACE FUNCTION role_effectively_active(p_role_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT COALESCE(
        role.date_deactivated IS NULL
        AND CASE
            WHEN role.is_system THEN
                role.account_type_restriction='service' AND role.org_unit_id IS NULL
            ELSE org_unit_effectively_active(role.org_unit_id)
        END,
        false
    )
    FROM roles role WHERE role.id=p_role_id;
$$;

CREATE OR REPLACE FUNCTION validate_active_role_assignment()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    selected_account_type text;
    selected_role_restriction text;
    selected_role_is_system boolean;
BEGIN
    SELECT account_type INTO selected_account_type
    FROM users
    WHERE id=NEW.user_id AND date_deactivated IS NULL AND date_suspended IS NULL;
    IF selected_account_type IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role assignments require an active user';
    END IF;
    SELECT account_type_restriction,is_system
      INTO selected_role_restriction,selected_role_is_system
      FROM roles WHERE id=NEW.role_id;
    IF NOT role_effectively_active(NEW.role_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role assignments require an effectively active role and organization hierarchy';
    END IF;
    IF selected_role_restriction IS NOT NULL
       AND selected_role_restriction<>selected_account_type THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='role account type restriction does not match user account type';
    END IF;
    IF selected_role_is_system AND EXISTS (
        SELECT 1 FROM user_role_assignments existing
        WHERE existing.user_id=NEW.user_id AND existing.id<>COALESCE(NEW.id,0)
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='service system role must be the account only role assignment';
    END IF;
    IF NOT selected_role_is_system AND EXISTS (
        SELECT 1 FROM user_role_assignments existing
        JOIN roles existing_role ON existing_role.id=existing.role_id
        WHERE existing.user_id=NEW.user_id AND existing.id<>COALESCE(NEW.id,0)
          AND existing_role.is_system AND existing_role.account_type_restriction='service'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='service system role must be the account only role assignment';
    END IF;
    RETURN NEW;
END;
$$;

INSERT INTO roles(
    org_unit_id,supervisor_role_id,code,name,description,security_level_id,
    profile_id,is_information_governance,is_system,account_type_restriction
)
SELECT NULL,NULL,'text-indexer-service','Text Indexer Service',
       'Protected non-organizational role for text-indexer service accounts.',
       level.id,profile.id,false,true,'service'
FROM security_levels level CROSS JOIN profiles profile
WHERE level.level_number=(SELECT min(level_number) FROM security_levels)
  AND profile.code='TEXT_INDEXER_SERVICE';

CREATE FUNCTION protect_text_indexer_profile_membership()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target_profile_id bigint;
    target_privilege_id bigint;
    target_profile_code text;
    target_privilege_code text;
BEGIN
    IF TG_OP='DELETE' THEN
        target_profile_id:=OLD.profile_id;
        target_privilege_id:=OLD.privilege_id;
    ELSE
        target_profile_id:=NEW.profile_id;
        target_privilege_id:=NEW.privilege_id;
    END IF;
    SELECT code INTO target_profile_code FROM profiles
    WHERE id=target_profile_id;
    SELECT code INTO target_privilege_code FROM privileges
    WHERE id=target_privilege_id;
    IF target_profile_code='TEXT_INDEXER_SERVICE' THEN
        IF TG_OP='DELETE' OR target_privilege_code<>'content.index.execute' THEN
            RAISE EXCEPTION USING ERRCODE='P0001',
                MESSAGE='TEXT_INDEXER_SERVICE profile is protected and contains exactly content.index.execute';
        END IF;
    END IF;
    IF TG_OP='DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER profile_privileges_protect_text_indexer
BEFORE INSERT OR UPDATE OR DELETE ON profile_privileges
FOR EACH ROW EXECUTE FUNCTION protect_text_indexer_profile_membership();

CREATE FUNCTION protect_text_indexer_profile()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.code='TEXT_INDEXER_SERVICE' THEN
        IF TG_OP='UPDATE' THEN
            IF ROW(
                NEW.id,NEW.code,NEW.name,NEW.description,NEW.is_system,
                NEW.date_created
            ) IS NOT DISTINCT FROM ROW(
                OLD.id,OLD.code,OLD.name,OLD.description,OLD.is_system,
                OLD.date_created
            ) THEN
                RETURN NEW;
            END IF;
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='TEXT_INDEXER_SERVICE profile is protected';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER profiles_protect_text_indexer
BEFORE UPDATE OR DELETE ON profiles
FOR EACH ROW EXECUTE FUNCTION protect_text_indexer_profile();

CREATE FUNCTION protect_text_indexer_role()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.code='text-indexer-service' AND OLD.is_system THEN
        IF TG_OP='UPDATE' THEN
            IF ROW(
                NEW.id,NEW.org_unit_id,NEW.supervisor_role_id,NEW.code,NEW.name,
                NEW.description,NEW.date_created,NEW.date_deactivated,
                NEW.security_level_id,NEW.profile_id,NEW.is_information_governance,
                NEW.is_system,NEW.account_type_restriction
            ) IS NOT DISTINCT FROM ROW(
                OLD.id,OLD.org_unit_id,OLD.supervisor_role_id,OLD.code,OLD.name,
                OLD.description,OLD.date_created,OLD.date_deactivated,
                OLD.security_level_id,OLD.profile_id,OLD.is_information_governance,
                OLD.is_system,OLD.account_type_restriction
            ) THEN
                RETURN NEW;
            END IF;
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001',
            MESSAGE='text-indexer-service role is protected';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER roles_protect_text_indexer
BEFORE UPDATE OR DELETE ON roles
FOR EACH ROW EXECUTE FUNCTION protect_text_indexer_role();

CREATE TABLE service_account_credentials (
    id bigserial PRIMARY KEY,
    service_user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name text NOT NULL,
    credential_identifier text NOT NULL,
    secret_hash text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz,
    last_worker_id text,
    date_revoked timestamptz,
    created_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    revoked_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT service_account_credentials_name_not_blank CHECK (btrim(name)<>''),
    CONSTRAINT service_account_credentials_identifier_format
        CHECK (credential_identifier ~ '^[0-9A-HJKMNP-TV-Z]{26}$'),
    CONSTRAINT service_account_credentials_identifier_unique UNIQUE(credential_identifier),
    CONSTRAINT service_account_credentials_hash_format CHECK (secret_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT service_account_credentials_status_valid CHECK (status IN ('active','revoked')),
    CONSTRAINT service_account_credentials_expiry_valid CHECK (expires_at>date_created),
    CONSTRAINT service_account_credentials_last_worker_not_blank
        CHECK (last_worker_id IS NULL OR btrim(last_worker_id)<>''),
    CONSTRAINT service_account_credentials_revocation_state CHECK (
        (status='active' AND date_revoked IS NULL AND revoked_by_user_id IS NULL)
        OR (status='revoked' AND date_revoked IS NOT NULL)
    )
);

CREATE INDEX service_account_credentials_service_user_idx
    ON service_account_credentials(service_user_id,date_created DESC,id DESC);
CREATE INDEX service_account_credentials_active_expiry_idx
    ON service_account_credentials(expires_at,id) WHERE status='active';
CREATE INDEX service_account_credentials_history_cleanup_idx
    ON service_account_credentials((coalesce(date_revoked,expires_at)),id);

CREATE FUNCTION validate_service_account_credential()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM users account
        WHERE account.id=NEW.service_user_id AND account.account_type='service'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='API key target must be a service account';
    END IF;
    IF NEW.created_by_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM users actor
        WHERE actor.id=NEW.created_by_user_id AND actor.account_type='person'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='API key creator must be a person account';
    END IF;
    IF NEW.revoked_by_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM users actor
        WHERE actor.id=NEW.revoked_by_user_id AND actor.account_type='person'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='API key revoker must be a person account';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER service_account_credentials_validate
BEFORE INSERT OR UPDATE ON service_account_credentials
FOR EACH ROW EXECUTE FUNCTION validate_service_account_credential();

CREATE FUNCTION reject_service_account_password()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM users account WHERE account.id=NEW.user_id AND account.account_type='service') THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='service accounts cannot have interactive passwords';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER user_credentials_reject_service_account
BEFORE INSERT OR UPDATE OF user_id ON user_credentials
FOR EACH ROW EXECUTE FUNCTION reject_service_account_password();

-- Full-text content search Phase 3 begins.
INSERT INTO privileges(code,name,description,category,is_reserved,account_type_restriction)
VALUES ('record.component.reindex','Reindex Record Components',
        'Request forced indexing of an authorized component or all eligible components of an authorized record.',
        'component',false,'person')
ON CONFLICT DO NOTHING;
UPDATE privileges SET name='Reindex Record Components',
       description='Request forced indexing of an authorized component or all eligible components of an authorized record.',
       category='component',account_type_restriction='person'
 WHERE code='record.component.reindex';

INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id FROM profiles profile CROSS JOIN privileges privilege
WHERE profile.code IN ('ALL_PRIVS','SYS_ADMIN','INFO_GOV_MGR','INFO_GOV_OFFICER')
  AND privilege.code='record.component.reindex'
ON CONFLICT DO NOTHING;

CREATE TABLE content_indexing_batches (
    id uuid PRIMARY KEY,
    record_id bigint REFERENCES records(id) ON DELETE SET NULL,
    requested_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_components integer NOT NULL CHECK(total_components>=0),
    queued_count integer NOT NULL CHECK(queued_count>=0),
    already_in_progress_count integer NOT NULL CHECK(already_in_progress_count>=0),
    unavailable_count integer NOT NULL CHECK(unavailable_count>=0),
    CONSTRAINT content_indexing_batch_counts_valid CHECK (
        queued_count+already_in_progress_count+unavailable_count=total_components
    )
);

CREATE TABLE content_indexing_batch_items (
    batch_id uuid NOT NULL REFERENCES content_indexing_batches(id) ON DELETE CASCADE,
    digital_component_id bigint REFERENCES digital_components(id) ON DELETE SET NULL,
    job_id bigint REFERENCES content_indexing_jobs(id) ON DELETE SET NULL,
    disposition text NOT NULL CHECK(disposition IN ('queued','already_in_progress','unsupported_or_no_content')),
    component_identifier bigint NOT NULL,
    PRIMARY KEY(batch_id,component_identifier)
);
CREATE INDEX content_indexing_batch_items_job_idx ON content_indexing_batch_items(job_id) WHERE job_id IS NOT NULL;
-- Full-text content search Phase 3 ends.

-- Advanced Search Phase 1 begins.
CREATE TABLE saved_searches (
    id              bigserial PRIMARY KEY,
    owner_user_id   bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            text NOT NULL,
    category        text,
    description     text,
    resource_type   text NOT NULL,
    definition      jsonb NOT NULL,
    audience_mode   text NOT NULL DEFAULT 'private',
    date_created    timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated    timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version         bigint NOT NULL DEFAULT 1,
    CONSTRAINT saved_searches_name_not_blank CHECK (btrim(name)<>''),
    CONSTRAINT saved_searches_name_bounded CHECK (length(name)<=120),
    CONSTRAINT saved_searches_category_valid CHECK (category IS NULL OR (btrim(category)<>'' AND length(category)<=80)),
    CONSTRAINT saved_searches_description_bounded CHECK (description IS NULL OR length(description)<=500),
    CONSTRAINT saved_searches_resource_type_valid CHECK (resource_type IN ('record','aggregation')),
    CONSTRAINT saved_searches_audience_mode_valid CHECK (audience_mode IN ('private','shared')),
    CONSTRAINT saved_searches_version_positive CHECK (version>0),
    CONSTRAINT saved_searches_definition_valid CHECK (
        jsonb_typeof(definition)='object'
        AND definition->>'schema_version'='1'
        AND definition->>'resource_type'=resource_type
        AND jsonb_typeof(definition->'request')='object'
        AND (definition->>'max_results') ~ '^[0-9]+$'
        AND (definition->>'max_results')::integer BETWEEN 1 AND 5000
    )
);
CREATE UNIQUE INDEX saved_searches_owner_name_ci_unique ON saved_searches(owner_user_id,lower(name));
CREATE INDEX saved_searches_owner_updated_idx ON saved_searches(owner_user_id,date_updated DESC,id DESC);
CREATE INDEX saved_searches_resource_updated_idx ON saved_searches(resource_type,date_updated DESC,id DESC);
CREATE INDEX saved_searches_category_ci_idx ON saved_searches(lower(category),date_updated DESC,id DESC) WHERE category IS NOT NULL;

CREATE TABLE saved_search_role_grants (
    saved_search_id bigint NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
    role_id bigint NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    PRIMARY KEY(saved_search_id,role_id)
);
CREATE INDEX saved_search_role_grants_role_idx ON saved_search_role_grants(role_id,saved_search_id);
CREATE TABLE saved_search_org_unit_grants (
    saved_search_id bigint NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
    org_unit_id bigint NOT NULL REFERENCES org_units(id) ON DELETE RESTRICT,
    PRIMARY KEY(saved_search_id,org_unit_id)
);
CREATE INDEX saved_search_org_unit_grants_unit_idx ON saved_search_org_unit_grants(org_unit_id,saved_search_id);

CREATE FUNCTION validate_saved_search_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM users owner WHERE owner.id=NEW.owner_user_id AND owner.account_type='person') THEN
        RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='saved_search_owner_must_be_person';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER saved_searches_validate_owner BEFORE INSERT OR UPDATE OF owner_user_id ON saved_searches
FOR EACH ROW EXECUTE FUNCTION validate_saved_search_owner();
CREATE FUNCTION touch_saved_search() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.date_updated:=CURRENT_TIMESTAMP; NEW.version:=OLD.version+1; RETURN NEW; END;
$$;
CREATE TRIGGER saved_searches_touch BEFORE UPDATE ON saved_searches FOR EACH ROW EXECUTE FUNCTION touch_saved_search();
CREATE FUNCTION enforce_saved_search_change_reason() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='saved_search_change_reason_required';
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER saved_searches_require_change_reason BEFORE UPDATE OR DELETE ON saved_searches
FOR EACH ROW EXECUTE FUNCTION enforce_saved_search_change_reason();
CREATE TRIGGER saved_searches_record_history AFTER INSERT OR UPDATE OR DELETE ON saved_searches
FOR EACH ROW EXECUTE FUNCTION record_entity_history('saved_search');

INSERT INTO privileges(code,name,description,category,is_reserved,account_type_restriction) VALUES
 ('search.saved_search.save','Save Searches','Create saved searches, copy accessible searches, and manage permitted audiences for owned searches.','administration',false,'person'),
 ('search.saved_search.administer','Administer Saved Searches','Inspect and modify any saved search and manage any eligible role or organizational-unit audience.','administration',false,'person'),
 ('search.saved_search.delete','Delete Saved Searches','Delete owned saved searches and, with saved-search administration, searches owned by other users.','administration',false,'person')
ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id FROM profiles profile CROSS JOIN privileges privilege
WHERE profile.code IN ('ALL_PRIVS','SYS_ADMIN','INFO_GOV_MGR','INFO_GOV_OFFICER')
  AND privilege.code IN ('search.saved_search.save','search.saved_search.administer','search.saved_search.delete')
ON CONFLICT DO NOTHING;
-- Advanced Search Phase 1 ends.

-- Internationalization and user preferences Phase 1 begins.
CREATE TABLE supported_languages (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    language_tag text NOT NULL UNIQUE,
    english_name text NOT NULL,
    native_name text NOT NULL,
    direction text NOT NULL CHECK (direction IN ('ltr','rtl')),
    is_enabled boolean NOT NULL DEFAULT true,
    is_default boolean NOT NULL DEFAULT false,
    formatting_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(formatting_config)='object'),
    catalogue_revision bigint NOT NULL DEFAULT 1 CHECK (catalogue_revision > 0),
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (language_tag ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
    CHECK (btrim(english_name)<>''), CHECK (btrim(native_name)<>''),
    CHECK (NOT is_default OR is_enabled)
);
CREATE UNIQUE INDEX supported_languages_one_default_idx ON supported_languages((is_default)) WHERE is_default;
CREATE UNIQUE INDEX supported_languages_tag_ci_unique ON supported_languages(lower(language_tag));
INSERT INTO supported_languages(language_tag,english_name,native_name,direction,is_enabled,is_default,formatting_config) VALUES
 ('en','English','English','ltr',true,true,'{"locale":"en"}'::jsonb),
 ('ar','Arabic','العربية','rtl',true,false,'{"locale":"ar"}'::jsonb);
CREATE FUNCTION enforce_one_enabled_default_language() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM supported_languages WHERE is_default AND is_enabled)<>1 THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='exactly_one_enabled_default_language_required';
 END IF;
 RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER supported_languages_require_one_default AFTER INSERT OR UPDATE OR DELETE ON supported_languages DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_one_enabled_default_language();

CREATE TABLE user_preferences (
    user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    language_tag text NOT NULL REFERENCES supported_languages(language_tag) ON DELETE RESTRICT,
    working_timezone text NOT NULL CHECK (btrim(working_timezone)<>''),
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE FUNCTION touch_localization_row() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.date_updated:=CURRENT_TIMESTAMP; NEW.version:=OLD.version+1; RETURN NEW; END;
$$;
CREATE TRIGGER supported_languages_touch BEFORE UPDATE ON supported_languages FOR EACH ROW EXECUTE FUNCTION touch_localization_row();
CREATE TRIGGER user_preferences_touch BEFORE UPDATE ON user_preferences FOR EACH ROW EXECUTE FUNCTION touch_localization_row();
CREATE TRIGGER supported_languages_record_history AFTER INSERT OR UPDATE OR DELETE ON supported_languages FOR EACH ROW EXECUTE FUNCTION record_entity_history('supported_language');
CREATE FUNCTION record_user_preference_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_state jsonb; new_state jsonb; changed text[];
BEGIN
 old_state:=CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END;
 new_state:=CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END;
 SELECT COALESCE(array_agg(key ORDER BY key),ARRAY[]::text[]) INTO changed FROM jsonb_object_keys(COALESCE(old_state,'{}'::jsonb)||COALESCE(new_state,'{}'::jsonb)) key WHERE old_state->key IS DISTINCT FROM new_state->key;
 INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,request_id,correlation_id,before_state,after_state,changed_fields,reason,metadata)
 VALUES ('user_preference',CASE WHEN TG_OP='DELETE' THEN OLD.user_id ELSE NEW.user_id END,CASE TG_OP WHEN 'INSERT' THEN 'CREATE' ELSE TG_OP END,NULLIF(current_setting('app.user_id',true),'')::bigint,COALESCE(NULLIF(current_setting('app.actor_type',true),''),'automated_process'),COALESCE(NULLIF(current_setting('app.event_source',true),''),'database'),NULLIF(current_setting('app.request_id',true),'')::uuid,NULLIF(current_setting('app.correlation_id',true),'')::uuid,old_state,new_state,changed,NULLIF(current_setting('app.change_reason',true),''),COALESCE(NULLIF(current_setting('app.event_metadata',true),'')::jsonb,'{}'::jsonb));
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER user_preferences_record_history AFTER INSERT OR UPDATE OR DELETE ON user_preferences FOR EACH ROW EXECUTE FUNCTION record_user_preference_history();

INSERT INTO privileges(code,name,description,category,is_reserved,account_type_restriction) VALUES
 ('localization.administer','Administer Localization','Manage supported languages and translation catalogues.','administration',true,'person'),
 ('classification_scheme.modify_metadata','Modify Classification Scheme Metadata','Modify multilingual names and descriptions for classification schemes.','administration',false,'person'),
 ('classification.modify_metadata','Modify Classification Metadata','Modify multilingual names and descriptions for classifications.','administration',false,'person'),
 ('user.modify_metadata','Modify User Metadata','Modify multilingual names and descriptions for users.','administration',false,'person'),
 ('role.modify_metadata','Modify Role Metadata','Modify multilingual names and descriptions for roles.','administration',false,'person'),
 ('org_unit.modify_metadata','Modify Organization Unit Metadata','Modify multilingual names and descriptions for organization units.','administration',false,'person'),
 ('security_level.modify_metadata','Modify Security Level Metadata','Modify multilingual names and descriptions for security levels.','administration',false,'person'),
 ('profile.modify_metadata','Modify Profile Metadata','Modify multilingual names and descriptions for authorization profiles.','administration',false,'person') ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT profile.id,privilege.id FROM profiles profile CROSS JOIN privileges privilege
WHERE (privilege.code='localization.administer' AND profile.code IN ('ALL_PRIVS','SYS_ADMIN'))
 OR (privilege.code IN ('classification_scheme.modify_metadata','classification.modify_metadata','user.modify_metadata','role.modify_metadata','org_unit.modify_metadata','security_level.modify_metadata') AND profile.code='ALL_PRIVS')
 OR (privilege.code='profile.modify_metadata' AND profile.code IN ('ALL_PRIVS','SYS_ADMIN'))
ON CONFLICT DO NOTHING;
-- Internationalization and user preferences Phase 1 ends.

-- Internationalization Phase 2 message catalogue begins.
CREATE TABLE ui_message_definitions (
 message_key text PRIMARY KEY, context_group text NOT NULL CHECK(btrim(context_group)<>''),
 default_text text NOT NULL CHECK(btrim(default_text)<>''), semantic_meaning text NOT NULL CHECK(btrim(semantic_meaning)<>''),
 common_locations jsonb NOT NULL CHECK(jsonb_typeof(common_locations)='array' AND jsonb_array_length(common_locations)>0),
 translator_guidance text NOT NULL CHECK(btrim(translator_guidance)<>''), grammatical_role text NOT NULL CHECK(btrim(grammatical_role)<>''),
 parameter_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(parameter_schema)='object'), rendered_example text NOT NULL CHECK(btrim(rendered_example)<>''),
 is_html boolean NOT NULL DEFAULT false, is_deprecated boolean NOT NULL DEFAULT false,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 version bigint NOT NULL DEFAULT 1 CHECK(version>0),CHECK(message_key~'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$')
);
CREATE INDEX ui_message_definitions_context_key_idx ON ui_message_definitions(context_group,message_key);
CREATE TABLE ui_message_translations (
 message_key text NOT NULL REFERENCES ui_message_definitions(message_key) ON DELETE RESTRICT,
 language_tag text NOT NULL REFERENCES supported_languages(language_tag) ON DELETE RESTRICT,
 translated_text text NOT NULL CHECK(btrim(translated_text)<>''),published_text text CHECK(published_text IS NULL OR btrim(published_text)<>''),
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),origin text NOT NULL DEFAULT 'source_copy' CHECK(origin IN ('source_copy','manual','generated','imported')),
 generation_metadata jsonb CHECK(generation_metadata IS NULL OR jsonb_typeof(generation_metadata)='object'),needs_review boolean NOT NULL DEFAULT false,
 updated_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,reviewed_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,date_reviewed timestamptz,
 published_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,date_published timestamptz,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 PRIMARY KEY(message_key,language_tag),
 CONSTRAINT ui_message_translations_source_copy_not_published
   CHECK(lower(language_tag)='en' OR origin<>'source_copy' OR
         (status='draft' AND published_text IS NULL AND published_by_user_id IS NULL AND date_published IS NULL)),
 CHECK(origin<>'generated' OR published_text IS NULL OR (reviewed_by_user_id IS NOT NULL AND date_reviewed IS NOT NULL)),
 CHECK((reviewed_by_user_id IS NULL)=(date_reviewed IS NULL)),CHECK((published_by_user_id IS NULL)=(date_published IS NULL))
);
CREATE INDEX ui_message_translations_language_status_idx ON ui_message_translations(language_tag,status,message_key);
CREATE INDEX ui_message_translations_language_origin_idx ON ui_message_translations(language_tag,origin,message_key);
CREATE INDEX ui_message_translations_attention_idx ON ui_message_translations(language_tag,needs_review,message_key);
CREATE FUNCTION require_localization_change_reason() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF NULLIF(btrim(current_setting('app.change_reason',true)),'') IS NULL THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='localization_change_reason_required'; END IF; RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END; END;
$$;
CREATE TRIGGER supported_languages_require_reason BEFORE INSERT OR UPDATE OR DELETE ON supported_languages FOR EACH ROW EXECUTE FUNCTION require_localization_change_reason();
CREATE TRIGGER ui_message_definitions_require_reason BEFORE INSERT OR UPDATE OR DELETE ON ui_message_definitions FOR EACH ROW EXECUTE FUNCTION require_localization_change_reason();
CREATE TRIGGER ui_message_translations_require_reason BEFORE INSERT OR UPDATE OR DELETE ON ui_message_translations FOR EACH ROW EXECUTE FUNCTION require_localization_change_reason();
CREATE TRIGGER ui_message_definitions_touch BEFORE UPDATE ON ui_message_definitions FOR EACH ROW EXECUTE FUNCTION touch_localization_row();
CREATE TRIGGER ui_message_translations_touch BEFORE UPDATE ON ui_message_translations FOR EACH ROW EXECUTE FUNCTION touch_localization_row();
CREATE FUNCTION record_localization_catalogue_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_state jsonb;new_state jsonb;changed text[];stable_key text;
BEGIN old_state:=CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END;new_state:=CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END;
 SELECT COALESCE(array_agg(key ORDER BY key),ARRAY[]::text[]) INTO changed FROM jsonb_object_keys(COALESCE(old_state,'{}'::jsonb)||COALESCE(new_state,'{}'::jsonb)) key WHERE old_state->key IS DISTINCT FROM new_state->key;
 stable_key:=COALESCE(new_state->>'message_key',old_state->>'message_key')||COALESCE('|'||COALESCE(new_state->>'language_tag',old_state->>'language_tag'),'');
 INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,request_id,correlation_id,before_state,after_state,changed_fields,reason,metadata)
 VALUES(TG_ARGV[0],hashtextextended(stable_key,0),CASE TG_OP WHEN 'INSERT' THEN 'CREATE' ELSE TG_OP END,NULLIF(current_setting('app.user_id',true),'')::bigint,COALESCE(NULLIF(current_setting('app.actor_type',true),''),'automated_process'),COALESCE(NULLIF(current_setting('app.event_source',true),''),'database'),NULLIF(current_setting('app.request_id',true),'')::uuid,NULLIF(current_setting('app.correlation_id',true),'')::uuid,old_state,new_state,changed,NULLIF(current_setting('app.change_reason',true),''),COALESCE(NULLIF(current_setting('app.event_metadata',true),'')::jsonb,'{}'::jsonb));
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;END;
$$;
CREATE TRIGGER ui_message_definitions_history AFTER INSERT OR UPDATE OR DELETE ON ui_message_definitions FOR EACH ROW EXECUTE FUNCTION record_localization_catalogue_history('ui_message_definition');
CREATE TRIGGER ui_message_translations_history AFTER INSERT OR UPDATE OR DELETE ON ui_message_translations FOR EACH ROW EXECUTE FUNCTION record_localization_catalogue_history('ui_message_translation');
-- Internationalization Phase 2 message catalogue ends.

-- Internationalization Phase 4 multilingual entity metadata begins.
ALTER TABLE classification_schemes ADD COLUMN translations jsonb;
ALTER TABLE classifications ADD COLUMN translations jsonb;
ALTER TABLE users ADD COLUMN description text, ADD COLUMN translations jsonb;
ALTER TABLE roles ADD COLUMN translations jsonb;
ALTER TABLE org_units ADD COLUMN translations jsonb;
ALTER TABLE security_levels ADD COLUMN description text, ADD COLUMN translations jsonb;
ALTER TABLE profiles ADD COLUMN translations jsonb;
ALTER TABLE classification_schemes ADD CONSTRAINT classification_schemes_translations_object CHECK (translations IS NULL OR jsonb_typeof(translations)='object');
ALTER TABLE classifications ADD CONSTRAINT classifications_translations_object CHECK (translations IS NULL OR jsonb_typeof(translations)='object');
ALTER TABLE users ADD CONSTRAINT users_translations_object CHECK (translations IS NULL OR jsonb_typeof(translations)='object');
ALTER TABLE roles ADD CONSTRAINT roles_translations_object CHECK (translations IS NULL OR jsonb_typeof(translations)='object');
ALTER TABLE org_units ADD CONSTRAINT org_units_translations_object CHECK (translations IS NULL OR jsonb_typeof(translations)='object');
ALTER TABLE security_levels ADD CONSTRAINT security_levels_translations_object CHECK (translations IS NULL OR jsonb_typeof(translations)='object');
ALTER TABLE profiles ADD CONSTRAINT profiles_translations_object CHECK (translations IS NULL OR jsonb_typeof(translations)='object');
CREATE FUNCTION validate_multilingual_entity_translations() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE locale_entry record;field_entry record;allowed_fields text[];
BEGIN
 IF NEW.translations IS NULL THEN RETURN NEW;END IF;
 allowed_fields:=CASE WHEN TG_TABLE_NAME IN ('classification_schemes','classifications') THEN ARRAY['title','description'] ELSE ARRAY['name','description'] END;
 FOR locale_entry IN SELECT key,value FROM jsonb_each(NEW.translations) LOOP
  IF locale_entry.key !~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$' OR NOT EXISTS(SELECT 1 FROM supported_languages WHERE language_tag=locale_entry.key AND is_enabled) OR jsonb_typeof(locale_entry.value)<>'object' OR locale_entry.value='{}'::jsonb THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='invalid_entity_translation_locale',DETAIL=locale_entry.key;END IF;
  FOR field_entry IN SELECT key,value FROM jsonb_each(locale_entry.value) LOOP
   IF NOT field_entry.key=ANY(allowed_fields) OR jsonb_typeof(field_entry.value)<>'string' OR btrim(field_entry.value #>> '{}')='' OR field_entry.value #>> '{}'<>btrim(field_entry.value #>> '{}') THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='invalid_entity_translation_field',DETAIL=locale_entry.key||'.'||field_entry.key;END IF;
  END LOOP;
 END LOOP;RETURN NEW;
END;$$;
CREATE TRIGGER classification_schemes_validate_translations BEFORE INSERT OR UPDATE OF translations ON classification_schemes FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();
CREATE TRIGGER classifications_validate_translations BEFORE INSERT OR UPDATE OF translations ON classifications FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();
CREATE TRIGGER users_validate_translations BEFORE INSERT OR UPDATE OF translations ON users FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();
CREATE TRIGGER roles_validate_translations BEFORE INSERT OR UPDATE OF translations ON roles FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();
CREATE TRIGGER org_units_validate_translations BEFORE INSERT OR UPDATE OF translations ON org_units FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();
CREATE TRIGGER security_levels_validate_translations BEFORE INSERT OR UPDATE OF translations ON security_levels FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();
CREATE TRIGGER profiles_validate_translations BEFORE INSERT OR UPDATE OF translations ON profiles FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();
DROP TRIGGER IF EXISTS security_levels_bump_version ON security_levels;
CREATE TRIGGER security_levels_bump_version BEFORE UPDATE ON security_levels FOR EACH ROW EXECUTE FUNCTION bump_entity_version();
CREATE INDEX classification_schemes_translations_gin ON classification_schemes USING gin(translations jsonb_path_ops);
CREATE INDEX classifications_translations_gin ON classifications USING gin(translations jsonb_path_ops);
CREATE INDEX users_translations_gin ON users USING gin(translations jsonb_path_ops);
CREATE INDEX roles_translations_gin ON roles USING gin(translations jsonb_path_ops);
CREATE INDEX org_units_translations_gin ON org_units USING gin(translations jsonb_path_ops);
CREATE INDEX security_levels_translations_gin ON security_levels USING gin(translations jsonb_path_ops);
CREATE INDEX profiles_translations_gin ON profiles USING gin(translations jsonb_path_ops);
-- Internationalization Phase 4 multilingual entity metadata ends.

-- Internationalization Phase 5 search and hardening begins.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX event_history_actor_name_trgm_idx ON event_history USING gin(actor_name gin_trgm_ops);
CREATE INDEX event_history_actor_email_trgm_idx ON event_history USING gin(actor_email gin_trgm_ops);
CREATE INDEX event_history_actor_identity_idx ON event_history(actor_user_id,md5(actor_name),md5(actor_email),actor_type);

CREATE INDEX classification_schemes_translation_text_trgm_idx ON classification_schemes USING gin ((translations::text) gin_trgm_ops);
CREATE INDEX classifications_translation_text_trgm_idx ON classifications USING gin ((translations::text) gin_trgm_ops);
CREATE INDEX users_translation_text_trgm_idx ON users USING gin ((translations::text) gin_trgm_ops);
CREATE INDEX roles_translation_text_trgm_idx ON roles USING gin ((translations::text) gin_trgm_ops);
CREATE INDEX org_units_translation_text_trgm_idx ON org_units USING gin ((translations::text) gin_trgm_ops);
CREATE INDEX security_levels_translation_text_trgm_idx ON security_levels USING gin ((translations::text) gin_trgm_ops);
CREATE INDEX profiles_translation_text_trgm_idx ON profiles USING gin ((translations::text) gin_trgm_ops);
-- Internationalization Phase 5 search and hardening ends.

COMMIT;

-- Notifications and messaging: complete storage model (specification section 7).
CREATE TABLE message_envelopes (
    id uuid PRIMARY KEY,
    sender_user_id bigint,
    sender_name text NOT NULL,
    sender_kind text NOT NULL,
    message_kind text NOT NULL,
    action_amendment_id uuid,
    system_producer_code text,
    system_configuration_version_id uuid,
    source_event_type text,
    source_event_id text,
    triggered_by_user_id bigint,
    is_test boolean NOT NULL DEFAULT false,
    test_run_id uuid,
    test_initiated_by_user_id bigint,
    subject text NOT NULL,
    priority text NOT NULL DEFAULT 'normal',
    body_rich_text text NOT NULL,
    security_level_id bigint NOT NULL,
    action_required boolean NOT NULL,
    action_due_date date,
    action_due_timezone text,
    action_due_at timestamptz,
    read_receipt_requested boolean NOT NULL,
    relationship_kind text,
    related_delivery_id uuid,
    related_envelope_id uuid,
    sent_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    sender_deleted_at timestamptz,
    sender_purge_after timestamptz,
    request_id uuid NOT NULL
 );

CREATE TABLE message_envelope_localizations (
    envelope_id uuid NOT NULL,
    language_tag text NOT NULL,
    subject text NOT NULL,
    body_rich_text text NOT NULL,
    direction text NOT NULL,
    rendered_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
 );

CREATE TABLE message_recipient_selectors (
    id bigserial PRIMARY KEY,
    envelope_id uuid NOT NULL,
    recipient_type text NOT NULL,
    selector_kind text NOT NULL,
    user_id bigint,
    role_id bigint,
    org_unit_id bigint,
    display_name text NOT NULL,
    ordinal integer NOT NULL
 );

CREATE TABLE message_addressees (
    envelope_id uuid NOT NULL,
    user_id bigint NOT NULL,
    recipient_name text NOT NULL,
    recipient_type text NOT NULL,
    ordinal integer NOT NULL
 );

CREATE TABLE message_mailboxes (
    user_id bigint PRIMARY KEY,
    last_sequence bigint NOT NULL DEFAULT 0
 );

CREATE TABLE message_deliveries (
    id uuid PRIMARY KEY,
    envelope_id uuid NOT NULL,
    recipient_user_id bigint NOT NULL,
    recipient_type text NOT NULL,
    mailbox_sequence bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    language_tag_at_send text NOT NULL,
    read_at timestamptz,
    deleted_at timestamptz,
    purge_after timestamptz,
    deletion_reason text
 );

CREATE TABLE message_action_completions (
    original_delivery_id uuid PRIMARY KEY,
    reply_envelope_id uuid NOT NULL,
    completed_by_user_id bigint NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
 );

CREATE TABLE message_action_amendments (
    id uuid PRIMARY KEY,
    original_envelope_id uuid NOT NULL,
    sequence integer NOT NULL,
    amendment_kind text NOT NULL,
    previous_action_required boolean NOT NULL,
    previous_due_date date,
    previous_due_timezone text,
    previous_due_at timestamptz,
    new_action_required boolean NOT NULL,
    new_due_date date,
    new_due_timezone text,
    new_due_at timestamptz,
    reason text NOT NULL,
    created_by_user_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    request_id uuid NOT NULL
 );

CREATE TABLE message_resource_links (
    id bigserial PRIMARY KEY,
    envelope_id uuid NOT NULL,
    link_token uuid NOT NULL,
    ordinal integer NOT NULL,
    resource_kind text NOT NULL,
    target_id_snapshot bigint NOT NULL,
    aggregation_id bigint,
    record_id bigint,
    security_level_id_at_send bigint NOT NULL
 );

CREATE TABLE message_drafts (
    id uuid PRIMARY KEY,
    owner_user_id bigint NOT NULL,
    subject text,
    priority text NOT NULL DEFAULT 'normal',
    body_rich_text text,
    security_level_id bigint NOT NULL,
    action_required boolean NOT NULL,
    action_due_date date,
    action_due_timezone text,
    read_receipt_requested boolean NOT NULL,
    relationship_kind text,
    related_delivery_id uuid,
    related_envelope_id uuid,
    version bigint NOT NULL DEFAULT 1,
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    deleted_at timestamptz,
    purge_after timestamptz,
    deletion_reason text
 );

CREATE TABLE message_record_captures (
    id uuid PRIMARY KEY,
    selected_envelope_id uuid,
    selected_envelope_id_at_capture uuid NOT NULL,
    record_id bigint,
    record_id_at_capture bigint NOT NULL,
    captured_by_user_id bigint NOT NULL,
    captured_by_name text NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
 );

CREATE TABLE message_record_capture_components (
    id bigserial PRIMARY KEY,
    capture_id uuid NOT NULL,
    component_kind text NOT NULL,
    envelope_id uuid,
    envelope_id_at_capture uuid,
    digital_component_id bigint,
    digital_component_id_at_capture bigint NOT NULL,
    component_order integer NOT NULL,
    is_selected_message boolean NOT NULL
 );

CREATE TABLE system_notification_producers (
    producer_code text PRIMARY KEY,
    feature_code text NOT NULL,
    event_type text NOT NULL,
    required_for_business_commit boolean NOT NULL,
    contract_version integer NOT NULL,
    contract_definition jsonb NOT NULL,
    active_configuration_version_id uuid
 );

CREATE TABLE system_notification_configuration_versions (
    id uuid PRIMARY KEY,
    producer_code text NOT NULL,
    version integer NOT NULL,
    enabled boolean NOT NULL,
    subject_template text NOT NULL,
    body_template_rich_text text NOT NULL,
    priority text NOT NULL DEFAULT 'normal',
    audience_mode text NOT NULL,
    resource_presentation jsonb NOT NULL,
    operational_owner text NOT NULL,
    change_reason text NOT NULL,
    created_by_user_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
 );

CREATE TABLE system_notification_configuration_translations (
    configuration_version_id uuid NOT NULL,
    language_tag text NOT NULL,
    subject_template text NOT NULL,
    body_template_rich_text text NOT NULL,
    review_status text NOT NULL,
    reviewed_by_user_id bigint,
    reviewed_at timestamptz
 );

CREATE TABLE message_request_receipts (
    id bigserial PRIMARY KEY,
    operation_kind text NOT NULL,
    principal_user_id bigint,
    producer_code text,
    request_id uuid NOT NULL,
    request_fingerprint text NOT NULL,
    source_event_type text,
    source_event_id text,
    result_envelope_id uuid NOT NULL,
    result_amendment_id uuid,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    result_purged_at timestamptz
 );

CREATE TABLE message_draft_recipient_selectors (
    id bigserial PRIMARY KEY,
    draft_id uuid NOT NULL,
    recipient_type text NOT NULL,
    selector_kind text NOT NULL,
    user_id bigint,
    role_id bigint,
    org_unit_id bigint,
    display_name text NOT NULL,
    ordinal integer NOT NULL
 );

CREATE TABLE message_draft_resource_links (
    id bigserial PRIMARY KEY,
    draft_id uuid NOT NULL,
    link_token uuid NOT NULL,
    ordinal integer NOT NULL,
    resource_kind text NOT NULL,
    target_id_snapshot bigint NOT NULL,
    aggregation_id bigint,
    record_id bigint,
    security_level_id_at_send bigint NOT NULL
 );

CREATE TABLE system_notification_configuration_audiences (
    id bigserial PRIMARY KEY,
    configuration_version_id uuid NOT NULL,
    recipient_type text NOT NULL,
    selector_kind text NOT NULL,
    user_id bigint,
    role_id bigint,
    org_unit_id bigint,
    display_name text NOT NULL,
    ordinal integer NOT NULL
 );

ALTER TABLE message_envelopes ADD FOREIGN KEY (sender_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_envelopes ADD FOREIGN KEY (action_amendment_id) REFERENCES message_action_amendments(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_envelopes ADD FOREIGN KEY (system_producer_code) REFERENCES system_notification_producers(producer_code) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_envelopes ADD FOREIGN KEY (system_configuration_version_id) REFERENCES system_notification_configuration_versions(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_envelopes ADD FOREIGN KEY (triggered_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_envelopes ADD FOREIGN KEY (test_initiated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_envelopes ADD FOREIGN KEY (security_level_id) REFERENCES security_levels(id) ON DELETE RESTRICT;
ALTER TABLE message_envelopes ADD FOREIGN KEY (related_delivery_id) REFERENCES message_deliveries(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_envelopes ADD FOREIGN KEY (related_envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_envelope_localizations ADD FOREIGN KEY (envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_envelope_localizations ADD FOREIGN KEY (language_tag) REFERENCES supported_languages(language_tag) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_recipient_selectors ADD FOREIGN KEY (envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_recipient_selectors ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_recipient_selectors ADD FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_recipient_selectors ADD FOREIGN KEY (org_unit_id) REFERENCES org_units(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_addressees ADD FOREIGN KEY (envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_addressees ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_mailboxes ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_deliveries ADD FOREIGN KEY (envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_deliveries ADD FOREIGN KEY (recipient_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_action_completions ADD FOREIGN KEY (original_delivery_id) REFERENCES message_deliveries(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_action_completions ADD FOREIGN KEY (reply_envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_action_completions ADD FOREIGN KEY (completed_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_action_amendments ADD FOREIGN KEY (original_envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_action_amendments ADD FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_resource_links ADD FOREIGN KEY (envelope_id) REFERENCES message_envelopes(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_resource_links ADD FOREIGN KEY (aggregation_id) REFERENCES aggregations(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_resource_links ADD FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_resource_links ADD FOREIGN KEY (security_level_id_at_send) REFERENCES security_levels(id) ON DELETE RESTRICT;
ALTER TABLE message_drafts ADD FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_drafts ADD FOREIGN KEY (security_level_id) REFERENCES security_levels(id) ON DELETE RESTRICT;
ALTER TABLE message_record_captures ADD FOREIGN KEY (selected_envelope_id) REFERENCES message_envelopes(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_record_captures ADD FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_record_captures ADD FOREIGN KEY (captured_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_record_capture_components ADD FOREIGN KEY (capture_id) REFERENCES message_record_captures(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_record_capture_components ADD FOREIGN KEY (envelope_id) REFERENCES message_envelopes(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_record_capture_components ADD FOREIGN KEY (digital_component_id) REFERENCES digital_components(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE system_notification_producers ADD FOREIGN KEY (active_configuration_version_id) REFERENCES system_notification_configuration_versions(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE system_notification_configuration_versions ADD FOREIGN KEY (producer_code) REFERENCES system_notification_producers(producer_code) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE system_notification_configuration_versions ADD FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE system_notification_configuration_translations ADD FOREIGN KEY (configuration_version_id) REFERENCES system_notification_configuration_versions(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE system_notification_configuration_translations ADD FOREIGN KEY (language_tag) REFERENCES supported_languages(language_tag) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE system_notification_configuration_translations ADD FOREIGN KEY (reviewed_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_request_receipts ADD FOREIGN KEY (principal_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_request_receipts ADD FOREIGN KEY (producer_code) REFERENCES system_notification_producers(producer_code) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_draft_recipient_selectors ADD FOREIGN KEY (draft_id) REFERENCES message_drafts(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_draft_recipient_selectors ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE message_draft_recipient_selectors ADD FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_draft_recipient_selectors ADD FOREIGN KEY (org_unit_id) REFERENCES org_units(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_draft_resource_links ADD FOREIGN KEY (draft_id) REFERENCES message_drafts(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_draft_resource_links ADD FOREIGN KEY (aggregation_id) REFERENCES aggregations(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_draft_resource_links ADD FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_draft_resource_links ADD FOREIGN KEY (security_level_id_at_send) REFERENCES security_levels(id) ON DELETE RESTRICT;
ALTER TABLE system_notification_configuration_audiences ADD FOREIGN KEY (configuration_version_id) REFERENCES system_notification_configuration_versions(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE system_notification_configuration_audiences ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE system_notification_configuration_audiences ADD FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE system_notification_configuration_audiences ADD FOREIGN KEY (org_unit_id) REFERENCES org_units(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE message_envelopes
    ADD CHECK (sender_kind IN ('user','system')),
    ADD CHECK (message_kind IN ('user_message','system_notification','action_amendment_notice')),
    ADD CHECK ((sender_kind='user')=(sender_user_id IS NOT NULL)),
    ADD CHECK ((sender_kind='system')=(message_kind='system_notification')),
    ADD CHECK ((message_kind='action_amendment_notice')=(action_amendment_id IS NOT NULL)),
    ADD UNIQUE (action_amendment_id), ADD UNIQUE (test_run_id),
    ADD CHECK ((sender_kind='system' AND system_producer_code IS NOT NULL
        AND system_configuration_version_id IS NOT NULL AND source_event_type IS NOT NULL
        AND source_event_id IS NOT NULL AND length(source_event_id) BETWEEN 1 AND 255)
        OR (sender_kind='user' AND system_producer_code IS NULL
        AND system_configuration_version_id IS NULL AND source_event_type IS NULL
        AND source_event_id IS NULL AND triggered_by_user_id IS NULL)),
    ADD CHECK ((is_test AND sender_kind='system' AND test_run_id IS NOT NULL AND test_initiated_by_user_id IS NOT NULL)
        OR (NOT is_test AND test_run_id IS NULL AND test_initiated_by_user_id IS NULL)),
    ADD CHECK (COALESCE((relationship_kind IS NULL AND related_delivery_id IS NULL AND related_envelope_id IS NULL)
        OR (relationship_kind='reply' AND related_delivery_id IS NOT NULL AND related_envelope_id IS NULL)
        OR (relationship_kind='follow_up' AND related_delivery_id IS NULL AND related_envelope_id IS NOT NULL)
        OR (relationship_kind='forward' AND num_nonnulls(related_delivery_id,related_envelope_id)=1),false)),
    ADD CHECK (sender_deleted_at IS NULL OR sender_purge_after IS NOT NULL),
    ADD CHECK (sender_kind='user' OR (sender_deleted_at IS NULL AND sender_purge_after IS NULL)),
    ADD CHECK (expires_at>sent_at),
    ADD CHECK (btrim(sender_name)<>''),
    ADD CHECK (char_length(subject) BETWEEN 1 AND 255 AND btrim(subject)<>''),
    ADD CHECK (priority IN ('normal','high','very_high')),
    ADD CHECK (octet_length(body_rich_text)<=65536),
    ADD CHECK (num_nonnulls(action_due_date,action_due_timezone,action_due_at) IN (0,3)),
    ADD CHECK (action_required IS TRUE OR action_due_date IS NULL),
    ADD CHECK (sender_kind<>'system' OR (sender_name='system' AND NOT action_required AND NOT read_receipt_requested)),
    ADD CHECK (message_kind<>'action_amendment_notice' OR
        (relationship_kind IS NULL AND NOT is_test AND NOT action_required AND NOT read_receipt_requested));
CREATE UNIQUE INDEX message_envelopes_user_request_idx ON message_envelopes(sender_user_id,request_id) WHERE sender_kind='user';
CREATE UNIQUE INDEX message_envelopes_system_request_idx ON message_envelopes(system_producer_code,request_id) WHERE sender_kind='system';
CREATE UNIQUE INDEX message_envelopes_system_event_idx ON message_envelopes(system_producer_code,source_event_type,source_event_id) WHERE sender_kind='system' AND NOT is_test;
CREATE INDEX message_envelopes_outbox_idx ON message_envelopes(sender_user_id,sent_at DESC,id DESC) WHERE sender_deleted_at IS NULL AND message_kind='user_message';
CREATE INDEX message_envelopes_expiry_idx ON message_envelopes(expires_at,id);
ALTER TABLE message_envelope_localizations ADD PRIMARY KEY(envelope_id,language_tag),
    ADD CHECK(direction IN ('ltr','rtl')), ADD CHECK(char_length(subject) BETWEEN 1 AND 255 AND btrim(subject)<>''),
    ADD CHECK(octet_length(body_rich_text)<=65536);
ALTER TABLE message_addressees ADD PRIMARY KEY(envelope_id,user_id),
    ADD UNIQUE(envelope_id,user_id,recipient_type), ADD UNIQUE(envelope_id,recipient_type,ordinal),
    ADD CHECK(recipient_type IN ('to','cc')), ADD CHECK(ordinal>=0), ADD CHECK(btrim(recipient_name)<>'');
ALTER TABLE message_mailboxes ADD CHECK(last_sequence>=0);
ALTER TABLE message_deliveries ADD UNIQUE(envelope_id,recipient_user_id), ADD UNIQUE(recipient_user_id,mailbox_sequence),
    ADD FOREIGN KEY(envelope_id,recipient_user_id,recipient_type) REFERENCES message_addressees(envelope_id,user_id,recipient_type),
    ADD CHECK(mailbox_sequence>0), ADD CHECK(recipient_type IN ('to','cc')),
    ADD CHECK((deleted_at IS NULL AND deletion_reason IS NULL)
        OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND deletion_reason IS NOT NULL AND deletion_reason IN ('user_deleted','retention_expired')));
CREATE INDEX message_deliveries_inbox_idx ON message_deliveries(recipient_user_id,deleted_at,read_at,created_at DESC,id);
CREATE INDEX message_deliveries_page_idx ON message_deliveries(recipient_user_id,mailbox_sequence DESC) WHERE deleted_at IS NULL;
ALTER TABLE message_action_completions ADD UNIQUE(reply_envelope_id);
CREATE INDEX message_action_completions_user_idx ON message_action_completions(completed_by_user_id,completed_at DESC);
ALTER TABLE message_action_amendments ADD UNIQUE(original_envelope_id,sequence), ADD UNIQUE(created_by_user_id,request_id),
    ADD CHECK(sequence>0), ADD CHECK(amendment_kind IN ('due_date_added','due_date_changed','due_date_removed','action_withdrawn')),
    ADD CHECK(btrim(reason)<>'' AND char_length(reason)<=2000),
    ADD CHECK(num_nonnulls(previous_due_date,previous_due_timezone,previous_due_at) IN (0,3)),
    ADD CHECK(num_nonnulls(new_due_date,new_due_timezone,new_due_at) IN (0,3));
ALTER TABLE message_drafts ADD CHECK(priority IN ('normal','high','very_high')), ADD CHECK(version>0),
    ADD CHECK(subject IS NULL OR char_length(subject)<=255), ADD CHECK(body_rich_text IS NULL OR octet_length(body_rich_text)<=65536),
    ADD CHECK((action_due_date IS NULL)=(action_due_timezone IS NULL)), ADD CHECK(action_required OR action_due_date IS NULL),
    ADD CHECK(relationship_kind IS NULL OR relationship_kind IN ('reply','forward','follow_up')),
    ADD CHECK((deleted_at IS NULL AND purge_after IS NULL AND deletion_reason IS NULL)
        OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND deletion_reason IS NOT NULL AND deletion_reason IN ('expired','discarded')));
CREATE INDEX message_drafts_owner_idx ON message_drafts(owner_user_id,date_updated DESC,id);
CREATE INDEX message_drafts_expiry_idx ON message_drafts(expires_at,id);
ALTER TABLE message_record_captures ADD UNIQUE(record_id), ADD UNIQUE(record_id_at_capture), ADD CHECK(btrim(captured_by_name)<>'');
ALTER TABLE message_record_capture_components ADD UNIQUE(digital_component_id), ADD UNIQUE(digital_component_id_at_capture),
    ADD UNIQUE(capture_id,component_order), ADD CHECK(component_order>0),
    ADD CHECK((component_kind='message' AND envelope_id_at_capture IS NOT NULL AND is_selected_message=(component_order=1))
        OR (component_kind='provenance' AND envelope_id IS NULL AND envelope_id_at_capture IS NULL AND NOT is_selected_message));
CREATE UNIQUE INDEX message_capture_provenance_idx ON message_record_capture_components(capture_id) WHERE component_kind='provenance';
CREATE UNIQUE INDEX message_capture_envelope_idx ON message_record_capture_components(capture_id,envelope_id_at_capture) WHERE component_kind='message';
ALTER TABLE system_notification_producers ADD CHECK(contract_version>0), ADD CHECK(jsonb_typeof(contract_definition)='object');
ALTER TABLE system_notification_configuration_versions ADD UNIQUE(producer_code,version), ADD UNIQUE(producer_code,id),
    ADD CHECK(version>0), ADD CHECK(priority IN ('normal','high','very_high')),
    ADD CHECK(char_length(subject_template) BETWEEN 1 AND 255 AND btrim(subject_template)<>''),
    ADD CHECK(octet_length(body_template_rich_text)<=65536), ADD CHECK(btrim(operational_owner)<>''), ADD CHECK(btrim(change_reason)<>''),
    ADD CHECK(jsonb_typeof(resource_presentation)='object');
ALTER TABLE system_notification_producers ADD FOREIGN KEY(producer_code,active_configuration_version_id)
    REFERENCES system_notification_configuration_versions(producer_code,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE message_envelopes ADD FOREIGN KEY(system_producer_code,system_configuration_version_id)
    REFERENCES system_notification_configuration_versions(producer_code,id);
ALTER TABLE system_notification_configuration_translations ADD PRIMARY KEY(configuration_version_id,language_tag),
    ADD CHECK(review_status IN ('draft','reviewed','published')),
    ADD CHECK(review_status='draft' OR (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)),
    ADD CHECK(char_length(subject_template) BETWEEN 1 AND 255 AND btrim(subject_template)<>''),
    ADD CHECK(octet_length(body_template_rich_text)<=65536);

ALTER TABLE message_recipient_selectors ADD CHECK(recipient_type IN ('to','cc')), ADD CHECK(ordinal>=0),
 ADD CHECK(btrim(display_name)<>''), ADD UNIQUE(envelope_id,recipient_type,ordinal),
 ADD CHECK((selector_kind='user' AND user_id IS NOT NULL AND role_id IS NULL AND org_unit_id IS NULL)
 OR (selector_kind='role' AND role_id IS NOT NULL AND user_id IS NULL AND org_unit_id IS NULL)
 OR (selector_kind='org_unit' AND org_unit_id IS NOT NULL AND user_id IS NULL AND role_id IS NULL)
 OR (selector_kind='everyone' AND user_id IS NULL AND role_id IS NULL AND org_unit_id IS NULL));
CREATE UNIQUE INDEX message_recipient_selectors_everyone_unique ON message_recipient_selectors(envelope_id,recipient_type) WHERE selector_kind='everyone';
CREATE UNIQUE INDEX message_recipient_selectors_user_id_unique ON message_recipient_selectors(envelope_id,recipient_type,user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX message_recipient_selectors_role_id_unique ON message_recipient_selectors(envelope_id,recipient_type,role_id) WHERE role_id IS NOT NULL;
CREATE UNIQUE INDEX message_recipient_selectors_org_unit_id_unique ON message_recipient_selectors(envelope_id,recipient_type,org_unit_id) WHERE org_unit_id IS NOT NULL;

ALTER TABLE message_draft_recipient_selectors ADD CHECK(recipient_type IN ('to','cc')), ADD CHECK(ordinal>=0),
 ADD CHECK(btrim(display_name)<>''), ADD UNIQUE(draft_id,recipient_type,ordinal),
 ADD CHECK((selector_kind='user' AND user_id IS NOT NULL AND role_id IS NULL AND org_unit_id IS NULL)
 OR (selector_kind='role' AND role_id IS NOT NULL AND user_id IS NULL AND org_unit_id IS NULL)
 OR (selector_kind='org_unit' AND org_unit_id IS NOT NULL AND user_id IS NULL AND role_id IS NULL)
 OR (selector_kind='everyone' AND user_id IS NULL AND role_id IS NULL AND org_unit_id IS NULL));
CREATE UNIQUE INDEX message_draft_recipient_selectors_everyone_unique ON message_draft_recipient_selectors(draft_id,recipient_type) WHERE selector_kind='everyone';
CREATE UNIQUE INDEX message_draft_recipient_selectors_user_id_unique ON message_draft_recipient_selectors(draft_id,recipient_type,user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX message_draft_recipient_selectors_role_id_unique ON message_draft_recipient_selectors(draft_id,recipient_type,role_id) WHERE role_id IS NOT NULL;
CREATE UNIQUE INDEX message_draft_recipient_selectors_org_unit_id_unique ON message_draft_recipient_selectors(draft_id,recipient_type,org_unit_id) WHERE org_unit_id IS NOT NULL;

ALTER TABLE system_notification_configuration_audiences ADD CHECK(recipient_type IN ('to','cc')), ADD CHECK(ordinal>=0),
 ADD CHECK(btrim(display_name)<>''), ADD UNIQUE(configuration_version_id,recipient_type,ordinal),
 ADD CHECK((selector_kind='user' AND user_id IS NOT NULL AND role_id IS NULL AND org_unit_id IS NULL)
 OR (selector_kind='role' AND role_id IS NOT NULL AND user_id IS NULL AND org_unit_id IS NULL)
 OR (selector_kind='org_unit' AND org_unit_id IS NOT NULL AND user_id IS NULL AND role_id IS NULL));
CREATE UNIQUE INDEX system_notification_configuration_audiences_user_id_unique ON system_notification_configuration_audiences(configuration_version_id,recipient_type,user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX system_notification_configuration_audiences_role_id_unique ON system_notification_configuration_audiences(configuration_version_id,recipient_type,role_id) WHERE role_id IS NOT NULL;
CREATE UNIQUE INDEX system_notification_configuration_audiences_org_unit_id_unique ON system_notification_configuration_audiences(configuration_version_id,recipient_type,org_unit_id) WHERE org_unit_id IS NOT NULL;

ALTER TABLE message_resource_links ADD UNIQUE(envelope_id,link_token), ADD UNIQUE(envelope_id,ordinal),
 ADD CHECK(ordinal>=0), ADD CHECK(resource_kind IN ('aggregation','record')),
 ADD CHECK(num_nonnulls(aggregation_id,record_id)<=1);
CREATE INDEX message_resource_links_aggregation_id_idx ON message_resource_links(aggregation_id) WHERE aggregation_id IS NOT NULL;
CREATE INDEX message_resource_links_record_id_idx ON message_resource_links(record_id) WHERE record_id IS NOT NULL;

ALTER TABLE message_draft_resource_links ADD UNIQUE(draft_id,link_token), ADD UNIQUE(draft_id,ordinal),
 ADD CHECK(ordinal>=0), ADD CHECK(resource_kind IN ('aggregation','record')),
 ADD CHECK(num_nonnulls(aggregation_id,record_id)<=1);
CREATE INDEX message_draft_resource_links_aggregation_id_idx ON message_draft_resource_links(aggregation_id) WHERE aggregation_id IS NOT NULL;
CREATE INDEX message_draft_resource_links_record_id_idx ON message_draft_resource_links(record_id) WHERE record_id IS NOT NULL;

ALTER TABLE message_request_receipts ADD CHECK(operation_kind IN ('send','amendment')),
 ADD CHECK(num_nonnulls(principal_user_id,producer_code)=1),
 ADD CHECK(operation_kind<>'amendment' OR principal_user_id IS NOT NULL),
 ADD CHECK((operation_kind='amendment')=(result_amendment_id IS NOT NULL)),
 ADD CHECK(length(request_fingerprint)=64),
 ADD CHECK((source_event_type IS NULL)=(source_event_id IS NULL));
CREATE UNIQUE INDEX message_request_receipts_user_key ON message_request_receipts(operation_kind,principal_user_id,request_id) WHERE principal_user_id IS NOT NULL;
CREATE UNIQUE INDEX message_request_receipts_producer_key ON message_request_receipts(operation_kind,producer_code,request_id) WHERE producer_code IS NOT NULL;
CREATE UNIQUE INDEX message_request_receipts_event_key ON message_request_receipts(producer_code,source_event_type,source_event_id) WHERE source_event_id IS NOT NULL;
CREATE INDEX message_request_receipts_result_idx ON message_request_receipts(result_envelope_id);

-- Reuse the established effective-role and privilege predicates everywhere.
CREATE FUNCTION messaging_user_clearance(p_user bigint) RETURNS integer LANGUAGE sql STABLE AS $$
 SELECT max(l.level_number)::integer FROM users u
 JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
 JOIN security_levels l ON l.id=r.security_level_id
 WHERE u.id=p_user AND u.status='active' AND u.account_type='person'
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND role_effectively_active(r.id)
$$;
CREATE FUNCTION messaging_user_eligible(p_user bigint,p_level integer) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(messaging_user_clearance(p_user)>=p_level,false)
 AND user_has_global_privilege(p_user,'messaging.user_messages.exchange')
$$;

-- Ordinary writes cannot edit sent content. Whole-group purge is a later-phase
-- service operation; no ordinary API is granted a way to enable deletion.
CREATE FUNCTION messaging_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_immutable';
END $$;
CREATE FUNCTION messaging_delivery_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-'read_at') IS DISTINCT FROM (to_jsonb(OLD)-'read_at')
 OR (OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at)
 OR NEW.read_at IS NULL THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_delivery_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION messaging_resource_link_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF num_nonnulls(NEW.aggregation_id,NEW.record_id)<>1
 OR (CASE NEW.resource_kind WHEN 'aggregation' THEN NEW.aggregation_id
 WHEN 'record' THEN NEW.record_id END)
 IS DISTINCT FROM NEW.target_id_snapshot THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_resource_target_mismatch';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION messaging_resource_link_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['aggregation_id','record_id'])
 IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['aggregation_id','record_id'])
 OR num_nonnulls(NEW.aggregation_id,NEW.record_id)<>0
 OR EXISTS(SELECT 1 FROM aggregations WHERE id=OLD.aggregation_id)
 OR EXISTS(SELECT 1 FROM records WHERE id=OLD.record_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_resource_link_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_envelopes_immutable BEFORE UPDATE OR DELETE ON message_envelopes FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_envelope_localizations_immutable BEFORE UPDATE OR DELETE ON message_envelope_localizations FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_recipient_selectors_immutable BEFORE UPDATE OR DELETE ON message_recipient_selectors FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_addressees_immutable BEFORE UPDATE OR DELETE ON message_addressees FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_action_completions_immutable BEFORE UPDATE OR DELETE ON message_action_completions FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_action_amendments_immutable BEFORE UPDATE OR DELETE ON message_action_amendments FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_request_receipts_immutable BEFORE UPDATE OR DELETE ON message_request_receipts FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER system_notification_configuration_versions_immutable BEFORE UPDATE OR DELETE ON system_notification_configuration_versions FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER system_notification_configuration_translations_immutable BEFORE UPDATE OR DELETE ON system_notification_configuration_translations FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER system_notification_configuration_audiences_immutable BEFORE UPDATE OR DELETE ON system_notification_configuration_audiences FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_deliveries_read_once BEFORE UPDATE ON message_deliveries FOR EACH ROW EXECUTE FUNCTION messaging_delivery_update();
CREATE TRIGGER message_deliveries_no_delete BEFORE DELETE ON message_deliveries FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_resource_links_insert BEFORE INSERT ON message_resource_links FOR EACH ROW EXECUTE FUNCTION messaging_resource_link_insert();
CREATE TRIGGER message_resource_links_update BEFORE UPDATE ON message_resource_links FOR EACH ROW EXECUTE FUNCTION messaging_resource_link_update();
CREATE TRIGGER message_resource_links_no_delete BEFORE DELETE ON message_resource_links FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();

-- Commit-time guards allow transactional fan-out, but never partial messages.
CREATE FUNCTION messaging_validate_envelope() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e message_envelopes; parent message_envelopes;
BEGIN
 SELECT * INTO e FROM message_envelopes WHERE id=NEW.id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM message_recipient_selectors WHERE envelope_id=e.id AND recipient_type='to')
 OR NOT EXISTS(SELECT 1 FROM message_addressees WHERE envelope_id=e.id AND recipient_type='to')
 OR EXISTS(SELECT 1 FROM message_addressees a LEFT JOIN message_deliveries d
       ON d.envelope_id=a.envelope_id AND d.recipient_user_id=a.user_id
       WHERE a.envelope_id=e.id AND (d.id IS NULL OR a.user_id=e.sender_user_id))
 OR NOT EXISTS(SELECT 1 FROM message_request_receipts WHERE result_envelope_id=e.id) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_incomplete_fanout';
 END IF;
 IF e.sender_kind='system' AND e.security_level_id<>(SELECT id FROM security_levels ORDER BY level_number LIMIT 1) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_system_level';
 END IF;
 IF e.action_due_date IS NOT NULL AND
   (NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=e.action_due_timezone)
    OR e.action_due_at IS DISTINCT FROM ((e.action_due_date+1)::timestamp AT TIME ZONE e.action_due_timezone)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_due_boundary';
 END IF;
 IF e.related_delivery_id IS NOT NULL THEN
  SELECT original.* INTO parent FROM message_envelopes original
  JOIN message_deliveries d ON d.envelope_id=original.id
  WHERE d.id=e.related_delivery_id AND d.recipient_user_id=e.sender_user_id;
 ELSIF e.related_envelope_id IS NOT NULL THEN
  SELECT * INTO parent FROM message_envelopes WHERE id=e.related_envelope_id AND sender_user_id=e.sender_user_id;
 END IF;
 IF e.relationship_kind IS NOT NULL AND (parent.id IS NULL OR parent.message_kind='action_amendment_notice'
 OR parent.is_test OR (SELECT level_number FROM security_levels WHERE id=parent.security_level_id)>
 (SELECT level_number FROM security_levels WHERE id=e.security_level_id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_relationship_invalid';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER message_envelope_complete AFTER INSERT ON message_envelopes
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION messaging_validate_envelope();

CREATE FUNCTION messaging_validate_delivery() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM message_mailboxes WHERE user_id=NEW.recipient_user_id AND last_sequence=NEW.mailbox_sequence) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_sequence_not_allocated';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_delivery_sequence BEFORE INSERT ON message_deliveries FOR EACH ROW EXECUTE FUNCTION messaging_validate_delivery();
CREATE FUNCTION messaging_mailbox_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.user_id<>OLD.user_id OR NEW.last_sequence<>OLD.last_sequence+1 THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_mailbox_sequence_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_mailbox_update BEFORE UPDATE ON message_mailboxes FOR EACH ROW EXECUTE FUNCTION messaging_mailbox_update();

CREATE FUNCTION messaging_validate_completion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM message_deliveries d JOIN message_envelopes original ON original.id=d.envelope_id
 JOIN message_envelopes reply ON reply.id=NEW.reply_envelope_id
 WHERE d.id=NEW.original_delivery_id AND d.recipient_user_id=NEW.completed_by_user_id
 AND d.recipient_type='to'
 AND reply.sender_user_id=NEW.completed_by_user_id AND reply.relationship_kind='reply'
 AND reply.related_delivery_id=d.id AND NEW.completed_by_user_id=current_user_id()
 AND EXISTS(SELECT 1 FROM message_addressees a WHERE a.envelope_id=reply.id AND a.user_id=original.sender_user_id AND a.recipient_type='to')
 AND original.action_required AND original.message_kind='user_message'
 AND NOT EXISTS(SELECT 1 FROM message_action_amendments a WHERE a.original_envelope_id=original.id AND NOT a.new_action_required)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_completion_invalid';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER message_completion_valid AFTER INSERT ON message_action_completions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION messaging_validate_completion();

ALTER TABLE message_action_amendments ADD CHECK(previous_action_required),
 ADD CHECK((amendment_kind='due_date_added' AND previous_due_date IS NULL AND new_due_date IS NOT NULL AND new_action_required)
 OR (amendment_kind='due_date_changed' AND previous_due_date IS NOT NULL AND new_due_date IS NOT NULL AND new_action_required
     AND ROW(previous_due_date,previous_due_timezone,previous_due_at) IS DISTINCT FROM ROW(new_due_date,new_due_timezone,new_due_at))
 OR (amendment_kind='due_date_removed' AND previous_due_date IS NOT NULL AND new_due_date IS NULL AND new_action_required)
 OR (amendment_kind='action_withdrawn' AND NOT new_action_required AND new_due_date IS NULL));
CREATE FUNCTION messaging_validate_amendment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original message_envelopes; previous message_action_amendments;
BEGIN
 SELECT * INTO original FROM message_envelopes WHERE id=NEW.original_envelope_id FOR UPDATE;
 SELECT * INTO previous FROM message_action_amendments WHERE original_envelope_id=NEW.original_envelope_id
 AND sequence<NEW.sequence ORDER BY sequence DESC LIMIT 1;
 IF original.message_kind<>'user_message' OR NOT original.action_required OR original.sender_user_id<>NEW.created_by_user_id
 OR original.is_test OR original.sender_deleted_at IS NOT NULL OR original.expires_at<=clock_timestamp()
 OR NEW.created_by_user_id<>current_user_id()
 OR (NEW.new_due_at IS NOT NULL AND NEW.new_due_at<=clock_timestamp())
 OR NEW.sequence<>COALESCE(previous.sequence,0)+1
 OR ROW(NEW.previous_action_required,NEW.previous_due_date,NEW.previous_due_timezone,NEW.previous_due_at)
 IS DISTINCT FROM ROW(COALESCE(previous.new_action_required,original.action_required),
 CASE WHEN previous.id IS NULL THEN original.action_due_date ELSE previous.new_due_date END,
 CASE WHEN previous.id IS NULL THEN original.action_due_timezone ELSE previous.new_due_timezone END,
 CASE WHEN previous.id IS NULL THEN original.action_due_at ELSE previous.new_due_at END)
 OR NOT EXISTS(SELECT 1 FROM message_envelopes WHERE action_amendment_id=NEW.id AND sender_user_id=NEW.created_by_user_id)
 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_amendment_invalid'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER message_amendment_valid AFTER INSERT ON message_action_amendments
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION messaging_validate_amendment();

CREATE FUNCTION messaging_draft_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id<>OLD.id OR NEW.owner_user_id<>OLD.owner_user_id OR NEW.date_created<>OLD.date_created
 OR NEW.version<>OLD.version+1 THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_draft_version_invalid';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_draft_update BEFORE UPDATE ON message_drafts FOR EACH ROW EXECUTE FUNCTION messaging_draft_update();
CREATE TRIGGER message_draft_resource_target BEFORE INSERT ON message_draft_resource_links FOR EACH ROW EXECUTE FUNCTION messaging_resource_link_insert();

-- Inbox ordering is the envelope send instant plus delivery UUID. Delivery's
-- created_at is the same transaction instant; the service joins the envelope.
CREATE INDEX message_delivery_sent_page_idx ON message_deliveries(recipient_user_id,created_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE INDEX message_envelope_related_delivery_idx ON message_envelopes(related_delivery_id) WHERE related_delivery_id IS NOT NULL;
CREATE INDEX message_envelope_related_envelope_idx ON message_envelopes(related_envelope_id) WHERE related_envelope_id IS NOT NULL;

CREATE FUNCTION messaging_snapshot_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM message_envelopes WHERE id=NEW.envelope_id
      AND xmin::text::bigint=(txid_current()%4294967296)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_snapshot_already_committed';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_selector_insert BEFORE INSERT ON message_recipient_selectors FOR EACH ROW EXECUTE FUNCTION messaging_snapshot_insert();
CREATE TRIGGER message_addressee_insert BEFORE INSERT ON message_addressees FOR EACH ROW EXECUTE FUNCTION messaging_snapshot_insert();
CREATE TRIGGER message_delivery_insert BEFORE INSERT ON message_deliveries FOR EACH ROW EXECUTE FUNCTION messaging_snapshot_insert();
CREATE TRIGGER message_localization_insert BEFORE INSERT ON message_envelope_localizations FOR EACH ROW EXECUTE FUNCTION messaging_snapshot_insert();
CREATE TRIGGER message_link_snapshot_insert BEFORE INSERT ON message_resource_links FOR EACH ROW EXECUTE FUNCTION messaging_snapshot_insert();

CREATE FUNCTION messaging_delivery_timestamp() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 -- Denormalize only the ordering instant, never message content; this permits
 -- the recipient/sent-time/UUID index to serve Inbox keyset pagination.
 SELECT sent_at INTO NEW.created_at FROM message_envelopes WHERE id=NEW.envelope_id;
 RETURN NEW;
END $$;
CREATE TRIGGER message_delivery_timestamp BEFORE INSERT ON message_deliveries FOR EACH ROW EXECUTE FUNCTION messaging_delivery_timestamp();
CREATE FUNCTION messaging_default_level() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.security_level_id IS NULL THEN
  SELECT id INTO NEW.security_level_id FROM security_levels ORDER BY level_number LIMIT 1;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_envelope_default_level BEFORE INSERT ON message_envelopes FOR EACH ROW EXECUTE FUNCTION messaging_default_level();
CREATE TRIGGER message_draft_default_level BEFORE INSERT ON message_drafts FOR EACH ROW EXECUTE FUNCTION messaging_default_level();

-- Immutable capture provenance survives nulling of live resource references.
CREATE FUNCTION messaging_capture_update() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE keys text[];
BEGIN
 keys:=CASE TG_TABLE_NAME WHEN 'message_record_captures' THEN ARRAY['selected_envelope_id','record_id']
 ELSE ARRAY['envelope_id','digital_component_id'] END;
 IF (to_jsonb(NEW)-keys) IS DISTINCT FROM (to_jsonb(OLD)-keys) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_immutable';
 END IF;
 IF EXISTS(SELECT 1 FROM unnest(keys) k WHERE to_jsonb(NEW)->k IS DISTINCT FROM to_jsonb(OLD)->k
    AND to_jsonb(NEW)->k<>'null'::jsonb) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_reference_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_capture_update BEFORE UPDATE ON message_record_captures FOR EACH ROW EXECUTE FUNCTION messaging_capture_update();
CREATE TRIGGER message_capture_component_update BEFORE UPDATE ON message_record_capture_components FOR EACH ROW EXECUTE FUNCTION messaging_capture_update();
CREATE TRIGGER message_capture_no_delete BEFORE DELETE ON message_record_captures FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE TRIGGER message_capture_component_no_delete BEFORE DELETE ON message_record_capture_components FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE FUNCTION messaging_validate_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE total integer; provenance integer; selected integer;
BEGIN
 SELECT count(*),count(*) FILTER(WHERE component_kind='provenance'),count(*) FILTER(WHERE is_selected_message)
 INTO total,provenance,selected FROM message_record_capture_components WHERE capture_id=NEW.id;
 IF total<2 OR provenance<>1 OR selected<>1 OR NEW.selected_envelope_id IS DISTINCT FROM NEW.selected_envelope_id_at_capture
 OR NEW.record_id IS DISTINCT FROM NEW.record_id_at_capture
 OR EXISTS(SELECT 1 FROM message_record_capture_components x LEFT JOIN digital_components d ON d.id=x.digital_component_id
    WHERE x.capture_id=NEW.id AND (x.component_order>total
    OR (x.component_kind='provenance' AND x.component_order<>total)
    OR (x.component_kind='message' AND x.envelope_id IS DISTINCT FROM x.envelope_id_at_capture)
    OR (x.is_selected_message AND x.envelope_id IS DISTINCT FROM NEW.selected_envelope_id)
    OR x.digital_component_id IS DISTINCT FROM x.digital_component_id_at_capture OR d.record_id IS DISTINCT FROM NEW.record_id OR d.component_order IS DISTINCT FROM x.component_order)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_incomplete';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER message_capture_valid AFTER INSERT ON message_record_captures
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION messaging_validate_capture();

CREATE FUNCTION messaging_validate_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.result_purged_at IS NULL AND NOT EXISTS(SELECT 1 FROM message_envelopes e WHERE e.id=NEW.result_envelope_id
 AND e.sender_user_id IS NOT DISTINCT FROM NEW.principal_user_id
 AND e.system_producer_code IS NOT DISTINCT FROM NEW.producer_code
 AND e.request_id=NEW.request_id
 AND ((NEW.operation_kind='send' AND e.message_kind<>'action_amendment_notice')
 OR (NEW.operation_kind='amendment' AND e.action_amendment_id=NEW.result_amendment_id))) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_receipt_result_mismatch';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER message_receipt_valid AFTER INSERT ON message_request_receipts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION messaging_validate_receipt();

CREATE FUNCTION messaging_capture_component_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM message_record_captures WHERE id=NEW.capture_id
      AND xmin::text::bigint=(txid_current()%4294967296)) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_capture_already_committed';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_capture_component_insert BEFORE INSERT ON message_record_capture_components FOR EACH ROW EXECUTE FUNCTION messaging_capture_component_insert();

CREATE TRIGGER message_mailbox_no_delete BEFORE DELETE ON message_mailboxes FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();

-- Transactional wake-up hints; PostgreSQL releases NOTIFY only after commit.
CREATE OR REPLACE FUNCTION messaging_notify_delivery() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('wathiq_messages', json_build_object(
        'delivery_id', NEW.id,
        'recipient_user_id', NEW.recipient_user_id,
        'mailbox_sequence', NEW.mailbox_sequence
    )::text);
    RETURN NEW;
END;
$$;
CREATE TRIGGER message_delivery_notify AFTER INSERT ON message_deliveries
FOR EACH ROW EXECUTE FUNCTION messaging_notify_delivery();

BEGIN;

-- A technical serialization row makes concurrent language/configuration writes
-- visible to repeatable-read/serializable snapshots as well as read committed.
CREATE TABLE messaging_notification_configuration_guard (
 singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
 revision bigint NOT NULL
);

-- Coordinate language enablement and activation, preserving complete coverage.
CREATE FUNCTION messaging_guard_notification_coverage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE active_id uuid;
BEGIN
 INSERT INTO messaging_notification_configuration_guard(singleton,revision) VALUES (true,1)
 ON CONFLICT(singleton) DO UPDATE SET revision=messaging_notification_configuration_guard.revision+1;
 IF TG_TABLE_NAME='system_notification_producers' THEN
  active_id := NEW.active_configuration_version_id;
  IF active_id IS NULL THEN
   RETURN NEW;
  END IF;
  IF NEW.required_for_business_commit AND NOT EXISTS (
   SELECT 1 FROM system_notification_configuration_versions WHERE id=active_id AND enabled
  ) THEN
   RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='notification_required_cannot_disable';
  END IF;
  IF EXISTS (
   SELECT 1 FROM supported_languages l WHERE (l.is_enabled OR l.language_tag='en')
   AND NOT EXISTS (SELECT 1 FROM system_notification_configuration_translations t
    WHERE t.configuration_version_id=active_id AND t.language_tag=l.language_tag
    AND t.review_status='published' AND t.reviewed_by_user_id IS NOT NULL AND t.reviewed_at IS NOT NULL
    AND btrim(t.subject_template)<>'' AND btrim(t.body_template_rich_text)<>'')
  ) THEN
   RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='notification_language_coverage_required';
  END IF;
 ELSIF NEW.is_enabled AND EXISTS (
  SELECT 1 FROM system_notification_producers p WHERE p.active_configuration_version_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM system_notification_configuration_translations t
   WHERE t.configuration_version_id=p.active_configuration_version_id AND t.language_tag=NEW.language_tag
   AND t.review_status='published' AND t.reviewed_by_user_id IS NOT NULL AND t.reviewed_at IS NOT NULL)
 ) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='notification_language_coverage_required';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER notification_active_coverage BEFORE INSERT OR UPDATE ON system_notification_producers
 FOR EACH ROW EXECUTE FUNCTION messaging_guard_notification_coverage();
CREATE TRIGGER notification_language_coverage BEFORE INSERT OR UPDATE OF is_enabled ON supported_languages
 FOR EACH ROW EXECUTE FUNCTION messaging_guard_notification_coverage();
CREATE INDEX notification_test_history_idx ON event_history ((metadata->>'producer_code'),id DESC)
 WHERE entity_type='system_notification' AND operation IN ('NOTIFICATION_TEST_SENT','NOTIFICATION_TEST_FAILED');
CREATE INDEX notification_test_rate_idx ON event_history (actor_user_id,occurred_at)
 WHERE operation='NOTIFICATION_TEST_SENT';

COMMIT;

-- Sent-message lifecycle and atomic connected-group cleanup.
CREATE FUNCTION messaging_mailbox_envelope_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['sender_deleted_at','sender_purge_after']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['sender_deleted_at','sender_purge_after'])
 OR (OLD.sender_purge_after IS NOT NULL AND NEW.sender_purge_after IS DISTINCT FROM OLD.sender_purge_after AND NOT (NEW.sender_purge_after IS NULL AND NEW.sender_deleted_at IS NULL AND OLD.expires_at>CURRENT_TIMESTAMP))
 OR (NEW.sender_deleted_at IS NOT NULL AND NEW.sender_purge_after IS NULL) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_immutable';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER message_envelopes_immutable ON message_envelopes;
CREATE TRIGGER message_envelopes_immutable BEFORE UPDATE ON message_envelopes FOR EACH ROW EXECUTE FUNCTION messaging_mailbox_envelope_update();
CREATE TRIGGER message_envelopes_no_delete BEFORE DELETE ON message_envelopes FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE OR REPLACE FUNCTION messaging_delivery_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['read_at','deleted_at','purge_after','deletion_reason']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['read_at','deleted_at','purge_after','deletion_reason'])
 OR (OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at)
 OR (OLD.purge_after IS NOT NULL AND NEW.purge_after IS DISTINCT FROM OLD.purge_after AND NOT (NEW.purge_after IS NULL AND NEW.deleted_at IS NULL AND EXISTS(SELECT 1 FROM message_envelopes WHERE id=OLD.envelope_id AND expires_at>CURRENT_TIMESTAMP)))
 OR (NEW.deleted_at IS NOT NULL AND NEW.purge_after IS NULL) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_delivery_immutable';
 END IF;
 RETURN NEW;
END $$;
-- Only members of the transaction-local, fully rechecked purge set may be deleted.
CREATE OR REPLACE FUNCTION messaging_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE envelope uuid; allowed boolean;
BEGIN
 IF TG_OP='DELETE' AND TG_TABLE_NAME=ANY(ARRAY['message_envelopes','message_envelope_localizations',
 'message_recipient_selectors','message_addressees','message_deliveries','message_resource_links',
 'message_action_completions','message_action_amendments']) AND to_regclass('pg_temp.messaging_purge_members') IS NOT NULL THEN
  envelope:=CASE TG_TABLE_NAME WHEN 'message_envelopes' THEN (to_jsonb(OLD)->>'id')::uuid
   WHEN 'message_action_amendments' THEN (to_jsonb(OLD)->>'original_envelope_id')::uuid
   WHEN 'message_action_completions' THEN (to_jsonb(OLD)->>'reply_envelope_id')::uuid
   ELSE (to_jsonb(OLD)->>'envelope_id')::uuid END;
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM pg_temp.messaging_purge_members WHERE id=$1)' INTO allowed USING envelope;
  IF allowed THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_immutable';
END $$;
CREATE FUNCTION messaging_receipt_purge_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF to_regclass('pg_temp.messaging_purge_members') IS NULL
 OR (to_jsonb(NEW)-'result_purged_at') IS DISTINCT FROM (to_jsonb(OLD)-'result_purged_at')
 OR OLD.result_purged_at IS NOT NULL OR NEW.result_purged_at IS NULL THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_receipt_immutable';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_temp.messaging_purge_members WHERE id=OLD.result_envelope_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='message_receipt_immutable';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER message_request_receipts_immutable ON message_request_receipts;
CREATE TRIGGER message_request_receipts_immutable BEFORE UPDATE ON message_request_receipts FOR EACH ROW EXECUTE FUNCTION messaging_receipt_purge_update();
CREATE TRIGGER message_request_receipts_no_delete BEFORE DELETE ON message_request_receipts FOR EACH ROW EXECUTE FUNCTION messaging_reject_mutation();
CREATE INDEX message_delivery_cleanup_idx ON message_deliveries(purge_after,envelope_id);
CREATE INDEX message_draft_cleanup_idx ON message_drafts(expires_at,purge_after,id);

-- Store the expiry restoration policy with each message; restart settings only
-- affect new messages, never an existing message's restoration deadline.
ALTER TABLE message_envelopes ADD COLUMN expiry_restoration_days integer NOT NULL DEFAULT 30 CHECK(expiry_restoration_days BETWEEN 1 AND 36500);
CREATE TABLE message_capture_drafts (
 draft_id bigint PRIMARY KEY REFERENCES record_drafts(id) ON DELETE CASCADE,
 capture_id uuid NOT NULL UNIQUE,
 selected_envelope_id uuid NOT NULL,
 root_envelope_id uuid NOT NULL,
 language_tag text NOT NULL,
 direction text NOT NULL CHECK(direction IN('ltr','rtl'))
);
-- Draft source identifiers are historical references, not retention edges.

CREATE TABLE messaging_operational_metrics (
 metric text NOT NULL, instance_id text NOT NULL DEFAULT '', producer_code text NOT NULL DEFAULT '',
 value double precision NOT NULL DEFAULT 0, observations bigint NOT NULL DEFAULT 0,
 last_observed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 unresolved_since timestamptz,
 PRIMARY KEY(metric,instance_id,producer_code)
);
CREATE TABLE messaging_gateway_health (
 instance_id uuid PRIMARY KEY, observed_at timestamptz NOT NULL,
 listener_connected boolean NOT NULL, listener_generation bigint NOT NULL,
 notifications_received bigint NOT NULL, last_notification_at timestamptz,
 active_connections integer NOT NULL, slow_disconnects bigint NOT NULL,
 host_addresses inet[], api_port integer CHECK (api_port BETWEEN 1 AND 65535)
);
CREATE FUNCTION messaging_count_delivery() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO messaging_operational_metrics(metric,value,observations)
 VALUES('notifications_emitted',1,1) ON CONFLICT(metric,instance_id,producer_code)
 DO UPDATE SET value=messaging_operational_metrics.value+1,observations=messaging_operational_metrics.observations+1,last_observed_at=CURRENT_TIMESTAMP;
 IF NOT (SELECT is_test FROM message_envelopes WHERE id=NEW.envelope_id) THEN
  INSERT INTO messaging_operational_metrics(metric,value,observations) VALUES('fanout_count',1,1)
  ON CONFLICT(metric,instance_id,producer_code) DO UPDATE SET value=messaging_operational_metrics.value+1,observations=messaging_operational_metrics.observations+1,last_observed_at=CURRENT_TIMESTAMP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_delivery_metric AFTER INSERT ON message_deliveries FOR EACH ROW EXECUTE FUNCTION messaging_count_delivery();

CREATE TABLE messaging_cleanup_groups (
 group_key uuid PRIMARY KEY,
 member_count bigint NOT NULL,
 expired_count bigint NOT NULL,
 eligible_at timestamptz NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 failure_count bigint NOT NULL DEFAULT 0,
 oldest_failure_at timestamptz
);

ALTER TABLE message_drafts ADD COLUMN expiry_restoration_days integer NOT NULL DEFAULT 30 CHECK(expiry_restoration_days BETWEEN 1 AND 36500);

-- Approved legal-hold expiry reminder checkpoints. No message content is retained here.
CREATE TABLE hold_notification_reminders (
    hold_id bigint NOT NULL REFERENCES holds(id) ON DELETE CASCADE,
    end_at timestamptz NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (hold_id, end_at)
);
CREATE INDEX holds_notification_due_idx ON holds(valid_to,id) WHERE valid_to IS NOT NULL;

-- Localized producer display metadata, separate from stable event contracts.
ALTER TABLE system_notification_producers ADD COLUMN name text CHECK(name IS NULL OR btrim(name)<>'');
ALTER TABLE system_notification_producers ADD COLUMN translations jsonb CHECK(translations IS NULL OR jsonb_typeof(translations)='object');
CREATE TRIGGER system_notification_producers_validate_translations BEFORE INSERT OR UPDATE OF translations ON system_notification_producers FOR EACH ROW EXECUTE FUNCTION validate_multilingual_entity_translations();

-- Hierarchical oversight authorization
CREATE OR REPLACE FUNCTION event_reference_identity(reference_field text, reference_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE snapshot jsonb;
DECLARE existing_snapshots jsonb;
BEGIN
    CASE reference_field
        WHEN 'profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'old_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'new_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'security_level_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name,'level_number',level_number) INTO snapshot FROM security_levels WHERE id=reference_id;
        WHEN 'classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'parent_classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'classification_scheme_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classification_schemes WHERE id=reference_id;
        WHEN 'aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'parent_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'destination_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'record_id' THEN SELECT jsonb_build_object('id',id,'code',record_number,'title',title) INTO snapshot FROM records WHERE id=reference_id;
        WHEN 'role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'managing_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'file_administrator_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'supervisor_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'owner_user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'parent_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'owning_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        ELSE snapshot := NULL;
    END CASE;
    RETURN snapshot;
END;
$$;

-- Prospective defaults only: this upgrade never changes existing ACL grants.
ALTER TABLE org_units
 ADD COLUMN managing_role_id bigint REFERENCES roles(id) ON DELETE RESTRICT,
 ADD COLUMN file_administrator_role_id bigint REFERENCES roles(id) ON DELETE RESTRICT;
CREATE INDEX org_units_managing_role_idx ON org_units(managing_role_id);
CREATE INDEX org_units_file_administrator_role_idx ON org_units(file_administrator_role_id);

CREATE FUNCTION validate_org_unit_designated_roles() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE designated bigint;
BEGIN
 FOREACH designated IN ARRAY ARRAY[NEW.managing_role_id,NEW.file_administrator_role_id] LOOP
  IF designated IS NOT NULL AND NOT EXISTS (
   SELECT 1 FROM roles WHERE id=designated AND org_unit_id=NEW.id AND NOT is_system
    AND account_type_restriction IS DISTINCT FROM 'service'
  ) THEN RAISE EXCEPTION 'designated role must belong to the same unit and be a non-system person role' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NEW.file_administrator_role_id IS DISTINCT FROM OLD.file_administrator_role_id
   AND NEW.file_administrator_role_id IS NOT NULL
   AND NOT role_effectively_active(NEW.file_administrator_role_id) THEN
  RAISE EXCEPTION 'File Administrator role must be active' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER org_units_validate_designated_roles BEFORE INSERT OR UPDATE ON org_units
 FOR EACH ROW EXECUTE FUNCTION validate_org_unit_designated_roles();

CREATE FUNCTION protect_designated_role_unit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM org_units WHERE
  (managing_role_id=NEW.id OR file_administrator_role_id=NEW.id)
  AND (id IS DISTINCT FROM NEW.org_unit_id OR NEW.is_system
    OR NEW.account_type_restriction='service')) THEN
  RAISE EXCEPTION 'role is designated by an organizational unit; clear or replace its designation first' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER roles_protect_designation BEFORE UPDATE ON roles
 FOR EACH ROW EXECUTE FUNCTION protect_designated_role_unit();

DO $$
DECLARE acl_table text; constraint_row record;
BEGIN
 FOREACH acl_table IN ARRAY ARRAY['aggregation_acl_grants','aggregation_child_aggregation_acl_defaults','aggregation_child_record_acl_defaults','record_acl_grants'] LOOP
  FOR constraint_row IN SELECT conname FROM pg_constraint WHERE conrelid=acl_table::regclass
    AND contype='c' AND pg_get_constraintdef(oid) LIKE '%principal_type%' LOOP
   EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',acl_table,constraint_row.conname);
  END LOOP;
  EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (
    (principal_type=''role'' AND role_id IS NOT NULL) OR
    (principal_type IN (''everyone'',''org_unit_members'',''owning_and_higher_level_unit_managers'',''effective_file_administrator'') AND role_id IS NULL))',acl_table,acl_table||'_principal_valid');
  EXECUTE format('CREATE UNIQUE INDEX %I ON %I(%I,principal_type,permission_id)
   WHERE principal_type IN (''owning_and_higher_level_unit_managers'',''effective_file_administrator'')',
   acl_table||'_oversight_unique',acl_table,CASE WHEN acl_table='record_acl_grants' THEN 'record_id' ELSE 'aggregation_id' END);
 END LOOP;
END $$;

-- Resolves roles from current data, with no authorization cache.
CREATE FUNCTION contextual_acl_roles(p_owner bigint,p_principal text)
 RETURNS TABLE(role_id bigint,org_unit_id bigint) LANGUAGE sql STABLE AS $$
 WITH RECURSIVE chain AS (
  SELECT id,parent_org_unit_id,managing_role_id,file_administrator_role_id,0 AS depth
   FROM org_units WHERE id=p_owner
  UNION ALL
  SELECT parent.id,parent.parent_org_unit_id,parent.managing_role_id,parent.file_administrator_role_id,child.depth+1
   FROM org_units parent JOIN chain child ON parent.id=child.parent_org_unit_id
 ), selected AS (
  SELECT managing_role_id AS role_id,id AS org_unit_id FROM chain
   WHERE p_principal='owning_and_higher_level_unit_managers'
  UNION ALL
  SELECT file_administrator_role_id,id FROM
   (SELECT * FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1) nearest
   WHERE p_principal='effective_file_administrator'
 )
 SELECT selected.role_id,selected.org_unit_id FROM selected JOIN roles role ON role.id=selected.role_id
 WHERE role.org_unit_id=selected.org_unit_id AND NOT role.is_system
   AND role.account_type_restriction IS DISTINCT FROM 'service' AND role_effectively_active(role.id)
$$;
CREATE FUNCTION user_matches_contextual_acl(p_user bigint,p_owner bigint,p_principal text)
 RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM contextual_acl_roles(p_owner,p_principal) match
  JOIN user_role_assignments assignment ON assignment.role_id=match.role_id
  WHERE assignment.user_id=p_user AND assignment.valid_from<=CURRENT_TIMESTAMP
   AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP))
$$;

CREATE OR REPLACE FUNCTION user_has_aggregation_permission(
  p_user_id bigint, p_aggregation_id bigint, p_permission text
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE
  cursor_row aggregations%ROWTYPE;
  parent_row aggregations%ROWTYPE;
  source_id bigint;
  source_kind text;
  target_owner_id bigint;
BEGIN
  SELECT * INTO cursor_row FROM aggregations WHERE id=p_aggregation_id;
  IF NOT FOUND THEN RETURN false; END IF;
  target_owner_id := cursor_row.owning_org_unit_id;
  IF NOT cursor_row.inherit_acl_from_parent OR cursor_row.parent_aggregation_id IS NULL THEN
    source_id := cursor_row.id; source_kind := 'resource';
  ELSE
    LOOP
      SELECT * INTO parent_row FROM aggregations WHERE id=cursor_row.parent_aggregation_id;
      IF NOT FOUND THEN RETURN false; END IF;
      IF parent_row.default_child_aggregation_acl_mode='custom' THEN
        source_id := parent_row.id; source_kind := 'child_default'; EXIT;
      ELSIF NOT parent_row.inherit_acl_from_parent OR parent_row.parent_aggregation_id IS NULL THEN
        source_id := parent_row.id; source_kind := 'resource'; EXIT;
      END IF;
      cursor_row := parent_row;
    END LOOP;
  END IF;

  IF source_kind='resource' THEN
    RETURN EXISTS (
      SELECT 1 FROM aggregation_acl_grants grant_row
      JOIN permissions permission ON permission.id=grant_row.permission_id
      WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
        AND (grant_row.principal_type='everyone'
          OR (grant_row.principal_type='role' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(assignment.role_id)))
          OR user_matches_contextual_acl(p_user_id,target_owner_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            JOIN roles role ON role.id=assignment.role_id
            WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(role.id))))
    );
  END IF;
  RETURN EXISTS (
    SELECT 1 FROM aggregation_child_aggregation_acl_defaults grant_row
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
        OR (grant_row.principal_type='role' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(assignment.role_id)))
        OR user_matches_contextual_acl(p_user_id,target_owner_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          JOIN roles role ON role.id=assignment.role_id
          WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(role.id))))
  );
END $$;

CREATE OR REPLACE FUNCTION user_has_record_permission(
  p_user_id bigint, p_record_id bigint, p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN record_acl_grants grant_row ON NOT resource.inherit_acl_from_parent
      AND grant_row.record_id=resource.id AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  ) OR EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN aggregation_child_record_acl_defaults grant_row
      ON resource.inherit_acl_from_parent AND grant_row.aggregation_id=resource.aggregation_id
      AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;

CREATE OR REPLACE FUNCTION user_has_destination_record_permission(
  p_user_id bigint,p_aggregation_id bigint,p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS(
    SELECT 1 FROM aggregations resource
    JOIN aggregation_child_record_acl_defaults grant_row
      ON grant_row.aggregation_id=resource.id
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE resource.id=p_aggregation_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;




CREATE OR REPLACE FUNCTION initialize_resource_acls() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE creator_role_id bigint := NULLIF(current_setting('app.creator_acl_role_id',true),'')::bigint;
  acl_scope record;
BEGIN
  IF creator_role_id IS NULL THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='aggregations' THEN
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.history.view']);
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  ELSE
    INSERT INTO record_acl_grants(record_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  END IF;
  FOR acl_scope IN SELECT * FROM (VALUES
    ('aggregation_acl_grants','aggregation_id','aggregation'),
    ('aggregation_child_aggregation_acl_defaults','aggregation_id','aggregation'),
    ('aggregation_child_record_acl_defaults','aggregation_id','record'),
    ('record_acl_grants','record_id','record')) AS scopes(table_name,owner_column,resource_type)
  LOOP
    IF (TG_TABLE_NAME='aggregations' AND acl_scope.table_name<>'record_acl_grants')
      OR (TG_TABLE_NAME='records' AND acl_scope.table_name='record_acl_grants') THEN
      EXECUTE format('INSERT INTO %I(%I,principal_type,permission_id)
        SELECT $1,principal,id FROM permissions CROSS JOIN
        (VALUES (''owning_and_higher_level_unit_managers''),(''effective_file_administrator'')) AS principals(principal)
        WHERE code=ANY(CASE WHEN principal=''owning_and_higher_level_unit_managers'' THEN $2 ELSE $3 END)',acl_scope.table_name,acl_scope.owner_column)
      USING NEW.id,
        CASE WHEN acl_scope.resource_type='aggregation' THEN ARRAY['aggregation.view','aggregation.history.view']
          ELSE ARRAY['record.view','record.component.list','record.component.view','record.component.download'] END,
        CASE WHEN acl_scope.resource_type='aggregation' THEN ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.acl.manage','aggregation.history.view']
          ELSE ARRAY['record.view','record.acl.manage','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print'] END;
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
