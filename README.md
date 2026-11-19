# StreamVault

StreamVault is a data-analysis lab for a fictional $14M film licensing decision. It compares franchise bundles with standalone films, ranks targets for each, and looks for useful director and cast signals. The analysis runs twice, once for all release years and once for films released on or after 1 January 2000. The recommendation analysis is in place. The one-page memo and deal note are pending. [Lab brief, available in the local lab files](data/lab_brief.md)

## Start here

The project starts with [the candidate list](id_list.csv). It contains TMDB movie IDs. The `streamvault` command reads that list and downloads movie details and credits into a local cache. The notebooks read the cache, turn the data into tables, and explain the results.

```text
id_list.csv → streamvault → local movie cache → Notebook 04 → rankings and reports
                                   └──────────→ Notebooks 01–03 → data checks and exploration
```

## Option A: Set up with Docker

Install Docker and start it. Run the commands below from the repository root in a Bash shell. The image installs Python 3.14, uv, and the locked dependencies, including JupyterLab. Docker is the only tool you need to install for this route. [Dockerfile](Dockerfile)

1. Build the image.

   ```sh
   docker build -t streamvault .
   ```

2. For a fresh download, get a TMDB API **read access token** and create a local `.env` file in the repository root. Replace the placeholder with your token. Git and the Docker build ignore this file.

   ```dotenv
   TMDB_API_READ_ACCESS_TOKEN=your_read_access_token
   ```

   Download the candidate data. Docker runs the command with your user ID and saves the results in your checkout. If you already have a snapshot for this list, restore its cache and logs to the paths below and skip this step.

   ```sh
   docker run --rm --user "$(id -u):$(id -g)" \
     --mount "type=bind,source=$PWD,target=/app" \
     --env-file .env streamvault streamvault
   ```

3. Start JupyterLab. Open the link printed in the terminal that starts with `http://127.0.0.1:8888` and includes the Jupyter token. Press **Ctrl+C** in the terminal when you are done. The mounted checkout keeps your notebook changes and reports.

   ```sh
   docker run --rm -it --user "$(id -u):$(id -g)" \
     --mount "type=bind,source=$PWD,target=/app" \
     --publish 127.0.0.1:8888:8888 streamvault
   ```

   Open [Notebook 04](notebooks/04_recommendation.ipynb) and choose **Run All** in a fresh kernel. Notebooks 01–03 can also be run separately in fresh kernels.

Rebuild the image when the Python dependencies or Dockerfile change. In the Docker commands, the first `streamvault` names the image. In step 2, the second `streamvault` is the download command.

## Option B: Set up with local uv

If you prefer to run directly on your laptop, install [uv](https://docs.astral.sh/uv/) and run these commands from the repository root. Use the same `.env` file for the download. Skip the download if you have restored a saved snapshot.

```sh
uv python install 3.14
uv sync --locked
uv run --locked --env-file .env streamvault
uv run --locked jupyter lab
```

The download needs internet access and reuses IDs already in the cache. JupyterLab reads the local cache and logs without a TMDB token.

### Notebook guide

| Notebook | What it does |
| --- | --- |
| [01 · Prepare the data](notebooks/01_prep_movie_data.ipynb) | Turns the raw responses into tables, checks that joining tables keeps each film once, and accounts for source rows. |
| [02 · Profile the data](notebooks/02_profile_movie_data.ipynb) | Checks for missing values, duplicates, unusual values, and types that need attention. |
| [03 · Explore the data](notebooks/03_eda_movie_data.ipynb) | Explores patterns in ratings, box office, genres, franchises, and talent. |
| [04 · Make the recommendation](notebooks/04_recommendation.ipynb) | Checks the current list, ranks both types of titles in both release windows, compares the results, reviews talent signals, and tests how the ranking responds to different scoring choices. |

Each notebook reads the local inputs directly. Notebook 04 can run on its own once the inputs are ready. It filters the cache to IDs in the current candidate list. Use a separate cache and removal log for a different candidate list when running Notebooks 01–03, which read the whole cache.

### Inputs and outputs

The paths below use the defaults in [config.toml](config.toml). A clean clone includes the candidate list. Supply the local lab brief separately if you need to read it. The download creates the cache and logs as needed.

| Path | What it contains |
| --- | --- |
| `data/raw/movies.jsonl` | Raw TMDB movie details and credits, one movie per line. |
| `id_list_removals.csv` | Log of blank, invalid, duplicate, and missing entries. |
| `data/raw/movies.acquisition.json` | Latest download timing and unresolved lookups by ID. Created when the download command makes requests. |
| `data/raw/movies.recommendation/` | Four ranked candidate CSVs and `run.json`, which records which inputs, code, settings, and timings produced the results. The timing script adds `benchmark.json`. |
| [docs/recommendation_exclusions.md](docs/recommendation_exclusions.md) | Notebook 04 updates this report with source rows left out and films that missed either shortlist. |

Git ignores `data/` and `id_list_removals.csv`. To repeat the same analysis, keep the input CSV, cache, and available logs together. For a fresh snapshot, archive the old cache and logs, then run the download with fresh paths or move the archived files out of the configured paths first.

## How the code is organized

| Path | Role |
| --- | --- |
| [src/streamvault/](src/streamvault/) | The Python package. It contains the download entry point and reusable code shared by the command, notebooks, and tests. |
| [notebooks/](notebooks/) | The walkthroughs, charts, and analysis. Most of the ranking and recommendation rules live in Notebook 04 today. |
| [scripts/](scripts/) | Commands for project maintenance. The benchmark here measures runtime using the current cache and 500 test titles. |
| [tests/](tests/) | Automated tests for the Python package. |
| [docs/](docs/) | The [findings](docs/findings.md), [questions](docs/questions.md), [decision notes](docs/DECISIONS.md), and exclusions report. |
| `data/` | Local lab brief, raw downloads, and generated tables and run records. |
| [config.toml](config.toml), [pyproject.toml](pyproject.toml), [uv.lock](uv.lock) | Settings for data paths and TMDB requests, the Python package and command, and the exact dependency versions. |

Inside the package, [main.py](src/streamvault/main.py) is where the download command starts. It uses [load.py](src/streamvault/load.py) to read candidate IDs, [fetch_movies.py](src/streamvault/fetch_movies.py) to call TMDB, [cache.py](src/streamvault/cache.py) to read and save responses, and [removals.py](src/streamvault/removals.py) to log removals. [config.py](src/streamvault/config.py) reads the settings. [normalize.py](src/streamvault/normalize.py) turns raw responses into tables for the notebooks. [diagnostics.py](src/streamvault/diagnostics.py) runs checks supplied by its callers and reports or raises failures. [run_record.py](src/streamvault/run_record.py) helps the command, Notebook 04, and the benchmark keep track of their inputs and results.

## Run tests and check speed

Run the package tests from the repository root. With Docker, run the following command.

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  streamvault python -m unittest discover -s tests
```

With local uv, run the following command.

```sh
uv run --locked python -m unittest discover -s tests
```

With a populated cache, run the timing script from the repository root. Use `python scripts/benchmark_recommendation.py` as the command in the Docker test example, or run it with local uv.

```sh
uv run --locked python scripts/benchmark_recommendation.py
```

It runs the cached recommendation in fresh Python processes for the current snapshot and for 500 test titles. The timer starts with the first code cell and ends after the candidate tables and file fingerprints are ready. TMDB requests and test-data setup happen outside that window. Run Notebook 04 again to see the timing comparison for matching inputs and code.
