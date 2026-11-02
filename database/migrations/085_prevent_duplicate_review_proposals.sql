BEGIN;
-- Equivalent desired effects, independent of proposer, reason or selection order.
CREATE FUNCTION disposition_private.proposal_duplicate_key(p jsonb) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE typ text:=p->>'proposal_type'; values_json jsonb:=p->'proposed_values';
BEGIN
 IF typ IN ('remove_aggregation_relationship','remove_record_relationship') THEN
  RETURN jsonb_build_array(typ,values_json->'relationship_id');
 ELSIF typ='create_aggregation_relationship' THEN
  RETURN jsonb_build_array(typ,disposition_private.proposal_relationship_key(p#>'{current_values,relationship}'));
 ELSIF typ='add_to_holds' THEN
  values_json:=jsonb_build_object('hold_ids',(SELECT jsonb_agg(v ORDER BY v) FROM (SELECT DISTINCT value::text::bigint v FROM jsonb_array_elements(values_json->'hold_ids')) ids));
 ELSIF typ='local_retention_override' THEN
  values_json:=jsonb_set(values_json,'{instructions}',to_jsonb(COALESCE(NULLIF(btrim(values_json->>'instructions'),''),'')));
 END IF;
 RETURN jsonb_build_array(typ,p->'target_aggregation_id',p->'target_record_id',values_json);
END $$;
CREATE FUNCTION disposition_private.reject_duplicate_proposal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.proposal_state<>'active' THEN RETURN NEW; END IF;
 -- Commands use this same transaction lock. Authorization/fact validation in
 -- disposition_proposal_guard runs first, before any duplicate is disclosed.
 PERFORM pg_advisory_xact_lock(7357,1);
 IF EXISTS(SELECT 1 FROM disposition_review_proposals p WHERE p.job_id=NEW.job_id
   AND p.review_round=NEW.review_round AND p.proposal_state='active' AND p.id<>NEW.id
   AND disposition_private.proposal_duplicate_key(to_jsonb(p))=disposition_private.proposal_duplicate_key(to_jsonb(NEW))) THEN
  RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='disposition_proposal_duplicate';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_proposal_unique BEFORE INSERT OR UPDATE ON disposition_review_proposals
 FOR EACH ROW EXECUTE FUNCTION disposition_private.reject_duplicate_proposal();
CREATE INDEX disposition_proposal_active_round ON disposition_review_proposals(job_id,review_round) WHERE proposal_state='active';
REVOKE ALL ON FUNCTION disposition_private.proposal_duplicate_key(jsonb),disposition_private.reject_duplicate_proposal() FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('085_prevent_duplicate_review_proposals') ON CONFLICT DO NOTHING;
COMMIT;
