# StreamVault project decisions and data guide

This document is the running record of the project’s important choices. It explains how the data is collected, what each analysis table means, how joins are checked, and which limitations remain. The language is intended to be understandable without a technical background.

## 1. Collection and network behavior

### Source and access

- The starting list is `id_list.csv`; each valid `tmdb_id` is requested from the TMDB movie-details endpoint, including credits.
- The API access token is read from the `TMDB_API_READ_ACCESS_TOKEN` environment variable. It is not stored in the repository.
- One reusable asynchronous HTTP session is used for a batch. The project allows up to eight requests in progress and schedules requests at four per second.
- Runtime settings are centralized in the root `config.toml`: API base URL, token environment-variable name, appended response data, connection concurrency, request rate and timeouts, retry/backoff settings, and input/cache/removal paths. Paths are relative to the config file. Package, build, and dependency settings remain in `pyproject.toml`.

### Timeouts and retries

- Each request has the configured total and connection timeouts (currently 10 seconds and 3.05 seconds).
- Network/request errors, HTTP 429 rate limits, and HTTP 5xx server errors are retried according to the configured retry count (currently three retries after the first attempt, at most four attempts total).
- For HTTP 429, the client honors the server’s `Retry-After` instruction when it is valid. Otherwise, and for server/network errors, it waits with the configured exponential backoff (currently 0.5, 1, then 2 seconds between retries).
- A final failed request is reported for that ID and does not stop other IDs in the batch. These final request failures are printed by the command, but are not yet saved to a durable failure-history file.

### Missing IDs and saved responses

- HTTP 404 is treated as “not found,” not as a fatal batch error. The ID, original source-file line, and reason are appended to the local `id_list_removals.csv` log. Empty responses are also reported as missing. Re-running may try those IDs again; a 404 is not a successful cache entry.
- Blank, invalid, and duplicate source-list rows are recorded in the same local log and skipped before requests are sent.
- Successful raw JSON responses are cached as one JSON object per line in `data/raw/movies.jsonl`. Existing cached IDs are skipped on later runs, avoiding repeat downloads. The cache is written through a temporary file and replaced atomically so an interrupted write is less likely to leave a partial cache.
- Each cached record has a UTC `cached_at_utc` field, the time the response was written to the cache. Older records were backfilled when timestamp support was introduced. For those entries, this is the backfill time—not a claim about when TMDB originally returned the response.
- The command-line fetch step is the only part of the project that makes API requests. The Jupyter notebook reads local cached responses and does not fetch.
- Removing the cache file is the deliberate way to refresh records already cached. A future choice is whether to add a refresh interval or update policy.

## 2. Naming and normalization decisions

- A raw TMDB response is useful for preserving the source data, but its nested arrays and objects are awkward to analyze directly. The normalizer converts the raw responses into a set of related tables.
- Column names are assigned their final, stable names at the normalization boundary, once. For example, a generic movie `id` becomes `movie_id`, a collection’s `id` becomes `collection_id`, and source company/language/country identifiers become named ID columns. Flattened nested credit fields use underscores. Notebook analysis uses these names directly rather than repeatedly renaming columns.
- Repeated facts are stored once in reference tables; separate link tables state which films relate to those facts. Cast and crew are kept as credit records because a person can have different roles on different films.
- Blank text is treated as missing information. Release dates are parsed as dates. Invalid IDs, malformed nested data, conflicting descriptions of the same reference entity, and duplicate relationship/credit IDs are rejected rather than silently accepted.
- Person popularity stays on each cast or crew credit. The value can differ between cached movie responses, and the data has no trustworthy history for selecting one value as the person’s permanent popularity.

## 3. Table definitions and row meaning

“Grain” means what a single row represents. Each table below has one defined grain; link tables deliberately have one row per relationship, not one row per film.

| Table | One row means | What it stores and how it links |
| --- | --- | --- |
| `movies` | One film | Film-level TMDB details, keyed by `movie_id`, plus `collection_id` when the film belongs to a collection. |
| `genres` | One genre | Shared genre name keyed by `genre_id`. |
| `movie_genres` | One film–genre link | `movie_id` and `genre_id`; connects films to the shared genre list. |
| `companies` | One production company | Shared company details keyed by `company_id`, including its name, logo path, and optional `origin_country_code`. |
| `movie_companies` | One film–company link | `movie_id` and `company_id`; connects films to production companies. |
| `countries` | One country code | Shared country details keyed by `country_code`; country names may be unknown when only a code was supplied. |
| `movie_origin_countries` | One film–origin-country link | `movie_id` and `country_code`; represents a country listed as a film’s origin. |
| `movie_production_countries` | One film–production-country link | `movie_id` and `country_code`; represents a country listed as a production location. |
| `languages` | One language | Shared language names keyed by `language_code`, including the language’s own and English names where available. |
| `movie_spoken_languages` | One film–language link | `movie_id` and `language_code`; connects a film to each listed spoken language. |
| `collections` | One collection | Shared collection name and artwork paths keyed by `collection_id`. |
| `people` | One person | Shared person details keyed by `person_id`, such as name, department, gender, and profile path. |
| `cast_credits` | One cast member’s credit in one film | `movie_id`, `person_id`, unique `credit_id`, character, cast order, and credit-specific popularity. A person in two films has two rows. |
| `crew_credits` | One crew member’s credit in one film | `movie_id`, `person_id`, unique `credit_id`, department, job, and credit-specific popularity. Different jobs are separate credits. |

The `movie_id` and entity-ID columns connect the link tables to their references. `movies.collection_id` connects to `collections.collection_id`; `companies.origin_country_code` connects to `countries.country_code`. Credit rows connect to both `movies` and `people`. The normalizer rejects duplicate `(movie_id, entity_id)` links and duplicate credit IDs so that the declared grains are enforced.

## 4. Join validations and coverage reporting

The notebook demonstrates joining `movie_genres` to `genres`, then to `movies`. The same principles apply to other link/reference tables.

- **Left join:** keeps every row from the table on the left. An unmatched film or link remains in the output for investigation; an inner join could silently discard exactly that evidence.
- **`validate="many_to_one"`:** declares that many link rows may point to one reference row, but the reference key must be unique. Pandas raises a `MergeError` if the reference side has duplicate keys that would fan out the results.
- **`indicator=`:** adds a named match-status column. `both` means the row matched; `left_only` means the left-side ID had no matching reference; `right_only` is possible for outer joins and is not expected in these left joins. Counts are displayed so unmatched data is visible.
- **Row-count check:** after each demonstrated left join, the check report compares the joined row count to the link count before joining. This catches accidental row multiplication even if a future join is edited incorrectly.
- **Source-list coverage:** every physical row in `id_list.csv` (including blank and duplicate rows) is left-joined to the cache with `validate="many_to_one"` and an indicator. It is then joined to the grouped removal log by source line and original value, with `validate="one_to_one"` and another indicator. The report checks row preservation, unique source lines, and that each unmatched cache row has a logged explanation. An unexplained cache miss is not guessed to be a 404.

### Automatic staged data-quality report

The notebook calls `run_data_checks` from `src/streamvault/diagnostics.py` after loading, after normalization, and after joins. It returns a table with one row per check and the columns `check`, `status` (`PASS` or `FAIL`), and `details`. The calling cell displays the stage name once as a heading, then displays the report with IPython’s `display`. It calls `raise_for_failed_checks` with that stage name, which raises `ValueError` if any check failed so later analysis does not continue on a known-bad assumption.

- **Loaded raw cache — 2 checks**
  1. Every response has a movie ID.
  2. Every `cached_at_utc` value parses as a UTC timestamp.

- **Cleaned and normalized tables — 29 checks**
  - **Row-count reconciliation — 1:** normalized movie row count equals the number of loaded responses.
  - **Table-grain checks — 14:** one combined report row for each table below verifies that its key column(s) exist, are non-null, and uniquely identify rows. The details state which condition failed.

    | Table | Key column(s) checked |
    | --- | --- |
    | `movies` | `movie_id` |
    | `genres` | `genre_id` |
    | `movie_genres` | `movie_id`, `genre_id` |
    | `companies` | `company_id` |
    | `movie_companies` | `movie_id`, `company_id` |
    | `countries` | `country_code` |
    | `movie_origin_countries` | `movie_id`, `country_code` |
    | `movie_production_countries` | `movie_id`, `country_code` |
    | `languages` | `language_code` |
    | `movie_spoken_languages` | `movie_id`, `language_code` |
    | `collections` | `collection_id` |
    | `people` | `person_id` |
    | `cast_credits` | `credit_id` |
    | `crew_credits` | `credit_id` |

  - **Reference checks — 14:** the two movie–genre relationships are checked by the later join indicators, so they are not repeated here. The other checks verify:
    - `movie_companies.movie_id` → `movies.movie_id`; `movie_companies.company_id` → `companies.company_id`
    - `movie_origin_countries.movie_id` → `movies.movie_id`; `movie_origin_countries.country_code` → `countries.country_code`
    - `movie_production_countries.movie_id` → `movies.movie_id`; `movie_production_countries.country_code` → `countries.country_code`
    - `movie_spoken_languages.movie_id` → `movies.movie_id`; `movie_spoken_languages.language_code` → `languages.language_code`
    - `cast_credits.movie_id` → `movies.movie_id`; `cast_credits.person_id` → `people.person_id`
    - `crew_credits.movie_id` → `movies.movie_id`; `crew_credits.person_id` → `people.person_id`
    - Non-null `movies.collection_id` values → `collections.collection_id`
    - Non-null `companies.origin_country_code` values → `countries.country_code`

- **Joined tables — 6 checks:** the notebook makes two left joins for the genre example (`movie_genres` → `genres`, then → `movies`). Each join checks that its row count is preserved, that every reference matched (`indicator` value `both`), and that the movie–genre link key remains unique.
- **Source coverage — 3 checks:** the final result after the two left joins preserves the input row count; each source line has one coverage row; and every source row without a cached movie has a logged explanation. A separate “every row has an outcome” check is omitted because the notebook assigns an outcome to every row by construction.

**Total: 40 reported checks** for the current non-empty dataset: 2 loaded-cache + 29 normalized-table + 6 join + 3 source-coverage checks. The KPI-field, KPI-value, and release-year plausibility checks are intentionally deferred until after data profiling and the KPI requirements are defined. The grain checks were consolidated for readability without dropping any of their three conditions, and duplicate or tautological checks were removed.

### Other fail-fast validations (outside the 48 report rows)

Some checks raise an error before a report can be produced; they protect the cache and normalization process rather than appearing as report rows:

- **Cache file checks:** each nonblank JSONL line must contain valid JSON; each record must be an object with string keys and a positive numeric movie ID. The cache loader stores records in a dictionary keyed by movie ID, so duplicate raw lines can be overwritten before the notebook sees them. A raw-line duplicate check is deliberately not included.
- **Nested-data shape checks:** nested lists such as genres, companies, countries, languages, cast, and crew must contain the expected kinds of values; collection and credits fields must have the expected object shape (or allowed null value).
- **Identifier and relationship checks:** IDs must be positive numeric values; required codes and credit IDs must be nonempty text; duplicate movie IDs, duplicate movie-to-entity links, and duplicate credit IDs are rejected.
- **Reference consistency checks:** repeated descriptions of the same genre, company, country, language, collection, or person must not conflict. Collection details without a collection ID are rejected.
- **Release-date parsing:** invalid dates are rejected by normalization. A plausible-year range is a separate domain assumption and is currently deferred.
- **Join cardinality checks:** pandas `validate="many_to_one"` requires the reference side to have one row per key. Source coverage uses `validate="one_to_one"` when attaching the grouped removal log. A violation raises `MergeError` before the report runs. The join `indicator` columns provide match counts, which the report checks; the row-count assertions are retained as the lab’s explicit fan-out audit.
- **Report-helper checks:** `run_data_checks` rejects a blank stage name or an empty set of checks. The caller displays the results; `raise_for_failed_checks` raises `ValueError` if any check fails.

The report does not include a cache-nonempty check because it only runs when records exist. The normalizer already rejects non-positive movie IDs, so the report does not repeat that check.

Release-year plausibility limits are not currently enforced. They can be considered after profiling the observed dates and agreeing on a business rule. The normalizer still rejects malformed date values. With an empty cache, raw and normalized checks are skipped with a message; the source-coverage stage still reports whether input IDs have cache results or logged reasons.

In the current local snapshot, the genre demonstration had 320 relationship rows matched to both references (no fan-out). The source coverage had 127 input rows: 118 rows linked to cached films and 9 with no cached film—5 recorded 404s, 3 invalid values, and 1 blank row. Six duplicate input rows were separately identified in the removal log and still link to their already-cached film. These counts describe the current files and will change as the input list/cache changes.

## 5. Business and operational limits still open

- Temporary request failures are visible in command output but are not saved to a durable retry/failure history. The current removal log is local and is ignored by Git; decide later whether operational outcomes should be shared or retained for audit.
- There is no automatic expiration or refresh schedule for successful cached responses. A deliberate cache removal currently forces a refresh.
- The current workflow is for exploration. Publishing these tables to a database or reporting tool is a separate future decision.
