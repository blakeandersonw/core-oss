"""Resend client for transactional emails."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence

import httpx

from api.config import settings

logger = logging.getLogger(__name__)

RESEND_SEND_EMAIL_URL = "https://api.resend.com/emails"


def _escape_html(value: str) -> str:
    """Basic HTML escaping for user-provided strings in email templates."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _frontend_base_url() -> str:
    frontend_base = settings.frontend_url.rstrip("/")
    if not frontend_base:
        raise ValueError("FRONTEND_URL is not configured")
    return frontend_base


async def _send_email(to: str, subject: str, html: str, text: str) -> str:
    """Send a single transactional email through Resend."""
    if not settings.resend_api_key:
        raise ValueError("RESEND_API_KEY is not configured")

    from_address = settings.resend_from_address
    if not from_address:
        raise ValueError("RESEND_FROM_EMAIL or RESEND_FROM_DOMAIN must be configured")

    payload = {
        "from": from_address,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }

    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(RESEND_SEND_EMAIL_URL, json=payload, headers=headers)

    if response.status_code >= 400:
        error_text: Optional[str]
        try:
            error_text = response.json().get("message")
        except Exception:
            error_text = response.text
        logger.error("Resend send failed (status=%s): %s", response.status_code, error_text)
        raise ValueError(error_text or f"Resend request failed with status {response.status_code}")

    data = response.json()
    provider_id = data.get("id")
    if not provider_id:
        raise ValueError("Resend response missing message id")

    return provider_id


def _build_invite_html(
    inviter_name: str,
    workspace_name: str,
    role: str,
    invite_url: str,
) -> str:
    safe_inviter = _escape_html(inviter_name)
    safe_workspace = _escape_html(workspace_name)
    safe_role = _escape_html(role)
    safe_url = _escape_html(invite_url)

    return f"""
<html>
  <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f6f7fb; margin: 0; padding: 24px;\">
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"560\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width: 560px; background: #ffffff; border-radius: 12px; padding: 28px;\">
            <tr>
              <td>
                <h2 style=\"margin: 0 0 12px; color: #111827;\">Workspace invitation</h2>
                <p style=\"margin: 0 0 10px; color: #374151; line-height: 1.5;\">
                  <strong>{safe_inviter}</strong> invited you to join <strong>{safe_workspace}</strong> as <strong>{safe_role}</strong>.
                </p>
                <p style=\"margin: 0 0 20px; color: #6b7280; line-height: 1.5;\">
                  This invitation expires in 14 days.
                </p>
                <p style=\"margin: 0 0 20px;\">
                  <a href=\"{safe_url}\" style=\"display: inline-block; background: #111827; color: #ffffff; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 600;\">Accept invitation</a>
                </p>
                <p style=\"margin: 0; color: #6b7280; font-size: 13px; word-break: break-all;\">
                  If the button does not work, open this link:<br />
                  <a href=\"{safe_url}\" style=\"color: #2563eb; text-decoration: none;\">{safe_url}</a>
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


def _build_invite_text(
    inviter_name: str,
    workspace_name: str,
    role: str,
    invite_url: str,
) -> str:
    return (
        f"{inviter_name} invited you to join {workspace_name} as {role}.\n\n"
        "This invitation expires in 14 days.\n\n"
        f"Accept invitation: {invite_url}"
    )


def _email_shell(title: str, inner_html: str) -> str:
    safe_title = _escape_html(title)
    return f"""
<html>
  <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f6f7fb; margin: 0; padding: 24px;\">
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"560\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width: 560px; background: #ffffff; border-radius: 12px; padding: 28px;\">
            <tr>
              <td>
                <h2 style=\"margin: 0 0 12px; color: #111827;\">{safe_title}</h2>
                {inner_html}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


def _build_notification_html(
    recipient_name: str,
    title: str,
    body: Optional[str],
    action_url: str,
    actor_name: Optional[str],
    category: Optional[str],
) -> str:
    safe_recipient = _escape_html(recipient_name or "there")
    safe_body = _escape_html(body or "")
    safe_url = _escape_html(action_url)
    safe_actor = _escape_html(actor_name or "Core")
    safe_category = _escape_html(category or "notification")
    prefs_url = _escape_html(f"{_frontend_base_url()}/settings/notifications")

    body_html = (
        f"<p style=\"margin: 0 0 20px; color: #374151; line-height: 1.5;\">{safe_body}</p>"
        if safe_body
        else ""
    )

    return _email_shell(
        title,
        f"""
                <p style=\"margin: 0 0 10px; color: #374151; line-height: 1.5;\">Hi {safe_recipient},</p>
                {body_html}
                <p style=\"margin: 0 0 20px;\">
                  <a href=\"{safe_url}\" style=\"display: inline-block; background: #111827; color: #ffffff; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 600;\">Open in Core</a>
                </p>
                <p style=\"margin: 0 0 8px; color: #6b7280; font-size: 13px; word-break: break-all;\">
                  If the button does not work, open this link:<br />
                  <a href=\"{safe_url}\" style=\"color: #2563eb; text-decoration: none;\">{safe_url}</a>
                </p>
                <p style=\"margin: 18px 0 0; color: #9ca3af; font-size: 12px; line-height: 1.5;\">
                  Sent because {safe_actor} triggered a {safe_category} notification.
                  Manage preferences at <a href=\"{prefs_url}\" style=\"color: #6b7280;\">notification settings</a>.
                </p>
""",
    )


def _build_notification_text(
    title: str,
    body: Optional[str],
    action_url: str,
    actor_name: Optional[str],
    category: Optional[str],
) -> str:
    lines = [title]
    if body:
        lines.extend(["", body])
    lines.extend(
        [
            "",
            f"Open in Core: {action_url}",
            "",
            f"Sent because {actor_name or 'Core'} triggered a {category or 'notification'} notification.",
            f"Manage notification preferences: {_frontend_base_url()}/settings/notifications",
        ]
    )
    return "\n".join(lines)


def _build_digest_html(
    recipient_name: str,
    grouped_items: Sequence[Mapping[str, Any]],
    manage_preferences_url: str,
) -> str:
    safe_recipient = _escape_html(recipient_name or "there")
    safe_prefs_url = _escape_html(manage_preferences_url)
    groups_html = []

    for group in grouped_items:
        workspace_name = _escape_html(str(group.get("workspace_name") or "Workspace"))
        items = group.get("items") or []
        item_html = []
        for item in items:
            title = _escape_html(str(item.get("title") or "Notification"))
            body = _escape_html(str(item.get("body") or ""))
            action_url = _escape_html(str(item.get("action_url") or _frontend_base_url()))
            body_fragment = (
                f"<div style=\"margin-top: 4px; color: #6b7280; line-height: 1.4;\">{body}</div>"
                if body
                else ""
            )
            item_html.append(
                f"""
                  <li style=\"margin: 0 0 14px; padding: 0;\">
                    <a href=\"{action_url}\" style=\"color: #111827; font-weight: 600; text-decoration: none;\">{title}</a>
                    {body_fragment}
                  </li>
""".rstrip()
            )

        groups_html.append(
            f"""
                <h3 style=\"margin: 22px 0 10px; color: #111827; font-size: 15px;\">{workspace_name}</h3>
                <ul style=\"margin: 0; padding-left: 18px; color: #374151; font-size: 14px;\">
                  {''.join(item_html)}
                </ul>
""".rstrip()
        )

    return _email_shell(
        "Core notification digest",
        f"""
                <p style=\"margin: 0 0 10px; color: #374151; line-height: 1.5;\">Hi {safe_recipient},</p>
                <p style=\"margin: 0 0 8px; color: #6b7280; line-height: 1.5;\">Here is what changed in your workspaces.</p>
                {''.join(groups_html)}
                <p style=\"margin: 22px 0 0; color: #9ca3af; font-size: 12px; line-height: 1.5;\">
                  Manage preferences at <a href=\"{safe_prefs_url}\" style=\"color: #6b7280;\">notification settings</a>.
                </p>
""",
    )


def _build_digest_text(
    grouped_items: Sequence[Mapping[str, Any]],
    manage_preferences_url: str,
) -> str:
    lines = ["Core notification digest", ""]
    for group in grouped_items:
        lines.append(str(group.get("workspace_name") or "Workspace"))
        for item in group.get("items") or []:
            lines.append(f"- {item.get('title') or 'Notification'}")
            if item.get("body"):
                lines.append(f"  {item['body']}")
            if item.get("action_url"):
                lines.append(f"  {item['action_url']}")
        lines.append("")
    lines.append(f"Manage notification preferences: {manage_preferences_url}")
    return "\n".join(lines).strip()


async def send_workspace_invitation_email(
    recipient_email: str,
    inviter_name: str,
    workspace_name: str,
    role: str,
    token: str,
) -> str:
    """Send a workspace invitation email via Resend.

    Returns provider message id on success.
    Raises ValueError if sending fails.
    """
    frontend_base = _frontend_base_url()

    invite_url = f"{frontend_base}/invite/{token}"
    subject = f"{inviter_name} invited you to join {workspace_name}"

    return await _send_email(
        to=recipient_email,
        subject=subject,
        html=_build_invite_html(inviter_name, workspace_name, role, invite_url),
        text=_build_invite_text(inviter_name, workspace_name, role, invite_url),
    )


async def send_notification_email(
    recipient_email: str,
    recipient_name: str,
    title: str,
    body: Optional[str],
    action_url: str,
    actor_name: Optional[str],
    category: Optional[str],
) -> str:
    """Send a single real-time notification email."""
    return await _send_email(
        to=recipient_email,
        subject=title,
        html=_build_notification_html(
            recipient_name=recipient_name,
            title=title,
            body=body,
            action_url=action_url,
            actor_name=actor_name,
            category=category,
        ),
        text=_build_notification_text(
            title=title,
            body=body,
            action_url=action_url,
            actor_name=actor_name,
            category=category,
        ),
    )


async def send_digest_email(
    recipient_email: str,
    recipient_name: str,
    grouped_items: Sequence[Mapping[str, Any]],
    manage_preferences_url: str,
) -> str:
    """Send a grouped notification digest email."""
    return await _send_email(
        to=recipient_email,
        subject="Core notification digest",
        html=_build_digest_html(
            recipient_name=recipient_name,
            grouped_items=grouped_items,
            manage_preferences_url=manage_preferences_url,
        ),
        text=_build_digest_text(grouped_items, manage_preferences_url),
    )
