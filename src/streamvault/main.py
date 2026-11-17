import asyncio

from streamvault.cache import load_cached_records, write_cached_records
from streamvault.config import CONFIG
from streamvault.fetch_movies import fetch_movies
from streamvault.load import iter_movie_ids


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
        records, missing, failures = await fetch_movies(ids_to_fetch)
    else:
        records, missing, failures = [], [], []
    if records or missing_timestamps:
        write_cached_records(
            CONFIG.cache_file, [*cached_records.values(), *records]
        )
    if missing_timestamps:
        print(f"Added cache timestamps to existing records: {missing_timestamps}")

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