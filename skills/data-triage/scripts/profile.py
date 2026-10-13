#!/usr/bin/env python3
"""data-triage skill CLI: profile a CSV/CSV.gz file and print one JSON object.

stdout carries exactly one JSON envelope; every human-readable line goes to stderr.
Exit codes: 0 ok, 2 usage, 3 load failure, 4 column/argument mismatch,
5 missing dependency, 1 uncaught.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import zlib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_LOAD_ERROR = 3
EXIT_MISMATCH = 4
EXIT_MISSING_DEPENDENCY = 5

PROFILE_FIELDS = (
    "rows",
    "columns",
    "duplicate_rows",
    "numeric_summary",
    "categorical_top_values",
    "columns_profile",
    "suspicious_columns",
    "details",
)

_MISMATCH_CODES = {"column_not_found"}
_MISSING_DEPENDENCY_MODULES = {"pandas", "numpy"}


class UsageError(Exception):
    """argv-level problem: missing input, unreadable path, bad option value."""

    def __init__(self, code: str, message: str, hint: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


class DependencyError(Exception):
    def __init__(self, code: str, message: str, hint: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _parse_max_rows(raw: str) -> int | None:
    """No --max-rows, `0`, or `all` mean 'no limit'. A positive integer is a cap."""
    text = str(raw).strip().lower()
    if text in ("", "all", "none"):
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise UsageError(
            "invalid_max_rows",
            f"--max-rows expects a positive integer, 0, or 'all'; got {raw!r}.",
            "Drop the flag to profile every row, or pass e.g. --max-rows 5000.",
        ) from exc
    if value == 0:
        return None
    if value < 0:
        raise UsageError(
            "invalid_max_rows",
            f"--max-rows must not be negative; got {value}.",
            "Use a positive integer as an upper bound, or 0/all for no limit.",
        )
    return value


class _ArgumentParser(argparse.ArgumentParser):
    """argparse normally exits(2) with an empty stdout; the caller needs the JSON envelope."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(
            "invalid_arguments",
            f"Invalid arguments: {message}",
            "Usage: profile.py --input <path.csv[.gz]> [--output <path.json>] "
            "[--separator ,] [--encoding utf-8] [--no-header] [--max-rows N].",
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _ArgumentParser(
        prog="profile.py",
        description="Profile a CSV/CSV.gz dataset and print one JSON object on stdout.",
    )
    parser.add_argument("--input", required=True, help="Path to a .csv or .csv.gz file.")
    parser.add_argument("--output", default=None, help="Also write the same JSON object to this path.")
    parser.add_argument("--separator", default=",", help="CSV field separator (default: ',').")
    parser.add_argument("--encoding", default="utf-8", help="Text encoding of the CSV (default: utf-8).")
    parser.add_argument("--no-header", action="store_true", help="Treat the first row as data (default: first row is the header).")
    parser.add_argument(
        "--max-rows",
        default=None,
        help="Upper bound on profiled rows. Omit, or pass 0/all, to profile every row.",
    )
    return parser.parse_args(argv)


def _resolve_input(raw_input: str) -> tuple[Path, bytes]:
    path = Path(raw_input).expanduser()
    if not path.exists():
        raise UsageError(
            "input_not_found",
            f"Input file not found: {raw_input}",
            "Check the path, or pass an existing .csv/.csv.gz file with --input.",
        )
    if path.is_dir():
        raise UsageError(
            "input_not_a_file",
            f"Input path is a directory, not a file: {raw_input}",
            "Point --input at a .csv or .csv.gz file.",
        )
    try:
        return path, path.read_bytes()
    except OSError as exc:
        raise UsageError(
            "input_unreadable",
            f"Could not read input file {raw_input}: {exc}",
            "Check file permissions, or copy the file somewhere readable.",
        ) from exc


def _load_modules() -> tuple[Any, Any, Any]:
    try:
        from loader import load_csv
        from models import CsvLoadOptions, DatasetLoadError
        from profiler import build_dataset_profile
    except ImportError as exc:
        module = (getattr(exc, "name", "") or "").split(".")[0]
        code = "missing_dependency" if module in _MISSING_DEPENDENCY_MODULES else "import_failed"
        raise DependencyError(
            code,
            f"Cannot import the pi-data-triage modules: {exc}",
            "Run this script with the project interpreter, e.g. <repo>/.venv/bin/python "
            "skills/data-triage/scripts/profile.py --input <file>.",
        ) from exc
    return load_csv, CsvLoadOptions, DatasetLoadError, build_dataset_profile


def _profile_to_dict(profile: Any) -> dict[str, Any]:
    """Frozen dataclasses have no asdict method; shape them explicitly.

    dataclasses.asdict turns tuples into lists, and the contract fixes every
    sequence as a JSON list, so recursive list conversion is deliberate.
    """
    payload = {field_name: getattr(profile, field_name) for field_name in PROFILE_FIELDS}
    return json.loads(json.dumps(payload, default=_json_default))


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _classify_load_error(exc: Exception) -> tuple[str, str]:
    """Reuse the loader's own error semantics rather than inventing a new taxonomy."""
    message = str(exc)
    lowered = message.lower()
    if "empty" in lowered:
        return "empty_file", EXIT_LOAD_ERROR
    if "decompress" in lowered or "gzip" in lowered:
        return "gzip_error", EXIT_LOAD_ERROR
    if "decoded with encoding" in lowered or "unknown text encoding" in lowered:
        return "encoding_error", EXIT_LOAD_ERROR
    if message.lower().startswith("csv parse error"):
        return "csv_parse_error", EXIT_LOAD_ERROR
    if "separator must be" in lowered or "row limit must be" in lowered or "large-file warning" in lowered:
        return "invalid_load_option", EXIT_MISMATCH
    if "unsupported upload type" in lowered:
        return "unsupported_input", EXIT_LOAD_ERROR
    return "load_failed", EXIT_LOAD_ERROR


def _emit(payload: dict[str, Any], stream: Any) -> None:
    json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
    stream.write("\n")
    stream.flush()


def _failure(code: str, message: str, hint: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "hint": hint}}


def _write_output(payload: dict[str, Any], raw_output: str) -> None:
    target = Path(raw_output).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
    except OSError as exc:
        raise UsageError(
            "output_not_writable",
            f"Could not write --output {raw_output}: {exc}",
            "Pick a writable path, or drop --output and read the JSON from stdout.",
        ) from exc


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        if not args.separator:
            raise UsageError(
                "invalid_separator",
                "--separator must be a non-empty string.",
                "Pass e.g. --separator ';' for semicolon-separated files.",
            )
        max_rows = _parse_max_rows(args.max_rows) if args.max_rows is not None else None
        input_path, raw_bytes = _resolve_input(args.input)
        load_csv, CsvLoadOptions, DatasetLoadError, build_dataset_profile = _load_modules()
    except UsageError as exc:
        _emit(_failure(exc.code, exc.message, exc.hint), sys.stdout)
        print(f"error: {exc.message}", file=sys.stderr)
        return EXIT_USAGE
    except DependencyError as exc:
        _emit(_failure(exc.code, exc.message, exc.hint), sys.stdout)
        print(f"error: {exc.message}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY

    options = CsvLoadOptions(
        separator=args.separator,
        encoding=args.encoding,
        has_header=not args.no_header,
        max_rows=max_rows,
    )

    try:
        loaded = load_csv(raw_bytes, options=options)
    except DatasetLoadError as exc:
        code, exit_code = _classify_load_error(exc)
        hint = (
            "Retry with --encoding <name> or --separator <char> if the file uses a "
            "different dialect, then re-run."
            if exit_code == EXIT_LOAD_ERROR
            else "Adjust the load options and re-run."
        )
        _emit(_failure(code, str(exc), hint), sys.stdout)
        print(f"error: {exc}", file=sys.stderr)
        return exit_code
    except (zlib.error, EOFError) as exc:
        # gzip.decompress raises zlib.error, which is not an OSError, so loader.py's
        # `except OSError` misses a corrupt/truncated stream. Map it to the same
        # gzip_error semantics the loader uses instead of letting it escape as uncaught.
        message = (
            "The uploaded .gz file could not be decompressed. "
            f"Please upload a valid gzip-compressed CSV. ({exc})"
        )
        _emit(
            _failure(
                "gzip_error",
                message,
                "Re-download the file, or gunzip it first and pass the plain .csv.",
            ),
            sys.stdout,
        )
        print(f"error: {message}", file=sys.stderr)
        return EXIT_LOAD_ERROR

    profile = build_dataset_profile(loaded.dataframe)

    payload: dict[str, Any] = {
        "ok": True,
        "dataset": {
            "name": loaded.upload.name or input_path.name,
            "size_bytes": loaded.upload.size_bytes,
            "fingerprint": loaded.upload.fingerprint,
        },
        "load": {
            "loaded_rows": loaded.load.loaded_rows,
            "row_limit": loaded.load.row_limit,
            "truncated": loaded.load.truncated,
            "notices": [
                {"level": notice.level, "code": notice.code, "message": notice.message}
                for notice in loaded.load.notices
            ],
        },
        "profile": _profile_to_dict(profile),
    }

    if args.output:
        try:
            _write_output(payload, args.output)
        except UsageError as exc:
            _emit(_failure(exc.code, exc.message, exc.hint), sys.stdout)
            print(f"error: {exc.message}", file=sys.stderr)
            return EXIT_USAGE

    for notice in loaded.load.notices:
        print(f"[{notice.level}] {notice.code}: {notice.message}", file=sys.stderr)
    print(
        f"profiled {profile.rows:,} rows x {profile.columns} columns "
        f"from {payload['dataset']['name']}",
        file=sys.stderr,
    )

    _emit(payload, sys.stdout)
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BrokenPipeError:
        sys.exit(EXIT_UNEXPECTED)
    except BaseException as exc:  # noqa: BLE001 - last-resort envelope for the Agent
        _emit(_failure("unexpected_error", f"{type(exc).__name__}: {exc}", "Re-run with a smaller --max-rows or report this traceback."), sys.stdout)
        print(f"unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(EXIT_UNEXPECTED)
