from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import PiProtocolError
from .models import CompactionResult
from .protocol_types import (
    AgentMessage,
    AssistantMessageEvent,
    ExtensionUiRequest,
    ThinkingLevel,
    ToolExecutionResult,
    parse_agent_message,
    parse_assistant_message_event,
    parse_extension_ui_request,
    parse_thinking_level_value,
    parse_tool_execution_result,
)


@dataclass(frozen=True)
class AgentStartEvent:
    type: str = "agent_start"


@dataclass(frozen=True)
class AgentEndEvent:
    messages: tuple[AgentMessage, ...]
    type: str = "agent_end"


@dataclass(frozen=True)
class TurnStartEvent:
    type: str = "turn_start"


@dataclass(frozen=True)
class TurnEndEvent:
    message: AgentMessage
    tool_results: tuple[AgentMessage, ...]
    type: str = "turn_end"


@dataclass(frozen=True)
class MessageStartEvent:
    message: AgentMessage
    type: str = "message_start"


@dataclass(frozen=True)
class MessageUpdateEvent:
    message: AgentMessage
    assistant_message_event: AssistantMessageEvent
    type: str = "message_update"


@dataclass(frozen=True)
class MessageEndEvent:
    message: AgentMessage
    type: str = "message_end"


@dataclass(frozen=True)
class ToolExecutionStartEvent:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    type: str = "tool_execution_start"


@dataclass(frozen=True)
class ToolExecutionUpdateEvent:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    partial_result: ToolExecutionResult
    type: str = "tool_execution_update"


@dataclass(frozen=True)
class ToolExecutionEndEvent:
    tool_call_id: str
    tool_name: str
    result: ToolExecutionResult
    is_error: bool
    type: str = "tool_execution_end"


@dataclass(frozen=True)
class AutoCompactionStartEvent:
    reason: str
    type: str = "auto_compaction_start"


@dataclass(frozen=True)
class AutoCompactionEndEvent:
    result: CompactionResult | None
    aborted: bool
    will_retry: bool
    error_message: str | None = None
    type: str = "auto_compaction_end"


@dataclass(frozen=True)
class AutoRetryStartEvent:
    attempt: int
    max_attempts: int
    delay_ms: int
    error_message: str
    type: str = "auto_retry_start"


@dataclass(frozen=True)
class AutoRetryEndEvent:
    success: bool
    attempt: int
    final_error: str | None = None
    type: str = "auto_retry_end"


@dataclass(frozen=True)
class ExtensionErrorEvent:
    extension_path: str
    event: str
    error: str
    type: str = "extension_error"


@dataclass(frozen=True)
class QueueUpdateEvent:
    steering: tuple[str, ...]
    follow_up: tuple[str, ...]
    type: str = "queue_update"


@dataclass(frozen=True)
class SessionInfoChangedEvent:
    name: str | None
    type: str = "session_info_changed"


@dataclass(frozen=True)
class ThinkingLevelChangedEvent:
    level: ThinkingLevel
    type: str = "thinking_level_changed"


@dataclass(frozen=True)
class ExtensionUiRequestEvent:
    request: ExtensionUiRequest
    type: str = "extension_ui_request"


@dataclass(frozen=True)
class AgentSettledEvent:
    type: str = "agent_settled"


AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
    | AutoCompactionStartEvent
    | AutoCompactionEndEvent
    | AutoRetryStartEvent
    | AutoRetryEndEvent
    | ExtensionErrorEvent
    | QueueUpdateEvent
    | SessionInfoChangedEvent
    | ThinkingLevelChangedEvent
    | ExtensionUiRequestEvent
    | AgentSettledEvent
)


def parse_event(payload: Any) -> AgentEvent:
    if not isinstance(payload, dict):
        raise PiProtocolError(f"Expected event object, got {type(payload).__name__}")
    event_type = payload.get("type")
    if event_type == "agent_start":
        return AgentStartEvent()
    if event_type == "agent_end":
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise PiProtocolError("Expected agent_end.messages to be a list")
        return AgentEndEvent(messages=tuple(parse_agent_message(item) for item in messages))
    if event_type == "turn_start":
        return TurnStartEvent()
    if event_type == "turn_end":
        tool_results = payload.get("toolResults")
        if not isinstance(tool_results, list):
            raise PiProtocolError("Expected turn_end.toolResults to be a list")
        return TurnEndEvent(
            message=parse_agent_message(payload.get("message")),
            tool_results=tuple(parse_agent_message(item) for item in tool_results),
        )
    if event_type == "message_start":
        return MessageStartEvent(message=parse_agent_message(payload.get("message")))
    if event_type == "message_update":
        return MessageUpdateEvent(
            message=parse_agent_message(payload.get("message")),
            assistant_message_event=parse_assistant_message_event(payload.get("assistantMessageEvent")),
        )
    if event_type == "message_end":
        return MessageEndEvent(message=parse_agent_message(payload.get("message")))
    if event_type == "tool_execution_start":
        args = payload.get("args", {})
        if not isinstance(args, dict):
            raise PiProtocolError("Expected tool_execution_start.args to be an object")
        return ToolExecutionStartEvent(
            tool_call_id=_require_str(payload, "toolCallId"),
            tool_name=_require_str(payload, "toolName"),
            args=dict(args),
        )
    if event_type == "tool_execution_update":
        args = payload.get("args", {})
        if not isinstance(args, dict):
            raise PiProtocolError("Expected tool_execution_update.args to be an object")
        return ToolExecutionUpdateEvent(
            tool_call_id=_require_str(payload, "toolCallId"),
            tool_name=_require_str(payload, "toolName"),
            args=dict(args),
            partial_result=parse_tool_execution_result(payload.get("partialResult", {})),
        )
    if event_type == "tool_execution_end":
        is_error = payload.get("isError")
        if not isinstance(is_error, bool):
            raise PiProtocolError("Expected tool_execution_end.isError to be a boolean")
        return ToolExecutionEndEvent(
            tool_call_id=_require_str(payload, "toolCallId"),
            tool_name=_require_str(payload, "toolName"),
            result=parse_tool_execution_result(payload.get("result", {})),
            is_error=is_error,
        )
    if event_type in {"auto_compaction_start", "compaction_start"}:
        return AutoCompactionStartEvent(reason=_require_str(payload, "reason"), type=event_type)
    if event_type in {"auto_compaction_end", "compaction_end"}:
        aborted = payload.get("aborted")
        will_retry = payload.get("willRetry")
        if not isinstance(aborted, bool) or not isinstance(will_retry, bool):
            raise PiProtocolError(f"Expected {event_type} aborted/willRetry to be booleans")
        result_payload = payload.get("result")
        result = None
        if result_payload is not None:
            if not isinstance(result_payload, dict):
                raise PiProtocolError(f"Expected {event_type}.result to be an object or null")
            details = result_payload.get("details", {})
            if not isinstance(details, dict):
                raise PiProtocolError(f"Expected {event_type}.result.details to be an object")
            result = CompactionResult(
                summary=str(result_payload.get("summary", "")),
                first_kept_entry_id=str(result_payload.get("firstKeptEntryId", "")),
                tokens_before=int(result_payload.get("tokensBefore", 0)),
                details=dict(details),
            )
        error_message = payload.get("errorMessage")
        if error_message is not None and not isinstance(error_message, str):
            raise PiProtocolError(f"Expected {event_type}.errorMessage to be a string when present")
        return AutoCompactionEndEvent(result=result, aborted=aborted, will_retry=will_retry, error_message=error_message, type=event_type)
    if event_type == "auto_retry_start":
        return AutoRetryStartEvent(
            attempt=_require_int(payload, "attempt"),
            max_attempts=_require_int(payload, "maxAttempts"),
            delay_ms=_require_int(payload, "delayMs"),
            error_message=_require_str(payload, "errorMessage"),
        )
    if event_type == "auto_retry_end":
        success = payload.get("success")
        if not isinstance(success, bool):
            raise PiProtocolError("Expected auto_retry_end.success to be a boolean")
        final_error = payload.get("finalError")
        if final_error is not None and not isinstance(final_error, str):
            raise PiProtocolError("Expected auto_retry_end.finalError to be a string when present")
        return AutoRetryEndEvent(success=success, attempt=_require_int(payload, "attempt"), final_error=final_error)
    if event_type == "extension_error":
        return ExtensionErrorEvent(
            extension_path=_require_str(payload, "extensionPath"),
            event=_require_str(payload, "event"),
            error=_require_str(payload, "error"),
        )
    if event_type == "queue_update":
        return QueueUpdateEvent(
            steering=_require_str_list(payload, "steering"),
            follow_up=_require_str_list(payload, "followUp"),
        )
    if event_type == "session_info_changed":
        return SessionInfoChangedEvent(name=_optional_str(payload, "name"))
    if event_type == "thinking_level_changed":
        return ThinkingLevelChangedEvent(level=parse_thinking_level_value(payload.get("level"), "thinking_level_changed.level"))
    if event_type == "extension_ui_request":
        return ExtensionUiRequestEvent(request=parse_extension_ui_request(payload))
    if event_type == "agent_settled":
        return AgentSettledEvent()
    raise PiProtocolError(f"Unsupported event type: {event_type!r}")


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise PiProtocolError(f"Expected '{key}' to be a string")
    return value


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PiProtocolError(f"Expected '{key}' to be an integer")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PiProtocolError(f"Expected '{key}' to be a string when present")
    return value


def _require_str_list(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise PiProtocolError(f"Expected '{key}' to be a list")
    if any(not isinstance(item, str) for item in value):
        raise PiProtocolError(f"Expected '{key}' to contain only strings")
    return tuple(value)
