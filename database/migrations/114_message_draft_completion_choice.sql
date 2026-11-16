BEGIN;

ALTER TABLE public.message_drafts
    ADD COLUMN complete_action boolean DEFAULT false NOT NULL;

INSERT INTO public.schema_migrations(version)
VALUES ('114_message_draft_completion_choice');

COMMIT;
