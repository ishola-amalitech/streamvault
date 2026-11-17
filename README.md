# Streamvault

## Fetch movie data

Set `TMDB_API_READ_ACCESS_TOKEN`, then run:

```sh
uv run streamvault
```

Fetched movie responses are saved as JSONL in `data/raw/movies.jsonl`. Later
runs use those cached responses and only request IDs that are not already
cached. To refresh existing records, remove the cache file before running the
command again.

## Explore the dataset

Launch the project notebook with:

```sh
uv run jupyter lab notebooks/explore_movies.ipynb
```

The notebook reads the local cache and does not make API requests. Run
`uv run streamvault` first if the cache does not exist yet.

The `movies` DataFrame has one row per movie. The notebook exposes reference
DataFrames for `genres`, `companies`, `countries`, `languages`, `collections`,
and `people`. Movie relationships are stored in bridge DataFrames such as
`movie_genres` and `movie_production_countries`. `cast_credits` and
`crew_credits` retain each credit by its `credit_id`. Join a bridge to its
reference DataFrame by the entity ID, and then to `movies` by `movie_id`.
Release dates are parsed as
datetimes, blank text values become missing values, and `movies.collection_id`
references the `collections` DataFrame. `companies.origin_country_code` also
references `countries`. Person popularity remains on credit rows because it
varies across the cached movie responses.

Project decisions and the plain-language rationale are recorded in [DECISIONS.md](DECISIONS.md).

Cached raw movie responses include a UTC `cached_at_utc` timestamp. Existing cache entries without timestamps are backfilled the next time `uv run streamvault` runs. The backfill time is when the existing record was timestamped, not its original fetch time.

Requests have timeouts and retry temporary network, rate-limit, and server errors. A TMDB 404 is added to the local removal log and does not stop the rest of the batch.
