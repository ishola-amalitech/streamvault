"""Read the saved candidate list and prepare the two recommendation windows."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pandas as pd

from streamvault.cache import CandidateCache, iter_cached_records, match_cached_candidates
from streamvault.config import AppConfig
from streamvault.diagnostics import raise_for_failed_checks, run_data_checks
from streamvault.load import MovieId, iter_movie_id_rows
from streamvault.movie_quality import film_quality_issues
from streamvault.normalize import MovieTables, normalization_checks, normalize_movie_records
from streamvault.removals import Removal, append_removals
from streamvault.run_record import acquisition_record_path, fingerprint, read_record, snapshot_inputs


ALL_YEARS = "All years"
RECENT = "2000 onward"
CUTOFF = pd.Timestamp("2000-01-01")


@dataclass
class CandidateSnapshot:
    """Keep the parsed list and cache together with the file versions they came from."""

    source_rows: list[MovieId | Removal]
    cache: CandidateCache
    source_sha256: str | None
    cache_sha256: str | None
    read_seconds: float

    def check_versions(self, current_inputs: Mapping[str, str | None]) -> None:
        if current_inputs["source"] != self.source_sha256 or current_inputs["cache"] != self.cache_sha256:
            raise ValueError("The candidate list or movie cache changed during the run. Run StreamVault again.")


def read_candidate_snapshot(config: AppConfig, *, log_removals: bool = False) -> CandidateSnapshot:
    """Read the candidate list and match it to the saved TMDB records."""
    started = perf_counter()
    source_sha256 = fingerprint(config.source_file)
    cache_sha256 = fingerprint(config.cache_file)
    source_rows: list[MovieId | Removal] = []
    try:
        source_rows.extend(iter_movie_id_rows(config.source_file))
    finally:
        if log_removals:
            # Keep issues found even if a later source row stops the run.
            append_removals(config.removals_file, (row for row in source_rows if isinstance(row, Removal)))
    cache = match_cached_candidates(iter_cached_records(config.cache_file), source_rows)
    return CandidateSnapshot(source_rows, cache, source_sha256, cache_sha256, perf_counter() - started)


@dataclass
class RecommendationInputs:
    """Validated movie rows and the evidence behind the scope of the analysis."""

    tables: MovieTables
    candidates: pd.DataFrame
    windows: dict[str, pd.DataFrame]
    window_counts: dict[str, dict[str, int]]
    release_outcomes: dict[str, pd.Series]
    changed_bundles: pd.DataFrame
    collection_names: pd.Series
    source_audit: pd.DataFrame
    source_counts: pd.Series
    quality_issues: pd.DataFrame
    checks: pd.DataFrame
    input_sha256: dict[str, str | None]
    cache_timestamps: pd.Series
    acquisition: dict[str, Any]


def recommendation_inputs(config: AppConfig) -> dict[str, str | None]:
    """Fingerprint the saved files that affect the recommendation."""
    return snapshot_inputs(config) | {
        "acquisition_record": fingerprint(acquisition_record_path(config)),
    }


def recorded_lookup_reasons(config: AppConfig, acquisition_run: dict[str, Any]) -> pd.Series:
    """Use the latest recorded outcome per ID, with older logs as a fallback."""
    # Match past lookup misses by ID so they still show up if a row moves.
    lookup_reasons = pd.Series(dtype="string")
    if config.removals_file.is_file() and config.removals_file.stat().st_size:
        removals = pd.read_csv(config.removals_file, dtype="string", keep_default_na=False)
        lookup_rows = removals.loc[
            removals["source_file"].eq(config.source_file.name)
            & removals["reason"].str.startswith("TMDB lookup: "),
            ["removed_value", "reason"],
        ].copy()
        lookup_rows["movie_key"] = lookup_rows["removed_value"].str.strip().str.lstrip("0")
        lookup_reasons = lookup_rows.groupby("movie_key")["reason"].agg(
            lambda reasons: " / ".join(sorted(set(reasons)))
        )

    # A newer fetch result takes priority over the older removal log.
    recorded_results = {}
    for movie_key, item in acquisition_run.get("unresolved_by_id", {}).items():
        prefix = {"lookup_miss": "TMDB lookup: ", "request_failed": "TMDB request failed: "}[item["status"]]
        recorded_results[movie_key] = prefix + item["reason"]
    return pd.Series(recorded_results, dtype="string").combine_first(lookup_reasons)


def _reconcile_source_rows(
    source_audit: pd.DataFrame, movies: pd.DataFrame, lookup_reasons: pd.Series,
) -> tuple[pd.Series, pd.DataFrame]:
    """Give each physical source row one outcome, including lookup misses and failures."""
    resolved_keys = set(movies["movie_id"].astype("string"))

    # A cached film takes priority over any earlier missing or failed request.
    pending = source_audit["outcome"].isna()
    cached = pending & source_audit["movie_key"].isin(resolved_keys)
    uncached = pending & ~cached
    unexplained_reason = "No cached record or logged acquisition outcome"
    source_audit.loc[cached, "outcome"] = "Cached"
    source_audit.loc[uncached, "outcome"] = (
        source_audit.loc[uncached, "movie_key"].map(lookup_reasons).fillna(unexplained_reason)
    )

    source_counts = source_audit["outcome"].value_counts().rename("source_rows")
    unexplained_count = int(source_audit["outcome"].eq(unexplained_reason).sum())
    source_stage = "After matching the source rows to the cache and removal log"
    source_checks = run_data_checks(
        source_stage,
        {
            "Every source row has one outcome": (
                bool(source_audit["source_line"].is_unique and source_audit["outcome"].notna().all()),
                f"{len(source_audit)} source rows accounted for",
            ),
            "The film table preserves the resolved IDs": (
                len(movies) == int(cached.sum()) and resolved_keys == set(source_audit.loc[cached, "movie_key"]),
                f"{len(movies)} distinct films in scope",
            ),
            "Every uncached candidate has a logged outcome": (
                unexplained_count == 0,
                f"{unexplained_count} unexplained misses. Example movie IDs: "
                f"{source_audit.loc[source_audit['outcome'].eq(unexplained_reason), 'movie_key'].head(5).tolist()}",
            ),
        },
    )

    raise_for_failed_checks(source_stage, source_checks)
    return source_counts, source_checks


def load_recommendation_inputs(
    config: AppConfig, snapshot: CandidateSnapshot, record_stage_time: Callable[[str], None],
) -> RecommendationInputs:
    """Validate and normalize the snapshot, then record how each window was formed."""
    analysis_inputs = recommendation_inputs(config)
    snapshot.check_versions(analysis_inputs)
    acquisition_run = read_record(acquisition_record_path(config))

    # Keep a row for every entry in the CSV, including entries the parser skips.
    source_audit = pd.DataFrame.from_records(
        (
            (row.source_line, row.source_value or row.value, None, row.value)
            if isinstance(row, MovieId)
            else (row.source_line, row.removed_value, row.reason, None)
            for row in snapshot.source_rows
        ),
        columns=["source_line", "source_value", "outcome", "movie_key"],
    ).astype({"source_value": "string", "outcome": "string", "movie_key": "string"})

    cache = snapshot.cache
    scoped_records = list(cache.records.values())
    # Use cache timestamps to set a release-year limit that stays fixed for this snapshot.
    cache_timestamps = pd.to_datetime(
        pd.Series([record.get("cached_at_utc") for record in scoped_records], dtype="object"),
        format="ISO8601",
        errors="coerce",
        utc=True,
    )
    missing_cache_times = int(cache_timestamps.isna().sum())

    load_stage = "After loading the current list and cache"
    load_checks = run_data_checks(load_stage, {
        "Source line numbers are unique": (
            bool(source_audit["source_line"].is_unique),
            f"{len(source_audit)} source rows",
        ),
        "Current candidate IDs are unique in the cache": cache.uniqueness_check(),
        "Cached films in scope have readable timestamps": (
            missing_cache_times == 0,
            f"{missing_cache_times} missing or unreadable timestamps among {len(scoped_records)} records",
        ),
    })
    raise_for_failed_checks(load_stage, load_checks)
    record_stage_time("Check saved inputs")

    # Reuse the pipeline's checks for film IDs, the collection join, genres, and credits.
    tables = normalize_movie_records(scoped_records)
    movies = tables.movies
    clean_stage = "After normalizing the film data"
    clean_checks = normalization_checks(clean_stage, tables, set(cache.records))
    raise_for_failed_checks(clean_stage, clean_checks)

    # Film-level issues are recorded with IDs. Other usable evidence can still contribute.
    quality_issues = film_quality_issues(movies)
    record_stage_time("Normalize and check films")

    lookup_reasons = recorded_lookup_reasons(config, acquisition_run)
    source_counts, source_checks = _reconcile_source_rows(source_audit, movies, lookup_reasons)
    candidates = movies.copy()
    # Keep date and status columns even when no cached film supplies those fields.
    candidates["release_date"] = movies.get(
        "release_date", pd.Series(pd.NaT, index=movies.index, dtype="datetime64[ns]")
    )
    candidates["status"] = movies.get(
        "status", pd.Series(pd.NA, index=movies.index, dtype="string")
    )
    candidates["title_type"] = candidates["collection_id"].notna().map(
        {True: "Collection-linked", False: "Standalone"}
    )
    candidates["release_year"] = candidates["release_date"].dt.year.astype("Int64")

    dated = candidates["release_date"].notna()
    released = candidates["status"].astype("string").eq("Released").fillna(False)
    all_years = dated & released
    # Use the same release rules in both windows and include 1 January 2000.
    since_2000 = all_years & candidates["release_date"].ge(CUTOFF)

    # Use a wide range. The newest cache timestamp keeps its upper end fixed for this snapshot.
    first_plausible_year = 1880
    snapshot_year = cache_timestamps.max().year
    invalid_year = all_years & ~candidates["release_year"].between(
        first_plausible_year, snapshot_year
    ).fillna(False)
    bad_year_ids = candidates.loc[invalid_year, "movie_id"]
    year_detail = (
        f"Allowed years: {first_plausible_year} to {snapshot_year}. "
        f"{len(bad_year_ids)} out of range. Example movie IDs: {bad_year_ids.head(5).tolist()}"
        if len(cache_timestamps)
        else "No cached films in scope"
    )
    windows = {
        ALL_YEARS: candidates.loc[all_years].copy(),
        RECENT: candidates.loc[since_2000].copy(),
    }

    # Count films with no date first so each excluded film appears under one reason.
    window_counts = {}
    for window, films in windows.items():
        collection_sizes = films["collection_id"].value_counts()
        window_counts[window] = {
            "Resolved films": len(candidates),
            "Missing release date": int((~dated).sum()),
            "Dated and missing release status": int((dated & candidates["status"].isna()).sum()),
            "Dated and marked with another status": int((dated & candidates["status"].notna() & ~released).sum()),
            "Dated and released but before the cutoff": (
                int((all_years & ~since_2000).sum()) if window == RECENT else 0
            ),
            "Films in window": len(films),
            "Collection-linked films": int(films["collection_id"].notna().sum()),
            "Standalone films": int(films["collection_id"].isna().sum()),
            "Observed collections": len(collection_sizes),
            "Collections with two or more observed films": int(collection_sizes.ge(2).sum()),
        }

    window_stage = "After applying the release windows"
    window_checks = run_data_checks(window_stage, {
        "Dated releases have a plausible year": (bad_year_ids.empty, year_detail),
        "Each window has unique film IDs and accounts for all resolved films": (
            all(films["movie_id"].is_unique for films in windows.values())
            and all(
                counts["Films in window"] + counts["Missing release date"]
                + counts["Dated and missing release status"]
                + counts["Dated and marked with another status"]
                + counts["Dated and released but before the cutoff"] == len(candidates)
                for counts in window_counts.values()
            ),
            f"{len(candidates)} films to account for in each window",
        ),
    })
    raise_for_failed_checks(window_stage, window_checks)

    # Normalization already proves that each supplied collection ID has one reference row.
    collection_names = tables.collections.set_index("collection_id")["collection_name"]
    collection_counts = pd.DataFrame({
        window: films["collection_id"].value_counts() for window, films in windows.items()
    }).fillna(0).astype(int)
    # Show collections with observed installments on both sides of the cutoff.
    cross_cutoff = collection_counts[RECENT].between(
        1, collection_counts[ALL_YEARS] - 1
    )
    changed_bundles = collection_counts.loc[cross_cutoff].copy()
    changed_bundles.insert(0, "Bundle", changed_bundles.index.map(collection_names))
    changed_bundles.insert(1, "Before 2000", changed_bundles[ALL_YEARS] - changed_bundles[RECENT])

    # Give every film one outcome per window, using the same order as the release-window audit.
    # Leave eligible releases blank until they get a scoring or ranking outcome.
    release_outcomes = pd.Series(pd.NA, index=candidates.index, dtype="string")
    release_outcomes.loc[~released] = "Release status is " + candidates.loc[~released, "status"].astype("string")
    release_outcomes.loc[candidates["status"].isna()] = "Missing release status"
    release_outcomes.loc[~dated] = "Missing release date"
    # Carry each window's release exclusions into the scoring audit.
    recent_outcomes = release_outcomes.copy()
    recent_outcomes.loc[all_years & ~since_2000] = "Before 1 January 2000"
    record_stage_time("Reconcile source rows and set release windows")
    return RecommendationInputs(
        tables=tables,
        candidates=candidates,
        windows=windows,
        window_counts=window_counts,
        release_outcomes={ALL_YEARS: release_outcomes, RECENT: recent_outcomes},
        changed_bundles=changed_bundles,
        collection_names=collection_names,
        source_audit=source_audit,
        source_counts=source_counts,
        quality_issues=quality_issues,
        checks=pd.concat([load_checks, clean_checks, source_checks, window_checks], ignore_index=True),
        input_sha256=analysis_inputs,
        cache_timestamps=cache_timestamps,
        acquisition=acquisition_run,
    )
