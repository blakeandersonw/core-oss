"""
Init router - batched endpoint for app cold start.

Returns workspaces, apps, channels, DMs, and unread counts in a single
round-trip to eliminate the sequential waterfall on first load.
"""
from fastapi import APIRouter, Depends
from typing import Dict, List, Any
import asyncio
import logging
import time

from api.dependencies import get_current_user_jwt, get_current_user_id
from api.exceptions import handle_api_exception
from api.services.workspaces import get_workspaces, get_workspace_apps, get_default_workspace
from api.services.messages import get_channels, get_user_dms, get_unread_counts
from lib.supabase_client import get_service_role_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["init"])


@router.get("/init")
async def get_init_data(
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Batched init endpoint for app cold start.

    Returns all data needed to render the app in a single request:
    workspaces with their apps, channels/DMs for message apps,
    and unread counts.
    """
    try:
        t_start = time.perf_counter()
        logger.info(f"[Init] Fetching init data for user {user_id}")

        # Step 0: Fetch onboarding status (non-blocking — don't fail init if column missing)
        onboarding_completed_at = None
        try:
            supabase = get_service_role_client()
            user_result = supabase.table("users").select("onboarding_completed_at").eq("id", user_id).maybe_single().execute()
            onboarding_completed_at = user_result.data.get("onboarding_completed_at") if user_result.data else None
        except Exception as e:
            logger.warning(f"[Init] Failed to fetch onboarding status: {e}")

        # Step 1: Fetch workspaces (recover default if none found)
        workspaces = await get_workspaces(user_id, user_jwt)
        t_workspaces = time.perf_counter()
        logger.info(f"[Init] Step 1 (workspaces): {(t_workspaces - t_start)*1000:.0f}ms — {len(workspaces)} workspaces")

        if not workspaces:
            logger.info(f"[Init] No workspaces found for user {user_id}, fetching default")
            try:
                default_ws = await get_default_workspace(user_id, user_jwt)
                if default_ws:
                    workspaces = [default_ws]
            except Exception as default_err:
                logger.error(f"[Init] Failed to get default workspace: {default_err}")

        if not workspaces:
            return {
                "workspaces": [],
                "channels_by_app": {},
                "dms_by_app": {},
                "unread_counts": {},
                "onboarding_completed_at": onboarding_completed_at,
            }

        # Step 2: Fetch apps for all workspaces in parallel
        t_apps_start = time.perf_counter()
        app_results = await asyncio.gather(
            *[get_workspace_apps(ws["id"], user_jwt, user_id) for ws in workspaces],
            return_exceptions=True,
        )
        t_apps = time.perf_counter()
        logger.info(f"[Init] Step 2 (apps): {(t_apps - t_apps_start)*1000:.0f}ms — {len(workspaces)} workspace(s) queried in parallel")

        # Attach apps to workspaces and collect message app IDs
        message_app_ids: List[str] = []
        for ws, apps in zip(workspaces, app_results):
            if isinstance(apps, Exception):
                logger.error(f"[Init] Failed to fetch apps for workspace {ws['id']}: {apps}")
                ws["apps"] = []
            else:
                ws["apps"] = apps
                for app in apps:
                    if app.get("app_type") == "messages":
                        message_app_ids.append(app["id"])

        # Step 3: Fetch channels, DMs, and unread counts for all message apps in parallel
        if message_app_ids:
            t_msgs_start = time.perf_counter()
            tasks = []
            for app_id in message_app_ids:
                tasks.append(get_channels(app_id, user_jwt))
                tasks.append(get_user_dms(app_id, user_id, user_jwt))
                tasks.append(get_unread_counts(app_id, user_jwt))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            t_msgs = time.perf_counter()
            logger.info(f"[Init] Step 3 (channels/DMs/unreads): {(t_msgs - t_msgs_start)*1000:.0f}ms — {len(message_app_ids)} message app(s), {len(tasks)} parallel queries")

            channels_by_app: Dict[str, List[Dict[str, Any]]] = {}
            dms_by_app: Dict[str, List[Dict[str, Any]]] = {}
            unread_counts: Dict[str, int] = {}

            for i, app_id in enumerate(message_app_ids):
                base = i * 3
                channels_result = results[base]
                dms_result = results[base + 1]
                unread_result = results[base + 2]

                channels_by_app[app_id] = [] if isinstance(channels_result, Exception) else channels_result
                dms_by_app[app_id] = [] if isinstance(dms_result, Exception) else dms_result

                if not isinstance(unread_result, Exception):
                    unread_counts.update(unread_result)
        else:
            channels_by_app = {}
            dms_by_app = {}
            unread_counts = {}

        t_total = time.perf_counter() - t_start
        logger.info(f"[Init] Total: {t_total*1000:.0f}ms for user {user_id}")

        return {
            "workspaces": workspaces,
            "channels_by_app": channels_by_app,
            "dms_by_app": dms_by_app,
            "unread_counts": unread_counts,
            "onboarding_completed_at": onboarding_completed_at,
        }

    except Exception as e:
        handle_api_exception(e, "Failed to fetch init data", logger)
