-- Migration: StarterStack Tables
-- Creates foundational user-facing tables: users, ext_connections, push_subscriptions,
-- user_preferences. Includes PKs, FKs, indexes, RLS policies, triggers, and grants.

-- =============================================================================
-- Functions
-- =============================================================================

CREATE OR REPLACE FUNCTION "public"."update_push_subscription_history_id"("p_subscription_id" "uuid", "p_history_id" "text") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $_$
DECLARE
  v_new BIGINT;
BEGIN
  -- Only proceed if new history_id is numeric
  IF p_history_id IS NULL OR p_history_id !~ '^[0-9]+$' THEN
    RETURN;
  END IF;

  v_new := p_history_id::bigint;

  UPDATE public.push_subscriptions
  SET history_id = CASE
        WHEN history_id IS NULL THEN p_history_id
        WHEN history_id ~ '^[0-9]+$' AND history_id::bigint <= v_new THEN p_history_id
        WHEN history_id !~ '^[0-9]+$' THEN p_history_id
        ELSE history_id
      END,
      updated_at = now()
  WHERE id = p_subscription_id;
END;
$_$;


ALTER FUNCTION "public"."update_push_subscription_history_id"("p_subscription_id" "uuid", "p_history_id" "text") OWNER TO "postgres";

-- =============================================================================
-- Tables
-- =============================================================================

-- users
CREATE TABLE IF NOT EXISTS "public"."users" (
    "id" "uuid" NOT NULL,
    "email" "text" NOT NULL,
    "name" "text",
    "avatar_url" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "onboarding_completed_at" timestamp with time zone
);


ALTER TABLE "public"."users" OWNER TO "postgres";


-- ext_connections
CREATE TABLE IF NOT EXISTS "public"."ext_connections" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "provider_user_id" "text" NOT NULL,
    "provider_email" "text",
    "access_token" "text",
    "refresh_token" "text",
    "token_expires_at" timestamp with time zone,
    "scopes" "jsonb" DEFAULT '[]'::"jsonb",
    "is_active" boolean DEFAULT true,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "last_synced" timestamp with time zone,
    "is_primary" boolean DEFAULT false,
    "account_order" integer DEFAULT 0,
    "delta_link" "text"
);


ALTER TABLE "public"."ext_connections" OWNER TO "postgres";


COMMENT ON COLUMN "public"."ext_connections"."is_primary" IS 'True for the signup account (cannot be removed)';



COMMENT ON COLUMN "public"."ext_connections"."account_order" IS 'Display order in account picker (0 = first)';



COMMENT ON COLUMN "public"."ext_connections"."delta_link" IS 'Microsoft Graph deltaLink for incremental sync. Google uses history_id in push_subscriptions instead.';


-- push_subscriptions
CREATE TABLE IF NOT EXISTS "public"."push_subscriptions" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "ext_connection_id" "uuid",
    "resource_type" "text",
    "channel_id" "text" NOT NULL,
    "resource_id" "text",
    "expiration" timestamp with time zone NOT NULL,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "provider" "text",
    "history_id" "text",
    "sync_token" "text",
    "notification_count" integer DEFAULT 0,
    "last_notification_at" timestamp with time zone,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "client_state" "text"
);


ALTER TABLE "public"."push_subscriptions" OWNER TO "postgres";


COMMENT ON TABLE "public"."push_subscriptions" IS 'Tracks push notification subscriptions (watches) for Gmail, Google Calendar, and Microsoft Graph. Google watches expire after 7 days, Microsoft subscriptions also expire after 7 days (10,080 minutes max).';



COMMENT ON COLUMN "public"."push_subscriptions"."ext_connection_id" IS 'Foreign key to ext_connections table. Links this push subscription to a specific Google OAuth connection.';



COMMENT ON COLUMN "public"."push_subscriptions"."provider" IS 'Provider type: gmail, calendar (Google), or microsoft (Outlook mail/calendar)';



COMMENT ON COLUMN "public"."push_subscriptions"."client_state" IS 'Secret value for Microsoft Graph webhook validation. Sent during subscription creation, verified on each notification.';


-- user_preferences
CREATE TABLE IF NOT EXISTS "public"."user_preferences" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "show_embedded_cards" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "disabled_categories" "text"[] DEFAULT '{}'::"text"[],
    "disabled_tools" "text"[] DEFAULT '{}'::"text"[],
    "always_search_content" boolean DEFAULT true,
    "timezone" "text" DEFAULT 'UTC'::"text"
);


ALTER TABLE "public"."user_preferences" OWNER TO "postgres";


COMMENT ON COLUMN "public"."user_preferences"."disabled_categories" IS 'Array of disabled tool categories (e.g., ["email", "calendar"])';



COMMENT ON COLUMN "public"."user_preferences"."disabled_tools" IS 'Array of disabled individual tools (e.g., ["send_email"])';



COMMENT ON COLUMN "public"."user_preferences"."always_search_content" IS 'When enabled, agent uses Gmail/Outlook native search for email queries';

-- =============================================================================
-- Primary Keys and Unique Constraints
-- =============================================================================

ALTER TABLE ONLY "public"."users"
    ADD CONSTRAINT "users_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ext_connections"
    ADD CONSTRAINT "ext_connections_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ext_connections"
    ADD CONSTRAINT "ext_connections_user_id_provider_provider_user_id_key" UNIQUE ("user_id", "provider", "provider_user_id");



ALTER TABLE ONLY "public"."push_subscriptions"
    ADD CONSTRAINT "push_subscriptions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."push_subscriptions"
    ADD CONSTRAINT "push_subscriptions_user_id_resource_type_channel_id_key" UNIQUE ("user_id", "resource_type", "channel_id");



ALTER TABLE ONLY "public"."user_preferences"
    ADD CONSTRAINT "user_preferences_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_preferences"
    ADD CONSTRAINT "user_preferences_user_id_key" UNIQUE ("user_id");

-- =============================================================================
-- Foreign Keys
-- =============================================================================

-- users.id -> auth.users
ALTER TABLE ONLY "public"."users"
    ADD CONSTRAINT "users_id_fkey" FOREIGN KEY ("id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

-- ext_connections.user_id -> public.users
ALTER TABLE ONLY "public"."ext_connections"
    ADD CONSTRAINT "ext_connections_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE CASCADE;

-- push_subscriptions.user_id -> public.users
ALTER TABLE ONLY "public"."push_subscriptions"
    ADD CONSTRAINT "push_subscriptions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE CASCADE;

-- push_subscriptions.ext_connection_id -> ext_connections
ALTER TABLE ONLY "public"."push_subscriptions"
    ADD CONSTRAINT "push_subscriptions_ext_connection_id_fkey" FOREIGN KEY ("ext_connection_id") REFERENCES "public"."ext_connections"("id") ON DELETE CASCADE;

-- user_preferences.user_id -> auth.users
ALTER TABLE ONLY "public"."user_preferences"
    ADD CONSTRAINT "user_preferences_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

-- =============================================================================
-- Indexes
-- =============================================================================

-- ext_connections indexes
CREATE INDEX "idx_ext_connections_delta_link" ON "public"."ext_connections" USING "btree" ("delta_link") WHERE ("delta_link" IS NOT NULL);

CREATE INDEX "idx_ext_connections_is_active" ON "public"."ext_connections" USING "btree" ("is_active");

CREATE INDEX "idx_ext_connections_last_synced" ON "public"."ext_connections" USING "btree" ("last_synced");

CREATE INDEX "idx_ext_connections_provider" ON "public"."ext_connections" USING "btree" ("provider");

CREATE INDEX "idx_ext_connections_user_id" ON "public"."ext_connections" USING "btree" ("user_id");

CREATE INDEX "idx_ext_connections_user_order" ON "public"."ext_connections" USING "btree" ("user_id", "account_order");

CREATE INDEX "idx_ext_connections_user_primary" ON "public"."ext_connections" USING "btree" ("user_id", "is_primary");

-- push_subscriptions indexes
CREATE INDEX "idx_push_subscriptions_channel_id" ON "public"."push_subscriptions" USING "btree" ("channel_id");

CREATE INDEX "idx_push_subscriptions_expiration" ON "public"."push_subscriptions" USING "btree" ("expiration");

CREATE INDEX "idx_push_subscriptions_is_active" ON "public"."push_subscriptions" USING "btree" ("is_active");

CREATE INDEX "idx_push_subscriptions_provider" ON "public"."push_subscriptions" USING "btree" ("provider");

CREATE INDEX "idx_push_subscriptions_resource_type" ON "public"."push_subscriptions" USING "btree" ("resource_type");

CREATE INDEX "idx_push_subscriptions_user_id" ON "public"."push_subscriptions" USING "btree" ("user_id");

-- user_preferences indexes
CREATE INDEX "idx_user_preferences_user_id" ON "public"."user_preferences" USING "btree" ("user_id");

-- =============================================================================
-- Enable Row Level Security
-- =============================================================================

ALTER TABLE "public"."users" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."ext_connections" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."push_subscriptions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."user_preferences" ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- RLS Policies
-- =============================================================================

-- users policies
CREATE POLICY "Users can insert own data" ON "public"."users" FOR INSERT WITH CHECK ((( SELECT "auth"."uid"() AS "uid") = "id"));

CREATE POLICY "Users can view own data" ON "public"."users" FOR SELECT USING ((( SELECT "auth"."uid"() AS "uid") = "id"));

CREATE POLICY "Users can update own data" ON "public"."users" FOR UPDATE USING ((( SELECT "auth"."uid"() AS "uid") = "id"));

CREATE POLICY "Authenticated users can lookup other users" ON "public"."users" FOR SELECT TO "authenticated" USING (true);

-- ext_connections policies
CREATE POLICY "Users can insert own connections" ON "public"."ext_connections" FOR INSERT WITH CHECK ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

CREATE POLICY "Users can view own connections" ON "public"."ext_connections" FOR SELECT USING ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

CREATE POLICY "Users can update own connections" ON "public"."ext_connections" FOR UPDATE USING ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

CREATE POLICY "Users can delete own connections" ON "public"."ext_connections" FOR DELETE USING ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

-- push_subscriptions policies
CREATE POLICY "Users can insert own subscriptions" ON "public"."push_subscriptions" FOR INSERT WITH CHECK ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

CREATE POLICY "Users can view own subscriptions" ON "public"."push_subscriptions" FOR SELECT USING ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

CREATE POLICY "Users can update own subscriptions" ON "public"."push_subscriptions" FOR UPDATE USING ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

CREATE POLICY "Users can delete own subscriptions" ON "public"."push_subscriptions" FOR DELETE USING ((( SELECT "auth"."uid"() AS "uid") = "user_id"));

-- user_preferences policies
CREATE POLICY "Users can insert own preferences" ON "public"."user_preferences" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));

CREATE POLICY "Users can view own preferences" ON "public"."user_preferences" FOR SELECT USING (("auth"."uid"() = "user_id"));

CREATE POLICY "Users can update own preferences" ON "public"."user_preferences" FOR UPDATE USING (("auth"."uid"() = "user_id"));

-- =============================================================================
-- Triggers
-- =============================================================================

CREATE OR REPLACE TRIGGER "update_users_updated_at" BEFORE UPDATE ON "public"."users" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

CREATE OR REPLACE TRIGGER "update_ext_connections_updated_at" BEFORE UPDATE ON "public"."ext_connections" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

CREATE OR REPLACE TRIGGER "update_push_subscriptions_updated_at" BEFORE UPDATE ON "public"."push_subscriptions" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

CREATE OR REPLACE TRIGGER "update_user_preferences_updated_at" BEFORE UPDATE ON "public"."user_preferences" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();

-- =============================================================================
-- GRANTs
-- =============================================================================

-- Table grants
GRANT ALL ON TABLE "public"."users" TO "anon";
GRANT ALL ON TABLE "public"."users" TO "authenticated";
GRANT ALL ON TABLE "public"."users" TO "service_role";

GRANT ALL ON TABLE "public"."ext_connections" TO "anon";
GRANT ALL ON TABLE "public"."ext_connections" TO "authenticated";
GRANT ALL ON TABLE "public"."ext_connections" TO "service_role";

GRANT ALL ON TABLE "public"."push_subscriptions" TO "anon";
GRANT ALL ON TABLE "public"."push_subscriptions" TO "authenticated";
GRANT ALL ON TABLE "public"."push_subscriptions" TO "service_role";

GRANT ALL ON TABLE "public"."user_preferences" TO "anon";
GRANT ALL ON TABLE "public"."user_preferences" TO "authenticated";
GRANT ALL ON TABLE "public"."user_preferences" TO "service_role";

-- Function grants
GRANT ALL ON FUNCTION "public"."update_push_subscription_history_id"("p_subscription_id" "uuid", "p_history_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."update_push_subscription_history_id"("p_subscription_id" "uuid", "p_history_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_push_subscription_history_id"("p_subscription_id" "uuid", "p_history_id" "text") TO "service_role";
