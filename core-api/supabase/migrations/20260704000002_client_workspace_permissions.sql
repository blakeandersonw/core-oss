-- Client workspace permissions and integration surfaces.

----------------------------------------------------------------------------
-- Chat workspace pinning
----------------------------------------------------------------------------

ALTER TABLE "public"."conversations"
    ADD COLUMN IF NOT EXISTS "workspace_id" "uuid";

ALTER TABLE ONLY "public"."conversations"
    DROP CONSTRAINT IF EXISTS "conversations_workspace_id_fkey";

ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS "idx_conversations_workspace_id"
    ON "public"."conversations" USING "btree" ("workspace_id");

----------------------------------------------------------------------------
-- Workspace client contacts/domains
----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "public"."workspace_client_contacts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "kind" "text" DEFAULT 'email'::"text" NOT NULL,
    "value" "text" NOT NULL,
    "label" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "workspace_client_contacts_kind_check" CHECK (("kind" = ANY (ARRAY['email'::"text", 'domain'::"text"]))),
    CONSTRAINT "workspace_client_contacts_value_check" CHECK ((length(trim("value")) > 0))
);

ALTER TABLE "public"."workspace_client_contacts" OWNER TO "postgres";

ALTER TABLE ONLY "public"."workspace_client_contacts"
    ADD CONSTRAINT "workspace_client_contacts_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."workspace_client_contacts"
    ADD CONSTRAINT "workspace_client_contacts_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."workspace_client_contacts"
    ADD CONSTRAINT "workspace_client_contacts_created_by_fkey"
    FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS "idx_workspace_client_contacts_unique"
    ON "public"."workspace_client_contacts" USING "btree" ("workspace_id", "kind", lower("value"));

CREATE INDEX IF NOT EXISTS "idx_workspace_client_contacts_workspace"
    ON "public"."workspace_client_contacts" USING "btree" ("workspace_id");

ALTER TABLE "public"."workspace_client_contacts" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view workspace client contacts"
    ON "public"."workspace_client_contacts" FOR SELECT
    USING ("public"."is_workspace_member"("workspace_id"));

CREATE POLICY "Admins can insert workspace client contacts"
    ON "public"."workspace_client_contacts" FOR INSERT
    WITH CHECK ("public"."is_workspace_admin"("workspace_id"));

CREATE POLICY "Admins can update workspace client contacts"
    ON "public"."workspace_client_contacts" FOR UPDATE
    USING ("public"."is_workspace_admin"("workspace_id"));

CREATE POLICY "Admins can delete workspace client contacts"
    ON "public"."workspace_client_contacts" FOR DELETE
    USING ("public"."is_workspace_admin"("workspace_id"));

CREATE OR REPLACE TRIGGER "update_workspace_client_contacts_updated_at"
    BEFORE UPDATE ON "public"."workspace_client_contacts"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

----------------------------------------------------------------------------
-- Project board controls, role presets, saved views
----------------------------------------------------------------------------

ALTER TABLE "public"."project_boards"
    ADD COLUMN IF NOT EXISTS "default_role_capabilities" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    ADD COLUMN IF NOT EXISTS "enforce_column_limits" boolean DEFAULT true NOT NULL;

ALTER TABLE "public"."project_states"
    ADD COLUMN IF NOT EXISTS "is_locked" boolean DEFAULT false NOT NULL,
    ADD COLUMN IF NOT EXISTS "wip_limit" integer,
    ADD CONSTRAINT "project_states_wip_limit_check" CHECK (("wip_limit" IS NULL) OR ("wip_limit" >= 0)) NOT VALID;

ALTER TABLE "public"."project_issues"
    ADD COLUMN IF NOT EXISTS "type" "text",
    ADD COLUMN IF NOT EXISTS "tags" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    ADD COLUMN IF NOT EXISTS "target_due_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "last_edited_by" "uuid",
    ADD COLUMN IF NOT EXISTS "last_edited_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "complexity" integer,
    ADD CONSTRAINT "project_issues_complexity_check" CHECK (("complexity" IS NULL) OR (("complexity" >= 0) AND ("complexity" <= 5))) NOT VALID;

ALTER TABLE ONLY "public"."project_issues"
    DROP CONSTRAINT IF EXISTS "project_issues_last_edited_by_fkey";

ALTER TABLE ONLY "public"."project_issues"
    ADD CONSTRAINT "project_issues_last_edited_by_fkey"
    FOREIGN KEY ("last_edited_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS "idx_project_issues_type"
    ON "public"."project_issues" USING "btree" ("workspace_id", "type") WHERE ("type" IS NOT NULL);

CREATE INDEX IF NOT EXISTS "idx_project_issues_target_due_at"
    ON "public"."project_issues" USING "btree" ("workspace_id", "target_due_at") WHERE ("target_due_at" IS NOT NULL);

CREATE INDEX IF NOT EXISTS "idx_project_issues_tags"
    ON "public"."project_issues" USING "gin" ("tags");

CREATE TABLE IF NOT EXISTS "public"."project_board_role_presets" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "board_id" "uuid" NOT NULL,
    "role" "public"."workspace_role" NOT NULL,
    "capabilities" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

ALTER TABLE "public"."project_board_role_presets" OWNER TO "postgres";

ALTER TABLE ONLY "public"."project_board_role_presets"
    ADD CONSTRAINT "project_board_role_presets_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."project_board_role_presets"
    ADD CONSTRAINT "project_board_role_presets_board_id_fkey"
    FOREIGN KEY ("board_id") REFERENCES "public"."project_boards"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."project_board_role_presets"
    ADD CONSTRAINT "project_board_role_presets_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

CREATE UNIQUE INDEX IF NOT EXISTS "idx_project_board_role_presets_unique"
    ON "public"."project_board_role_presets" USING "btree" ("board_id", "role");

ALTER TABLE "public"."project_board_role_presets" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view project board role presets"
    ON "public"."project_board_role_presets" FOR SELECT
    USING ("public"."is_workspace_member"("workspace_id"));

CREATE POLICY "Admins can manage project board role presets"
    ON "public"."project_board_role_presets" FOR ALL
    USING ("public"."is_workspace_admin"("workspace_id"))
    WITH CHECK ("public"."is_workspace_admin"("workspace_id"));

CREATE OR REPLACE TRIGGER "update_project_board_role_presets_updated_at"
    BEFORE UPDATE ON "public"."project_board_role_presets"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

CREATE TABLE IF NOT EXISTS "public"."project_board_member_permissions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "board_id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "capabilities" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

ALTER TABLE "public"."project_board_member_permissions" OWNER TO "postgres";

ALTER TABLE ONLY "public"."project_board_member_permissions"
    ADD CONSTRAINT "project_board_member_permissions_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."project_board_member_permissions"
    ADD CONSTRAINT "project_board_member_permissions_board_id_fkey"
    FOREIGN KEY ("board_id") REFERENCES "public"."project_boards"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."project_board_member_permissions"
    ADD CONSTRAINT "project_board_member_permissions_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."project_board_member_permissions"
    ADD CONSTRAINT "project_board_member_permissions_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

CREATE UNIQUE INDEX IF NOT EXISTS "idx_project_board_member_permissions_unique"
    ON "public"."project_board_member_permissions" USING "btree" ("board_id", "user_id");

ALTER TABLE "public"."project_board_member_permissions" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view project board member permissions"
    ON "public"."project_board_member_permissions" FOR SELECT
    USING ("public"."is_workspace_member"("workspace_id"));

CREATE POLICY "Admins can manage project board member permissions"
    ON "public"."project_board_member_permissions" FOR ALL
    USING ("public"."is_workspace_admin"("workspace_id"))
    WITH CHECK ("public"."is_workspace_admin"("workspace_id"));

CREATE OR REPLACE TRIGGER "update_project_board_member_permissions_updated_at"
    BEFORE UPDATE ON "public"."project_board_member_permissions"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

CREATE TABLE IF NOT EXISTS "public"."project_board_views" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "board_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "filters" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "sort" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "layout" "text" DEFAULT 'kanban'::"text" NOT NULL,
    "is_shared" boolean DEFAULT true NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "project_board_views_layout_check" CHECK (("layout" = ANY (ARRAY['kanban'::"text", 'list'::"text"])))
);

ALTER TABLE "public"."project_board_views" OWNER TO "postgres";

ALTER TABLE ONLY "public"."project_board_views"
    ADD CONSTRAINT "project_board_views_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."project_board_views"
    ADD CONSTRAINT "project_board_views_board_id_fkey"
    FOREIGN KEY ("board_id") REFERENCES "public"."project_boards"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."project_board_views"
    ADD CONSTRAINT "project_board_views_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."project_board_views"
    ADD CONSTRAINT "project_board_views_created_by_fkey"
    FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS "idx_project_board_views_board"
    ON "public"."project_board_views" USING "btree" ("board_id", "created_at");

ALTER TABLE "public"."project_board_views" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view shared or own project board views"
    ON "public"."project_board_views" FOR SELECT
    USING (("public"."is_workspace_member"("workspace_id") AND ("is_shared" OR ("created_by" = "auth"."uid"()))));

CREATE POLICY "Members can create project board views"
    ON "public"."project_board_views" FOR INSERT
    WITH CHECK (("public"."is_workspace_member"("workspace_id") AND ("created_by" = "auth"."uid"())));

CREATE POLICY "Owners can update project board views"
    ON "public"."project_board_views" FOR UPDATE
    USING ((("created_by" = "auth"."uid"()) OR "public"."is_workspace_admin"("workspace_id")));

CREATE POLICY "Owners can delete project board views"
    ON "public"."project_board_views" FOR DELETE
    USING ((("created_by" = "auth"."uid"()) OR "public"."is_workspace_admin"("workspace_id")));

CREATE OR REPLACE TRIGGER "update_project_board_views_updated_at"
    BEFORE UPDATE ON "public"."project_board_views"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

----------------------------------------------------------------------------
-- Workspace connectors, API keys, MCP, webhooks
----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "public"."workspace_connectors" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "display_name" "text",
    "status" "text" DEFAULT 'disconnected'::"text" NOT NULL,
    "external_account_id" "text",
    "scopes" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "workspace_connectors_status_check" CHECK (("status" = ANY (ARRAY['connected'::"text", 'disconnected'::"text", 'error'::"text", 'pending'::"text"])))
);

ALTER TABLE "public"."workspace_connectors" OWNER TO "postgres";

ALTER TABLE ONLY "public"."workspace_connectors"
    ADD CONSTRAINT "workspace_connectors_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."workspace_connectors"
    ADD CONSTRAINT "workspace_connectors_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS "idx_workspace_connectors_workspace"
    ON "public"."workspace_connectors" USING "btree" ("workspace_id", "provider");

CREATE UNIQUE INDEX IF NOT EXISTS "idx_workspace_connectors_unique_provider"
    ON "public"."workspace_connectors" USING "btree" ("workspace_id", "provider");

ALTER TABLE "public"."workspace_connectors" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view workspace connectors"
    ON "public"."workspace_connectors" FOR SELECT
    USING ("public"."is_workspace_member"("workspace_id"));

CREATE POLICY "Admins can manage workspace connectors"
    ON "public"."workspace_connectors" FOR ALL
    USING ("public"."is_workspace_admin"("workspace_id"))
    WITH CHECK ("public"."is_workspace_admin"("workspace_id"));

CREATE OR REPLACE TRIGGER "update_workspace_connectors_updated_at"
    BEFORE UPDATE ON "public"."workspace_connectors"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

CREATE TABLE IF NOT EXISTS "public"."workspace_api_keys" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "key_prefix" "text" NOT NULL,
    "key_hash" "text" NOT NULL,
    "scopes" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "created_by" "uuid",
    "last_used_at" timestamp with time zone,
    "revoked_at" timestamp with time zone,
    "expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"()
);

ALTER TABLE "public"."workspace_api_keys" OWNER TO "postgres";

ALTER TABLE ONLY "public"."workspace_api_keys"
    ADD CONSTRAINT "workspace_api_keys_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."workspace_api_keys"
    ADD CONSTRAINT "workspace_api_keys_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

CREATE UNIQUE INDEX IF NOT EXISTS "idx_workspace_api_keys_hash"
    ON "public"."workspace_api_keys" USING "btree" ("key_hash");

CREATE INDEX IF NOT EXISTS "idx_workspace_api_keys_workspace"
    ON "public"."workspace_api_keys" USING "btree" ("workspace_id", "revoked_at");

ALTER TABLE "public"."workspace_api_keys" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins can view workspace api keys"
    ON "public"."workspace_api_keys" FOR SELECT
    USING ("public"."is_workspace_admin"("workspace_id"));

CREATE POLICY "Admins can insert workspace api keys"
    ON "public"."workspace_api_keys" FOR INSERT
    WITH CHECK ("public"."is_workspace_admin"("workspace_id"));

CREATE POLICY "Admins can revoke workspace api keys"
    ON "public"."workspace_api_keys" FOR UPDATE
    USING ("public"."is_workspace_admin"("workspace_id"));

CREATE TABLE IF NOT EXISTS "public"."workspace_webhook_subscriptions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "url" "text" NOT NULL,
    "events" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "secret_prefix" "text",
    "secret_hash" "text",
    "is_active" boolean DEFAULT true NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

ALTER TABLE "public"."workspace_webhook_subscriptions" OWNER TO "postgres";

ALTER TABLE ONLY "public"."workspace_webhook_subscriptions"
    ADD CONSTRAINT "workspace_webhook_subscriptions_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."workspace_webhook_subscriptions"
    ADD CONSTRAINT "workspace_webhook_subscriptions_workspace_id_fkey"
    FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS "idx_workspace_webhook_subscriptions_workspace"
    ON "public"."workspace_webhook_subscriptions" USING "btree" ("workspace_id", "is_active");

ALTER TABLE "public"."workspace_webhook_subscriptions" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins can view workspace webhooks"
    ON "public"."workspace_webhook_subscriptions" FOR SELECT
    USING ("public"."is_workspace_admin"("workspace_id"));

CREATE POLICY "Admins can manage workspace webhooks"
    ON "public"."workspace_webhook_subscriptions" FOR ALL
    USING ("public"."is_workspace_admin"("workspace_id"))
    WITH CHECK ("public"."is_workspace_admin"("workspace_id"));

CREATE OR REPLACE TRIGGER "update_workspace_webhook_subscriptions_updated_at"
    BEFORE UPDATE ON "public"."workspace_webhook_subscriptions"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

GRANT ALL ON TABLE "public"."workspace_client_contacts" TO "anon";
GRANT ALL ON TABLE "public"."workspace_client_contacts" TO "authenticated";
GRANT ALL ON TABLE "public"."workspace_client_contacts" TO "service_role";
GRANT ALL ON TABLE "public"."project_board_role_presets" TO "anon";
GRANT ALL ON TABLE "public"."project_board_role_presets" TO "authenticated";
GRANT ALL ON TABLE "public"."project_board_role_presets" TO "service_role";
GRANT ALL ON TABLE "public"."project_board_member_permissions" TO "anon";
GRANT ALL ON TABLE "public"."project_board_member_permissions" TO "authenticated";
GRANT ALL ON TABLE "public"."project_board_member_permissions" TO "service_role";
GRANT ALL ON TABLE "public"."project_board_views" TO "anon";
GRANT ALL ON TABLE "public"."project_board_views" TO "authenticated";
GRANT ALL ON TABLE "public"."project_board_views" TO "service_role";
GRANT ALL ON TABLE "public"."workspace_connectors" TO "anon";
GRANT ALL ON TABLE "public"."workspace_connectors" TO "authenticated";
GRANT ALL ON TABLE "public"."workspace_connectors" TO "service_role";
GRANT ALL ON TABLE "public"."workspace_api_keys" TO "anon";
GRANT ALL ON TABLE "public"."workspace_api_keys" TO "authenticated";
GRANT ALL ON TABLE "public"."workspace_api_keys" TO "service_role";
GRANT ALL ON TABLE "public"."workspace_webhook_subscriptions" TO "anon";
GRANT ALL ON TABLE "public"."workspace_webhook_subscriptions" TO "authenticated";
GRANT ALL ON TABLE "public"."workspace_webhook_subscriptions" TO "service_role";
