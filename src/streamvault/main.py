import asyncio
from datetime import datetime, timezone
from time import perf_counter

from streamvault.cache import load_cached_records, write_cached_records
from streamvault.config import CONFIG
from streamvault.fetch_movies import fetch_movies
from streamvault.load import iter_movie_ids
from streamvault.run_record import read_record, snapshot_inputs, write_record


async def run() -> None:
    movie_ids = list(iter_movie_ids(CONFIG.source_file, CONFIG.removals_file))
    cached_records = load_cached_records(CONFIG.cache_file)
    missing_timestamps = sum(
        not isinstance(record.get("cached_at_utc"), str)
        for record in cached_records.values()
    )

    if not movie_ids:
        if missing_timestamps:
            write_cached_records(CONFIG.cache_file, cached_records.values())
            print(f"Added cache timestamps to existing records: {missing_timestamps}")
        print("No movie IDs to fetch.")
        return

    cached_ids = set(cached_records)
    already_cached = sum(movie.value in cached_ids for movie in movie_ids)
    ids_to_fetch = [movie for movie in movie_ids if movie.value not in cached_ids]

    if ids_to_fetch:
        fetch_start = perf_counter()
        records, missing, failures = await fetch_movies(ids_to_fetch)
        fetch_seconds = perf_counter() - fetch_start
    else:
        records, missing, failures = [], [], []
    if records or missing_timestamps:
        write_cached_records(
            CONFIG.cache_file, [*cached_records.values(), *records]
        )
    if missing_timestamps:
        print(f"Added cache timestamps to existing records: {missing_timestamps}")

    if ids_to_fetch:
        recorded_at = datetime.now(timezone.utc).isoformat()
        record_path = CONFIG.cache_file.with_suffix(".acquisition.json")
        unresolved = read_record(record_path).get("unresolved_by_id", {})
        # Keep the last observed result per ID until a lookup replaces it or we get the film.
        for movie_id in (*cached_ids, *(str(record["id"]) for record in records)):
            unresolved.pop(movie_id.lstrip("0"), None)
        source_lines = {movie.value: movie.source_line for movie in ids_to_fetch}
        for item in missing:
            unresolved[item.movie_id.lstrip("0")] = {
                "status": "lookup_miss", "reason": item.reason,
                "source_line": item.source_line, "recorded_at_utc": recorded_at,
            }
        for failure in failures:
            unresolved[failure.movie_id.lstrip("0")] = {
                "status": "request_failed", "reason": failure.message,
                "source_line": source_lines[failure.movie_id], "recorded_at_utc": recorded_at,
            }
        write_record(record_path, {
            "recorded_at_utc": recorded_at,
            "input_sha256": snapshot_inputs(CONFIG),
            "fetch_seconds": fetch_seconds,
            "requested": len(ids_to_fetch),
            "fetched": len(records),
            "lookup_misses": len(missing),
            "request_failures": len(failures),
            "unresolved_by_id": unresolved,
        })

    print(f"Movie IDs in source: {len(movie_ids)}")
    print(f"Already cached: {already_cached}")
    print(f"New records fetched: {len(records)}")
    print(f"Missing movie IDs: {len(missing)}")
    for item in missing:
        print(f"line {item.source_line}, {item.movie_id}: {item.reason}")

    print(f"Failed requests: {len(failures)}")
    for failure in failures:
        print(f"{failure.movie_id}: {failure.message}")


def main() -> None:
    asyncio.run(run())

if __name__ == "__main__":
    main()
