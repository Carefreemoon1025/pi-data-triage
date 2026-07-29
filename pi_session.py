from __future__ import annotations

import os
import queue
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from picable import PiClient, PiClientOptions
from picable.exceptions import (
    PiCommandError,
    PiProcessExitedError,
    PiProtocolError,
    PiStartupError,
    PiSubscriptionOverflowError,
    PiTimeoutError,
)

try:
    from runtime_config import build_example_client_options
except ImportError:  # pragma: no cover - supports package-style imports in tests
    import sys

    EXAMPLES_DIR = Path(__file__).resolve().parents[1]
    if str(EXAMPLES_DIR) not in sys.path:
        sys.path.insert(0, str(EXAMPLES_DIR))
    from runtime_config import build_example_client_options


class DatasetTriageSessionError(RuntimeError):
    """Raised when the Streamlit UI should show a safe Pi-related failure."""


class DatasetTriageSession:
    def __init__(
        self,
        options: PiClientOptions | None = None,
        *,
        client_factory: Callable[[PiClientOptions], Any] | None = None,
        subscription_maxsize: int = 500,
        event_timeout: float = 60.0,
    ) -> None:
        self._options = options or build_example_client_options()
        self._client_factory = client_factory or (lambda options: PiClient(options))
        self._subscription_maxsize = subscription_maxsize
        self._event_timeout = event_timeout
        self._client: Any | None = None
        self._subscription: Any | None = None
        self._current_session_name: str | None = None
        self._has_completed_initial_analysis = False

    @property
    def can_follow_up(self) -> bool:
        return self._has_completed_initial_analysis

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._subscription = None
        self._current_session_name = None
        self._has_completed_initial_analysis = False

    def reset_for_dataset(self, dataset_name: str) -> str:
        session_name = f"dataset-triage:{_sanitize_dataset_name(dataset_name)}"
        client = self._ensure_client()
        try:
            client.new_session()
            client.set_session_name(session_name)
        except _SESSION_ERRORS as exc:
            self._reset_subscription_if_closed()
            raise DatasetTriageSessionError(f"Pi request failed while creating a dataset session: {exc}") from exc
        self._current_session_name = session_name
        self._has_completed_initial_analysis = False
        return session_name

    def analyze_profile(self, prompt: str, *, on_update: Callable[[str], None] | None = None) -> str:
        final_text = self._run_stream(lambda client: client.prompt(prompt), on_update=on_update)
        self._has_completed_initial_analysis = True
        return final_text

    def ask_follow_up(self, question: str, *, on_update: Callable[[str], None] | None = None) -> str:
        if not self._has_completed_initial_analysis:
            raise DatasetTriageSessionError("Analyze the dataset with Pi before asking follow-up questions.")
        return self._run_stream(lambda client: client.continue_prompt(question), on_update=on_update)

    def export_session_html(self, output_path: str | None = None) -> str:
        client = self._ensure_client()
        try:
            return str(client.export_html(output_path=output_path).path)
        except _SESSION_ERRORS as exc:
            self._reset_subscription_if_closed()
            raise DatasetTriageSessionError(f"Pi request failed while exporting the session: {exc}") from exc

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self._options)
        if self._subscription is None or getattr(self._subscription, "closed", False):
            self._subscription = self._client.subscribe_events(maxsize=self._subscription_maxsize)
        return self._client

    def _run_stream(self, sender: Callable[[Any], None], *, on_update: Callable[[str], None] | None = None) -> str:
        client = self._ensure_client()
        try:
            sender(client)
            return self._consume_response(client, on_update=on_update)
        except _SESSION_ERRORS as exc:
            self._reset_subscription_if_closed()
            raise DatasetTriageSessionError(f"Pi request failed: {exc}") from exc
        except queue.Empty as exc:
            self._reset_subscription_if_closed()
            raise DatasetTriageSessionError("Pi request failed: timed out while waiting for streamed events.") from exc

    def _consume_response(self, client: Any, *, on_update: Callable[[str], None] | None = None) -> str:
        assert self._subscription is not None
        fragments: list[str] = []
        while True:
            event = self._subscription.get(timeout=self._event_timeout)
            if getattr(event, "type", None) == "message_update":
                assistant_event = getattr(event, "assistant_message_event", None)
                if getattr(assistant_event, "type", None) != "text_delta":
                    continue
                delta = getattr(assistant_event, "delta", None)
                if not delta:
                    continue
                fragments.append(delta)
                if on_update is not None:
                    on_update("".join(fragments))
                continue
            if getattr(event, "type", None) == "agent_end":
                final_message = getattr(event, "messages", ())[-1] if getattr(event, "messages", ()) else None
                stop_reason = getattr(final_message, "stop_reason", None)
                if stop_reason in {"error", "aborted"}:
                    error_message = getattr(final_message, "error_message", None)
                    detail = f": {error_message}" if error_message else ""
                    raise DatasetTriageSessionError(f"Pi request failed while streaming a response{detail}")
                break

        final_text = client.get_last_assistant_text() or "".join(fragments)
        if on_update is not None and final_text and final_text != "".join(fragments):
            on_update(final_text)
        return final_text


    def _reset_subscription_if_closed(self) -> None:
        if self._subscription is not None and getattr(self._subscription, "closed", False):
            self._subscription = None


def _sanitize_dataset_name(dataset_name: str) -> str:
    basename = os.path.basename(dataset_name) or "dataset"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip("-")
    return sanitized or "dataset"


_SESSION_ERRORS = (
    PiStartupError,
    PiProcessExitedError,
    PiProtocolError,
    PiCommandError,
    PiSubscriptionOverflowError,
    PiTimeoutError,
)
