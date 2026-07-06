-- Notification email delivery and project issue due-date reminder idempotency.

ALTER TABLE "public"."notifications"
    ADD COLUMN IF NOT EXISTS "emailed_at" timestamp with time zone;

ALTER TABLE "public"."project_issues"
    ADD COLUMN IF NOT EXISTS "due_reminder_sent_at" timestamp with time zone;

CREATE INDEX IF NOT EXISTS "idx_notifications_digest_pending"
    ON "public"."notifications" USING "btree" ("user_id", "created_at")
    WHERE (("read" = false) AND ("archived" = false) AND ("emailed_at" IS NULL));

CREATE INDEX IF NOT EXISTS "idx_project_issues_due_reminder_pending"
    ON "public"."project_issues" USING "btree" ("due_at")
    WHERE (("due_at" IS NOT NULL) AND ("completed_at" IS NULL) AND ("due_reminder_sent_at" IS NULL));
