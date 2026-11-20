import csv
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from streamvault.cache import iter_cached_records
from streamvault.config import CONFIG
from streamvault.fetch_movies import FetchFailure, FetchMissing, MissingTokenError
from streamvault.load import MovieId, iter_movie_id_rows
from streamvault.main import run
from streamvault.normalize import normalize_movie_records
from streamvault.recommendation_run import run_recommendation
from streamvault.run_record import read_record, snapshot_inputs, write_record


class MainTests(unittest.IsolatedAsyncioTestCase):
    async def test_loading_stops_on_duplicate_cached_candidates(self) -> None:
        with (
            patch("streamvault.recommendation_inputs.iter_movie_id_rows", return_value=[MovieId("155", 2)]),
            patch(
                "streamvault.recommendation_inputs.iter_cached_records",
                return_value=[("155", {"id": 155}), ("155", {"id": "00155"})],
            ),
            patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
            self.assertRaisesRegex(ValueError, "After loading.*repeated IDs"),
        ):
            await run()
        fetch.assert_not_awaited()

    async def test_fetching_stops_before_caching_an_unexpected_movie(self) -> None:
        with (
            patch("streamvault.recommendation_inputs.iter_movie_id_rows", return_value=[MovieId("155", 2)]),
            patch("streamvault.recommendation_inputs.iter_cached_records", return_value=[]),
            patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
            patch("streamvault.main.write_cached_records") as write_cache,
            self.assertRaisesRegex(ValueError, r"After fetching.*Unexpected: \['999'\]"),
        ):
            fetch.return_value = ([{"id": 999}], [], [])
            await run()
        write_cache.assert_not_called()

    async def test_pipeline_stops_when_normalization_returns_the_wrong_film(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                CONFIG, project_root=root, output_dir=root / "out", source_file=root / "titles.csv", cache_file=root / "movies.jsonl",
                removals_file=root / "removals.csv",
            )
            config.source_file.write_text("tmdb_id\n155\n", encoding="utf-8")
            # Another title in the shared cache must stay outside this run.
            config.cache_file.write_text(
                '{"id":155,"cached_at_utc":"2026-01-01T00:00:00Z"}\n'
                '{"id":165,"cached_at_utc":"2026-01-01T00:00:00Z"}\n',
                encoding="utf-8",
            )
            wrong_tables = normalize_movie_records([{"id": 999}])
            with (
                patch("streamvault.main.CONFIG", config),
                patch("streamvault.recommendation_inputs.normalize_movie_records", return_value=wrong_tables) as normalize,
                self.assertRaisesRegex(ValueError, r"Missing examples: \['155'\]"),
            ):
                await run()
            inputs = list(normalize.call_args.args[0])
            self.assertEqual([record["id"] for record in inputs], [155])

    async def test_cached_movie_ids_do_not_trigger_a_fetch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                CONFIG, project_root=root, output_dir=root / "out", source_file=root / "titles.csv",
                cache_file=root / "movies.jsonl", removals_file=root / "removals.csv",
            )
            config.source_file.write_text("tmdb_id\n155\n", encoding="utf-8")
            config.cache_file.write_text('{"id":155}\n', encoding="utf-8")
            with (
                patch("streamvault.main.CONFIG", config),
                patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
                patch("streamvault.recommendation_inputs.iter_cached_records", wraps=iter_cached_records) as read_cache,
                patch("streamvault.recommendation_inputs.iter_movie_id_rows", wraps=iter_movie_id_rows) as read_rows,
            ):
                await run()
            fetch.assert_not_awaited()
            read_cache.assert_called_once_with(config.cache_file)
            read_rows.assert_called_once_with(config.source_file)
            self.assertIn("cached_at_utc", json.loads(config.cache_file.read_text()))
            report = read_record(config.output_dir / "run.json")
            self.assertEqual(report["source_outcomes"], {"Cached": 1})

    async def test_pipeline_reports_film_issues_and_continues(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                CONFIG, project_root=root, output_dir=root / "out", source_file=root / "titles.csv", cache_file=root / "movies.jsonl",
                removals_file=root / "removals.csv",
            )
            config.source_file.write_text("tmdb_id\n1\n2\n3\n4\n5\n", encoding="utf-8")
            released = {"status": "Released", "release_date": "2000-01-01"}
            records = [
                {"id": 1, **released, "title": "Same Film", "vote_count": 800, "budget": 1, "revenue": 1},
                {"id": 2, **released, "title": "same  film", "vote_average": 7.5, "vote_count": 1.5, "revenue": 1},
                {"id": 3, **released, "vote_average": 7.5, "vote_count": 800, "budget": 1, "revenue": 1},
                {"id": 4, "status": "In Production", "release_date": "2030-01-01"},
                {"id": 5, "status": "Released"},
            ]
            config.cache_file.write_text(
                "".join(
                    json.dumps(record | {"cached_at_utc": "2026-01-01T00:00:00Z"}) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            with patch("streamvault.main.CONFIG", config):
                await run()

            with (config.output_dir / "movies.quality.csv").open(newline="", encoding="utf-8") as report:
                issues = {(row["movie_id"], row["issue"]) for row in csv.DictReader(report)}
            self.assertEqual(issues, {
                ("1", "Missing rating"),
                ("1", "Possible duplicate film"),
                ("2", "Invalid vote count"),
                ("2", "Missing production budget"),
                ("2", "Possible duplicate film"),
                ("4", "Missing production budget"),
                ("4", "Missing box office gross"),
                ("5", "Missing release date"),
                ("5", "Missing production budget"),
                ("5", "Missing box office gross"),
            })
            report = read_record(config.output_dir / "run.json")
            self.assertEqual(report["window_evidence"]["2000 onward"]["Films flagged for duplicate review"], 2)
            self.assertIn("Missing release date", (config.output_dir / "recommendation_exclusions.md").read_text())

    async def test_acquisition_record_follows_the_latest_outcome(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                CONFIG, project_root=root, output_dir=root / "out", source_file=root / "titles.csv", cache_file=root / "movies.jsonl",
                removals_file=root / "removals.csv",
            )
            config.source_file.write_text("tmdb_id\n10\n20\n", encoding="utf-8")
            record_path = config.acquisition_file
            with (
                patch("streamvault.main.CONFIG", config),
                patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
            ):
                fetch.return_value = (
                    [], [FetchMissing("20", 3, "TMDB returned HTTP 404.")],
                    [FetchFailure("10", "HTTP 503")],
                )
                await run()
                first = read_record(record_path)
                self.assertEqual(first["unresolved_by_id"]["10"]["status"], "request_failed")
                self.assertEqual(first["unresolved_by_id"]["10"]["reason"], "HTTP 503")
                self.assertEqual(first["unresolved_by_id"]["20"]["status"], "lookup_miss")
                self.assertGreaterEqual(first["fetch_seconds"], 0)

                # A success clears an old result. A retry can change a lookup miss to a failure.
                fetch.return_value = ([{"id": 10}], [], [FetchFailure("20", "HTTP 429")])
                await run()
                second = read_record(record_path)
                self.assertNotIn("10", second["unresolved_by_id"])
                self.assertEqual(second["unresolved_by_id"]["20"]["status"], "request_failed")
                self.assertEqual(second["input_sha256"], snapshot_inputs(config))

                config.source_file.write_text("tmdb_id\n10\n", encoding="utf-8")
                await run()
                self.assertEqual(fetch.await_count, 2)
                self.assertEqual(read_record(record_path), second)

    async def test_pipeline_fetches_and_writes_the_complete_two_window_recommendation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                CONFIG, project_root=root, output_dir=root / "out", source_file=root / "titles.csv",
                cache_file=root / "movies.jsonl", removals_file=root / "removals.csv",
            )
            ids = [*range(1, 12), 900, 901, 1]
            config.source_file.write_text("tmdb_id\n" + "".join(f"{key}\n" for key in ids), encoding="utf-8")
            movies = [
                {
                    "id": key, "title": f"Film {key}", "status": "Released",
                    "release_date": "1999-12-31" if key in (6, 11) else "2000-01-01",
                    "vote_average": 7.0 if key <= 5 or key == 11 else 9.0,
                    "vote_count": 5000, "budget": 10, "revenue": 100,
                }
                for key in range(1, 12)
            ]
            for key in range(1, 6):
                movies[key - 1]["belongs_to_collection"] = {"id": key, "name": f"Bundle {key}"}
            movies[-1]["belongs_to_collection"] = movies[0]["belongs_to_collection"]

            with (
                patch("streamvault.main.CONFIG", config),
                patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
            ):
                fetch.return_value = (
                    movies, [FetchMissing("900", 13, "TMDB returned HTTP 404.")],
                    [FetchFailure("901", "HTTP 503")],
                )
                await run()

            folder = config.output_dir
            record = read_record(folder / "run.json")
            self.assertEqual(record["source_rows"], len(ids))
            self.assertEqual(record["source_outcomes"]["Cached"], 11)
            self.assertEqual(record["windows"]["All years"]["shortlisted_bundles"], 3)
            self.assertEqual(record["windows"]["All years"]["shortlisted_standalones"], 5)
            self.assertEqual(record["windows"]["2000 onward"]["shortlisted_standalones"], 4)
            baseline = {(row["window"], row["conclusion"]) for row in record["comparison_results"] if row["scenario"] == "Baseline"}
            self.assertIn(("All years", "Favors standalones"), baseline)
            self.assertIn(("2000 onward", "Insufficient evidence to favor either group"), baseline)
            analysis_csvs = record["candidate_csv_sha256"] | record["detail_csv_sha256"]
            self.assertEqual(len(analysis_csvs), 12)
            self.assertEqual({path.name for path in folder.glob("*.csv")}, set(analysis_csvs) | {"movies.quality.csv"})
            self.assertIn("The ratings conclusion changes", (folder / "recommendation.md").read_text())
            exclusions = (config.output_dir / "recommendation_exclusions.md").read_text()
            self.assertIn("TMDB request failed: HTTP 503", exclusions)
            self.assertIn("Duplicate TMDB movie ID", exclusions)
            self.assertIn("Before 1 January 2000", exclusions)

            # The notebook uses the same calculation on the saved snapshot but writes separate files.
            notebook_dir = config.cache_file.with_suffix(".recommendation")
            self.assertFalse(notebook_dir.exists())
            self.assertFalse(config.cache_file.with_suffix(".quality.csv").exists())
            self.assertFalse((root / "docs/recommendation_exclusions.md").exists())
            notebook_run = run_recommendation(config)
            self.assertEqual(notebook_run.directory, notebook_dir)
            self.assertEqual(notebook_run.record["comparison_results"], record["comparison_results"])
            for field in ("candidate_csv_sha256", "detail_csv_sha256", "exclusions_report_sha256"):
                self.assertEqual(notebook_run.record[field], record[field])

    async def test_without_token_replay_requires_an_outcome_for_each_uncached_id(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                CONFIG, project_root=root, output_dir=root / "out", source_file=root / "titles.csv",
                cache_file=root / "movies.jsonl", removals_file=root / "removals.csv",
            )
            config.source_file.write_text("tmdb_id\n10\n11\n", encoding="utf-8")
            config.removals_file.write_text(
                "source_file,original_source_line,removed_value,reason\n"
                "titles.csv,2,10,TMDB lookup: TMDB returned HTTP 404.\n", encoding="utf-8",
            )
            write_record(config.cache_file.with_suffix(".acquisition.json"), {
                "unresolved_by_id": {"11": {"status": "request_failed", "reason": "HTTP 503"}},
            })
            run_path = config.output_dir / "run.json"
            with (
                patch("streamvault.main.CONFIG", config),
                patch("streamvault.main.fetch_movies", side_effect=MissingTokenError("A token is required")),
            ):
                await run()
                self.assertIn("TMDB request failed: HTTP 503", read_record(run_path)["source_outcomes"])
                saved_run = run_path.read_bytes()
                config.source_file.write_text("tmdb_id\n10\n11\n20\n", encoding="utf-8")
                with self.assertRaisesRegex(MissingTokenError, "token is required"):
                    await run()
                self.assertEqual(run_path.read_bytes(), saved_run)


if __name__ == "__main__":
    unittest.main()
