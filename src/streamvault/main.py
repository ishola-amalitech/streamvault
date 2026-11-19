"""Run the StreamVault pipeline from the candidate CSV through the TMDB cache."""

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from typing import cast

from streamvault.cache import load_cached_records, write_cached_records
from streamvault.config import CONFIG
from streamvault.fetch_movies import FetchFailure, FetchMissing, fetch_movies
from streamvault.load import iter_movie_ids
from streamvault.run_record import read_record, snapshot_inputs, write_record


async def run() -> None:
    """Download missing titles, update the cache, and record what happened."""
    # Reading the list also logs blank, invalid, and duplicate entries.
    movie_ids = list(iter_movie_ids(CONFIG.source_file, CONFIG.removals_file))
    cached_records = load_cached_records(CONFIG.cache_file)
    missing_timestamps = sum(
        not isinstance(record.get("cached_at_utc"), str)
        for record in cached_records.values()
    )

    ids_to_fetch = [movie for movie in movie_ids if movie.value not in cached_records]
    records: list[dict[str, object]] = []
    missing: list[FetchMissing] = []
    failures: list[FetchFailure] = []
    fetch_seconds: float | None = None
    if ids_to_fetch:
        # Time the fetch step before writing the cache and run report.
        fetch_start = perf_counter()
        records, missing, failures = await fetch_movies(ids_to_fetch)
        fetch_seconds = perf_counter() - fetch_start

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


def main() -> None:
    """Start the downloader when someone runs the streamvault command."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
