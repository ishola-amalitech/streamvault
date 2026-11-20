# StreamVault

**[Open StreamVault in your browser](https://streamvault-ishola.streamlit.app/)**

StreamVault helps Kwame decide which films to pursue for a fictional $14M licensing budget. It compares franchise bundles and standalone films across all years and again from 2000 onward. [Lab brief](lab_brief.md)

- **For Kwame.** Read the one-page decision, shortlists, and suggested order for asking for quotes. [Client memo and deal note](docs/01_client_memo.md)
- **For Adjoa.** Open the browser app to run a new list or compare two saved reviews.

## Contents

1. [Choose a way to run StreamVault](#run-the-pipeline)
   - [Hosted browser app](#upload-a-list-in-the-browser)
   - [Docker](#docker)
   - [Local uv](#local-uv)
2. [Read your reports](#read-your-reports)
3. [Compare two saved reviews](#compare-two-saved-reviews)
4. [Run the benchmarks](#run-the-benchmarks)
5. [Technical reference](#technical-reference)
   - [Submission files](#submission-files)
   - [Output files](#pipeline-outputs)
   - [Run the browser app on your computer](#run-the-browser-app-on-your-computer)
   - [Pipeline steps](#the-pipeline)
   - [Tests](#test-the-pipeline)
   - [Notebooks](#how-the-notebooks-informed-the-work)

## Run the pipeline

Choose **one** option. Start with the hosted browser app for a regular licensing review.

| Option | When to use it | What you need |
| --- | --- | --- |
| [1. Hosted browser app](#upload-a-list-in-the-browser) | Run or compare reviews without installing anything. | A browser and your candidate CSV or two saved report ZIPs. |
| [2. Docker](#docker) | Run the analysis on your computer. Docker sets up Python and uv inside the image. | Docker and the [computer setup](#before-running-on-your-computer). |
| [3. Local uv](#local-uv) | Run the analysis directly from your computer's terminal. | uv and the [computer setup](#before-running-on-your-computer). |

### Upload a list in the browser

1. Open the [StreamVault browser app](https://streamvault-ishola.streamlit.app/).
2. On **Run recommendation**, upload your candidate CSV. It needs one column called `tmdb_id`, with one film ID per row. You can try it with the [sample candidate list](id_list.csv).
3. Click **Run recommendation**. The page shows the recommendation and shortlist for each release window.
4. Click **Download reports** to save everything in one ZIP. Keep it for the next review. The app's **Output guide** explains what to open first.

### Before running on your computer

Complete these steps for Docker or local uv.

1. Download this project from GitHub and open a Bash terminal in the project folder. It contains `README.md` and `id_list.csv`.
2. Put the new candidate list in that folder as `id_list.csv`. The included list works as a sample.
3. Create a file called `.env` in the same folder. When downloading movie data, add your TMDB read access token there. Replace the placeholder below with the token. Git and Docker ignore the file, and the local commands load it when they run.

   ```dotenv
   TMDB_API_READ_ACCESS_TOKEN=your_read_access_token
   ```

   For a run that reuses saved movie data and already has an outcome for every uncached ID, the `.env` file can be empty.

### Docker

1. Complete the [computer setup](#before-running-on-your-computer) and start Docker. From the project folder, build the StreamVault image. Repeat this step when the Dockerfile or dependencies change. [Dockerfile](Dockerfile)

   ```sh
   docker build -t streamvault .
   ```

2. Run the pipeline for each candidate list. The command gives Docker access to your project folder so it can save reports there.

   ```sh
   docker run --rm --user "$(id -u):$(id -g)" \
     --mount "type=bind,source=$PWD,target=/app" \
     --env-file .env streamvault streamvault
   ```

3. Open `out/recommendation.md` in the project folder. [Read the reports](#read-your-reports)

### Local uv

1. Complete the [computer setup](#before-running-on-your-computer) and install uv. Run the setup commands from the project folder. [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)

   ```sh
   uv python install 3.14
   uv sync --locked
   ```

2. Run the pipeline for each candidate list.

   ```sh
   uv run --locked --env-file .env streamvault
   ```

3. Open `out/recommendation.md` in the project folder. [Read the reports](#read-your-reports)

## Read your reports

Open the ZIP from the browser or the `out/` folder from a local run.

| File | Where to start |
| --- | --- |
| `recommendation.md` | Read the decision, both shortlists, and what you still need to verify. |
| `rankings.xlsx` | Open the **Bundles** or **Standalones** tab to see how each option ranked. Filter a result column to **Shortlisted** to see just the picks for that window. |
| `recommendation_exclusions.md` | See which entries were left out, why, and which films need a second look. |
| `run.json` | Keep this with the other files. It records which inputs and settings produced the results. The browser app also uses it to compare reviews. |

### Review the evidence before using the shortlists

In the exclusions report, look at **Film data issues to review** for titles that need attention, and **Evidence left for Adjoa** for the number of eligible options and any unfilled shortlist spots.

- If a window is marked provisional, review the possible duplicate films before relying on those picks.
- If either side has fewer than five eligible options, use the shortlist as a starting point for negotiations and hold back a firm preference.
- Audience scores help decide whom to call first. Studio quotes and the list of films included in each deal are needed before committing any of the $14M. [Client memo and deal note](docs/01_client_memo.md)

## Compare two saved reviews

1. Open [StreamVault](https://streamvault-ishola.streamlit.app/) and choose **Compare saved runs**.
2. Upload the original ZIP from the earlier review and the original ZIP from the later review.
3. Check whether the recommendation changed in either release window. The shortlist table shows which films or bundles entered, left, or moved in rank.

The app reads the saved results from both ZIPs, so you can compare them without running either list again.

## Run the benchmarks

A benchmark checks how the analysis handles the roughly 500 titles Adjoa expects next year. The runtime test measures the steps from reading saved movie data through writing the reports. It leaves out the time to download movies. In the documented test with the rankings workbook, 500 test titles took **3.75 seconds**. The optional memory test checks whether using smaller field types saves enough memory to be worthwhile. [Benchmark guide and results](docs/05_benchmarks.md)

Run the pipeline on your computer first to save the movie data, then choose one of the methods below. For an ordinary review, just run the analysis. Its own timing is recorded in `run.json`.

### Benchmark with local uv

From the project folder, run the runtime test. Run the second command if you also want the memory test on Linux or macOS.

```sh
uv run --locked python scripts/benchmark_recommendation.py
uv run --locked python scripts/benchmark_movie_types.py
```

### Benchmark with Docker

After building the [Docker image](#docker), use the command below. For the optional memory test, replace `scripts/benchmark_recommendation.py` with `scripts/benchmark_movie_types.py`.

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  streamvault python scripts/benchmark_recommendation.py
```

The commands write `benchmark.json` for runtime and `movie_types_benchmark.json` for memory under `out/benchmarks/`. Add `--notebook` to the end of either command to run a separate measurement and save it in `data/recommendation-report/benchmark/` for Notebook 04.

## Technical reference

### Submission files

| Lab deliverable | Where to find it |
| --- | --- |
| Data diagnosis and candidate coverage | [Findings ranked by risk](docs/02_findings.md) and the generated [exclusions report](#pipeline-outputs). |
| Working analysis | [Pipeline entry point](src/streamvault/main.py) and [four analysis notebooks](#how-the-notebooks-informed-the-work). |
| Analyst judgments and architecture | [Questions and analysis methods](docs/03_questions.md) and [five architecture decisions](docs/03-adr/). |
| Client memo and deal note | [Kwame’s recommendation, shortlists, and evidence limits](docs/01_client_memo.md). |
| One improvement beyond the brief | [Browser app for running and comparing saved reviews](docs/06_beyond_the_brief.md). The app entry point is [app.py](app.py). |
| Scale and verification | The [benchmark guide](docs/05_benchmarks.md), runner scripts under [scripts/](scripts/), and automated checks under [tests/](tests/). |

### Pipeline outputs

Notebook 04 writes its own copies of the recommendation reports using saved movie data. These are the default locations for each run.

| Output | Pipeline | Notebook 04 | What it contains |
| --- | --- | --- | --- |
| Recommendation | `out/recommendation.md` | `data/recommendation-report/recommendation.md` | Start here for the decision, shortlists with reasons, talent signals, and evidence limits. |
| Rankings workbook | `out/rankings.xlsx` | `data/recommendation-report/rankings.xlsx` | Compare ranks across both windows on the **Bundles** and **Standalones** tabs. Filter either result column to **Shortlisted** for the picks. |
| Exclusions report | `out/recommendation_exclusions.md` | `data/recommendation-report/recommendation_exclusions.md` | What happened to candidate rows, which films need review, and why films missed either shortlist. |
| Run record | `out/run.json` | `data/recommendation-report/run.json` | Inputs, settings, checks, and the time taken by that run. Keep it with the reports to help reproduce them. |
| Lookup history | `out/movies.acquisition.json` | — | The pipeline updates this when it makes requests. It records fetch times and the latest lookup outcomes. |
| [Benchmarks](#run-the-benchmarks) | `out/benchmarks/` | `data/recommendation-report/benchmark/` | Runtime and memory reports written by separate benchmark commands. |

The workbook lists the observed titles behind each bundle's score for both windows. On the standalone tab, **Source gross** is the value we received and **Usable gross** is the amount that passed the data checks. Notebook 04 has the supporting tests for scoring, bundle strength, genres, and talent.

The raw cache (`data/raw/movies.jsonl`) and removal log (`id_list_removals.csv`) are working files shared with the notebooks. A repeat run reuses saved entries. With a TMDB token, it retries uncached IDs. Without a token, it can replay a saved list when every uncached ID has a recorded outcome. Keep the candidate CSV, cache, removal log, and any acquisition record together to reproduce a snapshot. Git ignores these local records and the reports in `out/`.

### Run the browser app on your computer

Finish either the [Docker](#docker) or [local uv](#local-uv) setup first. Choose the matching command, then open `http://localhost:8501`. Follow steps 2–4 in the [browser instructions](#upload-a-list-in-the-browser) to upload a list and save the reports.

**Docker**

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  --env-file .env --publish 127.0.0.1:8501:8501 \
  streamvault streamlit run app.py --server.address 0.0.0.0
```

**Local uv**

```sh
uv run --locked --env-file .env streamlit run app.py --server.address 127.0.0.1
```

The local app can update the saved movie data and lookup history. Let an app run finish before starting a terminal run that uses the same files. [App entry point](app.py)

### The pipeline

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

### Test the pipeline

The tests cover candidate IDs, the cache, the removal log, fetch outcomes, normalization, and recommendation rules. They check that the pipeline stops on duplicate cache entries, unexpected fetch results, or changed movie IDs and reports rating gaps and possible duplicate films while the run continues. Recommendation tests cover ranking ties, thin evidence, and the difference between source gross and usable gross. The tests run without an API token.

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  streamvault python -m unittest discover -s tests
```

With local uv, run `uv run --locked python -m unittest discover -s tests`.

### How the notebooks informed the work

The notebooks show the checks and experiments behind the pipeline design and the recommendation. Notebook 01 shows the preparation and join checks that informed the pipeline's normalization stage. Notebook 04 presents the same recommendation and reports as the command using the saved inputs. [Scoring and comparison](src/streamvault/recommendation.py) · [Talent analysis](src/streamvault/recommendation_talent.py) · [Report preparation](src/streamvault/recommendation_reports.py)

| Notebook | What it contributed |
| --- | --- |
| [01 · Validate normalization](notebooks/01_validate_normalization.ipynb) | Shows how to turn nested TMDB responses into usable tables, check joins, and account for source rows. |
| [02 · Profile the data](notebooks/02_profile_movie_data.ipynb) | Checks current candidates for missing fields, numeric validity, and possible duplicate films. It also audits identical raw records across the whole cache. |
| [03 · Explore the data](notebooks/03_eda_movie_data.ipynb) | Profiles matched films, shows release-window counts, and checks unusual values and four numeric relationships. For dated releases across all years, it reports coverage by category, usable ratings, production budgets, and reported box-office gross by genre, collection, and talent, and whether genre tags improve a gross model. |
| [04 · Make the recommendation](notebooks/04_recommendation.ipynb) | Compares bundles and standalones, ranks targets in both release windows, and tests how sensitive the results are to changes in scoring. |

The notebooks already share code for turning raw responses into tables and running data checks. [normalize.py](src/streamvault/normalize.py) · [diagnostics.py](src/streamvault/diagnostics.py)

The pipeline and all four notebooks use the same candidate matching rules. They match the valid IDs in the current CSV to the saved TMDB records and stop if a current candidate has multiple cache entries. Older films can stay in the cache for future reuse. Notebook 02 labels its whole-cache raw duplicate audit separately.

Run the pipeline on your computer first so the saved movie data is available. Then open Notebook 04 and choose **Run All**. See the [output table](#pipeline-outputs) for where it saves each file.

To open JupyterLab with Docker, use the image built above and open the link printed in the terminal. With local uv, run `uv run --locked jupyter lab`.

```sh
docker run --rm -it --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD,target=/app" \
  --publish 127.0.0.1:8888:8888 streamvault
```

For a new architecture decision, use the next numbered file and follow the existing ADR format. If a decision changes, record it in a new ADR that links to the one it replaces.
