-- Eligibility does not authorize admission or execution. Preserve closure protections.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.accelerate(p_root bigint,p_version bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; evaluation record;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'eligibility_accelerate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 PERFORM disposition_private.lock_current_blockers(p_root);
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 IF NOT FOUND OR root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF NOT current_user_can_view_aggregation(p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF root.disposition_status<>1 OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active') THEN RAISE EXCEPTION 'disposition_acceleration_state_invalid'; END IF;
 IF root.date_closed IS NULL THEN
  IF NOT current_user_can_aggregation_operation(p_root,'aggregation.close','aggregation.close') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='insufficient_privilege'; END IF;
  UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=p_root RETURNING * INTO root;
 END IF;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 IF evaluation.eligible_status IS NULL THEN RAISE EXCEPTION 'disposition_retention_rule_required'; END IF;
 PERFORM disposition_private.transition_unit(p_root,root.version,evaluation.eligible_status);
 PERFORM append_domain_event('aggregation',p_root,'DISPOSITION_ACCELERATED',to_jsonb(evaluation));
 RETURN jsonb_build_object('root_id',p_root,'status',evaluation.eligible_status);
END $$;

CREATE OR REPLACE FUNCTION protect_held_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE blocked boolean;
DECLARE allowed_old jsonb;
DECLARE allowed_new jsonb;
BEGIN
    PERFORM lock_hold_policy_shared();
    -- Recording an immutable physical outcome or redirecting preserved material
    -- changes only disposition bookkeeping; the hold and all content remain.
    IF TG_OP='UPDATE' AND disposition_private.context_operation() IN ('job_terminate','resolve_partial')
      AND disposition_private.recovery_active(NULL,disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END),NEW.disposition_status)
      AND ((OLD.disposition_status=6 AND NEW.disposition_status IN (10,13)) OR (OLD.disposition_status=13 AND NEW.disposition_status BETWEEN 2 AND 5))
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','final_disposition_event_id'])=(to_jsonb(OLD)-ARRAY['disposition_status','version','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','final_disposition_event_id']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;

    -- Leaving a job/terminating it restores eligibility and preserves the hold.
    -- This is status-only bookkeeping, never destruction or a metadata override.
    IF TG_OP='UPDATE' AND disposition_private.context_operation() IN ('membership_remove','job_terminate')
      AND OLD.disposition_status BETWEEN 6 AND 9 AND NEW.disposition_status=OLD.disposition_status-4
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    IF TG_OP='UPDATE' AND disposition_private.hook_applying()
      AND OLD.disposition_status BETWEEN 1 AND 9 AND NEW.disposition_status BETWEEN 1 AND 9
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    -- Eligibility bookkeeping does not alter content, hold assignments or held metadata.
    -- Acceleration's separate closure update still passes the ordinary hold guard.
    IF TG_OP='UPDATE' AND OLD.disposition_status=1 AND NEW.disposition_status BETWEEN 2 AND 5
      AND disposition_private.context_operation() IN ('eligibility_evaluate','eligibility_accelerate')
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
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
INSERT INTO schema_migrations(version) VALUES('077_acceleration_eligibility_protections') ON CONFLICT DO NOTHING;
COMMIT;
