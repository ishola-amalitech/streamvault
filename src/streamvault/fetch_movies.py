
import os
import httpx


BASE_URL = "https://api.themoviedb.org/3"


def fetch_movie(
    client: httpx.Client,
    movie_id: str
) -> dict[str, object] | None:

    response = client.get(f"/movie/{movie_id}")

    if response.status_code == 404:
        return None

    response.raise_for_status()

    return response.json()


def fetch_movies(movie_ids: list[str]) -> tuple[list[dict[str, object]], list[str]]:
    if not movie_ids:
        raise ValueError("movie_ids list is empty.")     
    if "TMDB_API_READ_ACCESS_TOKEN" not in os.environ:
        raise EnvironmentError("TMDB_API_READ_ACCESS_TOKEN environment variable is not set.")
    read_token = os.environ["TMDB_API_READ_ACCESS_TOKEN"]
    headers = {
        "Authorization": f"Bearer {read_token}",
        "accept": "application/json"
    }
    records: list[dict[str, object]] = []
    missing: list[str] = []

    with httpx.Client(
        base_url=BASE_URL,
        headers=headers,
        timeout=httpx.Timeout(10.0, connect=3.05)
    ) as client:

        for movie_id in movie_ids:
            try:
                movie = fetch_movie(client, movie_id)

                if movie is None:
                    missing.append(movie_id)
                else:
                    records.append(movie)

            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"HTTP error for {movie_id}: {e.response.status_code} - {e.response.text}") from e

            except httpx.RequestError as e:
                raise RuntimeError(f"Network error for {movie_id}: {e}") from e
    return records, missing
    


if __name__ == "__main__":
    records, missing = fetch_movies(["550", "603", "27205"])
    print("Fetched records:")
    for record in records:
        print(record)
    print("\nMissing movie IDs:")
    for movie_id in missing:
        print(movie_id)
