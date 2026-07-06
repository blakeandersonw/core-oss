"""Versioned attachments for project issues."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from api.config import settings
from api.services.projects.access import enforce_issue_not_locked, get_issue_context
from lib.filename_utils import sanitize_filename
from lib.r2_client import get_r2_client
from lib.supabase_client import get_authenticated_async_client


ALLOWED_ATTACHMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
    "text/csv",
    "application/json",
    "application/octet-stream",
    "application/zip",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _validate_attachment(filename: str, content_type: str, file_size: int) -> str:
    safe_filename = sanitize_filename(filename)
    if not safe_filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported attachment content type")
    if file_size <= 0 or file_size > settings.r2_max_file_size:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Attachment size is not allowed")
    return safe_filename


async def initiate_attachment_upload(
    *,
    user_id: str,
    user_jwt: str,
    issue_id: str,
    filename: str,
    content_type: str,
    file_size: int,
) -> Dict[str, Any]:
    safe_filename = _validate_attachment(filename, content_type, file_size)
    supabase = await get_authenticated_async_client(user_jwt)
    issue = await get_issue_context(supabase, issue_id)
    await enforce_issue_not_locked(
        supabase,
        issue=issue,
        user_id=user_id,
        board_id=issue["board_id"],
    )

    r2_client = get_r2_client()
    r2_key = r2_client.generate_key_for_context(user_id, safe_filename, context="projects")
    presigned = r2_client.generate_presigned_put_url(r2_key, content_type)
    return {
        "upload_url": presigned["url"],
        "r2_key": r2_key,
        "expires_at": presigned["expires_at"],
        "headers": {"Content-Type": content_type},
    }


async def confirm_attachment_version(
    *,
    user_id: str,
    user_jwt: str,
    issue_id: str,
    filename: str,
    content_type: str,
    file_size: int,
    r2_key: str,
    attachment_id: Optional[str] = None,
) -> Dict[str, Any]:
    safe_filename = _validate_attachment(filename, content_type, file_size)
    if not r2_key.startswith(f"projects/{user_id}/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="R2 key does not belong to this upload")

    supabase = await get_authenticated_async_client(user_jwt)
    issue = await get_issue_context(supabase, issue_id)
    await enforce_issue_not_locked(
        supabase,
        issue=issue,
        user_id=user_id,
        board_id=issue["board_id"],
    )

    if attachment_id:
        attachment_result = await supabase.table("issue_attachments")\
            .select("*")\
            .eq("id", attachment_id)\
            .eq("issue_id", issue_id)\
            .maybe_single()\
            .execute()
        attachment = attachment_result.data
        if not attachment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
        version_result = await supabase.rpc(
            "allocate_issue_attachment_version",
            {"p_attachment_id": attachment_id},
        ).execute()
        version_number = int(version_result.data)
    else:
        attachment_result = await supabase.table("issue_attachments")\
            .insert({
                "workspace_app_id": issue["workspace_app_id"],
                "workspace_id": issue["workspace_id"],
                "issue_id": issue_id,
                "filename": safe_filename,
                "content_type": content_type,
                "created_by": user_id,
            })\
            .execute()
        if not attachment_result.data:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create attachment")
        attachment = attachment_result.data[0]
        attachment_id = attachment["id"]
        version_number = 1

    version_result = await supabase.table("issue_attachment_versions")\
        .insert({
            "workspace_app_id": issue["workspace_app_id"],
            "workspace_id": issue["workspace_id"],
            "attachment_id": attachment_id,
            "version_number": version_number,
            "r2_key": r2_key,
            "file_size": file_size,
            "content_type": content_type,
            "uploaded_by": user_id,
        })\
        .execute()
    if not version_result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create attachment version")

    version = version_result.data[0]
    update_payload: Dict[str, Any] = {
        "filename": safe_filename,
        "content_type": content_type,
        "current_version_id": version["id"],
    }
    if version_number == 1:
        update_payload["next_version_number"] = 2

    updated = await supabase.table("issue_attachments")\
        .update(update_payload)\
        .eq("id", attachment_id)\
        .execute()
    attachment = updated.data[0] if updated.data else attachment
    attachment["current_version"] = version
    return attachment


async def list_issue_attachments(user_jwt: str, issue_id: str) -> List[Dict[str, Any]]:
    supabase = await get_authenticated_async_client(user_jwt)
    await get_issue_context(supabase, issue_id)
    result = await supabase.table("issue_attachments")\
        .select("*")\
        .eq("issue_id", issue_id)\
        .order("created_at")\
        .execute()
    return result.data or []


async def list_attachment_versions(user_jwt: str, attachment_id: str) -> List[Dict[str, Any]]:
    supabase = await get_authenticated_async_client(user_jwt)
    result = await supabase.table("issue_attachment_versions")\
        .select("*")\
        .eq("attachment_id", attachment_id)\
        .order("version_number", desc=True)\
        .execute()
    return result.data or []


async def get_attachment_version_url(
    *,
    user_jwt: str,
    version_id: str,
    expires_in: Optional[int] = None,
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    result = await supabase.table("issue_attachment_versions")\
        .select("*")\
        .eq("id", version_id)\
        .maybe_single()\
        .execute()
    version = result.data
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment version not found")

    r2_client = get_r2_client()
    expiration = expires_in or r2_client.presigned_url_expiry
    return {
        "url": r2_client.get_presigned_url(version["r2_key"], expiration=expiration),
        "expires_in": expiration,
    }
