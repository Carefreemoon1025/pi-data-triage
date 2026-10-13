#!/usr/bin/env python3
"""viz-craft · pick a plotly.express chart from the data's dtypes and render it.

Contract:
  stdout  -> exactly one JSON object
  stderr  -> human-readable text only
  exit    -> 0 ok / 2 usage / 3 load / 4 column mismatch / 5 missing dependency / 1 uncaught
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
from pandas.api.types import is_numeric_dtype  # noqa: E402

from loader import load_csv  # noqa: E402
from models import CsvLoadOptions, DatasetLoadError  # noqa: E402
from profiler import build_dataset_profile  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_LOAD = 3
EXIT_MISMATCH = 4
EXIT_DEPENDENCY = 5
EXIT_ERROR = 1

INTENTS = ("auto", "trend", "distribution", "correlation", "composition")
INTENT_KINDS = {
    "trend": ("line", "trend of a numeric measure over an ordered axis"),
    "distribution": ("histogram", "distribution of a single numeric column"),
    "correlation": ("scatter", "relationship between two numeric columns"),
    "composition": ("bar", "magnitude of a numeric measure across categories"),
}

# Cardinality / column-count thresholds. A category with more distinct values than
# MAX_CATEGORY_CARDINALITY is treated as an identifier-like axis: the bar chart
# degenerates into a barcode, so auto mode refuses it.
MAX_CATEGORY_CARDINALITY = 20
MAX_HEATMAP_COLUMNS = 12
# Above this many distinct values a "progression" numeric column (Year, level, period)
# is no longer credible as an ordered axis.
MAX_ORDERED_NUMERIC_CARDINALITY = 200
# A wide-range integer column whose name matches one of these still reads as a time axis.
ORDERED_NUMERIC_NAME_HINTS = ("year", "month", "quarter", "week", "day", "date", "time", "period", "hour", "epoch")
CORRELATION_FLATNESS = 0.35
DEFAULT_MAX_ROWS = 0
UNLIMITED_MAX_ROWS = None
DATETIME_NOTE_MARKER = "datetime"
LOW_CONFIDENCE_MARKER = "low-confidence"
HEATMAP_NOTE = "correlation coefficients only; the raw pairwise scatter matrix is not drawn."


class VizError(Exception):
    def __init__(self, code: str, message: str, hint: str, exit_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


def emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def fail(exc: VizError) -> int:
    emit({"ok": False, "error": {"code": exc.code, "message": exc.message, "hint": exc.hint}})
    print(f"viz-craft: {exc.message}", file=sys.stderr)
    print(f"viz-craft: hint — {exc.hint}", file=sys.stderr)
    return exc.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viz.py",
        description="Pick a plotly.express chart for a CSV/CSV.gz and render the figure JSON.",
        add_help=False,
    )
    parser.add_argument("--input", dest="input_path")
    parser.add_argument("--intent", dest="intent", default="auto", choices=INTENTS)
    parser.add_argument("--x", dest="x")
    parser.add_argument("--y", dest="y")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--max-rows", dest="max_rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("-h", "--help", action="store_true", dest="help_requested")
    return parser


def import_plotly() -> tuple[Any, Any]:
    """Imported lazily so a missing dependency exits 5 instead of dying at import time."""
    try:
        import plotly.express as px
        import plotly.io as pio
    except ImportError as exc:  # pragma: no cover - exercised only without plotly
        raise VizError(
            "dependency_missing",
            f"plotly is not importable in this interpreter: {exc}.",
            "Run the script with the project interpreter: .venv/bin/python skills/viz-craft/scripts/viz.py ...",
            EXIT_DEPENDENCY,
        ) from exc
    return px, pio


def classify_columns(profile: Any) -> dict[str, dict[str, Any]]:
    """Reuse the profiler's dtype judgement instead of inventing a second one."""
    kinds: dict[str, dict[str, Any]] = {}
    for column in profile.columns_profile:
        dtype = column.dtype
        has_datetime_note = any(DATETIME_NOTE_MARKER in note.lower() for note in column.notes)
        if dtype.startswith("datetime") or has_datetime_note:
            kind = "temporal"
        elif column.numeric_summary is not None or is_numeric_dtype(pd.Series([], dtype=dtype)):
            kind = "numeric"
        else:
            kind = "categorical"
        kinds[column.name] = {
            "kind": kind,
            "dtype": dtype,
            "unique_count": column.unique_count,
            "non_null_count": column.non_null_count,
            "null_pct": column.null_pct,
            "notes": tuple(column.notes),
        }
    return kinds


def find_column(frame: pd.DataFrame, raw: str, flag: str) -> str:
    if raw in frame.columns:
        return raw
    raise VizError(
        "unknown_column",
        f"Column {raw!r} (from {flag}) is not in this dataset.",
        "Available columns: " + ", ".join(repr(name) for name in frame.columns) + ".",
        EXIT_MISMATCH,
    )


def require_single(kinds: dict[str, dict[str, Any]], role: str, flag: str) -> str:
    candidates = [name for name, meta in kinds.items() if meta["kind"] == role]
    if not candidates:
        raise VizError(
            "no_matching_column",
            f"This dataset has no {role} column to use as the {flag} axis.",
            f"Pick another --intent, or pass an explicit column with {flag} that exists in the dataset.",
            EXIT_MISMATCH,
        )
    return candidates[0]


def numeric_columns(kinds: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, meta in kinds.items() if meta["kind"] == "numeric"]


def categorical_columns(kinds: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, meta in kinds.items() if meta["kind"] == "categorical"]


def density_only_numeric(kinds: dict[str, dict[str, Any]], numeric: list[str]) -> bool:
    """True when every numeric column is unique per row (an id, not a measurement)."""
    real_measures = [
        name
        for name in numeric
        if kinds[name]["non_null_count"] == 0
        or (kinds[name]["unique_count"] / max(kinds[name]["non_null_count"], 1)) < 0.99
    ]
    return not real_measures and bool(numeric)


def category_is_plottable(meta: dict[str, Any]) -> bool:
    return meta["unique_count"] <= MAX_CATEGORY_CARDINALITY


def ordered_axis(kinds: dict[str, dict[str, Any]], name: str) -> bool:
    meta = kinds[name]
    if meta["kind"] == "temporal":
        return True
    if meta["kind"] != "numeric":
        return False
    if meta["unique_count"] <= 1:
        return False
    if meta["unique_count"] <= MAX_ORDERED_NUMERIC_CARDINALITY:
        return True
    # A wide-range integer column named like a time unit (Year, Month, Quarter, Week) is
    # still a progression; cardinality alone would wrongly reject a decade-spanning year column.
    return meta["dtype"].startswith("int") and any(
        hint in name.lower() for hint in ORDERED_NUMERIC_NAME_HINTS
    )


def is_low_confidence(warnings: list[str]) -> bool:
    return any(LOW_CONFIDENCE_MARKER in warning for warning in warnings)


def new_chart(
    kind: str,
    x: str | None,
    y: str | None,
    reason: str,
    kinds: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "x": x,
        "y": y,
        "reason": reason,
        "encoding": {
            "x_type": kinds[x]["kind"] if x in kinds else "none",
            "y_type": kinds[y]["kind"] if y in kinds else "none",
        },
    }


def autoselect(
    kinds: dict[str, dict[str, Any]],
    numeric: list[str],
    categorical: list[str],
    temporal: list[str],
    x: str | None,
    y: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    # Stage A · the caller pinned a y measure.
    if y is not None:
        meta_y = kinds[y]
        if meta_y["kind"] != "numeric":
            raise VizError(
                "incompatible_column_type",
                f"--y {y!r} is {meta_y['kind']} (dtype {meta_y['dtype']!r}); a measured quantity must be numeric.",
                "Pass a numeric column as --y, or drop --y and let --intent auto pick both axes.",
                EXIT_MISMATCH,
            )
        if x is not None:
            return from_numeric_pair(kinds, x, y, warnings)
        measure = choose_ordered_axis(kinds, temporal, numeric, y)
        if measure is not None:
            return line_chart(kinds, measure, y, warnings)
        if categorical:
            return composition_chart(kinds, categorical, y, warnings)
        raise no_axis_error(kinds, "y")

    # Stage B · the caller pinned only x.
    if x is not None:
        meta_x = kinds[x]
        if meta_x["kind"] == "numeric":
            if ordered_axis(kinds, x) and len(numeric) >= 2:
                return line_chart(kinds, x, first_other(numeric, x), warnings)
            if len(numeric) >= 2:
                return from_numeric_pair(kinds, x, first_other(numeric, x), warnings)
            return distribution_chart(kinds, x, warnings, one_numeric_only=True)
        if categorical:
            if numeric:
                return composition_chart(kinds, [x], numeric[0], warnings)
            raise VizError(
                "no_matching_column",
                f"--x {x!r} is categorical but the dataset has no numeric column to measure.",
                "Add a numeric measure to the dataset, or use --intent distribution with a numeric column.",
                EXIT_MISMATCH,
            )
        # temporal
        if numeric:
            return line_chart(kinds, x, numeric[0], warnings)
        raise VizError(
            "no_matching_column",
            f"--x {x!r} is temporal but the dataset has no numeric column to plot against it.",
            "Add a numeric measure to the dataset, or plot a single numeric column with --intent distribution.",
            EXIT_MISMATCH,
        )

    # Stage C · both axes free.
    if temporal and numeric:
        if len(numeric) >= 2:
            return from_numeric_pair(kinds, temporal[0], numeric[0], warnings, penalize=True)
        return line_chart(kinds, temporal[0], numeric[0], warnings)

    if len(numeric) >= 3:
        return heatmap_chart(kinds, numeric, warnings, pair_count=len(numeric) * (len(numeric) - 1) // 2)

    if len(numeric) == 2:
        return scatter_chart(kinds, numeric[0], numeric[1], warnings)

    if len(numeric) == 1:
        return distribution_chart(kinds, numeric[0], warnings)

    if categorical and numeric:
        return composition_chart(kinds, categorical, numeric[0], warnings)

    raise VizError(
        "no_plottable_column",
        "This dataset has no numeric column, so no chart can be built from it.",
        "Provide a numeric measure column, or run the data-triage skill first to inspect the dataset.",
        EXIT_MISMATCH,
    )


def first_other(numeric: list[str], exclude: str) -> str:
    for name in numeric:
        if name != exclude:
            return name
    raise VizError(
        "no_matching_column",
        f"--x {exclude!r} is the only numeric column; a two-variable chart needs a second one.",
        "Add another numeric column, or use --intent distribution to plot this column alone.",
        EXIT_MISMATCH,
    )


def choose_ordered_axis(
    kinds: dict[str, dict[str, Any]], temporal: list[str], numeric: list[str], y: str
) -> str | None:
    if temporal:
        return temporal[0]
    for name in numeric:
        if name != y and ordered_axis(kinds, name):
            return name
    return None


def no_axis_error(kinds: dict[str, dict[str, Any]], flag: str) -> VizError:
    return VizError(
        "no_ordered_axis",
        f"No ordered axis is available for the {flag} measure: the dataset has no temporal column "
        "and no numeric column with a small enough set of distinct values.",
        "Pass --x with the column that orders the rows, or choose --intent distribution/correlation instead.",
        EXIT_MISMATCH,
    )


def from_numeric_pair(
    kinds: dict[str, dict[str, Any]], x: str, y: str, warnings: list[str], penalize: bool = False
) -> dict[str, Any]:
    meta_x = kinds[x]
    if meta_x["kind"] != "numeric":
        raise VizError(
            "incompatible_column_type",
            f"--x {x!r} is {meta_x['kind']} (dtype {meta_x['dtype']!r}) but a scatter/regression needs a numeric x.",
            "Pass a numeric --x, or use --intent composition for a categorical axis.",
            EXIT_MISMATCH,
        )
    if meta_x["unique_count"] < 3 or kinds[y]["unique_count"] < 3:
        warnings.append(
            f"{LOW_CONFIDENCE_MARKER}: {x!r} or {y!r} has fewer than 3 distinct values, "
            "so a scatter plot shows positions rather than a relationship."
        )
        return new_chart(
            "scatter",
            x,
            y,
            f"{x!r} and {y!r} are both numeric, but one of them is near-constant; scatter is shown at low confidence.",
            kinds,
        )
    if penalize:
        warnings.append(
            f"{LOW_CONFIDENCE_MARKER}: {x!r} looks like a timescale but carries {meta_x['unique_count']} distinct values; "
            f"summarizing {y!r} against it is dense, so a scatter of the raw points was preferred over a trend line."
        )
    return scatter_chart(kinds, x, y, warnings)


def apply_intent(
    kinds: dict[str, dict[str, Any]],
    numeric: list[str],
    categorical: list[str],
    temporal: list[str],
    intent: str,
    x: str | None,
    y: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    if intent == "trend":
        if y is not None and kinds[y]["kind"] != "numeric":
            raise VizError(
                "incompatible_column_type",
                f"--y {y!r} is {kinds[y]['kind']} (dtype {kinds[y]['dtype']!r}); a trend measures a numeric column.",
                'Pass a numeric --y, for example --y "CO₂ emissions per capita".',
                EXIT_MISMATCH,
            )
        measure = y
        if measure is None:
            # --x is the axis, never the measure, so prefer a numeric column other than it.
            measure = next((name for name in numeric if name != x), numeric[0] if numeric else None)
        if measure is None:
            raise VizError(
                "no_matching_column",
                "--intent trend needs a numeric column to measure, and this dataset has none.",
                "Add a numeric measure column, or pick another --intent.",
                EXIT_MISMATCH,
            )
        if x is not None and not ordered_axis(kinds, x):
            raise no_ordered_axis_error(kinds, x)
        axis = x if x is not None else choose_ordered_axis(kinds, temporal, numeric, measure)
        if axis is None:
            raise no_axis_error(kinds, "trend")
        return line_chart(kinds, axis, measure, warnings)

    if intent == "distribution":
        column = x if x is not None and kinds[x]["kind"] == "numeric" else y
        if column is None and numeric:
            column = numeric[0]
        if column is None:
            raise VizError(
                "no_matching_column",
                "--intent distribution needs one numeric column and this dataset has none.",
                "Add a numeric measure column, or pick another --intent.",
                EXIT_MISMATCH,
            )
        if kinds[column]["kind"] != "numeric":
            raise VizError(
                "incompatible_column_type",
                f"Column {column!r} is {kinds[column]['kind']} (dtype {kinds[column]['dtype']!r}); a distribution needs a numeric column.",
                f"Pass a numeric column via --x or --y, or use --intent composition for {column!r}.",
                EXIT_MISMATCH,
            )
        return distribution_chart(kinds, column, warnings, forced=True)

    if intent == "correlation":
        if x is not None and y is not None:
            return from_numeric_pair(kinds, x, y, warnings)
        if x is not None and kinds[x]["kind"] != "numeric":
            raise VizError(
                "incompatible_column_type",
                f"--x {x!r} is {kinds[x]['kind']} (dtype {kinds[x]['dtype']!r}); a correlation needs two numeric columns.",
                "Pass numeric --x and --y, or use --intent composition for a categorical axis.",
                EXIT_MISMATCH,
            )
        if y is not None and kinds[y]["kind"] != "numeric":
            raise VizError(
                "incompatible_column_type",
                f"--y {y!r} is {kinds[y]['kind']} (dtype {kinds[y]['dtype']!r}); a correlation needs two numeric columns.",
                "Pass numeric --x and --y, or use --intent composition for a categorical axis.",
                EXIT_MISMATCH,
            )
        pair = [name for name in (x, y) if name is not None]
        remaining = [name for name in numeric if name not in pair]
        pair.extend(remaining)
        if len(pair) < 2:
            raise VizError(
                "no_matching_column",
                "--intent correlation needs two numeric columns and this dataset has fewer than two.",
                "Add a second numeric column, or use --intent distribution to plot the single numeric column.",
                EXIT_MISMATCH,
            )
        return from_numeric_pair(kinds, pair[0], pair[1], warnings)

    # composition
    if y is not None and kinds[y]["kind"] != "numeric":
        raise VizError(
            "incompatible_column_type",
            f"--y {y!r} is {kinds[y]['kind']} (dtype {kinds[y]['dtype']!r}); a composition compares a numeric measure across categories.",
            "Pass a numeric --y, or drop --y and let the skill pick the numeric column.",
            EXIT_MISMATCH,
        )
    measure = y or (numeric[0] if numeric else None)
    if measure is None:
        raise VizError(
            "no_matching_column",
            "--intent composition needs one numeric measure and this dataset has none.",
            "Add a numeric measure column, or pick another --intent.",
            EXIT_MISMATCH,
        )
    if x is not None:
        if kinds[x]["kind"] == "numeric":
            raise VizError(
                "incompatible_column_type",
                f"--x {x!r} is numeric (dtype {kinds[x]['dtype']!r}); a composition bars categories, not measurements.",
                "Pass a categorical or temporal --x, or use --intent correlation for two numeric columns.",
                EXIT_MISMATCH,
            )
        return composition_chart(kinds, [x], measure, warnings)
    if not categorical:
        raise VizError(
            "no_matching_column",
            "--intent composition needs one non-numeric column to form the categories, and this dataset has none.",
            "Add a categorical column, or pick another --intent.",
            EXIT_MISMATCH,
        )
    return composition_chart(kinds, categorical, measure, warnings)


def no_ordered_axis_error(kinds: dict[str, dict[str, Any]], column: str) -> VizError:
    meta = kinds[column]
    return VizError(
        "no_ordered_axis",
        f"--intent trend needs a temporal or low-cardinality numeric axis, but {column!r} carries "
        f"{meta['unique_count']} distinct values and is not datetime-like.",
        "Pass --x with a time or level column, or use --intent correlation / distribution instead.",
        EXIT_MISMATCH,
    )


def line_chart(
    kinds: dict[str, dict[str, Any]], x: str, y: str, warnings: list[str], note: str | None = None
) -> dict[str, Any]:
    meta_x = kinds[x]
    if meta_x["kind"] == "categorical":
        raise VizError(
            "no_ordered_axis",
            f"--intent trend cannot use {x!r} as the axis: it is categorical (dtype {meta_x['dtype']!r}).",
            "Pass a time or level column via --x, or use --intent composition for a categorical axis.",
            EXIT_MISMATCH,
        )
    if meta_x["kind"] == "numeric" and not ordered_axis(kinds, x):
        warnings.append(
            f"{LOW_CONFIDENCE_MARKER}: {x!r} is numeric with {meta_x['unique_count']} distinct values; "
            "treating it as a progression is a guess, so the points are drawn in row order, not sorted."
        )
    elif meta_x["kind"] == "numeric":
        warnings.append(
            f"{LOW_CONFIDENCE_MARKER}: {x!r} was treated as an ordered axis by name and dtype "
            f"(numeric, {meta_x['unique_count']} distinct integer values); confirm it really is a progression."
        )
    if meta_x["notes"]:
        warnings.append(f"profiler notes on {x!r}: " + "; ".join(meta_x["notes"]))
    reason = note or f"{x!r} is an ordered axis ({meta_x['kind']}) and {y!r} is a numeric measure, so a line shows the trend of {y!r} over {x!r}."
    return new_chart("line", x, y, reason, kinds)


def composition_chart(kinds: dict[str, dict[str, Any]], categories: list[str], y: str, warnings: list[str]) -> dict[str, Any]:
    x = categories[0]
    meta_x = kinds[x]
    if not category_is_plottable(meta_x):
        warnings.append(
            f"{LOW_CONFIDENCE_MARKER}: {x!r} has {meta_x['unique_count']} distinct values (above the "
            f"{MAX_CATEGORY_CARDINALITY}-category bar-chart threshold), so the bars are unreadable; "
            "consider a histogram of the numeric column or pre-aggregating the categories."
        )
    reason = f"{x!r} is categorical ({meta_x['dtype']}) and {y!r} is numeric, so bars compare {y!r} across the categories of {x!r}."
    return new_chart("bar", x, y, reason, kinds)


def scatter_chart(kinds: dict[str, dict[str, Any]], x: str, y: str, warnings: list[str]) -> dict[str, Any]:
    reason = f"{x!r} and {y!r} are both numeric ({kinds[x]['dtype']}, {kinds[y]['dtype']}), so a scatter shows how the two measurements move together."
    return new_chart("scatter", x, y, reason, kinds)


def distribution_chart(
    kinds: dict[str, dict[str, Any]], column: str, warnings: list[str], forced: bool = False, one_numeric_only: bool = False
) -> dict[str, Any]:
    meta = kinds[column]
    uniqueness = meta["unique_count"] / max(meta["non_null_count"], 1)
    kind = "histogram" if meta["unique_count"] >= 3 else "box"
    if kind == "box":
        warnings.append(
            f"{LOW_CONFIDENCE_MARKER}: {column!r} has only {meta['unique_count']} distinct values, "
            "so a box renders its few values more legibly than a histogram."
        )
    if one_numeric_only:
        warnings.append(
            f"{LOW_CONFIDENCE_MARKER}: {column!r} is the only numeric column, so no two-variable chart was possible."
        )
    if forced:
        reason = f"--intent distribution: {column!r} is numeric, so its spread is shown as a {kind}."
    else:
        reason = f"{column!r} is the only numeric column in the dataset, so its distribution is shown as a {kind}."
    return new_chart(kind, column, None, reason, kinds)


def heatmap_chart(kinds: dict[str, dict[str, Any]], numeric: list[str], warnings: list[str], pair_count: int = 0) -> dict[str, Any]:
    warnings.append(
        f"{len(numeric)} numeric columns are available, so one correlation heatmap covers all "
        f"{pair_count} pairs at once instead of a single scatter."
    )
    warnings.append(HEATMAP_NOTE)
    reason = (
        f"the dataset has {len(numeric)} numeric columns, so a correlation heatmap covers every pair "
        "at once (kind=heatmap carries no single x/y pair; see encoding)."
    )
    return new_chart("heatmap", None, None, reason, kinds)


def build_figure(kinds: dict[str, dict[str, Any]], frame: pd.DataFrame, chart: dict[str, Any], warnings: list[str], px: Any) -> Any:
    kind = chart["kind"]
    x = chart["x"]
    y = chart["y"]
    if kind == "line":
        figure = px.line(frame, x=x, y=y)
    elif kind == "bar":
        figure = px.bar(frame, x=x, y=y)
    elif kind == "histogram":
        figure = px.histogram(frame, x=x)
    elif kind == "box":
        figure = px.box(frame, y=x if y is None else y)
    elif kind == "scatter":
        figure = px.scatter(frame, x=x, y=y)
    elif kind == "heatmap":
        columns = [name for name, meta in kinds.items() if meta["kind"] == "numeric"]
        if len(columns) > MAX_HEATMAP_COLUMNS:
            warnings.append(
                f"the correlation matrix was limited to the first {MAX_HEATMAP_COLUMNS} of {len(columns)} numeric columns."
            )
            columns = columns[:MAX_HEATMAP_COLUMNS]
        matrix = frame[columns].apply(pd.to_numeric, errors="coerce").corr()
        figure = px.imshow(matrix, text_auto=".2f", aspect="auto", color_continuous_scale="RdBu_r", zmin=-1, zmax=1)
    else:  # pragma: no cover - kind is chosen by this script only
        raise VizError(
            "unsupported_chart_kind",
            f"Internal error: no renderer for chart kind {kind!r}.",
            "Report this as a bug in viz-craft.",
            EXIT_ERROR,
        )
    figure.update_layout(title=chart["reason"], margin={"l": 60, "r": 30, "t": 60, "b": 50})
    return figure


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        print(__doc__, file=sys.stderr)
        return EXIT_USAGE

    if args.help_requested:
        print(__doc__, file=sys.stderr)
        return EXIT_USAGE

    if not args.input_path:
        return fail(
            VizError(
                "missing_input",
                "--input is required.",
                "Pass --input <path.csv|path.csv.gz>, for example --input sample_data/co2-emissions-per-capita.csv.gz.",
                EXIT_USAGE,
            )
        )

    input_path = Path(args.input_path)
    if not input_path.is_file():
        return fail(
            VizError(
                "input_not_found",
                f"Input file {str(input_path)!r} does not exist or is not a regular file.",
                "Check the path and re-run; relative paths resolve against the current working directory.",
                EXIT_USAGE,
            )
        )

    try:
        px, pio = import_plotly()

        # loader.load_csv rejects str paths, so the bytes are read here and handed over directly.
        raw = input_path.read_bytes()
        # --max-rows 0 or negative means "load every row"; CsvLoadOptions rejects 0 outright.
        max_rows = None if (args.max_rows is None or args.max_rows <= 0) else args.max_rows
        dataset = load_csv(raw, options=CsvLoadOptions(max_rows=max_rows))
        frame = dataset.dataframe

        profile = build_dataset_profile(frame)
        kinds = classify_columns(profile)
        warnings = [notice.message for notice in dataset.load.notices]
        if dataset.load.truncated:
            warnings.append(
                f"{LOW_CONFIDENCE_MARKER}: only the first {dataset.load.loaded_rows} rows were used; "
                "the chart does not cover the whole file."
            )

        numeric = numeric_columns(kinds)
        categorical = categorical_columns(kinds)
        temporal = [name for name, meta in kinds.items() if meta["kind"] == "temporal"]

        if density_only_numeric(kinds, numeric):
            warnings.append(
                f"{LOW_CONFIDENCE_MARKER}: every numeric column is distinct per row (identifier-like), "
                "so numeric charts describe identities rather than measurements."
            )

        if args.intent == "auto":
            chart = autoselect(kinds, numeric, categorical, temporal, args.x, args.y, warnings)
        else:
            chart = apply_intent(kinds, numeric, categorical, temporal, args.intent, args.x, args.y, warnings)

        if chart["x"] is None and chart["y"] is None and chart["kind"] != "heatmap":
            raise VizError(
                "no_plottable_column",
                f"No column pair could be resolved for chart kind {chart['kind']!r}.",
                "Pass --x and --y explicitly, or run the data-triage skill to inspect the columns.",
                EXIT_MISMATCH,
            )

        figure = build_figure(kinds, frame, chart, warnings, px)

        try:
            figure_json = json.loads(pio.to_json(figure))
        except (ValueError, TypeError) as exc:
            raise VizError(
                "figure_serialization_failed",
                f"The plotly figure could not be serialized to JSON: {exc}.",
                "Check the column values for types plotly cannot encode, then re-run.",
                EXIT_ERROR,
            ) from exc
    except VizError as exc:
        return fail(exc)
    except DatasetLoadError as exc:
        return fail(
            VizError(
                "dataset_load_failed",
                str(exc),
                "Re-export the file as UTF-8 CSV (optionally gzipped) and re-run.",
                EXIT_LOAD,
            )
        )
    except OSError as exc:
        return fail(
            VizError(
                "input_unreadable",
                f"Could not read {str(input_path)!r}: {exc}.",
                "Check file permissions, then re-run.",
                EXIT_USAGE,
            )
        )
    except Exception as exc:  # pragma: no cover - last-resort envelope
        return fail(
            VizError(
                "unexpected_error",
                f"{type(exc).__name__}: {exc}",
                "Re-run with a smaller --max-rows, or report the dataset shape that triggered this.",
                EXIT_ERROR,
            )
        )

    payload: dict[str, Any] = {"ok": True, "chart": chart, "figure": figure_json, "warnings": warnings}

    if args.output:
        output_path = Path(args.output)
        suffix = output_path.suffix.lower()
        if suffix not in (".json", ".html"):
            return fail(
                VizError(
                    "unsupported_output_format",
                    f"--output must end in .json or .html, got {str(output_path)!r}.",
                    "Pass --output chart.json for the figure spec, or --output chart.html for a standalone page.",
                    EXIT_USAGE,
                )
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if suffix == ".html":
                pio.write_html(figure, file=str(output_path), include_plotlyjs="cdn", full_html=True)
                output_path = output_path.resolve()
                payload["output"] = {"path": str(output_path), "format": "html", "bytes": output_path.stat().st_size}
                payload.pop("figure")
            else:
                output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                output_path = output_path.resolve()
                payload["output"] = {"path": str(output_path), "format": "json", "bytes": output_path.stat().st_size}
        except OSError as exc:
            return fail(
                VizError(
                    "output_write_failed",
                    f"Could not write {str(output_path)!r}: {exc}.",
                    "Check the directory exists and is writable, then re-run.",
                    EXIT_USAGE,
                )
            )

    if is_low_confidence(warnings) and "confidence" not in chart:
        chart["confidence"] = "low"
    elif "confidence" not in chart:
        chart["confidence"] = "high"

    emit(payload)
    print(
        f"viz-craft: {chart['kind']} x={chart['x']!r} y={chart['y']!r} — {chart['reason']}",
        file=sys.stderr,
    )
    for warning in warnings:
        print(f"viz-craft: warning — {warning}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
