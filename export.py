from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence

try:
    from .models import LoadNotice
except ImportError:  # pragma: no cover - supports `streamlit run examples/dataset_triage/app.py`
    from models import LoadNotice


def build_export_markdown(
    *,
    dataset_name: str | None,
    analysis_prompt: str | None,
    conversation_history: Sequence[Mapping[str, str]],
    load_notices: Sequence[LoadNotice] = (),
) -> str:
    lines = [
        "# Dataset Triage Export",
        "",
        f"- Dataset: {dataset_name or 'uploaded.csv'}",
        "- Privacy note: this example does not redact prompt or transcript values.",
    ]

    if load_notices:
        lines.extend(["", "## Loader notices"])
        for notice in load_notices:
            lines.append(f"- [{notice.level}] {notice.message}")

    lines.extend(["", "## Prompt sent to Pi"])
    if analysis_prompt:
        lines.extend(["", "```text", analysis_prompt, "```"])
    else:
        lines.extend(["", "_No Pi prompt was captured._"])

    lines.extend(["", "## Conversation"])
    if not conversation_history:
        lines.extend(["", "_No conversation captured._"])
        return "\n".join(lines)

    for index, message in enumerate(conversation_history, start=1):
        role = message.get("role", "unknown")
        text = message.get("text", "")
        lines.extend(["", f"### {index}. {role.title()}", "", text])

    return "\n".join(lines)


def build_export_basename(dataset_name: str | None) -> str:
    basename = os.path.basename(dataset_name or "dataset")
    stem = basename.rsplit(".", 1)[0] or basename
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")
    return sanitized or "dataset"
