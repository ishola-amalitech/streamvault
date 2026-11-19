"""Run the StreamVault pipeline from the candidate CSV through normalization."""

import asyncio
from collections import Counter
from datetime import datetime, timezone
from time import perf_counter
from typing import cast

from streamvault.cache import iter_cached_records, write_cached_records
from streamvault.config import CONFIG
from streamvault.diagnostics import print_check_report, run_data_checks
from streamvault.fetch_movies import FetchFailure, FetchMissing, fetch_movies
from streamvault.load import iter_movie_ids
from streamvault.normalize import normalization_checks, normalize_movie_records
from streamvault.run_record import read_record, snapshot_inputs, write_record


async def run() -> None:
    """Download missing titles, update the cache, and validate the movie tables."""
    # Reading the list also logs blank, invalid, and duplicate entries.
    movie_ids = list(iter_movie_ids(CONFIG.source_file, CONFIG.removals_file))
    candidate_ids = {movie.value for movie in movie_ids}
    cached_records: dict[str, dict[str, object]] = {}
    cached_candidates: Counter[str] = Counter()
    for key, record in iter_cached_records(CONFIG.cache_file):
        movie_key = key.lstrip("0")
        # Count candidate records before the dictionary can hide duplicates.
        if movie_key in candidate_ids:
            cached_candidates[movie_key] += 1
        cached_records[movie_key] = record
    duplicate_ids = sorted(key for key, count in cached_candidates.items() if count > 1)
    stage = "After loading"
    print_check_report(stage, run_data_checks(stage, {
        "Current candidate IDs are unique in the cache": (
            not duplicate_ids,
            f"{len(cached_candidates)} candidates already cached. "
            f"{len(duplicate_ids)} repeated IDs. Examples: {duplicate_ids[:5]}.",
        ),
    }))
    missing_timestamps = sum(
        not isinstance(record.get("cached_at_utc"), str)
        for record in cached_records.values()
    )

    ids_to_fetch = [movie for movie in movie_ids if movie.value not in cached_records]
    records: list[dict[str, object]] = []
    missing: list[FetchMissing] = []
    failures: list[FetchFailure] = []
    fetched_records: dict[str, dict[str, object]] = {}
    fetch_seconds: float | None = None
    if ids_to_fetch:
        # Time the fetch step before writing the cache and run report.
        fetch_start = perf_counter()
        records, missing, failures = await fetch_movies(ids_to_fetch)
        fetch_seconds = perf_counter() - fetch_start
        # Check the results before caching them. A miss or a failed request still accounts for an ID.
        returned_ids = [str(record.get("id")).lstrip("0") for record in records]
        outcomes = Counter(returned_ids)
        outcomes.update(item.movie_id for item in missing)
        outcomes.update(item.movie_id for item in failures)
        requested = {movie.value for movie in ids_to_fetch}
        missing_ids = sorted(requested - outcomes.keys())
        extra_ids = sorted(outcomes.keys() - requested)
        repeated_ids = sorted(key for key, count in outcomes.items() if count > 1)
        stage = "After fetching"
        print_check_report(stage, run_data_checks(stage, {
            "Each requested ID has exactly one outcome": (
                not (missing_ids or extra_ids or repeated_ids),
                f"{len(requested)} requested, {outcomes.total()} outcomes. "
                f"Missing: {missing_ids[:5]}. Unexpected: {extra_ids[:5]}. "
                f"Repeated: {repeated_ids[:5]}.",
            ),
        }))
        fetched_records = dict(zip(returned_ids, records, strict=True))

    # Writing the cache also adds timestamps to records saved by older versions.
    if records or missing_timestamps:
        write_cached_records(
            CONFIG.cache_file, [*cached_records.values(), *records]
        )
    if missing_timestamps:
        print(f"Added cache timestamps to existing records: {missing_timestamps}")

    if not movie_ids:
        print("No movie IDs to fetch.")
        return

    # Keep the previous download report if this run used only cached movies.
    if fetch_seconds is not None:
        recorded_at = datetime.now(timezone.utc).isoformat()
        record_path = CONFIG.cache_file.with_suffix(".acquisition.json")
        saved_unresolved: object = read_record(record_path).get("unresolved_by_id", {})
        if not isinstance(saved_unresolved, dict):
            raise ValueError(f"Expected an object for 'unresolved_by_id' in {record_path}.")
        unresolved = cast(dict[str, object], saved_unresolved)

        # Keep the last observed result per ID until a lookup replaces it or we get the film.
        for movie_id in (*cached_records, *(str(record["id"]) for record in records)):
            unresolved.pop(movie_id.lstrip("0"), None)
        source_lines = {movie.value: movie.source_line for movie in ids_to_fetch}
        for item in missing:
            unresolved[item.movie_id.lstrip("0")] = {
                "status": "lookup_miss",
                "reason": item.reason,
                "source_line": item.source_line,
                "recorded_at_utc": recorded_at,
            }
        for failure in failures:
            unresolved[failure.movie_id.lstrip("0")] = {
                "status": "request_failed",
                "reason": failure.message,
                "source_line": source_lines[failure.movie_id],
                "recorded_at_utc": recorded_at,
            }
        write_record(
            record_path,
            {
                "recorded_at_utc": recorded_at,
                "input_sha256": snapshot_inputs(CONFIG),
                "fetch_seconds": fetch_seconds,
                "requested": len(ids_to_fetch),
                "fetched": len(records),
                "lookup_misses": len(missing),
                "request_failures": len(failures),
                "unresolved_by_id": unresolved,
            },
        )

    print(f"Movie IDs in source: {len(movie_ids)}")
    print(f"Already cached: {len(movie_ids) - len(ids_to_fetch)}")
    print(f"New records fetched: {len(records)}")
    print(f"Missing movie IDs: {len(missing)}")
    for item in missing:
        print(f"line {item.source_line}, {item.movie_id}: {item.reason}")

    print(f"Failed requests: {len(failures)}")
    for failure in failures:
        print(f"{failure.movie_id}: {failure.message}")

    # The cache can contain films from older lists. Validate only today's resolved candidates.
    available_records = cached_records | fetched_records
    resolved_ids = candidate_ids & available_records.keys()
    tables = normalize_movie_records(
        record for key, record in available_records.items() if key in resolved_ids
    )
    stage = "After normalization"
    print_check_report(stage, normalization_checks(stage, tables, resolved_ids))


def main() -> None:
    """Start the pipeline when someone runs the streamvault command."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
