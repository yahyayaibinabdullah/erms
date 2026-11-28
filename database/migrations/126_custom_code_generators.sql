BEGIN;

-- Shared definition/counter/request storage; no generator is enabled by an upgrade.
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;

CREATE FUNCTION public.code_generator_parts(pattern text)
RETURNS TABLE(literal text, placeholder text)
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE pos integer := 1; ending integer; pair text; buffer text := ''; token text; serials integer := 0;
BEGIN
    WHILE pos <= char_length(pattern) LOOP
        pair := substr(pattern,pos,2);
        IF pair IN ('{{','}}') THEN
            buffer := buffer || substr(pair,1,1); pos := pos+2;
        ELSIF substr(pattern,pos,1)='{' THEN
            IF buffer<>'' THEN literal:=buffer; placeholder:=NULL; RETURN NEXT; buffer:=''; END IF;
            ending:=strpos(substr(pattern,pos+1),'}');
            IF ending=0 THEN RAISE EXCEPTION 'code_generator_invalid_pattern' USING ERRCODE='23514'; END IF;
            token:=substr(pattern,pos+1,ending-1);
            IF token NOT IN ('YYYY','YY','MM','DD','DATE','PARENT_AGGREGATION_NUMBER',
                             'CLASSIFICATION_CODE','CLASSIFICATION_SCHEME_CODE','ORG_UNIT_CODE','ROLE_CODE','SERIAL') THEN
                RAISE EXCEPTION 'code_generator_invalid_pattern' USING ERRCODE='23514';
            END IF;
            IF token='SERIAL' THEN serials:=serials+1; END IF;
            literal:=''; placeholder:=token; RETURN NEXT; pos:=pos+ending+1;
        ELSIF substr(pattern,pos,1)='}' THEN
            RAISE EXCEPTION 'code_generator_invalid_pattern' USING ERRCODE='23514';
        ELSE buffer:=buffer || substr(pattern,pos,1); pos:=pos+1;
        END IF;
    END LOOP;
    IF buffer<>'' THEN literal:=buffer; placeholder:=NULL; RETURN NEXT; END IF;
    IF serials<>1 THEN RAISE EXCEPTION 'code_generator_invalid_pattern' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION public.code_generator_whole(value numeric, minimum numeric DEFAULT 0)
RETURNS boolean LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
RETURN value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)
       AND value>=minimum AND value=trunc(value);

CREATE TABLE public.code_generators (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL CHECK (public.resource_type_has_text(name)),
    kind text NOT NULL CHECK (kind IN ('record','aggregation')),
    primary_field text,
    type_id bigint CHECK (type_id>0),
    field_id bigint,
    field_data_type text GENERATED ALWAYS AS (CASE WHEN field_id IS NOT NULL THEN 'text' END) STORED,
    type_population int8range GENERATED ALWAYS AS (
        CASE WHEN type_id IS NULL THEN int8range(NULL,NULL)
             WHEN type_id=9223372036854775807 THEN int8range(type_id,NULL,'[)')
             ELSE int8range(type_id,type_id+1,'[)') END) STORED,
    pattern text NOT NULL,
    start numeric NOT NULL DEFAULT 1 CHECK (public.code_generator_whole(start)),
    increment numeric NOT NULL DEFAULT 1 CHECK (public.code_generator_whole(increment,1)),
    scope text NOT NULL DEFAULT 'generator' CHECK (scope IN ('generator','parent_aggregation','classification','org_unit')),
    reset_frequency text NOT NULL DEFAULT 'never' CHECK (reset_frequency IN ('never','yearly','monthly')),
    padding_width integer NOT NULL DEFAULT 0 CHECK (padding_width>=0),
    max_code_length integer NOT NULL CHECK (max_code_length>0),
    enabled boolean NOT NULL DEFAULT true,
    version bigint NOT NULL DEFAULT 1 CHECK (version>0),
    date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_user_id bigint,
    CONSTRAINT code_generators_target_shape CHECK (
        (primary_field IS NOT NULL AND field_id IS NULL) OR
        (primary_field IS NULL AND field_id IS NOT NULL AND type_id IS NOT NULL) OR
        (NOT enabled AND primary_field IS NULL AND field_id IS NULL AND type_id IS NULL)),
    CONSTRAINT code_generators_primary_text CHECK (primary_field IS NULL OR
        (kind='record' AND primary_field IN ('record_number','title','description')) OR
        (kind='aggregation' AND primary_field IN ('aggregation_number','title','description','assigned_location','current_location'))),
    FOREIGN KEY (kind,type_id) REFERENCES public.resource_types(kind,id),
    FOREIGN KEY (kind,type_id,field_id,field_data_type)
        REFERENCES public.resource_type_fields(kind,type_id,id,data_type),
    CONSTRAINT code_generators_primary_overlap EXCLUDE USING gist
        (kind WITH =, primary_field WITH =, type_population WITH &&)
        WHERE (enabled AND primary_field IS NOT NULL)
);
CREATE UNIQUE INDEX code_generators_enabled_primary ON public.code_generators(kind,primary_field,coalesce(type_id,0))
    WHERE enabled AND primary_field IS NOT NULL;
CREATE UNIQUE INDEX code_generators_enabled_field ON public.code_generators(field_id)
    WHERE enabled AND field_id IS NOT NULL;
CREATE INDEX code_generators_target_lookup ON public.code_generators(kind,type_id,primary_field,field_id) WHERE enabled;
CREATE INDEX code_generators_field_reference ON public.code_generators(field_id) WHERE field_id IS NOT NULL;

CREATE TABLE public.code_generator_counters (
    generator_id bigint NOT NULL REFERENCES public.code_generators(id),
    scope_kind text NOT NULL CHECK (scope_kind IN ('generator','parent_aggregation','classification','org_unit')),
    scope_id bigint NOT NULL,
    reset_frequency text NOT NULL CHECK (reset_frequency IN ('never','yearly','monthly')),
    period_bucket date NOT NULL,
    last_serial numeric CHECK (public.code_generator_whole(last_serial)),
    forward_next numeric CHECK (public.code_generator_whole(forward_next)),
    version bigint NOT NULL DEFAULT 1 CHECK (version>0),
    PRIMARY KEY (generator_id,scope_kind,scope_id,reset_frequency,period_bucket),
    CHECK ((scope_kind='generator' AND scope_id=0) OR (scope_kind<>'generator' AND scope_id>0)),
    CHECK (isfinite(period_bucket) AND extract(year FROM period_bucket) BETWEEN 1 AND 9999 AND
        ((reset_frequency='never' AND period_bucket=DATE '0001-01-01') OR
         (reset_frequency='yearly' AND extract(month FROM period_bucket)=1 AND extract(day FROM period_bucket)=1) OR
         (reset_frequency='monthly' AND extract(day FROM period_bucket)=1))),
    CHECK (forward_next IS NULL OR last_serial IS NULL OR forward_next>last_serial)
);

CREATE TABLE public.resource_creation_requests (
    caller_user_id bigint NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    operation text NOT NULL CHECK (btrim(operation)<>''),
    submission_key uuid NOT NULL,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    result jsonb NOT NULL CHECK (jsonb_typeof(result)='object'),
    completed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (caller_user_id,operation,submission_key)
);

CREATE FUNCTION public.creation_response_resource_id(completion jsonb) RETURNS bigint
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
DECLARE value jsonb; identity_number numeric;
BEGIN
    value:=completion#>'{response,id}';
    IF jsonb_typeof(value) IS DISTINCT FROM 'number' THEN RETURN NULL; END IF;
    identity_number:=(value::text)::numeric;
    IF identity_number<1 OR identity_number>9223372036854775807 OR identity_number<>trunc(identity_number) THEN RETURN NULL; END IF;
    RETURN identity_number::bigint;
END $$;
-- Only the resource identity is indexed; long response Text values remain
-- valid. Count-only batch responses contain no descriptive metadata to erase.
CREATE INDEX resource_creation_requests_response_resource ON public.resource_creation_requests
    ((result->>'kind'),public.creation_response_resource_id(result))
    WHERE public.creation_response_resource_id(result) IS NOT NULL;

CREATE FUNCTION public.creation_response_is_retiring(completion jsonb) RETURNS boolean
LANGUAGE sql STABLE STRICT AS $$
    WITH governing AS (
        SELECT CASE completion->>'kind'
            WHEN 'record' THEN disposition_private.root_id((SELECT aggregation_id FROM records
                WHERE id=public.creation_response_resource_id(completion)))
            WHEN 'aggregation' THEN disposition_private.root_id(public.creation_response_resource_id(completion))
        END AS root_id)
    SELECT root_id IS NOT NULL AND disposition_private.destruction_active('finalize',root_id) FROM governing
$$;

CREATE FUNCTION public.code_generator_binding_key(resource_kind text, primary_key text, typed_field bigint)
RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN CASE WHEN primary_key IS NULL AND typed_field IS NULL THEN NULL ELSE
    hashtextextended(resource_kind || '/' || coalesce('primary/' || primary_key,'field/' || typed_field::text),1260001) END;

CREATE FUNCTION public.guard_code_generator() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_field bigint; old_kind text; old_primary text; guard_key bigint; tokens text[]; minimum_length integer;
        field public.resource_type_fields%ROWTYPE; installer boolean;
BEGIN
    installer:=current_user_id() IS NULL AND coalesce(current_setting('app.event_source',true),'') IN ('seeding','migration');
    IF NOT installer AND (NOT coalesce(user_has_global_privilege(current_user_id(),'app.settings.manage'),false) OR
        NOT EXISTS(SELECT FROM users WHERE id=current_user_id() AND account_type='person' AND status='active')) THEN
        RAISE EXCEPTION 'code_generator_access_denied' USING ERRCODE='42501';
    END IF;
    IF TG_OP<>'INSERT' AND NOT installer AND NOT resource_type_has_text(coalesce(current_setting('app.change_reason',true),'')) THEN
        RAISE EXCEPTION 'code_generator_reason_required' USING ERRCODE='23514';
    END IF;
    IF TG_OP<>'INSERT' THEN old_field:=OLD.field_id; old_kind:=OLD.kind; old_primary:=OLD.primary_field; END IF;
    -- Lock fields before target guards, matching direct field-edit protection.
    PERFORM id FROM resource_type_fields WHERE id=ANY(array_remove(ARRAY[old_field,
        CASE WHEN TG_OP<>'DELETE' THEN NEW.field_id END],NULL)) ORDER BY id FOR SHARE;
    FOR guard_key IN SELECT DISTINCT key FROM unnest(ARRAY[
        code_generator_binding_key(old_kind,old_primary,old_field),
        CASE WHEN TG_OP<>'DELETE' THEN code_generator_binding_key(NEW.kind,NEW.primary_field,NEW.field_id) END
    ]) key WHERE key IS NOT NULL ORDER BY key LOOP
        PERFORM pg_advisory_xact_lock(guard_key);
    END LOOP;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    IF TG_OP='UPDATE' AND NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'code_generator_identity_immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.field_id IS NOT NULL THEN
        SELECT * INTO field FROM resource_type_fields WHERE id=NEW.field_id;
        IF NOT FOUND OR (field.kind,field.type_id,field.data_type) IS DISTINCT FROM (NEW.kind,NEW.type_id,'text'::text) THEN
            RAISE EXCEPTION 'code_generator_invalid_target' USING ERRCODE='23514';
        END IF;
        IF NEW.max_code_length>field.max_length THEN
            RAISE EXCEPTION 'code_generator_length_exceeded' USING ERRCODE='23514';
        END IF;
    ELSIF NEW.primary_field IN ('assigned_location','current_location') AND NEW.max_code_length>200 THEN
        RAISE EXCEPTION 'code_generator_length_exceeded' USING ERRCODE='23514';
    END IF;
    SELECT array_agg(placeholder) FILTER(WHERE placeholder IS NOT NULL),
           sum(CASE WHEN placeholder IS NULL THEN char_length(literal)
                    WHEN placeholder='SERIAL' THEN greatest(NEW.padding_width,char_length(trunc(NEW.start)::text))
                    WHEN placeholder='YYYY' THEN 4 WHEN placeholder IN ('YY','MM','DD') THEN 2
                    WHEN placeholder='DATE' THEN 8 ELSE 1 END)
      INTO tokens,minimum_length FROM code_generator_parts(NEW.pattern);
    IF minimum_length>NEW.max_code_length THEN RAISE EXCEPTION 'code_generator_length_exceeded' USING ERRCODE='23514'; END IF;
    IF NEW.reset_frequency IN ('yearly','monthly') AND NOT tokens && ARRAY['YYYY','YY','DATE'] THEN
        RAISE EXCEPTION 'code_generator_invalid_reset' USING ERRCODE='23514';
    END IF;
    IF NEW.reset_frequency='monthly' AND NOT tokens && ARRAY['MM','DATE'] THEN
        RAISE EXCEPTION 'code_generator_invalid_reset' USING ERRCODE='23514';
    END IF;
    IF NEW.scope='org_unit' AND NOT 'ORG_UNIT_CODE'=ANY(tokens) THEN
        RAISE EXCEPTION 'code_generator_invalid_scope' USING ERRCODE='23514';
    END IF;
    IF NEW.primary_field IN ('record_number','aggregation_number') AND
       ((NEW.scope='parent_aggregation' AND NOT 'PARENT_AGGREGATION_NUMBER'=ANY(tokens)) OR
        (NEW.scope='classification' AND NOT tokens @> ARRAY['CLASSIFICATION_SCHEME_CODE','CLASSIFICATION_CODE'])) THEN
        RAISE EXCEPTION 'code_generator_invalid_scope' USING ERRCODE='23514';
    END IF;
    NEW.version:=CASE WHEN TG_OP='INSERT' THEN 1 ELSE OLD.version+1 END;
    NEW.date_updated:=CURRENT_TIMESTAMP; NEW.updated_by_user_id:=current_user_id();
    RETURN NEW;
END $$;
CREATE TRIGGER code_generators_guard BEFORE INSERT OR UPDATE OR DELETE ON public.code_generators
    FOR EACH ROW EXECUTE FUNCTION public.guard_code_generator();

CREATE FUNCTION public.code_generator_snapshot(definition public.code_generators) RETURNS jsonb
LANGUAGE sql STABLE STRICT AS $$
    SELECT (to_jsonb(definition)-'type_population'-'field_data_type') || jsonb_build_object(
        'start',trunc(definition.start)::text,'increment',trunc(definition.increment)::text,
        'target_snapshot',jsonb_build_object('kind',definition.kind,'primary_field',definition.primary_field,
            'type_id',definition.type_id,'type_name',(SELECT name FROM resource_types WHERE kind=definition.kind AND id=definition.type_id),
            'field_id',definition.field_id,'field_name',(SELECT name FROM resource_type_fields WHERE id=definition.field_id)))
$$;

CREATE FUNCTION public.audit_code_generator() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE before_value jsonb; after_value jsonb; changed text[]; definition public.code_generators;
BEGIN
    IF TG_OP<>'INSERT' THEN before_value:=code_generator_snapshot(OLD); END IF;
    IF TG_OP<>'DELETE' THEN after_value:=code_generator_snapshot(NEW); definition:=NEW; ELSE definition:=OLD; END IF;
    SELECT array_agg(key ORDER BY key) INTO changed FROM jsonb_object_keys(coalesce(before_value,'{}')||coalesce(after_value,'{}')) key
        WHERE before_value->key IS DISTINCT FROM after_value->key;
    INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,request_id,correlation_id,
                              before_state,after_state,changed_fields,reason,metadata)
    VALUES('code_generator',definition.id,CASE WHEN TG_OP='INSERT' THEN 'CREATE' ELSE TG_OP END,current_user_id(),
        coalesce(nullif(current_setting('app.actor_type',true),''),'automated_process'),
        coalesce(nullif(current_setting('app.event_source',true),''),'database'),
        nullif(current_setting('app.request_id',true),'')::uuid,nullif(current_setting('app.correlation_id',true),'')::uuid,
        before_value,after_value,changed,nullif(current_setting('app.change_reason',true),''),
        coalesce(nullif(current_setting('app.event_metadata',true),'')::jsonb,'{}') ||
        jsonb_build_object('generator_id',definition.id,'generator_name',definition.name));
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER code_generators_history AFTER INSERT OR UPDATE OR DELETE ON public.code_generators
    FOR EACH ROW EXECUTE FUNCTION public.audit_code_generator();

CREATE FUNCTION public.guard_generated_field_definition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' AND (NEW.data_type,NEW.max_length) IS NOT DISTINCT FROM (OLD.data_type,OLD.max_length) THEN
        RETURN NEW;
    END IF;
    -- An old snapshot can miss a committed generator-limit increase. Only a
    -- reduction needs this current-read check; compatible increases and label
    -- changes keep their existing behavior. Do not lock generator rows here:
    -- their writers can already be waiting for this field row.
    IF TG_OP='UPDATE' AND NEW.max_length<OLD.max_length AND
       current_setting('transaction_isolation') NOT IN ('read committed','read uncommitted') THEN
        RAISE EXCEPTION 'code_generator_current_snapshot_required' USING ERRCODE='40001';
    END IF;
    PERFORM pg_advisory_xact_lock(code_generator_binding_key(OLD.kind,NULL,OLD.id));
    IF EXISTS(SELECT FROM code_generators WHERE field_id=OLD.id) AND
       (TG_OP='DELETE' OR NEW.data_type<>'text' OR EXISTS(
            SELECT FROM code_generators WHERE field_id=OLD.id AND max_code_length>NEW.max_length)) THEN
        RAISE EXCEPTION 'code_generator_incompatible_field' USING ERRCODE='23514';
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER resource_fields_generator_guard BEFORE DELETE OR UPDATE OF data_type,max_length ON public.resource_type_fields
    FOR EACH ROW EXECUTE FUNCTION public.guard_generated_field_definition();

CREATE FUNCTION public.guard_code_generator_counter() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition public.code_generators; expected numeric; installer boolean; consumed_override boolean;
BEGIN
    SELECT * INTO STRICT definition FROM code_generators WHERE id=NEW.generator_id;
    installer:=current_user_id() IS NULL AND coalesce(current_setting('app.event_source',true),'') IN ('seeding','migration');
    IF TG_OP='UPDATE' THEN
        IF (NEW.generator_id,NEW.scope_kind,NEW.scope_id,NEW.reset_frequency,NEW.period_bucket) IS DISTINCT FROM
           (OLD.generator_id,OLD.scope_kind,OLD.scope_id,OLD.reset_frequency,OLD.period_bucket) THEN
            RAISE EXCEPTION 'code_generator_counter_identity_immutable' USING ERRCODE='23514';
        END IF;
        expected:=coalesce(OLD.forward_next,OLD.last_serial+definition.increment,definition.start);
        IF OLD.last_serial IS NOT NULL AND (NEW.last_serial IS NULL OR NEW.last_serial<OLD.last_serial) THEN
            RAISE EXCEPTION 'code_generator_counter_cannot_rewind' USING ERRCODE='23514';
        END IF;
        IF NEW.last_serial IS DISTINCT FROM OLD.last_serial AND
           (NEW.last_serial<expected OR mod(NEW.last_serial-expected,definition.increment)<>0) THEN
            RAISE EXCEPTION 'code_generator_invalid_counter_advance' USING ERRCODE='23514';
        END IF;
        consumed_override:=OLD.forward_next IS NOT NULL AND NEW.forward_next IS NULL
            AND NEW.last_serial IS DISTINCT FROM OLD.last_serial AND NEW.last_serial>=OLD.forward_next;
        IF NEW.forward_next IS DISTINCT FROM OLD.forward_next AND NOT coalesce(consumed_override,false) THEN
            IF NEW.forward_next IS NULL OR NEW.forward_next<=expected OR NEW.last_serial IS DISTINCT FROM OLD.last_serial THEN
                RAISE EXCEPTION 'code_generator_backward_adjustment' USING ERRCODE='23514';
            END IF;
            IF NOT installer AND NOT coalesce(user_has_global_privilege(current_user_id(),'app.settings.manage'),false) THEN
                RAISE EXCEPTION 'code_generator_access_denied' USING ERRCODE='42501';
            END IF;
            IF NOT installer AND NOT resource_type_has_text(coalesce(current_setting('app.change_reason',true),'')) THEN
                RAISE EXCEPTION 'code_generator_reason_required' USING ERRCODE='23514';
            END IF;
        END IF;
        NEW.version:=OLD.version+1;
    ELSE
        NEW.version:=1;
        IF NEW.last_serial IS NOT NULL AND
           (NEW.last_serial<definition.start OR mod(NEW.last_serial-definition.start,definition.increment)<>0) THEN
            RAISE EXCEPTION 'code_generator_invalid_counter_advance' USING ERRCODE='23514';
        END IF;
        IF NEW.forward_next IS NOT NULL THEN
            IF NEW.last_serial IS NOT NULL OR NEW.forward_next<=definition.start THEN
                RAISE EXCEPTION 'code_generator_backward_adjustment' USING ERRCODE='23514';
            END IF;
            IF NOT installer AND NOT coalesce(user_has_global_privilege(current_user_id(),'app.settings.manage'),false) THEN
                RAISE EXCEPTION 'code_generator_access_denied' USING ERRCODE='42501';
            END IF;
            IF NOT installer AND NOT resource_type_has_text(coalesce(current_setting('app.change_reason',true),'')) THEN
                RAISE EXCEPTION 'code_generator_reason_required' USING ERRCODE='23514';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER code_generator_counters_guard BEFORE INSERT OR UPDATE ON public.code_generator_counters
    FOR EACH ROW EXECUTE FUNCTION public.guard_code_generator_counter();

CREATE FUNCTION public.audit_code_generator_adjustment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition public.code_generators; previous_next numeric; previous_version bigint;
BEGIN
    IF NEW.forward_next IS NULL THEN RETURN NEW; END IF;
    IF TG_OP='UPDATE' AND NEW.forward_next IS NOT DISTINCT FROM OLD.forward_next THEN RETURN NEW; END IF;
    SELECT * INTO STRICT definition FROM code_generators WHERE id=NEW.generator_id;
    previous_next:=definition.start; previous_version:=0;
    IF TG_OP='UPDATE' THEN
        previous_next:=coalesce(OLD.forward_next,OLD.last_serial+definition.increment,definition.start);
        previous_version:=OLD.version;
    END IF;
    PERFORM append_domain_event('code_generator',NEW.generator_id,'NEXT_NUMBER_CHANGED',jsonb_build_object(
        'generator_id',definition.id,'generator_name',definition.name,
        'target_snapshot',code_generator_snapshot(definition)->'target_snapshot',
        'scope_kind',NEW.scope_kind,'scope_id',NEW.scope_id,'reset_frequency',NEW.reset_frequency,'period_bucket',NEW.period_bucket,
        'before',jsonb_build_object('next_number',trunc(previous_next)::text,'version',previous_version),
        'after',jsonb_build_object('next_number',trunc(NEW.forward_next)::text,'version',NEW.version)));
    RETURN NEW;
END $$;
CREATE TRIGGER code_generator_counters_adjustment_history AFTER INSERT OR UPDATE ON public.code_generator_counters
    FOR EACH ROW EXECUTE FUNCTION public.audit_code_generator_adjustment();

CREATE FUNCTION public.prevent_code_generator_state_erasure() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'code_generator_state_must_be_retained' USING ERRCODE='42501';
END $$;
CREATE TRIGGER code_generators_no_truncate BEFORE TRUNCATE ON public.code_generators
    FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_code_generator_state_erasure();
CREATE TRIGGER code_generator_counters_no_truncate BEFORE TRUNCATE ON public.code_generator_counters
    FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_code_generator_state_erasure();
CREATE TRIGGER code_generator_counters_no_delete BEFORE DELETE ON public.code_generator_counters
    FOR EACH ROW EXECUTE FUNCTION public.prevent_code_generator_state_erasure();
CREATE TRIGGER resource_creation_requests_no_truncate BEFORE TRUNCATE ON public.resource_creation_requests
    FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_code_generator_state_erasure();

CREATE FUNCTION public.guard_creation_completion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Account deletion removes an unusable caller identity; deleting a resource
    -- never removes its completion receipt. Completed receipts cannot be edited.
    IF TG_OP='DELETE' AND NOT EXISTS(SELECT FROM users WHERE id=OLD.caller_user_id) THEN RETURN OLD; END IF;
    IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'result')=(to_jsonb(OLD)-'result')
       AND NEW.result=OLD.result||jsonb_build_object('response',NULL,'unavailable',true)
       AND public.creation_response_is_retiring(OLD.result) THEN RETURN NEW; END IF;
    RAISE EXCEPTION 'creation_completion_immutable' USING ERRCODE='42501';
END $$;
CREATE TRIGGER resource_creation_requests_immutable BEFORE UPDATE OR DELETE ON public.resource_creation_requests
    FOR EACH ROW EXECUTE FUNCTION public.guard_creation_completion();

CREATE OR REPLACE FUNCTION disposition_private.minimize_unit_history(p_job bigint, p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NOT disposition_private.destruction_active('finalize',p_root) THEN RAISE EXCEPTION 'disposition_destruction_command_required'; END IF;
 UPDATE disposition_review_rounds SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot),proposal_snapshot=disposition_private.retained_history_json(proposal_snapshot),approval_execution=disposition_private.retained_history_json(approval_execution) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_review_decisions SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot),proposal_snapshot=disposition_private.retained_history_json(proposal_snapshot) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_job_documents SET provenance=disposition_private.retained_history_json(provenance) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_proposal_effects SET details=disposition_private.retained_json(details) WHERE governing_root_id=p_root;
 UPDATE disposition_private.command_receipts SET payload=disposition_private.retained_command_payload(payload),result=disposition_private.retained_history_json(result)
 WHERE completed_at IS NOT NULL AND (payload->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR payload->>'root_id'=p_root::text OR payload->>'task_id' IN (SELECT id::text FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)) OR result->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR operation='job_create' AND result->>'id'=p_job::text);
 UPDATE public.resource_creation_requests receipt SET result=receipt.result||jsonb_build_object('response',NULL,'unavailable',true)
 FROM (
  SELECT 'aggregation'::text AS kind,id FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root))
  UNION ALL SELECT 'record',id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))
 ) retiring
 WHERE receipt.result->>'kind'=retiring.kind
 AND public.creation_response_resource_id(receipt.result)=retiring.id
 AND public.creation_response_resource_id(receipt.result) IS NOT NULL;
 UPDATE event_history SET before_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(before_state) ELSE disposition_private.retained_history_json(before_state) END,after_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(after_state) ELSE disposition_private.retained_history_json(after_state) END,metadata=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(metadata) ELSE disposition_private.retained_history_json(metadata) END
 WHERE (entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root)))
 OR (entity_type='record' AND entity_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))))
 OR (entity_type IN ('digital_component','record_component') AND (SELECT identities->'component_ids' FROM disposition_private.destruction_identities WHERE transaction_id=txid_current() AND root_id=p_root) @> to_jsonb(entity_id))
 OR (entity_type='disposition_job' AND entity_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root))
 OR (entity_type='disposition_task' AND entity_id IN (SELECT id FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_round' AND entity_id IN (SELECT id FROM disposition_review_rounds WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_decision' AND entity_id IN (SELECT id FROM disposition_review_decisions WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_document' AND entity_id IN (SELECT id FROM disposition_job_documents WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_membership' AND entity_id IN (SELECT id FROM disposition_job_memberships WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)));
END $$;

-- Only the API database role (the function owner, or an explicit grantee) may
-- establish this context. It authorizes one new internal record ID, not a
-- general closure bypass, and expires with the transaction.
CREATE FUNCTION public.begin_closed_record_creation(p_destination bigint, p_level bigint) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE destination public.aggregations%ROWTYPE; identity_number bigint;
BEGIN
    SELECT * INTO STRICT destination FROM aggregations WHERE id=p_destination FOR SHARE;
    PERFORM id FROM aggregations WHERE id IN (WITH RECURSIVE ancestry AS (
        SELECT id,parent_aggregation_id FROM aggregations WHERE id=p_destination
        UNION ALL SELECT parent.id,parent.parent_aggregation_id
        FROM aggregations parent JOIN ancestry child ON parent.id=child.parent_aggregation_id
    ) SELECT id FROM ancestry) ORDER BY id FOR SHARE;
    IF current_setting('app.actor_type',true) IS DISTINCT FROM 'user'
       OR NOT EXISTS(SELECT FROM users WHERE id=current_user_id() AND account_type='person' AND status='active')
       OR NOT coalesce(user_has_global_privilege(current_user_id(),'record.create'),false)
       OR NOT coalesce(user_has_global_privilege(current_user_id(),'closure.correct_record_placement'),false)
       OR NOT coalesce(user_has_governance_clearance(current_user_id(),p_level),false)
       OR NOT coalesce(user_has_governance_clearance(current_user_id(),destination.security_level_id),false)
       OR NOT resource_type_has_text(coalesce(current_setting('app.change_reason',true),'')) THEN
        RAISE EXCEPTION 'governance_correction_required' USING ERRCODE='42501';
    END IF;
    IF NOT EXISTS(WITH RECURSIVE ancestry AS (
        SELECT id,parent_aggregation_id,date_closed FROM aggregations WHERE id=p_destination
        UNION ALL SELECT parent.id,parent.parent_aggregation_id,parent.date_closed
        FROM aggregations parent JOIN ancestry child ON parent.id=child.parent_aggregation_id
    ) SELECT FROM ancestry WHERE date_closed IS NOT NULL) THEN
        RAISE EXCEPTION 'closed placement correction requires a closed destination';
    END IF;
    identity_number:=nextval(pg_get_serial_sequence('records','id'));
    PERFORM set_config('app.closed_record_creation_context',jsonb_build_object(
        'transaction_id',txid_current(),'backend_id',pg_backend_pid(),'user_id',current_user_id(),
        'record_id',identity_number,'aggregation_id',p_destination,'security_level_id',p_level)::text,true);
    RETURN identity_number;
END $$;
REVOKE ALL ON FUNCTION public.begin_closed_record_creation(bigint,bigint) FROM PUBLIC;

CREATE FUNCTION public.closed_record_creation_allowed(p_record bigint, p_destination bigint, p_level bigint)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE context jsonb;
BEGIN
    context:=nullif(current_setting('app.closed_record_creation_context',true),'')::jsonb;
    RETURN coalesce(context IS NOT NULL
        AND has_function_privilege(current_user,'public.begin_closed_record_creation(bigint,bigint)','EXECUTE')
        AND context->>'transaction_id'=txid_current()::text AND context->>'backend_id'=pg_backend_pid()::text
        AND context->>'user_id'=current_user_id()::text AND context->>'record_id'=p_record::text
        AND context->>'aggregation_id'=p_destination::text AND context->>'security_level_id'=p_level::text
        AND current_setting('app.actor_type',true)='user'
        AND EXISTS(SELECT FROM users WHERE id=current_user_id() AND account_type='person' AND status='active')
        AND user_has_global_privilege(current_user_id(),'record.create')
        AND user_has_global_privilege(current_user_id(),'closure.correct_record_placement')
        AND user_has_governance_clearance(current_user_id(),p_level)
        AND user_has_governance_clearance(current_user_id(),(SELECT security_level_id FROM aggregations WHERE id=p_destination))
        AND resource_type_has_text(coalesce(current_setting('app.change_reason',true),'')),false);
END $$;

CREATE FUNCTION public.closed_record_birth_content_allowed(p_record bigint) RETURNS boolean
LANGUAGE sql STABLE STRICT AS $$
    SELECT coalesce(nullif(current_setting('app.closed_record_birth_context',true),'')::jsonb
        =nullif(current_setting('app.closed_record_creation_context',true),'')::jsonb
        AND (SELECT public.closed_record_creation_allowed(id,aggregation_id,security_level_id)
             FROM records WHERE id=p_record),false)
$$;

CREATE OR REPLACE FUNCTION public.protect_record_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 IF TG_OP='UPDATE' AND disposition_private.context_operation() IS NOT NULL
 AND (to_jsonb(NEW)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated'])=(to_jsonb(OLD)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated']) THEN
  PERFORM disposition_private.require_command(); RETURN NEW;
 END IF;
 IF TG_OP='INSERT' THEN
  IF nullif(current_setting('app.closed_record_creation_context',true),'') IS NOT NULL THEN
   IF public.closed_record_creation_allowed(NEW.id,NEW.aggregation_id,NEW.security_level_id) THEN
    PERFORM set_config('app.closed_record_birth_context',current_setting('app.closed_record_creation_context'),true);
    RETURN NEW;
   END IF;
  END IF;
  PERFORM assert_aggregation_effectively_open(NEW.aggregation_id); RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN OLD; END IF;
 IF current_setting('app.vital_status_change_authorized',true)='authorized' AND NEW.is_vital IS DISTINCT FROM OLD.is_vital AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.review_date_change_authorized',true)='authorized' AND NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review AND (to_jsonb(NEW)-'date_of_next_review'-'version')=(to_jsonb(OLD)-'date_of_next_review'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.security_level_change_authorized',true)='authorized' AND NEW.security_level_id IS DISTINCT FROM OLD.security_level_id AND (to_jsonb(NEW)-'security_level_id'-'version')=(to_jsonb(OLD)-'security_level_id'-'version') THEN RETURN NEW; END IF;
 PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION public.protect_component_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=OLD.record_id))) THEN RETURN OLD; END IF;

    IF TG_OP<>'DELETE' AND nullif(current_setting('app.closed_record_creation_context',true),'') IS NOT NULL THEN
        IF public.closed_record_birth_content_allowed(NEW.record_id) THEN
            IF TG_OP='INSERT' THEN RETURN NEW; END IF;
            IF NEW.record_id=OLD.record_id THEN RETURN NEW; END IF;
        END IF;
    END IF;
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

CREATE OR REPLACE FUNCTION public.protect_content_set_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_component_id bigint;
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=(SELECT record_id FROM digital_components WHERE id=OLD.digital_component_id)))) THEN RETURN OLD; END IF;

    IF TG_OP='INSERT' AND nullif(current_setting('app.closed_record_creation_context',true),'') IS NOT NULL THEN
        IF public.closed_record_birth_content_allowed((SELECT record_id FROM digital_components WHERE id=NEW.digital_component_id)) THEN RETURN NEW; END IF;
    END IF;
    target_component_id := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
    PERFORM assert_record_effectively_open(
        (SELECT record_id FROM digital_components WHERE id = target_component_id)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE OR REPLACE FUNCTION public.protect_blob_in_closed_aggregation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_content_set_id bigint;
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=(SELECT d.record_id FROM digital_component_content_sets s JOIN digital_components d ON d.id=s.digital_component_id WHERE s.id=OLD.content_set_id)))) THEN RETURN OLD; END IF;

    IF TG_OP='INSERT' AND nullif(current_setting('app.closed_record_creation_context',true),'') IS NOT NULL THEN
        IF public.closed_record_birth_content_allowed((SELECT component.record_id FROM digital_component_content_sets content_set
            JOIN digital_components component ON component.id=content_set.digital_component_id WHERE content_set.id=NEW.content_set_id)) THEN RETURN NEW; END IF;
    END IF;
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

-- Binding removal disables and clears the target, retaining the definition ID
-- and counters. Whole-definition deletion remains possible only without counters.
ALTER TABLE public.record_drafts ADD COLUMN generation_intent jsonb NOT NULL DEFAULT '{}'
    CHECK (jsonb_typeof(generation_intent)='object');

INSERT INTO public.schema_migrations(version) VALUES ('126_custom_code_generators');
COMMIT;
