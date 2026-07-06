-- Versioned binary attachments for project issues.

CREATE TABLE IF NOT EXISTS "public"."issue_attachments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_app_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "issue_id" "uuid" NOT NULL,
    "filename" "text" NOT NULL,
    "content_type" "text" NOT NULL,
    "current_version_id" "uuid",
    "next_version_number" integer DEFAULT 1 NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

ALTER TABLE "public"."issue_attachments" OWNER TO "postgres";

CREATE TABLE IF NOT EXISTS "public"."issue_attachment_versions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_app_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "attachment_id" "uuid" NOT NULL,
    "version_number" integer NOT NULL,
    "r2_key" "text" NOT NULL,
    "file_size" bigint NOT NULL,
    "content_type" "text" NOT NULL,
    "uploaded_by" "uuid",
    "uploaded_at" timestamp with time zone DEFAULT "now"()
);

ALTER TABLE "public"."issue_attachment_versions" OWNER TO "postgres";

ALTER TABLE ONLY "public"."issue_attachments"
    ADD CONSTRAINT "issue_attachments_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."issue_attachment_versions"
    ADD CONSTRAINT "issue_attachment_versions_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."issue_attachments"
    ADD CONSTRAINT "issue_attachments_issue_id_fkey"
    FOREIGN KEY ("issue_id") REFERENCES "public"."project_issues"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."issue_attachments"
    ADD CONSTRAINT "issue_attachments_workspace_app_id_fkey"
    FOREIGN KEY ("workspace_app_id") REFERENCES "public"."workspace_apps"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."issue_attachments"
    ADD CONSTRAINT "issue_attachments_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."issue_attachments"
    ADD CONSTRAINT "issue_attachments_created_by_fkey"
    FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."issue_attachment_versions"
    ADD CONSTRAINT "issue_attachment_versions_attachment_id_fkey"
    FOREIGN KEY ("attachment_id") REFERENCES "public"."issue_attachments"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."issue_attachment_versions"
    ADD CONSTRAINT "issue_attachment_versions_workspace_app_id_fkey"
    FOREIGN KEY ("workspace_app_id") REFERENCES "public"."workspace_apps"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."issue_attachment_versions"
    ADD CONSTRAINT "issue_attachment_versions_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."issue_attachment_versions"
    ADD CONSTRAINT "issue_attachment_versions_uploaded_by_fkey"
    FOREIGN KEY ("uploaded_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."issue_attachments"
    DROP CONSTRAINT IF EXISTS "issue_attachments_current_version_id_fkey";

ALTER TABLE ONLY "public"."issue_attachments"
    ADD CONSTRAINT "issue_attachments_current_version_id_fkey"
    FOREIGN KEY ("current_version_id") REFERENCES "public"."issue_attachment_versions"("id") ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS "idx_issue_attachments_issue_id"
    ON "public"."issue_attachments" USING "btree" ("issue_id");

CREATE INDEX IF NOT EXISTS "idx_issue_attachments_workspace_app_id"
    ON "public"."issue_attachments" USING "btree" ("workspace_app_id");

CREATE UNIQUE INDEX IF NOT EXISTS "idx_issue_attachment_versions_attachment_version"
    ON "public"."issue_attachment_versions" USING "btree" ("attachment_id", "version_number");

CREATE UNIQUE INDEX IF NOT EXISTS "idx_issue_attachment_versions_r2_key"
    ON "public"."issue_attachment_versions" USING "btree" ("r2_key");

CREATE INDEX IF NOT EXISTS "idx_issue_attachment_versions_attachment_id"
    ON "public"."issue_attachment_versions" USING "btree" ("attachment_id");

CREATE OR REPLACE FUNCTION "public"."allocate_issue_attachment_version"("p_attachment_id" "uuid") RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_number INT;
BEGIN
    UPDATE "public"."issue_attachments"
    SET "next_version_number" = "next_version_number" + 1
    WHERE "id" = p_attachment_id
    RETURNING "next_version_number" - 1 INTO v_number;

    IF v_number IS NULL THEN
        RAISE EXCEPTION 'Attachment not found or not accessible: %', p_attachment_id;
    END IF;

    RETURN v_number;
END;
$$;

ALTER FUNCTION "public"."allocate_issue_attachment_version"("p_attachment_id" "uuid") OWNER TO "postgres";

CREATE OR REPLACE TRIGGER "update_issue_attachments_updated_at"
    BEFORE UPDATE ON "public"."issue_attachments"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

ALTER TABLE "public"."issue_attachments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."issue_attachment_versions" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view issue attachments in accessible workspace apps"
    ON "public"."issue_attachments" FOR SELECT
    USING ("public"."can_access_workspace_app"("workspace_app_id"));

CREATE POLICY "Members can create issue attachments in accessible workspace apps"
    ON "public"."issue_attachments" FOR INSERT
    WITH CHECK ("public"."can_access_workspace_app"("workspace_app_id"));

CREATE POLICY "Members can update issue attachments in accessible workspace apps"
    ON "public"."issue_attachments" FOR UPDATE
    USING ("public"."can_access_workspace_app"("workspace_app_id"));

CREATE POLICY "Members can view issue attachment versions in accessible workspace apps"
    ON "public"."issue_attachment_versions" FOR SELECT
    USING ("public"."can_access_workspace_app"("workspace_app_id"));

CREATE POLICY "Members can create issue attachment versions in accessible workspace apps"
    ON "public"."issue_attachment_versions" FOR INSERT
    WITH CHECK ("public"."can_access_workspace_app"("workspace_app_id"));

GRANT ALL ON TABLE "public"."issue_attachments" TO "anon";
GRANT ALL ON TABLE "public"."issue_attachments" TO "authenticated";
GRANT ALL ON TABLE "public"."issue_attachments" TO "service_role";

GRANT ALL ON TABLE "public"."issue_attachment_versions" TO "anon";
GRANT ALL ON TABLE "public"."issue_attachment_versions" TO "authenticated";
GRANT ALL ON TABLE "public"."issue_attachment_versions" TO "service_role";

GRANT ALL ON FUNCTION "public"."allocate_issue_attachment_version"("p_attachment_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."allocate_issue_attachment_version"("p_attachment_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."allocate_issue_attachment_version"("p_attachment_id" "uuid") TO "service_role";
