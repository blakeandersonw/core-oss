"""
User profile router - endpoints for user profile management including avatar upload
"""
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional
from api.dependencies import get_current_user_jwt, get_current_user_id
from api.exceptions import handle_api_exception
from api.config import settings
from api.super_admin import is_super_admin_email
from lib.r2_client import R2ConfigurationError, get_r2_client
from lib.supabase_client import get_service_role_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["users"])

# Allowed image types for avatars
AVATAR_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB


class AvatarUploadInitiateRequest(BaseModel):
    """Request to initiate avatar upload"""
    filename: str
    content_type: str
    file_size: int


class AvatarUploadInitiateResponse(BaseModel):
    """Response with presigned URL for avatar upload"""
    upload_url: str
    r2_key: str
    public_url: str
    expires_at: str


class AvatarUploadConfirmRequest(BaseModel):
    """Request to confirm avatar upload"""
    r2_key: str


class AvatarUploadConfirmResponse(BaseModel):
    """Response after confirming avatar upload"""
    avatar_url: str


class UpdateUserProfileRequest(BaseModel):
    """Request to update user profile"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    onboarding_completed_at: Optional[str] = None


class UserProfileResponse(BaseModel):
    """User profile data"""
    id: str
    email: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    onboarding_completed_at: Optional[str] = None
    is_super_admin: bool = False


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    current_user_id: str = Depends(get_current_user_id),
    user_jwt: str = Depends(get_current_user_jwt)
):
    """
    Get current user's profile.
    """
    try:
        supabase = get_service_role_client()
        result = supabase.table("users").select("*").eq("id", current_user_id).maybe_single().execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        profile = result.data
        profile["is_super_admin"] = is_super_admin_email(profile.get("email"))
        return profile
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to get user profile", logger)


@router.patch("/me", response_model=UserProfileResponse)
async def update_current_user_profile(
    request: UpdateUserProfileRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Update current user's profile (name, onboarding status).
    """
    try:
        updates = {}
        if request.name is not None:
            updates["name"] = request.name
        if request.onboarding_completed_at is not None:
            updates["onboarding_completed_at"] = request.onboarding_completed_at

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        supabase = get_service_role_client()
        result = supabase.table("users").update(updates).eq("id", current_user_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to update user profile", logger)


@router.post("/avatar/initiate", response_model=AvatarUploadInitiateResponse)
async def initiate_avatar_upload(
    request: AvatarUploadInitiateRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Initiate avatar upload by getting a presigned URL.

    Client uploads directly to R2 using the returned URL,
    then calls /avatar/confirm to finalize.
    """
    # Validate content type
    if request.content_type not in AVATAR_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image type. Allowed: {', '.join(AVATAR_MIME_TYPES)}"
        )

    # Validate file size
    if request.file_size > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_AVATAR_SIZE // (1024*1024)}MB"
        )

    try:
        r2 = get_r2_client()

        # Generate R2 key for avatar
        r2_key = r2.generate_key_for_context(
            user_id=current_user_id,
            filename=request.filename,
            context="avatars"
        )

        # Generate presigned PUT URL (upload to public bucket)
        presigned = r2.generate_presigned_put_url(
            r2_key=r2_key,
            content_type=request.content_type,
            expiration=300,  # 5 minutes
            bucket=settings.r2_public_bucket
        )

        # Build public URL (using public r2.dev URL for avatars)
        public_url = f"{settings.r2_public_access_url}/{r2_key}" if settings.r2_public_access_url else ""

        logger.info(f"📤 Initiated avatar upload for user {current_user_id}")

        return AvatarUploadInitiateResponse(
            upload_url=presigned["url"],
            r2_key=r2_key,
            public_url=public_url,
            expires_at=presigned["expires_at"]
        )

    except R2ConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        handle_api_exception(e, "Failed to initiate avatar upload", logger)


@router.post("/avatar/confirm", response_model=AvatarUploadConfirmResponse)
async def confirm_avatar_upload(
    request: AvatarUploadConfirmRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Confirm avatar upload after client has uploaded to R2.

    Verifies the file exists in R2, then updates the user's avatar_url.
    """
    try:
        r2 = get_r2_client()

        # Verify file exists in R2 (public bucket)
        if not r2.file_exists(request.r2_key, bucket=settings.r2_public_bucket):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File not found in storage. Upload may have failed."
            )

        # Verify the r2_key belongs to this user (security check)
        if f"avatars/{current_user_id}/" not in request.r2_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid avatar key"
            )

        # Build public URL (using public r2.dev URL for avatars)
        public_url = f"{settings.r2_public_access_url}/{request.r2_key}"

        # Update user's avatar_url in database
        supabase = get_service_role_client()
        result = supabase.table("users").update({
            "avatar_url": public_url
        }).eq("id", current_user_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        logger.info(f"✅ Avatar updated for user {current_user_id}: {public_url}")

        return AvatarUploadConfirmResponse(avatar_url=public_url)

    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to confirm avatar upload", logger)


@router.delete("/avatar", response_model=AvatarUploadConfirmResponse)
async def delete_avatar(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Remove user's avatar, reverting to default.
    """
    try:
        supabase = get_service_role_client()

        # Get current avatar URL to delete from R2
        user_result = supabase.table("users").select("avatar_url").eq("id", current_user_id).maybe_single().execute()

        if not user_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        if user_result.data.get("avatar_url"):
            old_url = user_result.data["avatar_url"]
            # Extract r2_key from URL
            if settings.r2_public_access_url and old_url.startswith(settings.r2_public_access_url):
                r2_key = old_url.replace(f"{settings.r2_public_access_url}/", "")
                try:
                    r2 = get_r2_client()
                    r2.delete_file(r2_key, bucket=settings.r2_public_bucket)
                    logger.info(f"🗑️ Deleted old avatar from R2: {r2_key}")
                except Exception as e:
                    logger.warning(f"Failed to delete old avatar from R2: {e}")

        # Clear avatar_url in database
        supabase.table("users").update({
            "avatar_url": None
        }).eq("id", current_user_id).execute()

        logger.info(f"✅ Avatar removed for user {current_user_id}")

        return AvatarUploadConfirmResponse(avatar_url="")

    except Exception as e:
        handle_api_exception(e, "Failed to delete avatar", logger)
