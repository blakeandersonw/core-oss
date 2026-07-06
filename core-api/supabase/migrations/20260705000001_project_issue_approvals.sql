-- Project issue approval workflow.

DO $$
BEGIN
    CREATE TYPE "public"."project_issue_approval_status" AS ENUM ('none', 'pending', 'approved', 'rejected');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE "public"."project_issues"
    ADD COLUMN IF NOT EXISTS "approval_status" "public"."project_issue_approval_status" DEFAULT 'none'::"public"."project_issue_approval_status" NOT NULL,
    ADD COLUMN IF NOT EXISTS "approval_requested_by" "uuid",
    ADD COLUMN IF NOT EXISTS "approval_requested_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "approval_note" "text",
    ADD COLUMN IF NOT EXISTS "approved_by" "uuid",
    ADD COLUMN IF NOT EXISTS "approved_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "approval_decision_note" "text";

ALTER TABLE ONLY "public"."project_issues"
    DROP CONSTRAINT IF EXISTS "project_issues_approval_requested_by_fkey";

ALTER TABLE ONLY "public"."project_issues"
    ADD CONSTRAINT "project_issues_approval_requested_by_fkey"
    FOREIGN KEY ("approval_requested_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."project_issues"
    DROP CONSTRAINT IF EXISTS "project_issues_approved_by_fkey";

ALTER TABLE ONLY "public"."project_issues"
    ADD CONSTRAINT "project_issues_approved_by_fkey"
    FOREIGN KEY ("approved_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS "idx_project_issues_approval_status"
    ON "public"."project_issues" USING "btree" ("workspace_id", "approval_status")
    WHERE ("approval_status" <> 'none'::"public"."project_issue_approval_status");
