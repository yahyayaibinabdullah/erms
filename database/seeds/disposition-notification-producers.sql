BEGIN;
SELECT set_config('app.event_source','seeding',true);
INSERT INTO system_notification_producers(producer_code,feature_code,event_type,required_for_business_commit,contract_version,contract_definition,name) VALUES
('disposition.task_assigned','disposition','task_assigned',false,1,'{"audience_modes": ["current_eligible_task_recipients"], "resource_link_kinds": [], "resource_configuration": null, "placeholders": {"task_id": {"type": "integer", "max_length": 1000}}}'::jsonb,'Disposition task assigned')
ON CONFLICT (producer_code) DO NOTHING;
COMMIT;
