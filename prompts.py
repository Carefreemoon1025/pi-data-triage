from __future__ import annotations

try:
    from .models import ColumnProfile, CsvLoadMetadata, DatasetProfile
except ImportError:  # pragma: no cover - supports `streamlit run examples/dataset_triage/app.py`
    from models import ColumnProfile, CsvLoadMetadata, DatasetProfile


MAX_MISSING_COLUMNS = 5
MAX_SUSPICIOUS_COLUMNS = 8
MAX_NUMERIC_COLUMNS = 5
MAX_CATEGORICAL_COLUMNS = 5
MAX_DTYPE_COLUMNS = 12
MAX_CATEGORICAL_VALUE_LENGTH = 36


def build_initial_analysis_prompt(
    profile: DatasetProfile,
    *,
    dataset_name: str | None = None,
    load_metadata: CsvLoadMetadata | None = None,
) -> str:
    highest_missing = sorted(profile.columns_profile, key=lambda column: column.null_pct, reverse=True)[:MAX_MISSING_COLUMNS]
    suspicious = profile.suspicious_columns[:MAX_SUSPICIOUS_COLUMNS]
    numeric_lines = _format_numeric_highlights(profile)[:MAX_NUMERIC_COLUMNS]
    categorical_lines = _format_categorical_highlights(profile)[:MAX_CATEGORICAL_COLUMNS]
    dtype_overview = _format_dtype_overview(profile)

    lines = [
        "You are helping triage a CSV dataset.",
        "Use the structured profile below. Do not invent metrics that are not present.",
        "Base your analysis on the provided facts.",
        "Dataset profile:",
    ]
    if dataset_name:
        lines.append(f"- dataset name: {dataset_name}")
    if load_metadata is not None and load_metadata.truncated:
        lines.append(
            f"- Dataset profile is based on the first {load_metadata.loaded_rows} rows only because the local app keeps large analyses bounded."
        )
    lines.extend(
        [
            f"- rows: {profile.rows}",
            f"- columns: {profile.columns}",
            f"- duplicate rows: {profile.duplicate_rows}",
            f"- dtype overview: {dtype_overview}",
            "- columns with highest missing %: " + "; ".join(f"{column.name} ({column.null_pct:.1f}%)" for column in highest_missing),
            "- suspicious columns: " + (_format_suspicious_columns(suspicious) if suspicious else "none detected by the deterministic heuristics"),
            "- numeric highlights: " + ("; ".join(numeric_lines) if numeric_lines else "none"),
            "- categorical highlights: " + ("; ".join(categorical_lines) if categorical_lines else "none"),
            "",
            "Please provide:",
            "1. A short overview of what this dataset appears to contain.",
            "2. The top 3-5 data quality concerns, ranked by importance.",
            "3. Recommended cleanup steps.",
            "4. If useful, example pandas code for the most important fixes.",
        ]
    )
    return "\n".join(lines)


def _format_suspicious_columns(columns: tuple[ColumnProfile, ...]) -> str:
    formatted: list[str] = []
    for column in columns:
        notes = ", ".join(column.notes)
        formatted.append(f"{column.name} [{notes}]")
    return "; ".join(formatted)


def _format_dtype_overview(profile: DatasetProfile) -> str:
    entries = [f"{column.name} ({column.dtype})" for column in profile.columns_profile[:MAX_DTYPE_COLUMNS]]
    remaining = len(profile.columns_profile) - len(entries)
    if remaining > 0:
        entries.append(f"+ {remaining} more columns omitted")
    return ", ".join(entries) if entries else "none"


def _format_numeric_highlights(profile: DatasetProfile) -> list[str]:
    lines: list[str] = []
    for column_name, summary in profile.numeric_summary.items():
        lines.append(
            f"{column_name}: min={summary['min']}, median={summary['median']}, mean={summary['mean']:.2f}, max={summary['max']}"
        )
    return lines


def _format_categorical_highlights(profile: DatasetProfile) -> list[str]:
    lines: list[str] = []
    for column_name, values in profile.categorical_top_values.items():
        if not values:
            continue
        top_values = ", ".join(f"{_truncate_text(value)} ({count})" for value, count in values)
        lines.append(f"{column_name}: {top_values}")
    return lines


def _truncate_text(value: str) -> str:
    if len(value) <= MAX_CATEGORICAL_VALUE_LENGTH:
        return value
    return value[:MAX_CATEGORICAL_VALUE_LENGTH] + "..."
