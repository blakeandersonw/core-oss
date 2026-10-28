-- Wrap each unwrapped auth.* call (USING + WITH CHECK, including calls
-- nested inside EXISTS/IN subqueries) in (select ...) so Postgres evaluates
-- each once per statement (InitPlan) instead of once per row -- the
-- Supabase-documented RLS perf pattern. Predicate-equivalent (row visibility
-- unchanged). Already-wrapped calls are left as-is. Refs #50.

ALTER POLICY "Share managers can update requests" ON public.access_requests
    USING (can_manage_shares((select auth.uid()), resource_type, resource_id));

ALTER POLICY "Users can create access requests" ON public.access_requests
    WITH CHECK ((requester_id = (select auth.uid())));

ALTER POLICY "Users can view own requests or requests they manage" ON public.access_requests
    USING (((requester_id = (select auth.uid())) OR can_manage_shares((select auth.uid()), resource_type, resource_id)));

ALTER POLICY "Users can create conversations in their workspaces" ON public.agent_conversations
    WITH CHECK (((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE (wm.user_id = (select auth.uid())))) AND (created_by = (select auth.uid()))));

ALTER POLICY "Users can delete their own conversations" ON public.agent_conversations
    USING ((created_by = (select auth.uid())));

ALTER POLICY "Users can update conversations in their workspaces" ON public.agent_conversations
    USING ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE (wm.user_id = (select auth.uid())))));

ALTER POLICY "Users can view conversations in their workspaces" ON public.agent_conversations
    USING ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE (wm.user_id = (select auth.uid())))));

ALTER POLICY "Users can view agents in their workspaces" ON public.agent_instances
    USING ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE (wm.user_id = (select auth.uid())))));

ALTER POLICY "Workspace admins can delete agents" ON public.agent_instances
    USING ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE ((wm.user_id = (select auth.uid())) AND (wm.role = ANY (ARRAY['owner'::workspace_role, 'admin'::workspace_role]))))));

ALTER POLICY "Workspace admins can insert agents" ON public.agent_instances
    WITH CHECK ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE ((wm.user_id = (select auth.uid())) AND (wm.role = ANY (ARRAY['owner'::workspace_role, 'admin'::workspace_role]))))));

ALTER POLICY "Workspace admins can update agents" ON public.agent_instances
    USING ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE ((wm.user_id = (select auth.uid())) AND (wm.role = ANY (ARRAY['owner'::workspace_role, 'admin'::workspace_role]))))));

ALTER POLICY "Users can view steps in their workspaces" ON public.agent_task_steps
    USING ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE (wm.user_id = (select auth.uid())))));

ALTER POLICY "Users can create tasks in their workspaces" ON public.agent_tasks
    WITH CHECK ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE (wm.user_id = (select auth.uid())))));

ALTER POLICY "Users can view tasks in their workspaces" ON public.agent_tasks
    USING ((workspace_id IN ( SELECT wm.workspace_id FROM workspace_members wm WHERE (wm.user_id = (select auth.uid())))));

ALTER POLICY "builder_conversations_delete" ON public.builder_conversations
    USING ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_conversations.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_conversations_insert" ON public.builder_conversations
    WITH CHECK ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_conversations.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_conversations_select" ON public.builder_conversations
    USING ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_conversations.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_deployments_insert" ON public.builder_deployments
    WITH CHECK ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_deployments.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_deployments_select" ON public.builder_deployments
    USING ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_deployments.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_deployments_update" ON public.builder_deployments
    USING ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_deployments.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_messages_insert" ON public.builder_messages
    WITH CHECK ((EXISTS ( SELECT 1 FROM (builder_conversations bc JOIN builder_projects bp ON ((bp.id = bc.project_id))) WHERE ((bc.id = builder_messages.conversation_id) AND (bp.user_id = (select auth.uid()))))));

ALTER POLICY "builder_messages_select" ON public.builder_messages
    USING ((EXISTS ( SELECT 1 FROM (builder_conversations bc JOIN builder_projects bp ON ((bp.id = bc.project_id))) WHERE ((bc.id = builder_messages.conversation_id) AND (bp.user_id = (select auth.uid()))))));

ALTER POLICY "builder_projects_delete" ON public.builder_projects
    USING (((select auth.uid()) = user_id));

ALTER POLICY "builder_projects_insert" ON public.builder_projects
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "builder_projects_select" ON public.builder_projects
    USING (((select auth.uid()) = user_id));

ALTER POLICY "builder_projects_update" ON public.builder_projects
    USING (((select auth.uid()) = user_id));

ALTER POLICY "builder_versions_delete" ON public.builder_versions
    USING ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_versions.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_versions_insert" ON public.builder_versions
    WITH CHECK ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_versions.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "builder_versions_select" ON public.builder_versions
    USING ((EXISTS ( SELECT 1 FROM builder_projects WHERE ((builder_projects.id = builder_versions.project_id) AND (builder_projects.user_id = (select auth.uid()))))));

ALTER POLICY "Channel members can view members" ON public.channel_members
    USING (can_access_channel(channel_id, (select auth.uid())));

ALTER POLICY "Channel owners can add members" ON public.channel_members
    WITH CHECK (((EXISTS ( SELECT 1 FROM channel_members cm WHERE ((cm.channel_id = channel_members.channel_id) AND (cm.user_id = (select auth.uid())) AND (cm.role = ANY (ARRAY['owner'::text, 'moderator'::text]))))) OR (EXISTS ( SELECT 1 FROM channels c WHERE ((c.id = channel_members.channel_id) AND (c.created_by = (select auth.uid())))))));

ALTER POLICY "Channel owners can remove members" ON public.channel_members
    USING (((user_id = (select auth.uid())) OR (EXISTS ( SELECT 1 FROM channel_members cm WHERE ((cm.channel_id = channel_members.channel_id) AND (cm.user_id = (select auth.uid())) AND (cm.role = ANY (ARRAY['owner'::text, 'moderator'::text])))))));

ALTER POLICY "Users can delete their own read status" ON public.channel_read_status
    USING ((user_id = (select auth.uid())));

ALTER POLICY "Users can modify their own read status" ON public.channel_read_status
    USING ((user_id = (select auth.uid())));

ALTER POLICY "Users can update their own read status" ON public.channel_read_status
    WITH CHECK ((user_id = (select auth.uid())));

ALTER POLICY "Users can view their own read status" ON public.channel_read_status
    USING ((user_id = (select auth.uid())));

ALTER POLICY "Channel creators can delete channels" ON public.channels
    USING (((created_by = (select auth.uid())) OR is_workspace_admin(( SELECT workspace_apps.workspace_id FROM workspace_apps WHERE (workspace_apps.id = channels.workspace_app_id)), (select auth.uid()))));

ALTER POLICY "Channel creators can update channels" ON public.channels
    USING (((created_by = (select auth.uid())) OR is_workspace_admin(( SELECT workspace_apps.workspace_id FROM workspace_apps WHERE (workspace_apps.id = channels.workspace_app_id)), (select auth.uid()))));

ALTER POLICY "Users can view accessible channels" ON public.channels
    USING ((can_access_workspace_app(workspace_app_id, (select auth.uid())) AND (((is_dm = false) AND (is_private = false)) OR ((is_private = true) AND (is_dm = false) AND ((created_by = (select auth.uid())) OR (EXISTS ( SELECT 1 FROM channel_members WHERE ((channel_members.channel_id = channels.id) AND (channel_members.user_id = (select auth.uid()))))))) OR ((is_dm = true) AND ((select auth.uid()) = ANY (dm_participants))))));

ALTER POLICY "Workspace members can create channels" ON public.channels
    WITH CHECK ((can_access_workspace_app(workspace_app_id, (select auth.uid())) AND (created_by = (select auth.uid()))));

ALTER POLICY "Users can delete their own attachments" ON public.chat_attachments
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can insert their own attachments" ON public.chat_attachments
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "Users can update their own attachments" ON public.chat_attachments
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can view their own attachments" ON public.chat_attachments
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Owner or admin can delete files" ON public.files
    USING ((((select auth.uid()) = user_id) OR ((workspace_id IS NOT NULL) AND is_workspace_admin(workspace_id))));

ALTER POLICY "Users can upload files in accessible workspaces" ON public.files
    WITH CHECK ((((select auth.uid()) = user_id) AND ((workspace_app_id IS NULL) OR can_access_workspace_app(workspace_app_id))));

ALTER POLICY "Users can insert own relationships" ON public.memory_relationships
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "Users can update own relationships" ON public.memory_relationships
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can view own relationships" ON public.memory_relationships
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can remove their own reactions" ON public.message_reactions
    USING ((user_id = (select auth.uid())));

ALTER POLICY "Users can manage own preferences" ON public.notification_preferences
    USING (((select auth.uid()) = user_id))
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "Users can manage own subscriptions" ON public.notification_subscriptions
    USING (((select auth.uid()) = user_id))
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "Users can read own subscriptions" ON public.notification_subscriptions
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can read own notifications" ON public.notifications
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can update own notifications" ON public.notifications
    USING (((select auth.uid()) = user_id))
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "Share managers can create permissions" ON public.permissions
    WITH CHECK (can_manage_shares((select auth.uid()), resource_type, resource_id));

ALTER POLICY "Share managers can delete permissions" ON public.permissions
    USING (can_manage_shares((select auth.uid()), resource_type, resource_id));

ALTER POLICY "Share managers can update permissions" ON public.permissions
    USING (can_manage_shares((select auth.uid()), resource_type, resource_id));

ALTER POLICY "Users can view permissions they manage or own grants" ON public.permissions
    USING ((can_manage_shares((select auth.uid()), resource_type, resource_id) OR ((grantee_type = 'user'::text) AND (grantee_id = (select auth.uid())))));

ALTER POLICY "Creator or admin can delete boards" ON public.project_boards
    USING (((created_by = (select auth.uid())) OR is_workspace_admin(workspace_id)));

ALTER POLICY "Members can create boards in accessible workspace apps" ON public.project_boards
    WITH CHECK ((can_access_workspace_app(workspace_app_id) AND ((created_by IS NULL) OR (created_by = (select auth.uid())))));

ALTER POLICY "Members can add comment reactions" ON public.project_comment_reactions
    WITH CHECK ((can_access_workspace_app(workspace_app_id) AND (user_id = (select auth.uid()))));

ALTER POLICY "Users can remove their own comment reactions" ON public.project_comment_reactions
    USING ((user_id = (select auth.uid())));

ALTER POLICY "Author or admin can delete comments" ON public.project_issue_comments
    USING (((user_id = (select auth.uid())) OR is_workspace_admin(workspace_id)));

ALTER POLICY "Members can create comments in accessible workspace apps" ON public.project_issue_comments
    WITH CHECK ((can_access_workspace_app(workspace_app_id) AND (user_id = (select auth.uid()))));

ALTER POLICY "Users can edit their own comments" ON public.project_issue_comments
    USING ((user_id = (select auth.uid())));

ALTER POLICY "Creator or admin can delete issues" ON public.project_issues
    USING (((created_by = (select auth.uid())) OR is_workspace_admin(workspace_id)));

ALTER POLICY "Members can create issues in accessible workspace apps" ON public.project_issues
    WITH CHECK ((can_access_workspace_app(workspace_app_id) AND (created_by = (select auth.uid()))));

ALTER POLICY "Users can insert own memory" ON public.user_memory
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "Users can update own memory" ON public.user_memory
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can view own memory" ON public.user_memory
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can insert own preferences" ON public.user_preferences
    WITH CHECK (((select auth.uid()) = user_id));

ALTER POLICY "Users can update own preferences" ON public.user_preferences
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Users can view own preferences" ON public.user_preferences
    USING (((select auth.uid()) = user_id));

ALTER POLICY "Service role can manage workspace invitations" ON public.workspace_invitations
    USING (((select auth.role()) = 'service_role'::text))
    WITH CHECK (((select auth.role()) = 'service_role'::text));

ALTER POLICY "Members and shared users can view workspace" ON public.workspaces
    USING ((is_workspace_member(id) OR (EXISTS ( SELECT 1 FROM permissions WHERE ((permissions.workspace_id = workspaces.id) AND (permissions.grantee_type = 'user'::text) AND (permissions.grantee_id = (select auth.uid())))))));

ALTER POLICY "Users can create workspaces" ON public.workspaces
    WITH CHECK (((select auth.uid()) = owner_id));
