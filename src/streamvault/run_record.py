"""File fingerprints and safe writes for pipeline and analysis reports."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from streamvault.config import AppConfig


def fingerprint(path: Path) -> str | None:
    """Return a SHA-256 fingerprint of the file contents, if the file exists."""
    try:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    except FileNotFoundError:
        return None


def snapshot_inputs(config: AppConfig) -> dict[str, str | None]:
    """Record which versions of the source list, cache, and log a run used."""
    return {
        "source": fingerprint(config.source_file),
        "cache": fingerprint(config.cache_file),
        "removals": fingerprint(config.removals_file),
    }


def acquisition_record_path(config: AppConfig) -> Path:
    """Read new fetch reports or replay a snapshot saved before the move to out/."""
    if config.acquisition_file.is_file():
        return config.acquisition_file
    return config.cache_file.with_suffix(".acquisition.json")


def read_record(path: Path) -> dict[str, Any]:
    """Read a JSON report. Its fields depend on which report was saved."""
    try:
        record: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # The first run has no earlier report to read.
        return {}
    if not isinstance(record, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return cast(dict[str, Any], record)


@contextmanager
def atomic_output_path(path: Path) -> Iterator[Path]:
    """Give the report writer a temporary path and publish it on success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temporary file sits beside the destination so it can replace it in one step.
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        yield temp_path
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_text_atomic(path: Path, text: str | Iterable[str]) -> None:
    """Replace a file only after all the new text has been written."""
    with atomic_output_path(path) as temp_path, temp_path.open("w", encoding="utf-8") as temp:
        if isinstance(text, str):
            temp.write(text)
        else:
            temp.writelines(text)


def write_record(path: Path, record: Mapping[str, object]) -> None:
    text = json.dumps(dict(record), indent=2, ensure_ascii=False, allow_nan=False)
    write_text_atomic(path, text + "\n")
