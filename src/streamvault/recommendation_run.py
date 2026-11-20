"""Run and save the same recommendation from the CLI, notebook, or benchmark."""

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
from platform import python_version
import subprocess
from time import perf_counter
from typing import Any

import pandas as pd

from streamvault.config import AppConfig
from streamvault.recommendation import (
    BOOTSTRAP_DRAWS, BOOTSTRAP_SEED, BUNDLE_TARGET, COMPARISON_MARGIN,
    COMPARISON_MINIMUM, STANDALONE_TARGET,
)
from streamvault.recommendation_analysis import (
    BASELINE_SETTINGS, SCENARIOS, Recommendation, ScoringTests, recommend, test_scoring_choices,
)
from streamvault.recommendation_inputs import (
    CUTOFF, CandidateSnapshot, RecommendationInputs, load_recommendation_inputs,
    read_candidate_snapshot, recommendation_inputs,
)
from streamvault.recommendation_reports import (
    build_rankings, recommendation_summary, write_exclusions_report, write_rankings,
)
from streamvault.recommendation_talent import (
    GENRE_MODEL_MINIMUM, GENRE_SUMMARY_MINIMUM, TALENT_GROUP_MINIMUM, TALENT_TITLE_MINIMUM,
    TalentEvidence, review_talent,
)
from streamvault.run_record import fingerprint, read_record, write_record, write_text_atomic


CACHED_TIMING_BOUNDARY = (
    "From reading the saved analysis inputs through writing report files and checking fingerprints. "
    "TMDB fetching, test-cache setup, and writing the final run record happen outside this timing."
)


@dataclass
class RecommendationRun:
    """The calculated evidence and the files that were published for it."""

    inputs: RecommendationInputs
    results: Recommendation
    talent: TalentEvidence
    scoring_tests: ScoringTests
    summary: str
    directory: Path
    exclusions_path: Path
    rankings_path: Path
    record: dict[str, Any]


def _code_version(project: Path) -> dict[str, object]:
    # The notebook only displays the results. Record the package files that calculate them.
    try:
        git = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True, timeout=5,
        )
        revision = git.stdout.strip() if git.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        revision = None

    paths = [project / name for name in ("config.toml", "pyproject.toml", "uv.lock")]
    paths.extend(sorted((project / "src" / "streamvault").glob("*.py")))
    return {
        "git_revision": revision,
        "files": {path.relative_to(project).as_posix(): fingerprint(path) for path in paths},
    }


def _matching_benchmark(directory, input_sha256, code, versions) -> dict[str, Any] | None:
    # Only show the 500-title timing if it describes this version and the same source snapshot.
    benchmark = read_record(directory / "benchmark.json")
    matches = (
        benchmark.get("original_input_sha256") == input_sha256
        and benchmark.get("code", {}).get("files") == code["files"]
        and benchmark.get("versions") == versions
        and benchmark.get("timing_boundary") == CACHED_TIMING_BOUNDARY
    )
    if not matches:
        return None
    return {key: benchmark[key] for key in (
        "baseline_titles", "test_titles", "baseline_seconds", "projected_seconds", "seconds",
        "platform", "recorded_at_utc", "stages",
    )}


def run_recommendation(
    config: AppConfig, *, snapshot: CandidateSnapshot | None = None, output_dir: Path | None = None,
) -> RecommendationRun:
    """Use local data to produce both windows and write a complete set of reports."""
    if snapshot is None:
        snapshot = read_candidate_snapshot(config)
    # Include the same input-read time when the CLI passes in a snapshot loaded before fetching.
    stage_seconds = {"Read candidate list and cache": snapshot.read_seconds}
    stage_started = perf_counter()

    def record_stage_time(stage: str) -> None:
        nonlocal stage_started
        now = perf_counter()
        stage_seconds[stage] = now - stage_started
        stage_started = now

    inputs = load_recommendation_inputs(config, snapshot, record_stage_time)
    results = recommend(inputs, record_stage_time)
    talent = review_talent(inputs.tables, results.scored_windows, inputs.collection_names)
    record_stage_time("Review genre and talent")
    tests = test_scoring_choices(inputs, results)
    record_stage_time("Test scoring alternatives")
    rankings, candidate_checks = build_rankings(inputs, results)
    summary = recommendation_summary(inputs, results, talent)
    record_stage_time("Prepare the rankings and recommendation")

    # Finish all analysis checks before publishing, and reject an input edit during the run.
    if recommendation_inputs(config) != inputs.input_sha256:
        raise ValueError("A saved input changed during analysis. Run StreamVault again.")

    # Notebook runs keep their generated reports beside the saved cache.
    directory = output_dir if output_dir is not None else config.cache_file.with_suffix(".recommendation")
    exclusions_dir = directory if output_dir is not None else config.cache_file.parent
    exclusions = exclusions_dir / "recommendation_exclusions.md"
    rankings_path = directory / "rankings.xlsx"
    # Publish the run record last so its fingerprints describe the finished reports.
    write_rankings(rankings_path, rankings)
    write_exclusions_report(exclusions, inputs.source_audit, results.film_outcomes, results.window_evidence, inputs.quality_issues)
    write_text_atomic(directory / "recommendation.md", summary)
    report_hashes = {
        "recommendation_sha256": fingerprint(directory / "recommendation.md"),
        "exclusions_report_sha256": fingerprint(exclusions),
        "rankings_sha256": fingerprint(rankings_path),
    }
    code = _code_version(config.project_root)
    record_stage_time("Save reports and check fingerprints")

    window_counts = {
        window: inputs.window_counts[window] | {
            "scored_films": int(scored["adjusted_rating"].count()),
            "score_exclusion_reasons": {
                str(reason): int(count) for reason, count in scored["score_exclusion"].value_counts().items() if reason
            },
            "eligible_bundles": len(results.ranked_bundles[window]),
            "shortlisted_bundles": len(results.bundle_shortlists[window]),
            "eligible_standalones": len(results.ranked_standalones[window]),
            "shortlisted_standalones": len(results.standalone_shortlists[window]),
        }
        for window, scored in results.scored_windows.items()
    }
    # A timing from an older fetch only applies if the source, cache, and removal log match.
    fetch_measured = inputs.acquisition.get("input_sha256") == {
        key: inputs.input_sha256[key] for key in ("source", "cache", "removals")
    }
    fetch_record = {
        key: inputs.acquisition.get(key) if fetch_measured else None
        for key in ("recorded_at_utc", "fetch_seconds", "requested", "fetched", "lookup_misses", "request_failures")
    }
    fetch_record["status"] = "Matched acquisition run" if fetch_measured else "No measured acquisition for this snapshot"
    versions = {"python": python_version(), **{
        name: version(name) for name in ("numpy", "pandas", "scikit-learn", "xlsxwriter")
    }}
    timestamps = inputs.cache_timestamps
    checks = pd.concat([inputs.checks, results.checks, talent.checks, candidate_checks], ignore_index=True)
    record = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": inputs.input_sha256,
        "code": code,
        "versions": versions,
        "cache_timestamps_utc": {
            "first_in_scope": timestamps.min().isoformat() if len(timestamps) else None,
            "last_in_scope": timestamps.max().isoformat() if len(timestamps) else None,
        },
        "parameters": BASELINE_SETTINGS | {
            "cutoff": CUTOFF.date().isoformat(), "bundle_target": BUNDLE_TARGET, "standalone_target": STANDALONE_TARGET,
            "comparison_minimum": COMPARISON_MINIMUM, "comparison_margin": COMPARISON_MARGIN,
            "bootstrap_draws": BOOTSTRAP_DRAWS, "bootstrap_seed": BOOTSTRAP_SEED, "scenarios": SCENARIOS,
            "genre_summary_minimum": GENRE_SUMMARY_MINIMUM, "genre_model_minimum": GENRE_MODEL_MINIMUM,
            "talent_title_minimum": TALENT_TITLE_MINIMUM, "talent_group_minimum": TALENT_GROUP_MINIMUM,
        },
        "source_rows": len(inputs.source_audit),
        "source_outcomes": {str(reason): int(count) for reason, count in inputs.source_counts.items()},
        "windows": window_counts,
        "window_evidence": results.window_evidence.to_dict(orient="index"),
        "film_issue_rows": len(inputs.quality_issues),
        "checks": checks.to_dict(orient="records"),
        "comparison_results": json.loads(tests.comparisons.to_json(orient="records", double_precision=15)),
        "shortlist_leaders": json.loads(tests.leaders.to_json(orient="records")),
        "shortlist_changes": json.loads(tests.shortlist_changes.to_json(orient="records")),
        **report_hashes,
        "acquisition": fetch_record,
        "cached_analysis_seconds": sum(stage_seconds.values()),
        "cached_timing_boundary": CACHED_TIMING_BOUNDARY,
        "cached_stage_seconds": stage_seconds,
        "cached_scale_check": _matching_benchmark(config.output_dir, inputs.input_sha256, code, versions),
    }
    write_record(directory / "run.json", record)
    return RecommendationRun(inputs, results, talent, tests, summary, directory, exclusions, rankings_path, record)
