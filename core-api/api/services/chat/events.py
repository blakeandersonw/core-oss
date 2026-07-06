"""
NDJSON Streaming Event Types

This module defines the event schema for NDJSON streaming responses.
Each line in the stream is a JSON object with a "type" field indicating the event type.

Event Types:
- content: Text delta from AI response
- action: Staged action requiring user confirmation
- display: Embedded data to render inline (calendar events, emails, todos)
- ping: Keep-alive heartbeat (prevents Vercel timeout)
- error: Error during stream processing
- done: Stream completion signal

Usage:
    from api.services.chat.events import ContentEvent, ActionEvent, format_event

    yield format_event(ContentEvent(type="content", delta="Hello"))
    yield format_event(ActionEvent(type="action", action="create_task", ...))
"""

from typing import TypedDict, Any, Dict, List, Literal, Union
import json


# =============================================================================
# EVENT TYPE DEFINITIONS (TypedDict for type safety without runtime overhead)
# =============================================================================

class ContentEvent(TypedDict):
    """Text delta from AI response."""
    type: Literal["content"]
    delta: str


class ActionEvent(TypedDict):
    """Staged action requiring user confirmation."""
    type: Literal["action"]
    id: str  # Unique ID for this action (used for persistence)
    action: str
    status: Literal["staged"]
    data: Dict[str, Any]
    description: str


class DisplayEvent(TypedDict):
    """Embedded data to render inline in chat (calendar events, emails, todos)."""
    type: Literal["display"]
    display_type: str  # "calendar_events", "emails", "todos"
    items: List[Dict[str, Any]]
    total_count: int  # Total items available (may be more than items if truncated)


class PingEvent(TypedDict):
    """Keep-alive heartbeat to prevent Vercel timeout."""
    type: Literal["ping"]


class ErrorEvent(TypedDict):
    """Error during stream processing."""
    type: Literal["error"]
    message: str


class DoneEvent(TypedDict):
    """Stream completion signal with message ID for action persistence."""
    type: Literal["done"]
    message_id: str  # The persisted assistant message ID


class StatusEvent(TypedDict):
    """Status/thinking indicator (e.g., "Searching the web...")."""
    type: Literal["status"]
    message: str


class SourceItem(TypedDict):
    """Individual source from web search."""
    url: str
    title: str
    domain: str
    favicon: str


class SourcesEvent(TypedDict):
    """Web search sources for citation display."""
    type: Literal["sources"]
    sources: List[SourceItem]


class ToolCallEvent(TypedDict, total=False):
    """Tool call lifecycle event (start/end) for showing agent steps in the UI."""
    type: Literal["tool_call"]
    phase: Literal["start", "end"]
    name: str
    args: Dict[str, Any]  # Only present on "start"
    duration_ms: int  # Only present on "end"
    status: str  # Only present on "end": "success", "error", "staged"


# Union type for all events (for type hints)
StreamEvent = Union[
    ContentEvent,
    ActionEvent,
    DisplayEvent,
    PingEvent,
    ErrorEvent,
    DoneEvent,
    StatusEvent,
    SourcesEvent,
    ToolCallEvent,
]


# =============================================================================
# EVENT FORMATTING HELPERS
# =============================================================================

def format_event(event: StreamEvent) -> str:
    """
    Format an event as an NDJSON line.

    CRITICAL: Every line MUST end with \\n for proper NDJSON parsing.

    Args:
        event: A typed event dictionary

    Returns:
        JSON string terminated with newline
    """
    return json.dumps(event, ensure_ascii=False) + "\n"


def content_event(delta: str) -> str:
    """Create and format a content event."""
    return format_event(ContentEvent(type="content", delta=delta))


def action_event(action_id: str, action: str, data: Dict[str, Any], description: str) -> str:
    """Create and format a staged action event.

    Args:
        action_id: Unique ID for this action (used for persistence)
        action: Action type (e.g., "create_todo", "send_email")
        data: Action-specific data
        description: Human-readable description
    """
    return format_event(ActionEvent(
        type="action",
        id=action_id,
        action=action,
        status="staged",
        data=data,
        description=description
    ))


def display_event(display_type: str, items: List[Dict[str, Any]], total_count: int) -> str:
    """
    Create and format a display event for embedded content.

    Args:
        display_type: Type of content - "calendar_events", "emails", or "todos"
        items: List of items to display (max 5 recommended)
        total_count: Total number of items available (for "See all" UI)

    Returns:
        Formatted NDJSON line
    """
    return format_event(DisplayEvent(
        type="display",
        display_type=display_type,
        items=items,
        total_count=total_count
    ))


def ping_event() -> str:
    """Create and format a ping keep-alive event."""
    return format_event(PingEvent(type="ping"))


def error_event(message: str) -> str:
    """Create and format an error event."""
    return format_event(ErrorEvent(type="error", message=message))


def done_event(message_id: str = "") -> str:
    """Create and format a done event with the persisted message ID."""
    return format_event(DoneEvent(type="done", message_id=message_id))


def status_event(message: str) -> str:
    """Create and format a status/thinking indicator event."""
    return format_event(StatusEvent(type="status", message=message))


def sources_event(sources: List[Dict[str, Any]]) -> str:
    """
    Create and format a sources event for web search citations.

    Args:
        sources: List of source dicts with url, title, domain, favicon

    Returns:
        Formatted NDJSON line
    """
    return format_event(SourcesEvent(
        type="sources",
        sources=[
            SourceItem(
                url=s.get("url", ""),
                title=s.get("title", ""),
                domain=s.get("domain", ""),
                favicon=s.get("favicon", "")
            )
            for s in sources
        ]
    ))


def tool_call_start_event(name: str, args: Dict[str, Any]) -> str:
    """Create and format a tool call start event."""
    event: Dict[str, Any] = {
        "type": "tool_call",
        "phase": "start",
        "name": name,
        "args": args,
    }
    return json.dumps(event, ensure_ascii=False) + "\n"


def tool_call_end_event(name: str, duration_ms: int, status: str = "success") -> str:
    """Create and format a tool call end event."""
    event: Dict[str, Any] = {
        "type": "tool_call",
        "phase": "end",
        "name": name,
        "duration_ms": duration_ms,
        "status": status,
    }
    return json.dumps(event, ensure_ascii=False) + "\n"


def tool_exchange_event(tool_use_id: str, name: str, args: Dict[str, Any], result_json: str) -> str:
    """Create a tool_exchange event capturing the full tool_use + tool_result pair for persistence.

    This event is NOT streamed to the client — it's consumed by the router to persist
    tool call context in content_parts so history can be reconstructed on the next turn.
    """
    event: Dict[str, Any] = {
        "type": "tool_exchange",
        "tool_use_id": tool_use_id,
        "name": name,
        "args": args,
        "result": result_json,
    }
    return json.dumps(event, ensure_ascii=False) + "\n"

