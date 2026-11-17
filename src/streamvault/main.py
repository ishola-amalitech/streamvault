import asyncio
from pathlib import Path

from streamvault.fetch_movies import fetch_movies
from streamvault.load import iter_movie_ids


async def run() -> None:
    csv_path = Path(__file__).resolve().parents[2] / "id_list.csv"
    records, missing, failures = await fetch_movies(iter_movie_ids(csv_path))

    if not (records or missing or failures):
        print("No movie IDs to fetch.")
        return

    processed = len(records) + len(missing) + len(failures)
    print(f"Processed movie IDs: {processed}")
    print(f"Fetched records: {len(records)}")
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