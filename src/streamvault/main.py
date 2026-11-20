"""Run the StreamVault pipeline from the candidate CSV through the recommendation."""

import asyncio
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import cast

from streamvault.cache import match_cached_candidates, write_cached_records
from streamvault.config import CONFIG, AppConfig
from streamvault.diagnostics import print_check_report, run_data_checks
from streamvault.fetch_movies import FetchFailure, FetchMissing, MissingTokenError, fetch_movies
from streamvault.load import MovieId
from streamvault.recommendation_inputs import CandidateSnapshot, read_candidate_snapshot, recorded_lookup_reasons
from streamvault.recommendation_run import RecommendationRun, run_recommendation
from streamvault.run_record import acquisition_record_path, fingerprint, read_record, snapshot_inputs, write_record


async def _acquire_movies(config: AppConfig) -> CandidateSnapshot:
    """Download uncached candidates and keep a record of every attempted ID."""
    # Reading the list also logs blank, invalid, and duplicate entries.
    snapshot = read_candidate_snapshot(config, log_removals=True)
    movie_ids = [row for row in snapshot.source_rows if isinstance(row, MovieId)]
    cache = snapshot.cache
    stage = "After loading"
    print_check_report(stage, run_data_checks(stage, {
        "Current candidate IDs are unique in the cache": cache.uniqueness_check(),
    }))
    cached_records = cache.records | cache.other_records
    missing_timestamps = sum(
        not isinstance(record.get("cached_at_utc"), str)
        for record in cached_records.values()
    )

    ids_to_fetch = [movie for movie in movie_ids if movie.value not in cached_records]
    records: list[dict[str, object]] = []
    missing: list[FetchMissing] = []
    failures: list[FetchFailure] = []
    fetch_seconds: float | None = None
    if ids_to_fetch:
        # Time the fetch step before writing the cache and run report.
        fetch_start = perf_counter()
        try:
            records, missing, failures = await fetch_movies(ids_to_fetch, config=config)
        except MissingTokenError:
            # A saved snapshot can be replayed if every unfetched ID already has an explanation.
            acquisition = read_record(acquisition_record_path(config))
            known = recorded_lookup_reasons(config, acquisition)
            if any(movie.value not in known.index for movie in ids_to_fetch):
                raise
            print(f"Using saved outcomes for {len(ids_to_fetch)} uncached IDs. Supply a TMDB token to retry them.")
        else:
            fetch_seconds = perf_counter() - fetch_start
            # Check the results before caching them. A miss or a failed request still accounts for an ID.
            returned_ids = [str(record.get("id")).lstrip("0") for record in records]
            outcomes = Counter(returned_ids)
            outcomes.update(item.movie_id for item in missing)
            outcomes.update(item.movie_id for item in failures)
            requested = {movie.value for movie in ids_to_fetch}
            missing_ids = sorted(requested - outcomes.keys())
            extra_ids = sorted(outcomes.keys() - requested)
            repeated_ids = sorted(key for key, count in outcomes.items() if count > 1)
            stage = "After fetching"
            print_check_report(stage, run_data_checks(stage, {
                "Each requested ID has exactly one outcome": (
                    not (missing_ids or extra_ids or repeated_ids),
                    f"{len(requested)} requested, {outcomes.total()} outcomes. "
                    f"Missing: {missing_ids[:5]}. Unexpected: {extra_ids[:5]}. "
                    f"Repeated: {repeated_ids[:5]}.",
                ),
            }))

    # Confirm we are updating the files we loaded, including after a slow fetch.
    if fetch_seconds is not None or missing_timestamps:
        snapshot.check_versions(snapshot_inputs(config))
    if records or missing_timestamps:
        saved_records = write_cached_records(
            config.cache_file, [*cached_records.values(), *records]
        )
        # Use the stored records, including timestamps, without decoding the cache again.
        snapshot.cache = match_cached_candidates(saved_records.items(), snapshot.source_rows)
        snapshot.cache_sha256 = fingerprint(config.cache_file)
    if missing_timestamps:
        print(f"Added cache timestamps to existing records: {missing_timestamps}")

    if not movie_ids:
        print("No movie IDs to fetch.")

    # Keep the previous download report if this run used only cached movies.
    if fetch_seconds is not None:
        recorded_at = datetime.now(timezone.utc).isoformat()
        record_path = acquisition_record_path(config)
        saved_unresolved: object = read_record(record_path).get("unresolved_by_id", {})
        if not isinstance(saved_unresolved, dict):
            raise ValueError(f"Expected an object for 'unresolved_by_id' in {record_path}.")
        unresolved = cast(dict[str, object], saved_unresolved)

        # Keep the last observed result per ID until a lookup replaces it or we get the film.
        for movie_id in (*cached_records, *(str(record["id"]) for record in records)):
            unresolved.pop(movie_id.lstrip("0"), None)
        source_lines = {movie.value: movie.source_line for movie in ids_to_fetch}
        for item in missing:
            unresolved[item.movie_id.lstrip("0")] = {
                "status": "lookup_miss",
                "reason": item.reason,
                "source_line": item.source_line,
                "recorded_at_utc": recorded_at,
            }
        for failure in failures:
            unresolved[failure.movie_id.lstrip("0")] = {
                "status": "request_failed",
                "reason": failure.message,
                "source_line": source_lines[failure.movie_id],
                "recorded_at_utc": recorded_at,
            }
        write_record(
            config.acquisition_file,
            {
                "recorded_at_utc": recorded_at,
                "input_sha256": snapshot_inputs(config),
                "fetch_seconds": fetch_seconds,
                "requested": len(ids_to_fetch),
                "fetched": len(records),
                "lookup_misses": len(missing),
                "request_failures": len(failures),
                "unresolved_by_id": unresolved,
            },
        )

    print(f"Movie IDs in source: {len(movie_ids)}")
    print(f"Already cached: {len(movie_ids) - len(ids_to_fetch)}")
    print(f"New records fetched: {len(records)}")
    print(f"Missing movie IDs: {len(missing)}")
    for item in missing:
        print(f"line {item.source_line}, {item.movie_id}: {item.reason}")

    print(f"Failed requests: {len(failures)}")
    for failure in failures:
        print(f"{failure.movie_id}: {failure.message}")
    return snapshot


async def run(
    config: AppConfig | None = None, *, output_dir: Path | None = None,
) -> RecommendationRun:
    """Bring the cache up to date, then run the analysis on the saved inputs."""
    if config is None:
        config = CONFIG
    snapshot = await _acquire_movies(config)
    # The notebook calls the same function and lets it load the saved candidate snapshot.
    # The app saves download files separately while keeping the shared acquisition history.
    analysis = run_recommendation(config, snapshot=snapshot, output_dir=output_dir or config.output_dir)
    print_check_report("Recommendation input checks", analysis.inputs.checks)
    print()
    print(analysis.summary, end="")
    print(f"\nSaved recommendation and CSVs to {analysis.directory}")
    print(f"Exclusions report: {analysis.exclusions_path}")
    print(f"Film issues: {analysis.quality_path}")
    print(f"Run record: {analysis.directory / 'run.json'}")
    return analysis


def main() -> None:
    """Start the full pipeline when someone runs the streamvault command."""
    try:
        asyncio.run(run())
    except (OSError, ValueError) as error:
        raise SystemExit(f"StreamVault could not complete: {error}") from None


if __name__ == "__main__":
    main()
