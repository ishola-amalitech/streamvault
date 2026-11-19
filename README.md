# StreamVault

StreamVault is a lab about a fictional $14M film licensing decision. The pipeline gathers the movie data used to compare franchise bundles with standalone films. The analysis considers all release years and a second window starting on 1 January 2000. [Lab brief, supplied separately](data/lab_brief.md)

## The pipeline

**Start in `src/streamvault/main.py`.** The `streamvault` command runs this file, which coordinates the steps below. The pipeline fetches and caches TMDB responses, then turns the resolved candidates into tables and validates them. [Pipeline entry point](src/streamvault/main.py)

| Step | What happens | Code |
| --- | --- | --- |
| Read the candidate list | Read one TMDB ID per row from `id_list.csv`. Keep the first valid entry for each ID and log blank, invalid, and duplicate rows. | [load.py](src/streamvault/load.py), [removals.py](src/streamvault/removals.py) |
| Check the cache | Stop if a current candidate has duplicate cache entries. Reuse saved movies and pass only the missing IDs to the downloader. | [cache.py](src/streamvault/cache.py) |
| Fetch the missing movies | Request movie details and credits from TMDB, limit request speed, and retry temporary failures. Report whether every requested ID has one outcome before saving new responses. | [fetch_movies.py](src/streamvault/fetch_movies.py) |
| Save and report | Add successful responses to the local cache. Record the fetch time and unresolved IDs when the pipeline makes requests, then print a summary. | [cache.py](src/streamvault/cache.py), [run_record.py](src/streamvault/run_record.py) |
| Normalize and validate | Build the tables in memory. Check candidate IDs, collection joins, and genre and talent links. Stop on structural failures. Save film-level review issues beside the cache. | [normalize.py](src/streamvault/normalize.py), [diagnostics.py](src/streamvault/diagnostics.py) |

The [candidate list](id_list.csv) is included in the checkout. [config.toml](config.toml) sets the file paths, request limits, timeouts, and retry settings.

## Run the pipeline

Run the commands from the repository root. For a fresh download, get a TMDB API **read access token** and put it in a local `.env` file. Replace the placeholder with your token. Git and the Docker build ignore this file.

```dotenv
TMDB_API_READ_ACCESS_TOKEN=your_read_access_token
```

### Docker

Start Docker and run the following in Bash. The image installs Python 3.14, uv, and the locked dependencies. The pipeline writes its outputs to your checkout through the mounted folder. [Dockerfile](Dockerfile)

```sh
docker build -t streamvault .
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  --env-file .env streamvault streamvault
```

In the second command, the first `streamvault` names the image and the second runs the pipeline inside it. Rebuild the image when the dependencies or Dockerfile change.

### Local uv

Install [uv](https://docs.astral.sh/uv/) and run the same pipeline directly on your laptop.

```sh
uv python install 3.14
uv sync --locked
uv run --locked --env-file .env streamvault
```

### Pipeline outputs

| Default path | What to look for |
| --- | --- |
| `data/raw/movies.jsonl` | Raw movie details and credits, one movie per line. |
| `id_list_removals.csv` | Source line and reason for each logged blank, invalid ID, duplicate ID, or TMDB lookup miss. |
| `data/raw/movies.acquisition.json` | The latest fetch timing and counts, plus the last known outcome for each unresolved ID. |
| `data/raw/movies.quality.csv` | Affected movie IDs, film titles, release years when available, and the effect of each issue. A report with only column headers means no films were flagged. |

A repeat run reuses saved entries and tries uncached IDs again. Git ignores the cache and logs. Keep them together with the candidate CSV to reproduce a snapshot. To start a new snapshot, archive the existing cache and logs and use fresh output paths.

### Review the evidence before using the shortlists

After running Notebook 04, open the sections **Film data issues to review** and **Evidence left for Adjoa**. The first lists individual film issues. The second shows how many bundles and standalones qualify in each release window and how many shortlist spots are unfilled. [Exclusions report](docs/recommendation_exclusions.md)

- **Missing or invalid data.** A film without a usable release date stays out of both windows. A dated, released film with unusable rating inputs stays unscored and can make its bundle ineligible. Missing budget or gross affects only the financial calculations that need it.
- **Provisional.** Compare the flagged TMDB records before relying on that window’s shortlist or ratings preference. A shared title and year calls for review, and both movie IDs stay visible.
- **Too few options.** If either side has fewer than five eligible options, use the available shortlist entries as leads and hold back a firm franchise-versus-standalone recommendation.

## Test the pipeline

The tests cover candidate IDs, the cache, the removal log, fetch outcomes, and normalization. They also check that the pipeline stops on duplicate cache entries, unexpected fetch results, or changed movie IDs. They also verify that rating gaps and possible duplicate films are reported while the run continues. They use simulated TMDB responses and run without an API token.

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  streamvault python -m unittest discover -s tests
```

With local uv, run `uv run --locked python -m unittest discover -s tests`.

## How the notebooks informed the work

The notebooks show the checks and experiments behind the pipeline design and the recommendation. Notebook 01 shows the preparation and join checks that informed the pipeline's normalization stage. The recommendation analysis still runs in Notebook 04.

| Notebook | What it contributed |
| --- | --- |
| [01 · Validate normalization](notebooks/01_validate_normalization.ipynb) | Shows how to turn nested TMDB responses into usable tables, check joins, and account for source rows. |
| [02 · Profile the data](notebooks/02_profile_movie_data.ipynb) | Checks current candidates for missing fields, numeric validity, and possible duplicate films. It also audits identical raw records across the whole cache. |
| [03 · Explore the data](notebooks/03_eda_movie_data.ipynb) | Flags unusually high or low values and explores patterns in ratings, box office, genres, franchises, and talent. |
| [04 · Make the recommendation](notebooks/04_recommendation.ipynb) | Compares bundles and standalones, ranks targets in both release windows, and tests how sensitive the results are to changes in scoring. |

The notebooks already share code for turning raw responses into tables and running data checks. [normalize.py](src/streamvault/normalize.py) · [diagnostics.py](src/streamvault/diagnostics.py)

The pipeline and all four notebooks use the same candidate matching rules. They match the valid IDs in the current CSV to the saved TMDB records and stop if a current candidate has multiple cache entries. Older films can stay in the cache for future reuse. Notebook 02 labels its whole-cache raw duplicate audit separately. For a fresh analysis, open Notebook 04 in a fresh kernel and choose **Run All**. It writes the ranked CSVs and analysis run record under `data/raw/movies.recommendation/` and updates the [exclusions report](docs/recommendation_exclusions.md). The one-page memo and deal note are pending.

To open JupyterLab with Docker, use the image built above and open the link printed in the terminal. With local uv, run `uv run --locked jupyter lab`.

```sh
docker run --rm -it --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  --publish 127.0.0.1:8888:8888 streamvault
```

The [benchmark script](scripts/benchmark_recommendation.py) measures the current notebook analysis against the cached snapshot and 500 test titles, with TMDB requests and test-data setup outside the timer. With a populated cache, run `uv run --locked python scripts/benchmark_recommendation.py`, or use `python scripts/benchmark_recommendation.py` in the Docker test command above.

See the [findings](docs/findings.md), [questions](docs/questions.md), and [decision notes](docs/DECISIONS.md) for the evidence and choices behind the work.
