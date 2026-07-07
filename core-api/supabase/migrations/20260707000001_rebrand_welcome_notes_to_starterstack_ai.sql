-- Rebrand default workspace welcome notes created before the StarterStack.ai rename.
-- This intentionally targets only the stock welcome note shape so user-created
-- or substantially customized documents are not overwritten.

WITH starterstack_ai_welcome AS (
    SELECT
        E'## What is StarterStack.ai?\n\nStarterStack.ai is an all-in-one productivity workspace that brings together your email, calendar, projects, files, and team messaging — all powered by an AI agent that helps you get things done faster.\n\nThink of it as your unified hub for work — where everything connects and your AI assistant (the StarterStack.ai Agent) understands your full context.\n\n## StarterStack.ai Features\n\n- **Messaging** — Team channels for real-time discussions\n- **Projects Board** — Organize and track your work with a visual project board\n- **Files** — Upload, manage, and organize your files — including docs and notes that live right inside your file system\n- **Email** — Search, read, and send emails right from StarterStack.ai\n- **Calendar** — View, create, and manage your events\n- **StarterStack.ai Agent** — An AI assistant that can search across all your data, answer questions, and take actions on your behalf\n\n## Getting Started\n\n1. **Set up your workspace** — Create or join a workspace to get started\n2. **Connect your accounts** — Link your email and calendar for the full experience\n3. **Explore your files** — Create docs, upload files, and keep everything organized in one place\n4. **Try the AI agent** — Ask it anything about your emails, calendar, projects, or files\n5. **Invite your team** — Add teammates to collaborate in channels and shared workspaces\n\n## Platforms\n\n- **Web app** — Available now\n- **Desktop app** — Coming soon\n- **Mobile app** — Coming soon\n\n## Need Help?\n\nThe StarterStack.ai Agent is always here to help! Just ask it questions about your workspace, find information, or get things done.\n\nWelcome aboard — let''s build something great together!'::text AS content
)
UPDATE public.documents AS d
SET
    title = 'Welcome to StarterStack.ai!',
    content = starterstack_ai_welcome.content
FROM starterstack_ai_welcome
WHERE d.type = 'note'
  AND d.title IN (
      'Welcome to Core!',
      'Welcome to StarterStack!',
      'Welcome to StarterStack.ai!'
  )
  AND (
      d.content ILIKE '%What is Core?%'
      OR d.content ILIKE '%Core Features%'
      OR d.content ILIKE '%Core Agent%'
      OR d.content ILIKE '%What is StarterStack?%'
      OR d.content ILIKE '%StarterStack Features%'
      OR d.content ILIKE '%StarterStack Agent%'
  )
  AND (
      d.title <> 'Welcome to StarterStack.ai!'
      OR d.content NOT ILIKE '%StarterStack.ai%'
  );
