-- Assigned approver and approval lock for project issues.

ALTER TABLE "public"."project_issues"
    ADD COLUMN IF NOT EXISTS "approver_id" "uuid",
    ADD COLUMN IF NOT EXISTS "approval_locked" boolean DEFAULT false NOT NULL;

ALTER TABLE ONLY "public"."project_issues"
    DROP CONSTRAINT IF EXISTS "project_issues_approver_id_fkey";

ALTER TABLE ONLY "public"."project_issues"
    ADD CONSTRAINT "project_issues_approver_id_fkey"
    FOREIGN KEY ("approver_id") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS "idx_project_issues_approver_id"
    ON "public"."project_issues" USING "btree" ("approver_id")
    WHERE ("approver_id" IS NOT NULL);
