"""File fingerprints and safe writes for pipeline and analysis reports."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
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


def write_text_atomic(path: Path, text: str | Iterable[str]) -> None:
    """Replace a file only after all the new text has been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        # Keep the temporary file beside the destination so it can replace it in one step.
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            if isinstance(text, str):
                temp.write(text)
            else:
                temp.writelines(text)
        os.replace(temp_path, path)
    finally:
        # An error while writing should leave the old file and remove the unfinished one.
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_record(path: Path, record: Mapping[str, object]) -> None:
    text = json.dumps(dict(record), indent=2, ensure_ascii=False, allow_nan=False)
    write_text_atomic(path, text + "\n")
