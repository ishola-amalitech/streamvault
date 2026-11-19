from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from streamvault.config import CONFIG
from streamvault.fetch_movies import FetchFailure, FetchMissing
from streamvault.load import MovieId
from streamvault.main import run
from streamvault.normalize import normalize_movie_records
from streamvault.run_record import read_record, snapshot_inputs


class MainTests(unittest.IsolatedAsyncioTestCase):
    async def test_loading_stops_on_duplicate_cached_candidates(self) -> None:
        with (
            patch("streamvault.main.iter_movie_ids", return_value=[MovieId("155", 2)]),
            patch(
                "streamvault.main.iter_cached_records",
                return_value=[("155", {"id": 155}), ("155", {"id": "00155"})],
            ),
            patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
            self.assertRaisesRegex(ValueError, "After loading.*repeated IDs"),
        ):
            await run()
        fetch.assert_not_awaited()

    async def test_fetching_stops_before_caching_an_unexpected_movie(self) -> None:
        with (
            patch("streamvault.main.iter_movie_ids", return_value=[MovieId("155", 2)]),
            patch("streamvault.main.iter_cached_records", return_value=[]),
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
                CONFIG, source_file=root / "titles.csv", cache_file=root / "movies.jsonl",
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
                patch("streamvault.main.normalize_movie_records", return_value=wrong_tables) as normalize,
                self.assertRaisesRegex(ValueError, r"Missing examples: \['155'\]"),
            ):
                await run()
            inputs = list(normalize.call_args.args[0])
            self.assertEqual([record["id"] for record in inputs], [155])

    async def test_cached_movie_ids_do_not_trigger_a_fetch(self) -> None:
        with (
            patch(
                "streamvault.main.iter_movie_ids",
                return_value=[MovieId("155", 1)],
            ),
            patch(
                "streamvault.main.iter_cached_records",
                return_value=[("155", {"id": 155})],
            ),
            patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
            patch("streamvault.main.write_cached_records") as write_cache,
        ):
            await run()

        fetch.assert_not_awaited()
        write_cache.assert_called_once()

    async def test_acquisition_record_follows_the_latest_outcome(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                CONFIG, source_file=root / "titles.csv", cache_file=root / "movies.jsonl",
                removals_file=root / "removals.csv",
            )
            config.source_file.write_text("tmdb_id\n10\n20\n", encoding="utf-8")
            record_path = config.cache_file.with_suffix(".acquisition.json")
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


if __name__ == "__main__":
    unittest.main()
