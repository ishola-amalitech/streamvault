import json
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast


def _movie_id(record: dict[str, object]) -> str:
    value = record.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Cached movie records must have a numeric 'id'.")

    movie_id = str(value)
    if not movie_id.isascii() or not movie_id.isdecimal() or int(movie_id) <= 0:
        raise ValueError("Cached movie records must have a positive numeric 'id'.")
    return movie_id


def load_cached_records(path: str | Path) -> dict[str, dict[str, object]]:
    cache_path = Path(path)
    if not cache_path.exists():
        return {}

    records: dict[str, dict[str, object]] = {}
    with cache_path.open(encoding="utf-8") as cache_file:
        for line_number, line in enumerate(cache_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON in {cache_path} at line {line_number}: "
                    f"{error.msg}"
                ) from error

            if not isinstance(record, dict) or not all(
                isinstance(key, str) for key in record
            ):
                raise ValueError(
                    f"Expected a JSON object in {cache_path} at line {line_number}."
                )

            record_dict = cast(dict[str, object], record)
            records[_movie_id(record_dict)] = record_dict
    return records


def write_cached_records(
    path: str | Path, records: Iterable[dict[str, object]]
) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    records_by_id: dict[str, dict[str, object]] = {}
    cached_at_utc = datetime.now(timezone.utc).isoformat()
    for record in records:
        cached_record = dict(record)
        if not isinstance(cached_record.get("cached_at_utc"), str):
            cached_record["cached_at_utc"] = cached_at_utc
        records_by_id[_movie_id(cached_record)] = cached_record

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            for record in records_by_id.values():
                temporary_file.write(json.dumps(record, ensure_ascii=False))
                temporary_file.write("\n")

        if temporary_path is None:
            raise RuntimeError("The temporary cache file was not created.")
        os.replace(temporary_path, cache_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
