import tempfile
import unittest
from pathlib import Path

from streamvault.cache import load_cached_records, write_cached_records


class CachedRecordsTests(unittest.TestCase):
    def test_missing_cache_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_cached_records(Path(directory) / "movies.jsonl"), {})

    def test_write_and_load_cache_deduplicates_by_movie_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw" / "movies.jsonl"
            write_cached_records(
                path,
                [
                    {"id": 155, "title": "Original"},
                    {"id": 155, "title": "Updated", "credits": {"cast": []}},
                    {"id": 165, "title": "Second"},
                ],
            )

            self.assertEqual(
                load_cached_records(path),
                {
                    "155": {"id": 155, "title": "Updated", "credits": {"cast": []}},
                    "165": {"id": 165, "title": "Second"},
                },
            )
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

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
