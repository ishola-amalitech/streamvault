# StreamVault project decisions and data guide

This document is the running record of the project’s important choices. It explains how the data is collected, what each analysis table means, how joins are checked, and which limitations remain. The language is intended to be understandable without a technical background.

## 1. Collection and network behavior

### Source and access

- The starting list is `id_list.csv`; each valid `tmdb_id` is requested from the TMDB movie-details endpoint, including credits.
- The API access token is read from the `TMDB_API_READ_ACCESS_TOKEN` environment variable. It is not stored in the repository.
- One reusable asynchronous HTTP session is used for a batch. The project allows up to eight requests in progress and schedules requests at four per second.

### Timeouts and retries

- Each request has a 10-second timeout and a 3.05-second connection timeout.
- Network/request errors, HTTP 429 rate limits, and HTTP 5xx server errors are retried up to three times after the first attempt (at most four attempts total).
- For HTTP 429, the client honors the server’s `Retry-After` instruction when it is valid. Otherwise, and for server/network errors, it waits with exponential backoff: 0.5, 1, then 2 seconds between retries.
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
- **Row-count assertion:** after each left join, the notebook asserts that the row count is unchanged. This catches accidental row multiplication even if a future join is edited incorrectly.
- **Source-list coverage:** every physical row in `id_list.csv` (including blank and duplicate rows) is left-joined to the cache with `validate="many_to_one"` and an indicator. It is then joined to the grouped removal log by source line and original value, with `validate="one_to_one"` and another indicator. The row count is checked after both joins. A cached match, known invalid/duplicate/not-found entry, and an unmatched row without a recorded reason are distinguishable; an unexplained cache miss is not guessed to be a 404.

In the current local snapshot, the genre demonstration had 320 relationship rows matched to both references (no fan-out). The source coverage had 127 input rows: 118 rows linked to cached films and 9 with no cached film—5 recorded 404s, 3 invalid values, and 1 blank row. Six duplicate input rows were separately identified in the removal log and still link to their already-cached film. These counts describe the current files and will change as the input list/cache changes.

## 5. Business and operational limits still open

- Temporary request failures are visible in command output but are not saved to a durable retry/failure history. The current removal log is local and is ignored by Git; decide later whether operational outcomes should be shared or retained for audit.
- There is no automatic expiration or refresh schedule for successful cached responses. A deliberate cache removal currently forces a refresh.
- The current workflow is for exploration. Publishing these tables to a database or reporting tool is a separate future decision.
