"""Read and save the raw TMDB responses, one JSON object per line."""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from streamvault.load import MovieId, is_tmdb_movie_id
from streamvault.removals import Removal
from streamvault.run_record import write_text_atomic


@dataclass
class CandidateCache:
    records: dict[str, dict[str, object]]
    other_records: dict[str, dict[str, object]]
    repeated_ids: list[str]

    def uniqueness_check(self) -> tuple[bool, str]:
        return (
            not self.repeated_ids,
            f"{len(self.records)} candidates already cached. "
            f"{len(self.repeated_ids)} repeated IDs. Examples: {self.repeated_ids[:5]}.",
        )


def _movie_id(record: dict[str, object]) -> str:
    value = record.get("id")
    # JSON true and false are not movie IDs, even though Python treats them as integers.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Cached movie records must have a numeric 'id'.")

    # Use the same key format and range as the CSV parser.
    movie_id = str(value).lstrip("0")
    if not is_tmdb_movie_id(movie_id):
        raise ValueError("Cached movie records must have a positive numeric 'id' within TMDB's range.")
    return movie_id


def iter_cached_records(path: str | Path) -> Iterator[tuple[str, dict[str, object]]]:
    """Read each cache entry so a caller can check for repeated IDs."""
    cache_path = Path(path)
    try:
        cache_file = cache_path.open(encoding="utf-8")
    except FileNotFoundError:
        # A fresh run starts with an empty cache.
        return

    with cache_file:
        for line_number, line in enumerate(cache_file, start=1):
            if not line.strip():
                continue
            try:
                record: object = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON in {cache_path} at line {line_number}: "
                    f"{error.msg}"
                ) from error

            # JSON object keys are already strings.
            if not isinstance(record, dict):
                raise ValueError(
                    f"Expected a JSON object in {cache_path} at line {line_number}."
                )

            record_dict = cast(dict[str, object], record)
            yield _movie_id(record_dict), record_dict


def load_cached_records(path: str | Path) -> dict[str, dict[str, object]]:
    """Load the whole cache and reject repeated movie IDs."""
    records: dict[str, dict[str, object]] = {}
    for movie_id, record in iter_cached_records(path):
        if movie_id in records:
            raise ValueError(f"Repeated movie ID {movie_id} in {path}.")
        records[movie_id] = record
    return records


def match_cached_candidates(
    cached_entries: Iterable[tuple[str, dict[str, object]]],
    source_rows: Iterable[MovieId | Removal],
) -> CandidateCache:
    """Match validated cache keys to the current list and report repeated IDs."""
    candidate_ids = {row.value for row in source_rows if isinstance(row, MovieId)}
    records: dict[str, dict[str, object]] = {}
    other_records: dict[str, dict[str, object]] = {}
    repeated_ids: set[str] = set()
    for key, record in cached_entries:
        if key in candidate_ids:
            # Record repeats before the dictionary can hide them.
            if key in records:
                repeated_ids.add(key)
            records[key] = record
        else:
            other_records[key] = record
    return CandidateCache(records, other_records, sorted(repeated_ids))


def write_cached_records(
    path: str | Path, records: Iterable[dict[str, object]]
) -> dict[str, dict[str, object]]:
    """Save one record per movie ID and return the exact records that were written."""
    records_by_id: dict[str, dict[str, object]] = {}
    # This is the time of the cache write, shared by the batch.
    cached_at_utc = datetime.now(timezone.utc).isoformat()
    for record in records:
        # Preserve existing timestamps and leave the caller's records untouched.
        cached_record = dict(record)
        if not isinstance(cached_record.get("cached_at_utc"), str):
            cached_record["cached_at_utc"] = cached_at_utc
        records_by_id[_movie_id(cached_record)] = cached_record

    # Write one JSON line at a time so we don't build a second copy of the whole cache.
    lines = (
        json.dumps(record, ensure_ascii=False) + "\n"
        for record in records_by_id.values()
    )
    write_text_atomic(Path(path), lines)
    return records_by_id
