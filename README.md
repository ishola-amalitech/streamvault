# StreamVault

StreamVault is a data-analysis lab about a fictional $14M back-catalog licensing decision. Kwame Boateng needs a recommendation on franchise bundles versus standalone films, a shortlist, a read on talent signals, and a relative-value note. Yaw in Finance requires a separate comparison for films released from 2000 onward. [Local lab brief](data/lab_brief.md)

## Run locally

From the repository root, use Python 3.14 and [uv](https://docs.astral.sh/uv/). Install the locked dependencies, then set `TMDB_API_READ_ACCESS_TOKEN` to your TMDB API read access token and run the acquisition command.

```sh
uv sync --locked
uv run --locked streamvault
uv run --locked jupyter lab
```

You can also set the token in a local `.env` file and use `uv run --locked --env-file .env streamvault`. Keep the token outside tracked files.

The fetch command reads [id_list.csv](id_list.csv), requests movie details with appended credits, and saves responses to `data/raw/movies.jsonl`. It records invalid, blank, duplicate, and missing inputs in `id_list_removals.csv`. When the command fetches titles, it saves the elapsed fetch time and the latest unresolved outcomes by ID in `data/raw/movies.acquisition.json`. Keep these files with the input CSV and cache for an exact rerun. The cache and logs stay local. Configuration, including the request limits and local paths, lives in [config.toml](config.toml).

Later fetches reuse cached IDs. To refresh them, archive the current cache, then move it out of the configured path before running the fetch command again. Notebook 04 filters the cache to the current candidate list. Use a separate cache and removal log when profiling or exploring a new list in notebooks 01–03, which read the whole cache.

## Notebook order

| Notebook | Purpose | Status |
| --- | --- | --- |
| [01 Prep](notebooks/01_prep_movie_data.ipynb) | Normalize responses, validate keys and joins, and reconcile each source row. | Runs against the local cache and removal log. |
| [02 Profile](notebooks/02_profile_movie_data.ipynb) | Profile schema, duplicates, missingness, value ranges, and candidate data types. | Complete for the current snapshot. |
| [03 EDA](notebooks/03_eda_movie_data.ipynb) | Explore numeric, genre, collection, and talent patterns and review plausible extremes. | Complete for the current snapshot. |
| [04 Recommendation](notebooks/04_recommendation.ipynb) | Apply a fixed ranking method to both windows and produce shortlists and a deal note. | Candidate audit, ranking, comparisons, talent review, and scoring stress tests are complete. The memo and deal note follow. |

Run each analysis notebook from the top in its own kernel. The first three notebooks load their respective inputs directly from the configured local paths. The current snapshot reconciles **127 list rows to 112 distinct cached titles**, with 71 titles from 2000 onward. [Findings log](docs/findings.md)

Save Notebook 04 and use **Run All** for comparable timings. It writes the four full candidate tables and `run.json` under `data/raw/movies.recommendation/`. The run record includes the input and code fingerprints, settings, counts, and seconds spent on each part of the cached analysis. The timer starts in the first code cell and stops after the candidate tables and file fingerprints are ready. The CLI measures fetching separately.

To compare the current snapshot with 500 test titles, run the command below. It measures both sizes in separate Python processes and saves the per-stage timings and the 500-title estimate in `benchmark.json`. TMDB fetching and test-cache setup are outside the timing. Run Notebook 04 again to see the comparison table for the matching code and inputs.

```sh
uv run --locked python scripts/benchmark_recommendation.py
```

Run the package tests with this command.

```sh
uv run --locked python -m unittest discover -s tests
```

## Project records

- [Findings](docs/findings.md) ranks issues by decision risk and traces them to evidence and handling.
- [Recommendation exclusions](docs/recommendation_exclusions.md) lists source rows left out before scoring and films that missed either shortlist. Notebook 04 updates it on each run.
- [Questions](docs/questions.md) records answers drawn from the brief, completed analysis, and explicit analyst assumptions.
- [Decisions](docs/DECISIONS.md) explains technical and analytical choices, the alternatives, and what is still open.
