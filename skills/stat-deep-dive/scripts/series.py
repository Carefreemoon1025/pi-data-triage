"""Numeric-matrix and time-series preparation for stat-deep-dive.

Kept free of sklearn/statsmodels imports so a missing modelling dependency can never
break argument handling or the loader path.
"""

from __future__ import annotations

import math
from typing import Any

try:
    from .errors import EXIT_MISMATCH, EXIT_USAGE, StatError
except ImportError:
    from errors import EXIT_MISMATCH, EXIT_USAGE, StatError

# An axis whose unique values cover this share of its rows is treated as a "dense
# axis" (a genuine variable), not as a time key. Panel data such as
# co2-emissions-per-capita (231 entities x 230 years) falls on the dense side, so
# auto-selection never mistakes it for a per-observation index.
DENSE_AXIS_RATIO = 0.5


def select_numeric_columns(dataframe: Any) -> list[str]:
    from pandas.api.types import is_numeric_dtype

    return [str(name) for name in dataframe.columns if is_numeric_dtype(dataframe[name])]


def select_features(dataframe: Any, names: list[str]) -> list[str]:
    """Drop columns that carry one value per row: they are identifiers, not features."""
    selected: list[str] = []
    rows = max(int(dataframe.shape[0]), 1)
    for name in names:
        unique = int(dataframe[name].nunique(dropna=True))
        if unique / rows >= DENSE_AXIS_RATIO:
            continue
        selected.append(name)
    return selected


def build_series(dataframe: Any, requested: list[str] | None, *, method: str) -> dict[str, Any]:
    from pandas.api.types import is_numeric_dtype

    all_columns = [str(name) for name in dataframe.columns]
    numeric_columns = select_numeric_columns(dataframe)

    if requested is None:
        non_numeric: list[str] = []
        if method == "decompose":
            index_column = _pick_index_column(dataframe, numeric_columns)
            if index_column is None:
                raise StatError(
                    "index_column_required",
                    (
                        "No numeric column in this dataset reads as a time key "
                        "(every numeric column carries one distinct value per row)."
                    ),
                    "Pass --columns with exactly one name to decompose that column against its row position.",
                    EXIT_MISMATCH,
                )
            selected = [name for name in numeric_columns if name != index_column]
        else:
            index_column = None
            selected = select_features(dataframe, numeric_columns)
            non_numeric = [name for name in all_columns if name not in selected]
            if not selected:
                raise StatError(
                    "no_numeric_columns",
                    "This dataset exposes no numeric column usable for PCA or KMeans.",
                    "Pass --columns with numeric column names.",
                    EXIT_MISMATCH,
                )
        return _assemble(dataframe, selected, index_column, non_numeric, method)

    found_missing = [name for name in requested if name not in all_columns]
    if found_missing:
        raise StatError(
            "columns_not_found",
            f"Column(s) not found in this dataset: {found_missing}.",
            f"Columns available: {all_columns}.",
            EXIT_MISMATCH,
        )

    non_numeric = [name for name in requested if not is_numeric_dtype(dataframe[name])]
    if non_numeric:
        raise StatError(
            "non_numeric_column",
            f"Column(s) are not numeric and cannot enter a numeric matrix: {non_numeric}.",
            f"Numeric columns: {numeric_columns}.",
            EXIT_MISMATCH,
        )

    if method == "decompose":
        if len(requested) != 1:
            raise StatError(
                "decompose_needs_one_column",
                f"--method decompose takes exactly one numeric column; got {len(requested)}: {requested}.",
                "Pass a single column, e.g. --columns \"CO₂ emissions per capita\".",
                EXIT_USAGE,
            )
        return _assemble(dataframe, requested, None, [], method)

    if len(requested) < 2:
        raise StatError(
            "too_few_columns",
            f"--method {method} needs at least 2 numeric columns; got {len(requested)}: {requested}.",
            "Pass comma-separated numeric column names, e.g. --columns \"A,B,C\".",
            EXIT_MISMATCH,
        )
    return _assemble(dataframe, requested, None, [name for name in all_columns if name not in requested], method)


def _pick_index_column(dataframe: Any, numeric_columns: list[str]) -> str | None:
    rows = max(int(dataframe.shape[0]), 1)
    best: tuple[int, str] | None = None
    for name in numeric_columns:
        unique = int(dataframe[name].nunique(dropna=True))
        if unique / rows >= DENSE_AXIS_RATIO:
            continue
        if best is None or unique > best[0]:
            best = (unique, name)
    return best[1] if best else None


def _assemble(
    dataframe: Any,
    selected: list[str],
    index_column: str | None,
    non_numeric: list[str],
    method: str,
) -> dict[str, Any]:
    """Return the numeric matrix, the resolved time index and the drop accounting."""
    columns_used = [index_column, *selected] if index_column is not None else list(selected)
    frame = dataframe[columns_used]
    total_rows = int(frame.shape[0])
    clean = frame.dropna()
    null_rows = total_rows - int(clean.shape[0])

    if int(clean.shape[0]) == 0:
        raise StatError(
            "no_rows_after_dropna",
            f"All {total_rows} row(s) were dropped because {columns_used} contains missing values.",
            "Choose --columns that have no missing values, or clean the dataset first.",
            EXIT_MISMATCH,
        )

    index: list[Any] = [int(value) for value in clean[index_column].tolist()] if index_column is not None else list(range(int(clean.shape[0])))
    value_frame = clean[selected]
    values = value_frame.to_numpy(dtype=float) if method == "decompose" else value_frame

    return {
        "columns_used": columns_used,
        "features": selected,
        "index": index,
        "values": values,
        "dense": method != "decompose",
        "rows": int(clean.shape[0]),
        "dropped": {
            "non_numeric": list(non_numeric),
            "null_rows": int(null_rows),
            "duplicate_time_key_rows": 0,
        },
    }


def one_value_per_index(values: Any, index: list[Any], column_name: str) -> list[float]:
    """Aggregate to exactly one observation per time key.

    Panel data repeats the same time key across entities, so a raw y-over-row vector
    would interleave unrelated series. Mean-per-key keeps the observation order
    distinct while summarising the repeats. A key that still carries more than one
    row per entity is a panel violation: reporting it beats silently averaging.
    """
    seen: dict[Any, float] = {}
    counts: dict[Any, int] = {}
    for position, key in enumerate(index):
        value = float(values[position][0])
        seen[key] = seen.get(key, 0.0) + value
        counts[key] = counts.get(key, 0) + 1

    for key in index:
        if counts[key] > 1:
            raise StatError(
                "duplicate_time_key",
                (
                    f"Time key {key!r} occurs {counts[key]} times for column {column_name!r}: "
                    "this is panel data, not a single time series."
                ),
                (
                    "Seasonal decomposition needs one observation per period. Collapse the repeats first "
                    "(e.g. group by the time key and take the mean at the Entity level), then re-run."
                ),
                EXIT_MISMATCH,
            )
    return [seen[key] / counts[key] for key in index]


def as_float_list(values: Any) -> list[float]:
    """JSON-safe floats: NaN/inf become null, matching a list-shaped numeric column."""
    output: list[float | None] = []
    for value in values:
        number = float(value)
        output.append(number if math.isfinite(number) else None)
    return output  # type: ignore[return-value]
