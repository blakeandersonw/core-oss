-- Migration: Super Admin Access
-- Adds a small allowlist for global admins and wires workspace helper
-- functions to treat those users as workspace owners/admins.

CREATE TABLE IF NOT EXISTS "public"."super_admins" (
    "email" "text" PRIMARY KEY,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);

ALTER TABLE "public"."super_admins" OWNER TO "postgres";

-- Add super admins explicitly per deployment, for example:
-- INSERT INTO "public"."super_admins" ("email")
-- VALUES ('owner@example.com')
-- ON CONFLICT ("email") DO NOTHING;

ALTER TABLE "public"."super_admins" ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION "public"."is_super_admin"("p_user_id" "uuid" DEFAULT "auth"."uid"()) RETURNS boolean
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
        SELECT EXISTS (
            SELECT 1
            FROM public.users u
            JOIN public.super_admins sa ON lower(sa.email) = lower(u.email)
            WHERE u.id = p_user_id
        );
    $$;

ALTER FUNCTION "public"."is_super_admin"("p_user_id" "uuid") OWNER TO "postgres";

DROP POLICY IF EXISTS "Super admins can view super admin allowlist" ON "public"."super_admins";
CREATE POLICY "Super admins can view super admin allowlist"
    ON "public"."super_admins"
    FOR SELECT
    USING ("public"."is_super_admin"());

CREATE OR REPLACE FUNCTION "public"."is_workspace_member"("p_workspace_id" "uuid", "p_user_id" "uuid" DEFAULT "auth"."uid"()) RETURNS boolean
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
    IF public.is_super_admin(p_user_id) THEN
        RETURN TRUE;
    END IF;

    RETURN EXISTS (
        SELECT 1 FROM workspace_members
        WHERE workspace_id = p_workspace_id
        AND user_id = p_user_id
    );
END;
$$;

CREATE OR REPLACE FUNCTION "public"."is_workspace_admin"("p_workspace_id" "uuid", "p_user_id" "uuid" DEFAULT "auth"."uid"()) RETURNS boolean
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
    IF public.is_super_admin(p_user_id) THEN
        RETURN TRUE;
    END IF;

    RETURN EXISTS (
        SELECT 1 FROM workspace_members
        WHERE workspace_id = p_workspace_id
        AND user_id = p_user_id
        AND role IN ('owner', 'admin')
    );
END;
$$;

CREATE OR REPLACE FUNCTION "public"."is_workspace_owner"("p_workspace_id" "uuid", "p_user_id" "uuid" DEFAULT "auth"."uid"()) RETURNS boolean
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
    IF public.is_super_admin(p_user_id) THEN
        RETURN TRUE;
    END IF;

    RETURN EXISTS (
        SELECT 1 FROM workspace_members
        WHERE workspace_id = p_workspace_id
        AND user_id = p_user_id
        AND role = 'owner'
    );
END;
$$;

CREATE OR REPLACE FUNCTION "public"."get_workspace_role"("p_workspace_id" "uuid", "p_user_id" "uuid" DEFAULT "auth"."uid"()) RETURNS "public"."workspace_role"
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_role workspace_role;
BEGIN
    IF public.is_super_admin(p_user_id) THEN
        RETURN 'owner'::workspace_role;
    END IF;

    SELECT role INTO v_role
    FROM workspace_members
    WHERE workspace_id = p_workspace_id
    AND user_id = p_user_id;

    RETURN v_role;
END;
$$;

GRANT ALL ON TABLE "public"."super_admins" TO "service_role";
GRANT SELECT ON TABLE "public"."super_admins" TO "authenticated";
GRANT EXECUTE ON FUNCTION "public"."is_super_admin"("p_user_id" "uuid") TO "anon";
GRANT EXECUTE ON FUNCTION "public"."is_super_admin"("p_user_id" "uuid") TO "authenticated";
GRANT EXECUTE ON FUNCTION "public"."is_super_admin"("p_user_id" "uuid") TO "service_role";
