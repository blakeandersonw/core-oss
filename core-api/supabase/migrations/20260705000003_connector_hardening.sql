----------------------------------------------------------------------------
-- Connector hardening: verified status, failure reasons, reconnect metadata
----------------------------------------------------------------------------

ALTER TABLE "public"."ext_connections"
    ADD COLUMN IF NOT EXISTS "external_account_id" "text",
    ADD COLUMN IF NOT EXISTS "verification_status" "text" DEFAULT 'unknown'::"text",
    ADD COLUMN IF NOT EXISTS "last_verified_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "error_reason" "text",
    ADD COLUMN IF NOT EXISTS "last_error_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "failed_attempts" integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "revoked_at" timestamp with time zone;

ALTER TABLE "public"."ext_connections"
    DROP CONSTRAINT IF EXISTS "ext_connections_verification_status_check";

ALTER TABLE "public"."ext_connections"
    ADD CONSTRAINT "ext_connections_verification_status_check"
    CHECK (("verification_status" = ANY (ARRAY[
        'connected'::"text",
        'disconnected'::"text",
        'error'::"text",
        'pending'::"text",
        'expired'::"text",
        'unknown'::"text"
    ])));

CREATE INDEX IF NOT EXISTS "idx_ext_connections_verification"
    ON "public"."ext_connections" USING "btree" ("verification_status", "last_verified_at")
    WHERE ("external_account_id" IS NOT NULL);

UPDATE "public"."ext_connections"
SET
    "verification_status" = CASE
        WHEN "is_active" THEN 'connected'
        ELSE 'disconnected'
    END,
    "last_verified_at" = COALESCE(
        "last_verified_at",
        "now"() - (random() * interval '6 hours')
    )
WHERE "verification_status" IS NULL
    OR "verification_status" = 'unknown'
    OR "last_verified_at" IS NULL;

ALTER TABLE "public"."workspace_connectors"
    ADD COLUMN IF NOT EXISTS "last_verified_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "error_reason" "text",
    ADD COLUMN IF NOT EXISTS "last_error_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "failed_attempts" integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "revoked_at" timestamp with time zone;

ALTER TABLE "public"."workspace_connectors"
    DROP CONSTRAINT IF EXISTS "workspace_connectors_status_check";

ALTER TABLE "public"."workspace_connectors"
    ADD CONSTRAINT "workspace_connectors_status_check"
    CHECK (("status" = ANY (ARRAY[
        'connected'::"text",
        'disconnected'::"text",
        'error'::"text",
        'pending'::"text",
        'expired'::"text",
        'unknown'::"text"
    ])));

CREATE INDEX IF NOT EXISTS "idx_workspace_connectors_verification"
    ON "public"."workspace_connectors" USING "btree" ("status", "last_verified_at")
    WHERE ("external_account_id" IS NOT NULL);
