# StreamVault decision record

This record explains where the acquisition, profiling and licensing methods came from, what could change the answer, and what Adjoa can reuse. The [lab brief](../data/lab_brief.md) defines the fictional assignment. Snapshot evidence and analyst answers live in the [findings](findings.md) and [questions](questions.md) logs.

## Implemented acquisition and preparation

### D01 · Account for each input and reuse successful responses

The input contract is a single `tmdb_id` column. The parser keeps the first occurrence of a valid positive numeric ID and records blanks, invalid values and repeated entries with source line and reason. The client requests movie details with credits appended, using one shared HTTP session. Configuration supplies eight concurrent workers, four request starts per second, 10-second total and 3.05-second connect timeouts, and up to three retries after the first attempt for network errors, HTTP 429 and HTTP 5xx. Retryable HTTP responses use a valid `Retry-After` value when present. Otherwise the initial delay is 0.5 seconds and doubles for each retry.

Cache the successful JSON responses by ID in JSONL, stamp them in UTC, and replace the file atomically. The backfill timestamp indicates when an existing entry was stamped. Reuse cached IDs and retry uncached IDs on subsequent runs. The removal log records 404s and empty responses alongside malformed or duplicate inputs. Terminal request failures are printed with IDs. A durable terminal-failure record remains to be implemented.

The prep notebook reconciles physical input rows against cached IDs and the removal log. Its source join retains cached matches for duplicate input rows so the audit can account for all 127 source lines while counting 112 distinct titles. Unexplained cache misses fail the source-coverage check. Refreshing the whole cache every time would provide fresher audience metrics at the cost of more API traffic, slower meetings, and comparisons against different snapshots. Until the recommendation scopes inputs explicitly, preserve a cache and removal log for each candidate-list snapshot to avoid retaining past candidates in an analysis. [Configuration](../config.toml) · [ID parser](../src/streamvault/load.py) · [Fetcher](../src/streamvault/fetch_movies.py) · [Cache](../src/streamvault/cache.py) · [Prep](../notebooks/01_prep_movie_data.ipynb)

### D02 · Keep film, relationship, and credit grains distinct

Assign the stable keys when normalizing. Keep one movie row per `movie_id`, with an optional `collection_id`. The reference tables contain one row per entity, and links for multiply occurring attributes live in bridge or credit tables. Cast and crew retain popularity at the credit level because a person's value can differ between cached movie responses.

| Grain | Tables and keys |
| --- | --- |
| Film | `movies`, keyed by `movie_id` |
| Reference entity | `genres.genre_id`, `companies.company_id`, `countries.country_code`, `languages.language_code`, `collections.collection_id`, `people.person_id` |
| Film–entity link | `movie_genres`, `movie_companies`, `movie_origin_countries`, `movie_production_countries`, `movie_spoken_languages`, each keyed by `movie_id` plus the entity key |
| Credit | `cast_credits` and `crew_credits`, keyed by `credit_id`, with film and person references |

The prep notebook runs 40 staged report checks on the current nonempty input. These include two for raw cache, 29 for normalized tables, six for the illustrative genre joins and three for source coverage. It also runs a cross-table join audit across seven bridges or credit tables and the optional collection and company-country references. Required joins use left joins and declared cardinality, with indicators to expose unresolved IDs. The current 320 genre links survive both reference joins. Source coverage also checks one row per physical input line after attaching grouped removal reasons. Normalization and merge cardinality can raise before a report.

The raw loader checks JSON, object shape and positive numeric IDs. The normalizer rejects malformed relationship shapes or dates, duplicate movie/relationship/credit keys and conflicting reference attributes. The profile reads raw lines directly to detect identical entries that the loader's ID index could hide. A rough title-and-year match remains a manual-review candidate. A flat table could be quick to inspect, but aggregating money on exploded genre or credit rows would overcount films. Aggregate to movie grain before attaching relationship measures. [Normalizer](../src/streamvault/normalize.py) · [Prep](../notebooks/01_prep_movie_data.ipynb) · [Profile](../notebooks/02_profile_movie_data.ipynb)

### D03 · Treat validity, missingness and plausible extremes according to their effect

Normalize blank text to missing and parse release dates. Preserve optional text or reference-label gaps. Keep nonnegative numeric fields and a 0–10 vote rating as validity expectations. Current numeric range checks are profiling reports. The recommendation plan adds KPI-specific eligibility gates, with separate counts for missing values, zeros, and impossible values. Positive budget and gross are required for the planned financial proxies. Observed ranges are descriptive.

Keep plausible IQR extremes in the primary analysis and use omission as a sensitivity case. Discarding observations because they are rare would remove some of the films most relevant to the bundle decision. Keeping a plausible outlier can make a result depend heavily on one title, so report influence and disclose when the direction changes. [Profile](../notebooks/02_profile_movie_data.ipynb) · [EDA](../notebooks/03_eda_movie_data.ipynb)

### D04 · Keep the canonical types and measure runtime separately

Benchmark downcasts and categories on a copy. The experiment reduced movie-frame memory from 140,626 to 125,716 bytes with 112 films. Keep the canonical normalized frame until a repeatable benchmark at the next scale shows a practical benefit. Applying narrow types now would couple the pipeline to the current observed ranges and risk incorrect representation on a larger snapshot. The profile result measures memory. Laptop runtime and cold fetch time still need measurements. [Profile](../notebooks/02_profile_movie_data.ipynb)

## Chosen methods for the recommendation plan

These decisions make the planned analysis reproducible. Notebook 04 specifies the operational rules and sensitivity cases. Execution, conclusions, and the client memo remain pending. [Recommendation notebook](../notebooks/04_recommendation.ipynb)

### D05 · Bound the conclusion to the list and the two release windows

Work from the current unique resolved IDs and include dated, released titles. Run the whole analysis separately for all years and for releases on or after 1 January 2000. The windows are nested. Agreement shows sensitivity to the cutoff, and differences can come from changed bundle membership as well as changed outcomes. Eight collections in the current cache cross the cutoff. A pooled window would discard Yaw's comparison. Applying the cutoff addresses the era concern directly, while release-period summaries give context for nominal gross. The candidate list's narrow coverage and mixed provenance limit generalization beyond this pool. [Brief](../data/lab_brief.md) · [Findings](findings.md)

### D06 · Rank by a fixed audience response measure

Give priority to the TMDB audience rating, shrunk toward 7.0 with weight equal to 1,000 votes. Use a minimum of 1,000 recorded votes for ranking. The fixed constants are analyst choices and apply identically across both windows and future reruns. The anchor sits below the current pool mean of about 7.59. At the threshold, audience votes and the anchor contribute equally. These choices can lower the rank of well-reviewed titles with fewer votes, which is why the plan checks the anchor and vote floor separately. The EDA's cache-derived mean and vote quartile served exploratory comparisons.

Rank standalones by adjusted rating, votes, then numeric movie ID. Rank collections by median adjusted rating, lowest installment adjusted rating, median votes, then numeric collection ID. Order the performance metrics descending and IDs ascending. Use full precision and deterministic ties. Report vote count as evidence of breadth and popularity as snapshot context. A reach-first ranking could favor broader awareness and a gross-first ranking could favor larger or newer theatrical releases. Run reach-first, alternate eligibility thresholds and a lower rating anchor to show what each choice costs. A smaller candidate pool can produce fewer than the target three franchises or five standalones. [EDA](../notebooks/03_eda_movie_data.ipynb) · [Recommendation notebook](../notebooks/04_recommendation.ipynb)

### D07 · Compare equally weighted packages and single titles

TMDB collection membership supplies the hypothetical package. Count at least two observed, dated, released films in the window and require usable rating evidence for each. List included installments and report what the candidate list cannot establish about completeness. A title without a collection ID is a standalone proxy. The lab comparison uses the observed list and its metadata.

Compare one median score per eligible collection with one score per standalone. Require at least five units per side and a descriptive 95% bootstrap interval beyond a 0.25 rating-point margin to favor either type. This margin is a judgment about how large a gap should be to drive a preference. Show the gap, the interval, and per-film comparisons so the reader can see how the rule affects the answer. Film weighting would give larger series extra influence. Summed gross grows with bundle size, so show it only alongside the typical film and remove the highest-scoring installment in a sensitivity run to expose reliance on the strongest entry. [Recommendation notebook](../notebooks/04_recommendation.ipynb)

### D08 · Base talent evidence on identities, roles and cross-group repetition

Use director crew jobs and cast orders 0–2 as the lead-cast proxy. Count distinct films by `person_id` and use IDs for collection membership. Require three films across two or more groups, with each collection or standalone representing one group. Assess directional sensitivity to leaving out the largest group. Keep the descriptive result when sample size or dependence limits the claim. A three-film-only rule can mistake one successful franchise for a transferable talent signal. Use period and collection-aware validation for any future predictive claim. [EDA](../notebooks/03_eda_movie_data.ipynb) · [Recommendation notebook](../notebooks/04_recommendation.ipynb)

### D09 · Give relative deal priority and name the supporting metric

Show reported gross minus production budget and that difference divided by budget for positive inputs. These are nominal theatrical proxies. The deal note names the strongest eligible lab package, its main KPI, the denominator and window, how it compares with the runner-up bundle and strongest standalone, and what limits the comparison. The one-page memo explains the relative priority within the fictional $14M decision. An exact offer would require a relationship between platform outcomes, package costs and licensing terms that the provided data cannot establish. [Brief](../data/lab_brief.md) · [Recommendation notebook](../notebooks/04_recommendation.ipynb)

### D10 · Make quarterly reruns explainable

Use the current ID list to scope the cached candidate set and preserve the same scoring logic across windows. The existing request limits, cache, keys, and aggregate join design can be reused at about 500 titles. Verify that claim with measured cold-fetch and cached-analysis timings. Record final outcomes by ID and recheck reference conflicts, eligibility counts, and small groups when the list grows.

The proposed improvement beyond the brief is a run record with source and cache fingerprints, code revision, timestamps, analysis parameters, exclusion counts and timings. Saving the record with the snapshot gives Adjoa a way to reproduce a meeting result and explain whether a later shortlist changed because of the input or the method. End-to-end clean-clone execution of the recommendation, the 500-title benchmark, the run record, and the final memo still need verification or implementation. [Recommendation notebook](../notebooks/04_recommendation.ipynb)
