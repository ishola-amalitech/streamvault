# StreamVault

StreamVault is a lab about a fictional $14M film licensing decision. Run **`uv run streamvault`** to fetch missing data, validate it, and get the recommendation and reports for both release windows. The analysis compares all years with films released from 1 January 2000 onward. [Lab brief](lab_brief.md)

The one-page memo summarizes the decision for Kwame, including the shortlist for each release window and the relative deal priority for the strongest bundle. [Client memo and deal note](docs/01_client_memo.md)

## The pipeline

**Start in `src/streamvault/main.py`.** This file starts the end-to-end command. Acquisition saves TMDB outcomes, then the shared recommendation step reads the saved inputs, validates the movies, and writes the decision and evidence. [Pipeline entry point](src/streamvault/main.py) · [Recommendation notebook](notebooks/04_recommendation.ipynb)

| Step | What happens | Code |
| --- | --- | --- |
| Read the candidate list | Read one TMDB ID per row from `id_list.csv`. Keep the first valid entry for each ID and log blank, invalid, and duplicate rows. | [load.py](src/streamvault/load.py), [removals.py](src/streamvault/removals.py) |
| Check the cache | Stop if a current candidate has duplicate cache entries. Reuse saved movies and pass only the missing IDs to the downloader. | [cache.py](src/streamvault/cache.py) |
| Fetch the missing movies | Request movie details and credits from TMDB, limit request speed, and retry temporary failures. Report whether every requested ID has one outcome before saving new responses. | [fetch_movies.py](src/streamvault/fetch_movies.py) |
| Save and report | Add successful responses to the local cache. Record the fetch time and unresolved IDs when the pipeline makes requests, then print a summary. | [cache.py](src/streamvault/cache.py), [run_record.py](src/streamvault/run_record.py) |
| Normalize and validate | Build the tables in memory. Check candidate IDs, collection joins, and genre and talent links. Stop on structural failures. List film issues in the exclusions report using the same budget and gross rules as Notebooks 03 and 04. | [normalize.py](src/streamvault/normalize.py), [diagnostics.py](src/streamvault/diagnostics.py), [movie_quality.py](src/streamvault/movie_quality.py) |
| Recommend | Account for every source row and select both release windows. Rank up to three bundles and five standalones per window. Compare all eligible options and review talent and scoring alternatives. | [recommendation_inputs.py](src/streamvault/recommendation_inputs.py), [recommendation_analysis.py](src/streamvault/recommendation_analysis.py), [recommendation_talent.py](src/streamvault/recommendation_talent.py) |
| Publish | Print the recommendation and save it with the rankings workbook, exclusions report, and run record. | [recommendation_run.py](src/streamvault/recommendation_run.py), [recommendation_reports.py](src/streamvault/recommendation_reports.py) |

The [candidate list](id_list.csv) is included in the checkout. [config.toml](config.toml) sets the input paths, the CLI report folder (`out/` by default), request limits, timeouts, and retry settings.

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

Install [uv](https://docs.astral.sh/uv/) and set up the project from the repository root. In Bash, set `UV_ENV_FILE` in the terminal Adjoa will use so uv loads the local token file.

```sh
uv python install 3.14
uv sync --locked
export UV_ENV_FILE=.env
```

Update `id_list.csv` when Adjoa receives a new candidate list. Run the full pipeline from the project root.

```sh
uv run streamvault
```

### Upload a list in the browser

Use the upload page to run the same pipeline on a CSV with one column named `tmdb_id`. After the local uv setup above, run this from the repository root.

```sh
uv run --locked streamlit run app.py --server.address 127.0.0.1
```

If you use Docker, rebuild the image with `docker build -t streamvault .`, then run it as follows.

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  --env-file .env --publish 127.0.0.1:8501:8501 \
  streamvault streamlit run app.py --server.address 0.0.0.0
```

Open `http://localhost:8501`, upload the CSV, then click **Run recommendation**. The page shows the results for both release windows. **Download reports** saves the recommendation, the rankings workbook, and the exclusions report in one ZIP. It also includes the original upload, the run record, and a row removal log when there are rows to log. Download the ZIP before closing the page or switching to another list.

Open **Output guide** in the app to see which file to read first, how to use the workbook, and what to keep for the next review.

To compare two reviews, open **Compare saved runs** and upload the earlier and later report ZIPs. The app shows the recommendation in each window and which shortlist picks entered, left, or moved in rank. This uses the saved reports, so you can compare them without fetching movies or rerunning the analysis. [Improvement beyond the brief](docs/06_beyond_the_brief.md)

The app reuses the local movie cache and saved lookup outcomes. New IDs need the same TMDB token as the command line. The app keeps the project candidate CSV and the CLI recommendation reports in place. It can update the shared movie cache and acquisition history in `out/`, so let an app run finish before starting a CLI run. The run record in the ZIP includes the acquisition counts and timing when this upload fetched data. [App entry point](app.py)

### Pipeline outputs

Notebook 04 writes its own copies of the recommendation reports using saved movie data. These are the default locations for each run.

| Output | Pipeline | Notebook 04 | What it contains |
| --- | --- | --- | --- |
| Recommendation | `out/recommendation.md` | `data/recommendation-report/recommendation.md` | Start here for the decision, shortlists with reasons, talent signals, and evidence limits. |
| Rankings workbook | `out/rankings.xlsx` | `data/recommendation-report/rankings.xlsx` | Compare ranks across both windows on the **Bundles** and **Standalones** tabs. Filter either result column to **Shortlisted** for the picks. |
| Exclusions report | `out/recommendation_exclusions.md` | `data/recommendation-report/recommendation_exclusions.md` | What happened to candidate rows, which films need review, and why films missed either shortlist. |
| Run record | `out/run.json` | `data/recommendation-report/run.json` | Inputs, settings, checks, and the time taken by that run. Keep it with the reports to help reproduce them. |
| Lookup history | `out/movies.acquisition.json` | — | The pipeline updates this when it makes requests. It records fetch times and the latest lookup outcomes. |
| Benchmarks | `out/benchmarks/` | `data/recommendation-report/benchmark/` | Runtime and memory reports written by separate benchmark commands. |

The workbook lists the observed titles behind each bundle's score for both windows. On the standalone tab, **Source gross** is the value we received and **Usable gross** is the amount that passed the data checks. Notebook 04 has the supporting tests for scoring, bundle strength, genres, and talent.

Every ordinary run records its own analysis time in `run.json`. The separate runtime benchmark measures the analysis on 500 saved test titles and leaves out download time. The memory benchmark is optional and tests whether smaller field types reduce memory use. Use `--notebook` with the benchmark commands to refresh Notebook 04's copies. [Benchmark commands and results](docs/05_benchmarks.md#rerun-the-benchmarks)

The raw cache (`data/raw/movies.jsonl`) and removal log (`id_list_removals.csv`) are working files shared with the notebooks. A repeat run reuses saved entries. With a TMDB token, it retries uncached IDs. Without a token, it can replay a saved list when every uncached ID has a recorded outcome. Keep the candidate CSV, cache, removal log, and any acquisition record together to reproduce a snapshot. Git ignores these local records and the reports in `out/`.

If upgrading an existing checkout, archive any old recommendation CSVs left by the pipeline or notebook. The new runs publish the workbook and show film issues in the exclusions report.

### Review the evidence before using the shortlists

Run the pipeline for `out/recommendation_exclusions.md`, or run Notebook 04 for `data/recommendation-report/recommendation_exclusions.md`. Open **Film data issues to review** for individual film issues and **Evidence left for Adjoa** for how many bundles and standalones qualify in each release window and how many shortlist spots are unfilled.

- **Missing or invalid data.** A film without a usable release date stays out of both windows. A dated, released film with unusable rating inputs stays unscored and can make its bundle ineligible. For financial summaries, keep each positive, finite dollar amount. Missing, zero, or invalid budget affects only calculations that need budget. For example, a film with valid gross and a zero budget still counts toward median gross. Gross less budget needs both amounts.
- **Provisional.** Compare the flagged TMDB records before relying on that window’s shortlist or ratings preference. A shared title and year calls for review, and both movie IDs stay visible.
- **Too few options.** If either side has fewer than five eligible options, use the available shortlist entries as leads and hold back a firm franchise-versus-standalone recommendation.

## Test the pipeline

The tests cover candidate IDs, the cache, the removal log, fetch outcomes, normalization, and recommendation rules. They check that the pipeline stops on duplicate cache entries, unexpected fetch results, or changed movie IDs and reports rating gaps and possible duplicate films while the run continues. Recommendation tests cover ranking ties, thin evidence, and the difference between source gross and usable gross. The tests run without an API token.

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  streamvault python -m unittest discover -s tests
```

With local uv, run `uv run --locked python -m unittest discover -s tests`.

## How the notebooks informed the work

The notebooks show the checks and experiments behind the pipeline design and the recommendation. Notebook 01 shows the preparation and join checks that informed the pipeline's normalization stage. Notebook 04 presents the same recommendation and reports as the command using the saved inputs. [Scoring and comparison](src/streamvault/recommendation.py) · [Talent analysis](src/streamvault/recommendation_talent.py) · [Report preparation](src/streamvault/recommendation_reports.py)

| Notebook | What it contributed |
| --- | --- |
| [01 · Validate normalization](notebooks/01_validate_normalization.ipynb) | Shows how to turn nested TMDB responses into usable tables, check joins, and account for source rows. |
| [02 · Profile the data](notebooks/02_profile_movie_data.ipynb) | Checks current candidates for missing fields, numeric validity, and possible duplicate films. It also audits identical raw records across the whole cache. |
| [03 · Explore the data](notebooks/03_eda_movie_data.ipynb) | Profiles matched films, shows release-window counts, and checks unusual values and four numeric relationships. For dated releases across all years, it reports coverage by category, usable ratings, production budgets, and reported box-office gross by genre, collection, and talent, and whether genre tags improve a gross model. |
| [04 · Make the recommendation](notebooks/04_recommendation.ipynb) | Compares bundles and standalones, ranks targets in both release windows, and tests how sensitive the results are to changes in scoring. |

The notebooks already share code for turning raw responses into tables and running data checks. [normalize.py](src/streamvault/normalize.py) · [diagnostics.py](src/streamvault/diagnostics.py)

The pipeline and all four notebooks use the same candidate matching rules. They match the valid IDs in the current CSV to the saved TMDB records and stop if a current candidate has multiple cache entries. Older films can stay in the cache for future reuse. Notebook 02 labels its whole-cache raw duplicate audit separately.

Open Notebook 04 and choose **Run All** to review the analysis on the saved inputs. See the [output table](#pipeline-outputs) for where it saves each file.

To open JupyterLab with Docker, use the image built above and open the link printed in the terminal. With local uv, run `uv run --locked jupyter lab`.

```sh
docker run --rm -it --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  --publish 127.0.0.1:8888:8888 streamvault
```

See the [findings](docs/02_findings.md), [questions](docs/03_questions.md), and [decision notes](docs/04_DECISIONS.md) for the evidence and choices behind the work.
