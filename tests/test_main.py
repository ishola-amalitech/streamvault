from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from streamvault.config import CONFIG
from streamvault.fetch_movies import FetchFailure, FetchMissing
from streamvault.load import MovieId
from streamvault.main import run
from streamvault.run_record import read_record, snapshot_inputs


class MainTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_movie_ids_do_not_trigger_a_fetch(self) -> None:
        with (
            patch(
                "streamvault.main.iter_movie_ids",
                return_value=[MovieId("155", 1)],
            ),
            patch(
                "streamvault.main.load_cached_records",
                return_value={"155": {"id": 155}},
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
