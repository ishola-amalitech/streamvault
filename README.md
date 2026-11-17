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
