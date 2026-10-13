#!/usr/bin/env python3
"""stat-deep-dive · PCA / KMeans / seasonal decomposition over a CSV or CSV.gz.

stdout carries exactly one JSON object; every human-readable line goes to stderr.

Contract
    python3 stat.py --input <path.csv[.gz]> --method {pca,kmeans,decompose}
                    [--columns A,B,C] [--n-components N] [--n-clusters N]
                    [--period N] [--output <path.json>]

Exit codes
    0 success · 2 usage (missing argv / missing input file) · 3 load failure
    4 column or parameter mismatch · 5 missing optional dependency · 1 anything else
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Per-load guard: the bundled sample is 26,509 rows and the default limit is 5,000.
MAX_LOAD_ROWS = 10_000_000

try:
    from .errors import (  # type: ignore[import-not-found]
        EXIT_DEPENDENCY,
        EXIT_MISMATCH,
        EXIT_USAGE,
        StatError,
    )
    from .series import as_float_list, build_series, one_value_per_index  # type: ignore[import-not-found]
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from errors import EXIT_DEPENDENCY, EXIT_MISMATCH, EXIT_USAGE, StatError
    from series import as_float_list, build_series, one_value_per_index


# --------------------------------------------------------------------------- io


def emit(payload: dict[str, Any], output: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text)


def fail(code: str, message: str, hint: str, exit_code: int) -> None:
    print(json.dumps({"ok": False, "error": {"code": code, "message": message, "hint": hint}}, ensure_ascii=False))
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)


# ------------------------------------------------------------------- structure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat.py",
        description="PCA / KMeans / seasonal decomposition over a CSV or CSV.gz.",
    )
    parser.add_argument("--input", required=True, help="path to a .csv or .csv.gz file")
    parser.add_argument("--method", required=True, choices=("pca", "kmeans", "decompose"))
    parser.add_argument("--columns", default=None, help="comma-separated column names; default = every numeric column")
    parser.add_argument("--n-components", dest="n_components", type=int, default=None)
    parser.add_argument("--n-clusters", dest="n_clusters", type=int, default=None)
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--output", default=None, help="also write the JSON object to this path")
    return parser


def parse_columns(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    names = [part.strip() for part in raw.split(",")]
    return [name for name in names if name]


def requested_column_error(names: list[str], dataframe_columns: list[str]) -> str:
    missing = [name for name in names if name not in dataframe_columns]
    if not missing:
        return ""
    return f"Column(s) not found in this dataset: {missing}."


def describe_available(dataframe: Any) -> str:
    from pandas.api.types import is_numeric_dtype

    numeric = [str(name) for name in dataframe.columns if is_numeric_dtype(dataframe[name])]
    preview = numeric[:12]
    suffix = f" (+{len(numeric) - len(preview)} more)" if len(numeric) > len(preview) else ""
    return f"Columns available: {[str(name) for name in dataframe.columns]}. Numeric columns: {preview}{suffix}."


# ------------------------------------------------------------------- profiling


def numeric_summary(series: Any) -> dict[str, float] | None:
    """Mirror profiler._numeric_summary so field spellings stay identical."""
    clean = series.dropna()
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


def profile_excerpt(dataframe: Any, numeric_columns: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in numeric_columns:
        values = numeric_summary(dataframe[name])
        if values is not None:
            summary[str(name)] = values
    return {"numeric_summary": summary}


# -------------------------------------------------------------------- methods


def run_pca(matrix: Any, names: list[str], n_components: int) -> dict[str, Any]:
    from sklearn.decomposition import PCA

    model = PCA(n_components=n_components)
    model.fit(matrix)

    components = model.components_
    loadings = {
        str(name): [float(value) for value in components[component]]
        for component, name in enumerate(names)
    }
    return {
        "explained_variance": [float(value) for value in model.explained_variance_],
        "explained_variance_ratio": [float(value) for value in model.explained_variance_ratio_],
        "loadings": loadings,
    }


def run_kmeans(matrix: Any, names: list[str], n_clusters: int) -> dict[str, Any]:
    from sklearn.cluster import KMeans

    model = KMeans(n_clusters=n_clusters, n_init=10, random_state=0)
    labels = model.fit_predict(matrix)

    sizes = [int((labels == index).sum()) for index in range(n_clusters)]
    centroids = {
        str(name): [float(value) for value in model.cluster_centers_[:, position]]
        for position, name in enumerate(names)
    }
    return {
        "n_clusters": int(n_clusters),
        "inertia": float(model.inertia_),
        "cluster_sizes": sizes,
        "centroids": centroids,
    }


def run_decompose(
    index: list[Any],
    values: list[float],
    period: int,
    series_label: str,
) -> dict[str, Any]:
    import numpy as np
    from statsmodels.tsa.seasonal import seasonal_decompose

    series = np.asarray(values, dtype=float)
    if series.size < 2 * period:
        raise StatError(
            "period_too_large",
            (
                f"--period {period} needs at least {2 * period} observations after aggregation, "
                f"but the resolved series for {series_label!r} has {series.size}."
            ),
            f"Lower --period, or point --columns at a series with more distinct time values than {series.size}.",
            EXIT_MISMATCH,
        )

    decomposition = seasonal_decompose(series, model="additive", period=period, extrapolate_trend="freq")
    index_out = [int(value) if isinstance(value, int) else value for value in index]
    return {
        "period": int(period),
        "index": index_out,
        "trend": as_float_list(decomposition.trend),
        "seasonal": as_float_list(decomposition.seasonal),
        "resid": as_float_list(decomposition.resid),
    }


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.is_file():
        fail(
            "input_not_found",
            f"Input file does not exist: {args.input}",
            "Pass --input with the path to an existing .csv or .csv.gz file.",
            EXIT_USAGE,
        )

    columns_arg = parse_columns(args.columns)
    if columns_arg is not None and not columns_arg:
        fail(
            "empty_columns",
            "--columns was given but lists no column name.",
            'Pass comma-separated names, e.g. --columns "Year,CO₂ emissions per capita".',
            EXIT_USAGE,
        )
    if args.method == "decompose" and args.columns is None:
        fail(
            "columns_required",
            "--method decompose needs exactly one numeric column in --columns.",
            'Name the single series to decompose, e.g. --columns "CO₂ emissions per capita".',
            EXIT_USAGE,
        )
    if args.method == "pca" and args.n_components is not None and args.n_components < 1:
        fail("bad_n_components", "--n-components must be at least 1.", "Pass a positive integer.", EXIT_USAGE)
    if args.method == "kmeans" and args.n_clusters is not None and args.n_clusters < 1:
        fail("bad_n_clusters", "--n-clusters must be at least 1.", "Pass a positive integer.", EXIT_USAGE)
    if args.method == "decompose" and args.period is not None and args.period < 2:
        fail("bad_period", "--period must be at least 2.", "Pass an integer of 2 or more.", EXIT_USAGE)

    raw_bytes = input_path.read_bytes()  # loader.load_csv rejects str paths (loader.py:121)

    for candidate in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parent):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    from loader import load_csv
    from models import CsvLoadOptions, DatasetLoadError
    from profiler import build_dataset_profile

    try:
        loaded = load_csv(raw_bytes, options=CsvLoadOptions(max_rows=MAX_LOAD_ROWS))
    except DatasetLoadError as exc:
        fail("load_failed", str(exc), "Check that the file is a valid UTF-8 CSV or gzip-compressed CSV.", 3)

    dataframe = loaded.dataframe
    profile = build_dataset_profile(dataframe)
    all_columns = [str(name) for name in dataframe.columns]

    if columns_arg is not None:
        error = requested_column_error(columns_arg, all_columns)
        if error:
            fail("columns_not_found", error, describe_available(dataframe), EXIT_MISMATCH)

    try:
        data = build_series(dataframe, columns_arg, method=args.method)
    except StatError as exc:
        fail(exc.code, exc.message, exc.hint, exc.exit_code)

    used = list(data["columns_used"])

    if args.method == "pca":
        n_components = args.n_components or len(used)
        if n_components > len(used):
            fail(
                "n_components_too_large",
                f"--n-components {n_components} exceeds the {len(used)} numeric column(s) in use.",
                f"Pass --n-components between 1 and {len(used)}, or add more numeric columns via --columns.",
                EXIT_MISMATCH,
            )
        result = run_pca(data["values"], used, n_components)
    elif args.method == "kmeans":
        n_clusters = args.n_clusters or 3
        if n_clusters > data["rows"]:
            fail(
                "n_clusters_too_large",
                f"--n-clusters {n_clusters} exceeds the {data['rows']} usable row(s).",
                "Lower --n-clusters, or drop rows with missing values so more rows remain.",
                EXIT_MISMATCH,
            )
        result = run_kmeans(data["values"], used, n_clusters)
    else:
        period = args.period or 12
        result = run_decompose(
            data["index"],
            one_value_per_index(data["values"], data["index"], used[0]),
            period,
            used[0],
        )

    singular = profile.numeric_summary if profile.numeric_summary else {}
    excerpt = {"numeric_summary": {str(name): dict(values) for name, values in singular.items()}}

    emit(
        {
            "ok": True,
            "method": args.method,
            "input": {
                "rows": int(data["rows"]),
                "columns_used": used,
                "dropped": data["dropped"],
            },
            "result": result,
            "profile_excerpt": excerpt,
        },
        args.output,
    )
    print(
        f"stat-deep-dive {args.method}: {data['rows']} row(s) x {len(used)} column(s); "
        f"dropped {data['dropped']['null_rows']} null row(s), {len(data['dropped']['non_numeric'])} non-numeric column(s).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort envelope so stdout stays parseable
        try:
            from errors import StatError as _StatError
        except ImportError:  # pragma: no cover
            _StatError = None  # type: ignore[assignment]
        if _StatError is not None and isinstance(exc, _StatError):
            fail(exc.code, exc.message, exc.hint, exc.exit_code)
        if isinstance(exc, ImportError):
            fail(
                "dependency_missing",
                f"A required dependency is not installed: {exc}",
                "Install the packages listed in the skill's requirements (scikit-learn, statsmodels, pandas, numpy).",
                EXIT_DEPENDENCY,
            )
        fail("unexpected_error", f"{type(exc).__name__}: {exc}", "Re-run with the same arguments to confirm; report the stderr line if it repeats.", 1)
