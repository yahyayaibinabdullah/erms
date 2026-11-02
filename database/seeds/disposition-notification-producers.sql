BEGIN;
SELECT set_config('app.event_source','seeding',true);
INSERT INTO system_notification_producers(producer_code,feature_code,event_type,required_for_business_commit,contract_version,contract_definition,name) VALUES
('disposition.task_assigned','disposition','task_assigned',false,1,'{"audience_modes": ["current_eligible_task_recipients"], "resource_link_kinds": [], "resource_configuration": null, "placeholders": {"task_id": {"type": "integer", "max_length": 1000}}}'::jsonb,'Disposition task assigned')
ON CONFLICT (producer_code) DO NOTHING;
INSERT INTO system_notification_producers(producer_code,feature_code,event_type,required_for_business_commit,contract_version,contract_definition,name) VALUES
('disposition.eligibility_reminder','disposition','eligibility_reminder',false,1,'{"placeholders": {"recipient_id": {"type": "integer", "max_length": 1000}, "scheduled_interval": {"type": "text", "max_length": 1000}}, "audience_modes": ["current_governance_person"], "resource_link_kinds": [], "resource_configuration": null}'::jsonb,'Destruction eligibility reminder')
ON CONFLICT (producer_code) DO NOTHING;
INSERT INTO system_notification_producers(producer_code,feature_code,event_type,required_for_business_commit,contract_version,contract_definition,name) VALUES
('disposition.destruction_outcome','disposition','destruction_outcome',false,1,'{"audience_modes": ["current_eligible_managers"], "resource_link_kinds": [], "resource_configuration": null, "placeholders": {"run_id": {"type": "integer", "max_length": 1000}}}'::jsonb,'Digital destruction outcome')
ON CONFLICT(producer_code) DO NOTHING;
INSERT INTO system_notification_producers(producer_code,feature_code,event_type,required_for_business_commit,contract_version,contract_definition,name) VALUES
('disposition.completion_outcome','disposition','completion_outcome',false,1,'{"audience_modes": ["current_eligible_managers"], "resource_link_kinds": [], "resource_configuration": null, "placeholders": {"job_id": {"type": "integer", "max_length": 1000}}}'::jsonb,'Destruction completion or certificate failure')
ON CONFLICT(producer_code) DO NOTHING;
COMMIT;
