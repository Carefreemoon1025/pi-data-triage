from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

try:
    from .export import build_export_basename, build_export_markdown
    from .loader import load_csv
    from .models import CsvLoadOptions, DatasetLoadError
    from .pi_session import DatasetTriageSession, DatasetTriageSessionError
    from .profiler import build_dataset_profile
    from .prompts import build_initial_analysis_prompt
except ImportError:  # pragma: no cover - supports `streamlit run examples/dataset_triage/app.py`
    import sys

    APP_DIR = Path(__file__).resolve().parent
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))

    from export import build_export_basename, build_export_markdown
    from loader import load_csv
    from models import CsvLoadOptions, DatasetLoadError
    from pi_session import DatasetTriageSession, DatasetTriageSessionError
    from profiler import build_dataset_profile
    from prompts import build_initial_analysis_prompt


PREVIEW_ROWS = 20


def main() -> None:
    st.set_page_config(page_title="Dataset Triage Assistant", layout="wide")
    st.title("Dataset Triage Assistant")
    st.caption("Profile a CSV or CSV.gz locally with pandas, then ask Pi for a streamed triage summary and follow-up guidance.")

    state = _state()

    with st.expander("CSV parse options", expanded=False):
        st.selectbox(
            "Delimiter",
            options=[",", ";", "\t", "|"],
            format_func=_format_delimiter,
            key="parse_separator",
            help="Use this when the uploaded file is separated by semicolons, tabs, or pipes instead of commas.",
        )
        st.text_input("Encoding", key="parse_encoding", help="For example: utf-8, latin-1, cp1252")
        st.checkbox("First row contains column names", key="parse_has_header")

    uploaded_file = st.file_uploader("Upload a CSV or CSV.gz file", type=["csv", "gz"])
    if uploaded_file is None:
        uploaded_file = state.get("test_uploaded_file")

    left, right = st.columns((3, 2))
    with right:
        if st.button(
            "Reset conversation",
            disabled=state["loaded_dataset"] is None,
            use_container_width=True,
            key="reset_conversation_button",
        ):
            _reset_conversation_state()
            state["session_needs_reset"] = True
            st.success("The next Pi request will start a fresh session for the current dataset.")

    with left:
        st.info("Try `examples/dataset_triage/sample_data/co2-emissions-per-capita.csv.gz` for a quick demo.")

    if uploaded_file is not None:
        _handle_upload(uploaded_file, _current_load_options())

    loaded_dataset = state["loaded_dataset"]
    dataset_profile = state["dataset_profile"]
    analysis_prompt = None
    if loaded_dataset is not None and dataset_profile is not None:
        analysis_prompt = build_initial_analysis_prompt(
            dataset_profile,
            dataset_name=loaded_dataset.upload.name,
            load_metadata=loaded_dataset.load,
        )

    if state["analysis_error"]:
        st.error(state["analysis_error"])
    if state["export_error"]:
        st.warning(state["export_error"])

    if loaded_dataset is None or dataset_profile is None:
        st.warning("Upload a CSV or CSV.gz file to preview its contents, inspect a compact profile, and ask Pi for cleanup advice.")
        return

    for notice in loaded_dataset.load.notices:
        if notice.level == "warning":
            st.warning(notice.message)
        else:
            st.info(notice.message)

    preview_col, profile_col = st.columns((3, 2))
    with preview_col:
        st.subheader("Preview")
        st.write(f"**Dataset:** {loaded_dataset.upload.name or 'uploaded.csv'}")
        st.dataframe(loaded_dataset.dataframe.head(PREVIEW_ROWS), use_container_width=True)

    with profile_col:
        st.subheader("Profile summary")
        metrics = st.columns(3)
        metrics[0].metric("Rows profiled", dataset_profile.rows)
        metrics[1].metric("Columns", dataset_profile.columns)
        metrics[2].metric("Duplicate rows", dataset_profile.duplicate_rows)
        if loaded_dataset.load.truncated and loaded_dataset.load.row_limit is not None:
            st.caption(f"The deterministic profile uses the first {loaded_dataset.load.row_limit:,} rows only.")
        if dataset_profile.suspicious_columns:
            st.markdown("**Suspicious columns**")
            for column in dataset_profile.suspicious_columns:
                st.markdown(f"- `{column.name}`: {', '.join(column.notes)}")
        else:
            st.success("No suspicious columns were flagged by the deterministic heuristics.")

    st.subheader("What Pi receives")
    st.caption("Pi receives the bounded prompt below, not the full raw dataframe.")
    if analysis_prompt is not None:
        with st.expander("Preview the exact prompt sent to Pi", expanded=False):
            st.code(analysis_prompt, language="markdown")

    st.subheader("Conversation")
    for message in state["conversation_history"]:
        with st.chat_message(message["role"]):
            st.markdown(message["text"])

    stream_placeholder = st.empty()
    if state["latest_stream_text"]:
        with stream_placeholder.container():
            with st.chat_message("assistant"):
                st.markdown(state["latest_stream_text"])

    analyze_disabled = state["analysis_running"]
    if st.button("Analyze with Pi", disabled=analyze_disabled, type="primary", use_container_width=True, key="analyze_button"):
        assert analysis_prompt is not None
        state["conversation_history"].append({"role": "user", "text": "Analyze the uploaded dataset."})
        _run_streamed_request(
            lambda on_update: state["controller"].analyze_profile(analysis_prompt, on_update=on_update),
            dataset_name=loaded_dataset.upload.name or "uploaded.csv",
            placeholder=stream_placeholder,
            history=state["conversation_history"],
            marks_initial_analysis_complete=True,
        )
        st.rerun()

    follow_up_disabled = analyze_disabled or not state["has_completed_initial_analysis"]
    if not state["has_completed_initial_analysis"]:
        st.info("Run **Analyze with Pi** first so follow-up questions stay grounded in the uploaded dataset.")

    with st.form("follow_up_form", clear_on_submit=True):
        question = st.text_input(
            "Ask a follow-up question",
            placeholder="Which three columns should I clean first?",
            key="follow_up_question",
        )
        submitted = st.form_submit_button("Send", disabled=follow_up_disabled, use_container_width=True)
    if submitted and question.strip():
        if not state["has_completed_initial_analysis"]:
            state["analysis_error"] = "Analyze the dataset with Pi before asking follow-up questions."
            st.rerun()
        state["conversation_history"].append({"role": "user", "text": question.strip()})
        _run_streamed_request(
            lambda on_update: state["controller"].ask_follow_up(question.strip(), on_update=on_update),
            dataset_name=loaded_dataset.upload.name or "uploaded.csv",
            placeholder=stream_placeholder,
            history=state["conversation_history"],
        )
        st.rerun()

    st.subheader("Export")
    export_disabled = not state["has_completed_initial_analysis"]
    transcript_markdown = build_export_markdown(
        dataset_name=loaded_dataset.upload.name,
        analysis_prompt=analysis_prompt,
        conversation_history=tuple(state["conversation_history"]),
        load_notices=loaded_dataset.load.notices,
    )
    export_basename = build_export_basename(loaded_dataset.upload.name)

    download_col, html_col = st.columns(2)
    with download_col:
        st.download_button(
            "Download prompt + transcript (.md)",
            data=transcript_markdown,
            file_name=f"{export_basename}-triage.md",
            mime="text/markdown",
            disabled=export_disabled,
            use_container_width=True,
        )

    with html_col:
        if st.button(
            "Prepare session HTML export",
            disabled=export_disabled,
            use_container_width=True,
            key="prepare_session_html_export_button",
        ):
            _prepare_session_html_export(loaded_dataset.upload.name)

    if state["session_export_bytes"] is not None and state["session_export_name"] is not None:
        st.download_button(
            "Download session HTML",
            data=state["session_export_bytes"],
            file_name=state["session_export_name"],
            mime="text/html",
            use_container_width=True,
        )


def _handle_upload(uploaded_file: Any, options: CsvLoadOptions) -> None:
    state = _state()
    try:
        loaded_dataset = load_csv(uploaded_file, options=options)
    except DatasetLoadError as exc:
        state["analysis_error"] = str(exc)
        state["current_load_signature"] = None
        state["loaded_dataset"] = None
        state["dataset_profile"] = None
        _reset_conversation_state()
        state["analysis_error"] = str(exc)
        return

    if state["current_load_signature"] == loaded_dataset.load_signature:
        return

    state["current_load_signature"] = loaded_dataset.load_signature
    state["loaded_dataset"] = loaded_dataset
    state["dataset_profile"] = build_dataset_profile(loaded_dataset.dataframe)
    state["analysis_error"] = None
    _reset_conversation_state()
    state["session_needs_reset"] = True


def _prepare_session_html_export(dataset_name: str | None) -> None:
    state = _state()
    temp_paths: set[str] = set()
    try:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as handle:
            request_path = handle.name
        temp_paths.add(request_path)
        exported_path = state["controller"].export_session_html(request_path)
        temp_paths.add(exported_path)
        with open(exported_path, "rb") as exported_file:
            state["session_export_bytes"] = exported_file.read()
        state["session_export_name"] = f"{build_export_basename(dataset_name)}-session.html"
        state["export_error"] = None
    except (DatasetTriageSessionError, OSError) as exc:
        state["session_export_bytes"] = None
        state["session_export_name"] = None
        state["export_error"] = f"Session HTML export failed: {exc}"
    finally:
        for path in temp_paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                continue
            except OSError:
                pass


def _run_streamed_request(
    runner: Any,
    *,
    dataset_name: str,
    placeholder: Any,
    history: list[dict[str, str]],
    marks_initial_analysis_complete: bool = False,
) -> None:
    state = _state()
    state["analysis_running"] = True
    state["latest_stream_text"] = ""
    state["analysis_error"] = None

    def on_update(text: str) -> None:
        state["latest_stream_text"] = text
        with placeholder.container():
            with st.chat_message("assistant"):
                st.markdown(text)

    try:
        _ensure_dataset_session(dataset_name)
        final_text = runner(on_update)
    except DatasetTriageSessionError as exc:
        state["latest_stream_text"] = ""
        state["analysis_error"] = str(exc)
    else:
        if marks_initial_analysis_complete:
            state["has_completed_initial_analysis"] = True
        if final_text:
            history.append({"role": "assistant", "text": final_text})
            state["latest_stream_text"] = ""
            state["export_error"] = None
    finally:
        state["analysis_running"] = False


def _ensure_dataset_session(dataset_name: str) -> None:
    state = _state()
    if not state["session_needs_reset"]:
        return
    state["controller"].reset_for_dataset(dataset_name)
    state["session_needs_reset"] = False


def _reset_conversation_state() -> None:
    state = _state()
    state["conversation_history"] = []
    state["latest_stream_text"] = ""
    state["analysis_error"] = None
    state["analysis_running"] = False
    state["has_completed_initial_analysis"] = False
    state["export_error"] = None
    state["session_export_bytes"] = None
    state["session_export_name"] = None


def _current_load_options() -> CsvLoadOptions:
    state = _state()
    encoding = str(state["parse_encoding"]).strip() or "utf-8"
    return CsvLoadOptions(
        separator=str(state["parse_separator"]),
        encoding=encoding,
        has_header=bool(state["parse_has_header"]),
    )


def _format_delimiter(value: str) -> str:
    return {
        ",": "Comma (,)",
        ";": "Semicolon (;) ",
        "\t": "Tab",
        "|": "Pipe (|)",
    }.get(value, value)


def _state() -> Any:
    if "controller" not in st.session_state:
        st.session_state["controller"] = DatasetTriageSession()

    defaults = {
        "current_load_signature": None,
        "loaded_dataset": None,
        "dataset_profile": None,
        "conversation_history": [],
        "latest_stream_text": "",
        "analysis_error": None,
        "analysis_running": False,
        "session_needs_reset": False,
        "has_completed_initial_analysis": False,
        "parse_separator": ",",
        "parse_encoding": "utf-8",
        "parse_has_header": True,
        "export_error": None,
        "session_export_bytes": None,
        "session_export_name": None,
        "test_uploaded_file": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    return st.session_state


if __name__ == "__main__":
    main()
