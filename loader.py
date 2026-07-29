from __future__ import annotations

import gzip
import hashlib
from io import BytesIO
from typing import Any, BinaryIO

import pandas as pd
from pandas.errors import EmptyDataError, ParserError

try:
    from .models import CsvLoadMetadata, CsvLoadOptions, DatasetLoadError, LoadedDataset, LoadNotice, UploadMetadata
except ImportError:  # pragma: no cover - supports `streamlit run examples/dataset_triage/app.py`
    from models import CsvLoadMetadata, CsvLoadOptions, DatasetLoadError, LoadedDataset, LoadNotice, UploadMetadata


UploadLike = bytes | bytearray | memoryview | BinaryIO | Any


def load_csv(uploaded_file: UploadLike, *, options: CsvLoadOptions | None = None) -> LoadedDataset:
    load_options = options or CsvLoadOptions()
    _validate_load_options(load_options)

    raw_bytes = _read_uploaded_bytes(uploaded_file)
    if not raw_bytes:
        raise DatasetLoadError("The uploaded file is empty. Please choose a CSV or CSV.gz file with data.")

    csv_bytes = _maybe_decompress_gzip(raw_bytes)
    if not csv_bytes:
        raise DatasetLoadError("The uploaded file is empty. Please choose a CSV or CSV.gz file with data.")

    metadata = UploadMetadata(
        name=_optional_string(getattr(uploaded_file, "name", None)),
        content_type=_optional_string(getattr(uploaded_file, "type", None)),
        size_bytes=len(raw_bytes),
        fingerprint=hashlib.sha256(csv_bytes).hexdigest(),
    )

    try:
        dataframe = pd.read_csv(
            BytesIO(csv_bytes),
            sep=load_options.separator,
            encoding=load_options.encoding,
            header=0 if load_options.has_header else None,
            nrows=(load_options.max_rows + 1) if load_options.max_rows is not None else None,
            on_bad_lines="error",
        )
    except EmptyDataError as exc:
        raise DatasetLoadError("The uploaded file is empty. Please choose a CSV or CSV.gz file with data.") from exc
    except UnicodeDecodeError as exc:
        raise DatasetLoadError(
            f"The uploaded file could not be decoded with encoding {load_options.encoding!r}. Please choose the correct encoding."
        ) from exc
    except LookupError as exc:
        raise DatasetLoadError(f"Unknown text encoding: {load_options.encoding!r}.") from exc
    except ParserError as exc:
        raise DatasetLoadError(f"CSV parse error: {exc}") from exc
    except ValueError as exc:
        raise DatasetLoadError(f"Could not read the CSV file: {exc}") from exc

    notices: list[LoadNotice] = []
    truncated = False
    if load_options.max_rows is not None and len(dataframe) > load_options.max_rows:
        dataframe = dataframe.iloc[: load_options.max_rows].copy()
        truncated = True
        notices.append(
            LoadNotice(
                level="warning",
                code="row_limit",
                message=f"Profiled only the first {load_options.max_rows:,} rows to keep the local example bounded.",
            )
        )

    if load_options.large_file_warning_bytes is not None and len(raw_bytes) >= load_options.large_file_warning_bytes:
        size_text = _format_bytes(len(raw_bytes))
        if load_options.max_rows is not None:
            message = f"Large upload detected ({size_text}); profiling uses at most the first {load_options.max_rows:,} rows."
        else:
            message = f"Large upload detected ({size_text}); local parsing and profiling may take longer than the bundled sample."
        notices.append(LoadNotice(level="warning", code="large_file", message=message))

    load_metadata = CsvLoadMetadata(
        options=load_options,
        loaded_rows=int(dataframe.shape[0]),
        row_limit=load_options.max_rows,
        truncated=truncated,
        notices=tuple(notices),
    )

    return LoadedDataset(dataframe=dataframe, upload=metadata, load=load_metadata)


def _validate_load_options(options: CsvLoadOptions) -> None:
    if not options.separator:
        raise DatasetLoadError("CSV separator must be a non-empty string.")
    if options.max_rows is not None and options.max_rows <= 0:
        raise DatasetLoadError("CSV row limit must be greater than zero when provided.")
    if options.large_file_warning_bytes is not None and options.large_file_warning_bytes <= 0:
        raise DatasetLoadError("Large-file warning threshold must be greater than zero when provided.")


def _read_uploaded_bytes(uploaded_file: UploadLike) -> bytes:
    if isinstance(uploaded_file, bytes):
        return uploaded_file
    if isinstance(uploaded_file, bytearray):
        return bytes(uploaded_file)
    if isinstance(uploaded_file, memoryview):
        return uploaded_file.tobytes()
    if hasattr(uploaded_file, "getvalue"):
        value = uploaded_file.getvalue()
        if isinstance(value, str):
            return value.encode("utf-8")
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
    if hasattr(uploaded_file, "read"):
        payload = uploaded_file.read()
        if isinstance(payload, str):
            return payload.encode("utf-8")
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)
    raise DatasetLoadError("Unsupported upload type. Please provide CSV/CSV.gz bytes or a file-like object.")


def _maybe_decompress_gzip(raw_bytes: bytes) -> bytes:
    if not raw_bytes.startswith(b"\x1f\x8b"):
        return raw_bytes
    try:
        return gzip.decompress(raw_bytes)
    except OSError as exc:
        raise DatasetLoadError("The uploaded .gz file could not be decompressed. Please upload a valid gzip-compressed CSV.") from exc


def _format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KiB"
    return f"{size_bytes / (1024 * 1024):.1f} MiB"


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
