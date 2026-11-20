"""Measure smaller movie-table types on the same 500 cached films."""

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import pandas as pd

from benchmark_recommendation import (
    TEST_TITLES, prepare_snapshot, read_templates, run_snapshot, write_test_snapshot,
)
from streamvault._normalize_tables import Row
from streamvault.cache import iter_cached_records
from streamvault.config import CONFIG
from streamvault.normalize import MovieTables, normalize_movie_records
from streamvault.run_record import fingerprint, read_record, snapshot_inputs, write_record


TRIALS_PER_TYPE = 3
LABEL_COLUMNS = ("original_language", "status")
KEY_COLUMNS = ("movie_id", "collection_id")


def compact_movies(movies: pd.DataFrame) -> pd.DataFrame:
    """Try smaller types for whole numbers and repeated labels on a separate table."""
    # Share the other columns. Pandas keeps the original table intact when a column is replaced.
    compact = movies.copy(deep=False)
    for column in movies.select_dtypes(include="integer").columns:
        # The talent analysis uses one group-ID column for both collection IDs and movie IDs.
        # A type that fits the collections alone can be too small for the movie IDs.
        if column in KEY_COLUMNS:
            continue
        values = movies[column]
        observed = values.dropna()
        if observed.empty:
            continue
        # Let pandas choose a size based on the actual values. Keep signed types for negatives.
        kind = "unsigned" if observed.min() >= 0 else "integer"
        compact[column] = pd.to_numeric(values, downcast=kind)

    for column in LABEL_COLUMNS:
        if column in movies and pd.api.types.is_string_dtype(movies[column]):
            values = movies[column]
            encoded = values.astype("category")
            # A lookup table for labels helps only if it costs less than the original column.
            if encoded.memory_usage(index=False, deep=True) < values.memory_usage(index=False, deep=True):
                compact[column] = encoded
    return compact


def verify_values(original: pd.DataFrame, compact: pd.DataFrame) -> None:
    # Compare in the original types to check exact values, row order, and missing values.
    pd.testing.assert_frame_equal(original, compact.astype(original.dtypes.to_dict()), check_exact=True)


def verify_integer_limits() -> None:
    # Include a budget above the unsigned 32-bit limit and a missing integer in each column.
    large_budget = 1 << 40
    original = pd.DataFrame({
        "small": pd.array([1, None, 255], dtype="Int64"),
        "budget": pd.array([100, None, large_budget], dtype="Int64"),
        "signed": pd.array([-129, None, 127], dtype="Int64"),
        "movie_id": [1, 2, 3],
        "collection_id": pd.array([2, None, 10], dtype="Int64"),
    })
    compact = compact_movies(original)
    verify_values(original, compact)
    expected_types = {
        "small": "UInt8", "budget": "UInt64", "signed": "Int16",
        "movie_id": "int64", "collection_id": "Int64",
    }
    if compact.dtypes.astype(str).to_dict() != expected_types:
        raise AssertionError("The test integers did not use types large enough to hold their ranges.")


def measure_snapshot(source_name: str, variant: str) -> None:
    # OS high-water marks need a separate process for every trial.
    import resource

    def normalize_for_trial(records: Iterable[Row]) -> MovieTables:
        tables = normalize_movie_records(records)
        if variant == "compact":
            return replace(tables, movies=compact_movies(tables.movies))
        return tables

    # Use the pipeline analysis with one alternate movie-table step. Time the conversion too.
    with patch("streamvault.recommendation_inputs.normalize_movie_records", normalize_for_trial):
        tables = run_snapshot(source_name)

    # Linux reports KiB and macOS reports bytes. Measure before inspecting the tables.
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak_rss if sys.platform == "darwin" else peak_rss * 1024
    write_record(Path("trial.json"), {
        "movie_table_bytes": int(tables.movies.memory_usage(index=True, deep=True).sum()),
        "peak_process_bytes": peak_bytes,
    })


def main() -> None:
    verify_integer_limits()
    variants = ("original", "compact")
    trials: dict[str, list[dict[str, int | float]]] = {variant: [] for variant in variants}
    reference_run: dict[str, Any] | None = None
    same_result_fields = (
        "input_sha256", "windows", "window_evidence", "checks", "comparison_results",
        "shortlist_leaders", "shortlist_changes", "rankings_sha256",
        "exclusions_report_sha256", "recommendation_sha256", "cached_timing_boundary",
    )

    with TemporaryDirectory(prefix="streamvault-types-") as directory:
        project = Path(directory)
        settings = prepare_snapshot(CONFIG.project_root, project, CONFIG.source_file.name)
        source_fingerprints = snapshot_inputs(CONFIG)
        templates = read_templates(CONFIG)
        write_test_snapshot(settings, templates)
        run_path = settings.output_dir / "run.json"

        # Both versions read the exact same saved inputs. Alternate which one runs first.
        for trial in range(TRIALS_PER_TYPE):
            order = variants if trial % 2 == 0 else variants[::-1]
            for variant in order:
                subprocess.run([
                    sys.executable, str(Path(__file__).resolve()), "--trial",
                    settings.source_file.name, variant,
                ], cwd=project, check=True)
                run = read_record(run_path)
                if run["source_outcomes"].get("Cached") != TEST_TITLES:
                    raise AssertionError("The recommendation did not account for all test films.")
                if reference_run is None:
                    reference_run = run
                else:
                    differences = [field for field in same_result_fields if run[field] != reference_run[field]]
                    if differences:
                        raise AssertionError(f"The recommendation outputs differ in {', '.join(differences)}.")
                measurements = read_record(project / "trial.json")
                trials[variant].append({
                    "movie_table_bytes": int(measurements["movie_table_bytes"]),
                    "peak_process_bytes": int(measurements["peak_process_bytes"]),
                    "cached_analysis_seconds": float(run["cached_analysis_seconds"]),
                })

        # Check every normalized movie value outside the timed runs.
        original = normalize_movie_records(record for _, record in iter_cached_records(settings.cache_file)).movies
        compact = compact_movies(original)
        verify_values(original, compact)

    if reference_run is None:
        raise RuntimeError("The memory benchmark recorded no completed trials.")

    report_path = CONFIG.output_dir / "movie_types_benchmark.json"
    summary: dict[str, dict[str, int | float]] = {
        variant: {key: median(trial[key] for trial in attempts) for key in attempts[0]}
        for variant, attempts in trials.items()
    }
    changes: dict[str, dict[str, str | int]] = {
        str(column): {
            "original": str(original[column].dtype),
            "compact": str(compact[column].dtype),
            "saved_bytes": int(
                original[column].memory_usage(index=False, deep=True)
                - compact[column].memory_usage(index=False, deep=True)
            ),
        }
        for column in original.columns if original[column].dtype != compact[column].dtype
    }
    write_record(report_path, {
        "test_titles": TEST_TITLES,
        "template_titles": len(templates),
        "trials_per_type": TRIALS_PER_TYPE,
        "platform": platform.platform(),
        "versions": reference_run["versions"],
        "timing_boundary": reference_run["cached_timing_boundary"],
        "peak_memory_boundary": "Analysis process from startup through execution, including imports.",
        "input_sha256": reference_run["input_sha256"],
        "source_input_sha256": source_fingerprints,
        "package_code": reference_run["code"],
        "benchmark_code_sha256": {
            name: fingerprint(Path(__file__).with_name(name))
            for name in ("benchmark_movie_types.py", "benchmark_recommendation.py")
        },
        "type_changes": changes,
        "results_verified": list(same_result_fields) + ["exact movie values and missing values", "integer limits"],
        "medians": summary,
        "trials": trials,
    })
    for variant, values in summary.items():
        print(
            f"{variant.capitalize()}: "
            f"{values['movie_table_bytes'] / 1024:,.1f} KiB in the movie table, "
            f"{values['peak_process_bytes'] / 1024**2:,.1f} MiB peak process memory, "
            f"{values['cached_analysis_seconds']:.2f} seconds."
        )
    print(f"Saved {report_path}")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--trial":
        measure_snapshot(sys.argv[2], sys.argv[3])
    else:
        main()
