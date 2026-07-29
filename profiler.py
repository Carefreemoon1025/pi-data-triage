from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pandas as pd
from pandas.api.types import is_numeric_dtype, is_object_dtype, is_string_dtype

try:
    from .models import ColumnProfile, DatasetProfile
except ImportError:  # pragma: no cover - supports `streamlit run examples/dataset_triage/app.py`
    from models import ColumnProfile, DatasetProfile


MAX_SAMPLE_VALUES = 3
MAX_TOP_VALUES = 5
HIGH_CARDINALITY_RATIO = 0.8
MIN_HIGH_CARDINALITY_ROWS = 8
MIN_IDENTIFIER_ROWS = 5
IDENTIFIER_NAME_HINTS = ("id", "uuid", "guid", "token", "key", "ref", "code")


def build_dataset_profile(dataframe: pd.DataFrame) -> DatasetProfile:
    duplicate_rows = int(dataframe.duplicated().sum())
    numeric_summary: dict[str, dict[str, float | int | None]] = {}
    categorical_top_values: dict[str, tuple[tuple[str, int], ...]] = {}
    columns_profile: list[ColumnProfile] = []
    suspicious_columns: list[ColumnProfile] = []

    for column_name in dataframe.columns:
        series = dataframe[column_name]
        non_null = series.dropna()
        non_null_count = int(non_null.shape[0])
        null_count = int(series.isna().sum())
        unique_count = int(non_null.nunique(dropna=True))
        null_pct = round((null_count / len(series)) * 100, 2) if len(series) else 0.0
        sample_values = tuple(_stringify(value) for value in non_null.head(MAX_SAMPLE_VALUES).tolist())
        top_values = _top_values(series)
        numeric_values = _numeric_summary(series)
        notes = _collect_notes(str(column_name), series, non_null, unique_count)

        if top_values:
            categorical_top_values[str(column_name)] = top_values
        if numeric_values is not None:
            numeric_summary[str(column_name)] = numeric_values

        column_profile = ColumnProfile(
            name=str(column_name),
            dtype=str(series.dtype),
            non_null_count=non_null_count,
            null_count=null_count,
            null_pct=null_pct,
            unique_count=unique_count,
            sample_values=sample_values,
            notes=tuple(notes),
            numeric_summary=numeric_values,
            top_values=top_values,
        )
        columns_profile.append(column_profile)
        if notes:
            suspicious_columns.append(column_profile)

    return DatasetProfile(
        rows=int(dataframe.shape[0]),
        columns=int(dataframe.shape[1]),
        duplicate_rows=duplicate_rows,
        numeric_summary=numeric_summary,
        categorical_top_values=categorical_top_values,
        columns_profile=tuple(columns_profile),
        suspicious_columns=tuple(suspicious_columns),
        details={"duplicate_rows_present": duplicate_rows > 0},
    )


def _collect_notes(column_name: str, series: pd.Series[Any], non_null: pd.Series[Any], unique_count: int) -> list[str]:
    notes: list[str] = []
    non_null_count = int(non_null.shape[0])
    null_pct = (float(series.isna().mean()) * 100.0) if len(series) else 0.0

    if len(series) and null_pct >= 40.0:
        notes.append(f"high missingness ({null_pct:.1f}% null)")

    if non_null_count >= 2 and unique_count == 1:
        notes.append("constant values")
    elif non_null_count >= 5 and _has_low_entropy(non_null):
        notes.append("low-entropy values dominated by a small number of categories")

    normalization_note = _categorical_normalization_note(non_null)
    if normalization_note is not None:
        notes.append(normalization_note)

    identifier_like = _is_identifier_like(column_name, series, non_null, unique_count, non_null_count)
    if identifier_like:
        notes.append("identifier-like values; avoid treating them as stable categories")
    elif non_null_count >= MIN_HIGH_CARDINALITY_ROWS and _is_high_cardinality_categorical(series, unique_count, non_null_count):
        notes.append("high-cardinality categorical values")

    datetime_note = _datetime_note(series, non_null)
    if datetime_note is not None:
        notes.append(datetime_note)

    if non_null_count >= 3 and _has_extreme_numeric_range(series):
        notes.append("extreme numeric range relative to the median")

    return notes


def _numeric_summary(series: pd.Series[Any]) -> dict[str, float | int | None] | None:
    if not is_numeric_dtype(series):
        return None
    clean = pd.to_numeric(series.dropna(), errors="coerce").dropna()
    if clean.empty:
        return None
    quantiles = clean.quantile([0.25, 0.5, 0.75])
    return {
        "min": float(clean.min()),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.5]),
        "mean": float(clean.mean()),
        "p75": float(quantiles.loc[0.75]),
        "max": float(clean.max()),
    }


def _top_values(series: pd.Series[Any]) -> tuple[tuple[str, int], ...]:
    if is_numeric_dtype(series):
        return ()
    counts = Counter(_stringify(value) for value in series.dropna().tolist())
    return tuple(counts.most_common(MAX_TOP_VALUES))


def _has_low_entropy(non_null: pd.Series[Any]) -> bool:
    if non_null.empty:
        return False
    proportions = non_null.astype(str).value_counts(normalize=True, dropna=True)
    if proportions.empty:
        return False
    return bool(proportions.iloc[0] >= 0.8 and len(proportions.index) <= max(3, int(len(non_null) * 0.2) + 1))


def _categorical_normalization_note(non_null: pd.Series[Any]) -> str | None:
    if non_null.empty:
        return None
    values = non_null.astype(str)
    if not any(any(character.isalpha() for character in value) for value in values):
        return None
    normalized = values.map(lambda value: re.sub(r"\s+", " ", value.strip().lower()))
    if normalized.nunique(dropna=True) < values.nunique(dropna=True):
        return "categorical normalization opportunity (casing/whitespace variants)"
    return None


def _is_identifier_like(column_name: str, series: pd.Series[Any], non_null: pd.Series[Any], unique_count: int, non_null_count: int) -> bool:
    if non_null_count < MIN_IDENTIFIER_ROWS or non_null_count == 0:
        return False
    if (unique_count / non_null_count) < 0.8:
        return False
    lower_name = column_name.lower()
    name_hint = any(hint in lower_name for hint in IDENTIFIER_NAME_HINTS)
    if is_numeric_dtype(series):
        return name_hint
    values = non_null.astype(str).str.strip()
    identifier_pattern_ratio = values.str.fullmatch(r"[A-Za-z]{0,8}[-_:/]?[0-9]{3,}").fillna(False).mean()
    hex_like_ratio = values.str.fullmatch(r"[0-9a-fA-F-]{8,}").fillna(False).mean()
    return bool(name_hint or identifier_pattern_ratio >= 0.8 or hex_like_ratio >= 0.8)


def _is_high_cardinality_categorical(series: pd.Series[Any], unique_count: int, non_null_count: int) -> bool:
    if not (is_object_dtype(series) or is_string_dtype(series)):
        return False
    return (unique_count / non_null_count) >= HIGH_CARDINALITY_RATIO


def _datetime_note(series: pd.Series[Any], non_null: pd.Series[Any]) -> str | None:
    if not _looks_like_datetime_text(series, non_null):
        return None
    if _has_mixed_datetime_formats(non_null):
        return "looks like datetime text stored as object/string; normalize mixed formats before parsing"
    return "looks like datetime text stored as object/string"


def _looks_like_datetime_text(series: pd.Series[Any], non_null: pd.Series[Any]) -> bool:
    if not (is_object_dtype(series) or is_string_dtype(series)):
        return False
    parsed = pd.to_datetime(non_null.astype(str), errors="coerce", format="mixed")
    return bool(parsed.notna().mean() >= 0.8)


def _has_mixed_datetime_formats(non_null: pd.Series[Any]) -> bool:
    shapes = {_datetime_shape(value) for value in non_null.astype(str) if value.strip()}
    return len(shapes) > 1


def _datetime_shape(value: str) -> str:
    return re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "9", value.strip()))


def _has_extreme_numeric_range(series: pd.Series[Any]) -> bool:
    if not is_numeric_dtype(series):
        return False
    clean = pd.to_numeric(series.dropna(), errors="coerce").dropna()
    if clean.empty:
        return False
    median = float(clean.median())
    scale = max(abs(median), 1.0)
    return (max(abs(float(clean.min())), abs(float(clean.max()))) / scale) >= 50.0


def _stringify(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
