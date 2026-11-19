"""Compare cached notebook timings at the current size and at 500 titles."""

import copy
from dataclasses import replace
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output
import nbformat

import streamvault.config as config
from streamvault.cache import iter_cached_records, match_cached_candidates, write_cached_records
from streamvault.load import iter_movie_id_rows
from streamvault.run_record import read_record, write_record


NOTEBOOK_PATH = Path("notebooks/04_recommendation.ipynb")
TEST_TITLES = 500


def make_test_records(templates, size):
    # Repeat the shapes of real records using fresh movie, collection and credit IDs.
    collection_ids = {}
    for index in range(size):
        repeat, template = divmod(index, len(templates))
        record = copy.deepcopy(templates[template])
        record["id"] = 1_000_000_000 + index
        collection = record.get("belongs_to_collection")
        if collection:
            key = (repeat, int(collection["id"]))
            collection["id"] = collection_ids.setdefault(key, len(collection_ids) + 1)
        for role in ("cast", "crew"):
            for credit in (record.get("credits") or {}).get(role) or []:
                credit["credit_id"] = f"benchmark-{index}-{credit['credit_id']}"
        yield record


def prepare_snapshot(root, project, source_name):
    # Copy the files needed to run and identify the code in the timing record.
    for path in (NOTEBOOK_PATH, Path("config.toml"), Path("pyproject.toml"), Path("uv.lock")):
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / path, project / path)
    shutil.copytree(
        root / "src" / "streamvault", project / "src" / "streamvault",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (project / "docs").mkdir()
    (project / "inputs").mkdir()
    (project / "data" / "raw").mkdir(parents=True)
    return snapshot_config(project, source_name)


def snapshot_config(project, source_name):
    return replace(
        config.load_config(project / "config.toml"), source_file=project / "inputs" / source_name,
        cache_file=project / "data/raw/movies.jsonl", removals_file=project / "id_list_removals.csv",
    )


def run_snapshot(source_name):
    project = Path.cwd()
    notebook = nbformat.read(project / NOTEBOOK_PATH, as_version=4)
    shell = InteractiveShell.instance()
    with patch.object(config, "CONFIG", snapshot_config(project, source_name)):
        for cell in notebook.cells:
            if cell.cell_type == "code" and cell.source.strip():
                with capture_output():
                    result = shell.run_cell(cell.source, store_history=False)
                result.raise_error()


def time_snapshot(settings):
    # Start a fresh Python process for each size so imports are timed the same way.
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-snapshot", settings.source_file.name],
        cwd=settings.project_root, check=True,
    )
    return read_record(settings.cache_file.with_suffix(".recommendation") / "run.json")


def read_templates(source_config):
    cache = match_cached_candidates(
        iter_cached_records(source_config.cache_file),
        iter_movie_id_rows(source_config.source_file),
    )
    passed, details = cache.uniqueness_check()
    if not passed:
        raise ValueError(details)
    templates = [cache.records[key] for key in sorted(cache.records, key=int)]
    if not templates:
        raise ValueError("Fetch the candidate cache before running the local timing check.")
    return templates


def main():
    source_config = config.CONFIG
    root = source_config.project_root

    with TemporaryDirectory(prefix="streamvault-benchmark-") as directory:
        # Prepare both copies before the timers start and keep their reports away from the live snapshot.
        # The removal log matches the source by filename, so preserve the name in the baseline copy.
        baseline_config = prepare_snapshot(root, Path(directory) / "baseline", source_config.source_file.name)
        test_config = prepare_snapshot(root, Path(directory) / "test", "id_list.csv")
        shutil.copyfile(source_config.source_file, baseline_config.source_file)
        shutil.copyfile(source_config.cache_file, baseline_config.cache_file)
        for original, copied in (
            (source_config.removals_file, baseline_config.removals_file),
            (source_config.cache_file.with_suffix(".acquisition.json"), baseline_config.cache_file.with_suffix(".acquisition.json")),
        ):
            if original.is_file():
                shutil.copyfile(original, copied)

        # Build the test titles from the exact copy used by the baseline run.
        templates = read_templates(baseline_config)
        records = list(make_test_records(templates, TEST_TITLES))
        test_config.source_file.write_text("tmdb_id\n" + "".join(f"{row['id']}\n" for row in records), encoding="utf-8")
        write_cached_records(test_config.cache_file, records)
        baseline = time_snapshot(baseline_config)
        timed = time_snapshot(test_config)

    baseline_titles = baseline["source_outcomes"].get("Cached", 0)
    if baseline_titles != len(templates) or timed["source_outcomes"].get("Cached") != TEST_TITLES:
        raise ValueError("The notebook did not account for all timing records.")
    if (
        baseline["cached_timing_boundary"] != timed["cached_timing_boundary"]
        or list(baseline["cached_stage_seconds"]) != list(timed["cached_stage_seconds"])
    ):
        raise ValueError("Both runs must time the same stages within the same boundary.")

    # Estimate the larger run by using the same time per resolved film for each stage.
    scale = TEST_TITLES / baseline_titles
    stages = [
        {
            "stage": stage,
            "baseline_seconds": elapsed,
            "projected_seconds": elapsed * scale,
            "measured_seconds": timed["cached_stage_seconds"][stage],
        }
        for stage, elapsed in baseline["cached_stage_seconds"].items()
    ]
    benchmark = {
        "test_titles": TEST_TITLES,
        "baseline_titles": baseline_titles,
        "original_templates": len(templates),
        "original_input_sha256": baseline["input_sha256"],
        "test_input_sha256": timed["input_sha256"],
        "code": timed["code"],
        "versions": timed["versions"],
        "platform": platform.platform(),
        "counts": timed["windows"],
        "timing_boundary": timed["cached_timing_boundary"],
        "baseline_seconds": baseline["cached_analysis_seconds"],
        "projected_seconds": baseline["cached_analysis_seconds"] * scale,
        "seconds": timed["cached_analysis_seconds"],
        "stages": stages,
        "recorded_at_utc": timed["recorded_at_utc"],
    }
    report = source_config.cache_file.with_suffix(".recommendation") / "benchmark.json"
    write_record(report, benchmark)
    print(f"Cached analysis for {baseline_titles} titles took {benchmark['baseline_seconds']:.2f} seconds.")
    print(f"Estimated time for {TEST_TITLES} titles: {benchmark['projected_seconds']:.2f} seconds.")
    print(f"Measured time for {TEST_TITLES} test titles: {benchmark['seconds']:.2f} seconds.")
    print(f"Saved {report}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--run-snapshot":
        run_snapshot(sys.argv[2])
    else:
        main()
