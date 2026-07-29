from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd


class DatasetLoadError(ValueError):
    """Raised when an uploaded dataset cannot be loaded safely."""


NoticeLevel = Literal["info", "warning"]


@dataclass(frozen=True)
class LoadNotice:
    level: NoticeLevel
    code: str
    message: str


@dataclass(frozen=True)
class CsvLoadOptions:
    separator: str = ","
    encoding: str = "utf-8"
    has_header: bool = True
    max_rows: int | None = 5000
    large_file_warning_bytes: int | None = 5_000_000


@dataclass(frozen=True)
class UploadMetadata:
    name: str | None
    content_type: str | None
    size_bytes: int
    fingerprint: str


@dataclass(frozen=True)
class CsvLoadMetadata:
    options: CsvLoadOptions
    loaded_rows: int
    row_limit: int | None
    truncated: bool
    notices: tuple[LoadNotice, ...] = ()


@dataclass(frozen=True)
class LoadedDataset:
    dataframe: pd.DataFrame
    upload: UploadMetadata
    load: CsvLoadMetadata

    @property
    def load_signature(self) -> tuple[str | None, str | None, str, str, str, bool]:
        return (
            self.upload.name,
            self.upload.content_type,
            self.upload.fingerprint,
            self.load.options.separator,
            self.load.options.encoding,
            self.load.options.has_header,
        )


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    dtype: str
    non_null_count: int
    null_count: int
    null_pct: float
    unique_count: int
    sample_values: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    numeric_summary: dict[str, float | int | None] | None = None
    top_values: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class DatasetProfile:
    rows: int
    columns: int
    duplicate_rows: int
    numeric_summary: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    categorical_top_values: dict[str, tuple[tuple[str, int], ...]] = field(default_factory=dict)
    columns_profile: tuple[ColumnProfile, ...] = ()
    suspicious_columns: tuple[ColumnProfile, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
