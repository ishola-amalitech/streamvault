import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from streamvault.cache import (
    iter_cached_records, load_cached_records, match_cached_candidates, write_cached_records,
)
from streamvault.load import iter_movie_id_rows


class CachedRecordsTests(unittest.TestCase):
    def test_missing_cache_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_cached_records(Path(directory) / "movies.jsonl"), {})

    def test_reader_exposes_repeated_ids_before_loading_into_a_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movies.jsonl"
            path.write_text('{"id": 155, "title": "Older"}\n{"id": "00155", "title": "Newer"}\n')

            entries = list(iter_cached_records(path))
            self.assertEqual([key for key, _ in entries], ["155", "155"])
            with self.assertRaisesRegex(ValueError, "Repeated movie ID 155"):
                load_cached_records(path)

    def test_write_and_load_cache_deduplicates_by_movie_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw" / "movies.jsonl"
            write_cached_records(
                path,
                [
                    {"id": 155, "title": "Original"},
                    {
                        "id": 155,
                        "title": "Updated",
                        "credits": {"cast": []},
                        "cached_at_utc": "2020-01-02T03:04:05+00:00",
                    },
                    {"id": 165, "title": "Second"},
                ],
            )

            cached = load_cached_records(path)
            self.assertEqual(
                cached["155"],
                {
                    "id": 155,
                    "title": "Updated",
                    "credits": {"cast": []},
                    "cached_at_utc": "2020-01-02T03:04:05+00:00",
                },
            )
            self.assertEqual(cached["165"]["id"], 165)
            self.assertEqual(cached["165"]["title"], "Second")
            timestamp_value = cached["165"].get("cached_at_utc")
            if not isinstance(timestamp_value, str):
                self.fail("New cache records need a UTC timestamp.")
            timestamp = datetime.fromisoformat(timestamp_value)
            self.assertEqual(timestamp.utcoffset(), timedelta(0))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

    def test_candidate_matching_reports_repeated_ids_and_keeps_older_films_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "titles.csv"
            cache_path = Path(directory) / "movies.jsonl"
            source.write_text("tmdb_id\n00155\n155\n170\n", encoding="utf-8")
            cache_path.write_text(
                '{"id":"00155","title":"Older"}\n'
                '{"id":155,"title":"Newer"}\n'
                '{"id":165}\n',
                encoding="utf-8",
            )
            cache = match_cached_candidates(iter_cached_records(cache_path), iter_movie_id_rows(source))

            self.assertEqual(list(cache.records), ["155"])
            self.assertEqual(list(cache.other_records), ["165"])
            self.assertEqual(cache.repeated_ids, ["155"])
            self.assertFalse(cache.uniqueness_check()[0])

    def test_invalid_cached_json_reports_its_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movies.jsonl"
            path.write_text('{"id": 155}\nnot-json\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "line 2"):
                load_cached_records(path)

    def test_cache_record_requires_positive_numeric_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movies.jsonl"

            with self.assertRaisesRegex(ValueError, "positive numeric"):
                write_cached_records(path, [{"id": 0}])

            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
