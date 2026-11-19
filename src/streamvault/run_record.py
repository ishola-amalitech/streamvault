import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from streamvault.config import AppConfig


def fingerprint(path: Path) -> str | None:
    try:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    except FileNotFoundError:
        return None


def snapshot_inputs(config: AppConfig) -> dict[str, str | None]:
    return {
        "source": fingerprint(config.source_file),
        "cache": fingerprint(config.cache_file),
        "removals": fingerprint(config.removals_file),
    }


def read_record(path: Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(record, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return record


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        # A stopped write should leave the earlier report readable.
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            temp.write(text)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_record(path: Path, record: dict) -> None:
    write_text_atomic(path, json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
