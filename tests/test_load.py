import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from streamvault.load import MovieId, iter_movie_id_rows, iter_movie_ids
from streamvault.removals import Removal


class LoadTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(self.enterContext(TemporaryDirectory()))
        self.source = root / "titles.csv"
        self.log = root / "removals.csv"

    def test_parser_keeps_line_numbers_and_only_the_first_numeric_id(self) -> None:
        self.source.write_text(
            " tmdb_id \r\n 00123 \r\n123\r\n\r\n000\r\n-1\r\n１２\r\n42\r\n",
            encoding="utf-8-sig",
        )

        self.assertEqual(
            list(iter_movie_id_rows(self.source)),
            [
                MovieId("123", 2, "00123"),
                Removal("titles.csv", 3, "123", "Duplicate TMDB movie ID; skipped."),
                Removal("titles.csv", 4, "", "Blank row; no TMDB movie ID."),
                Removal("titles.csv", 5, "000", "Not a positive numeric TMDB movie ID."),
                Removal("titles.csv", 6, "-1", "Not a positive numeric TMDB movie ID."),
                Removal("titles.csv", 7, "１２", "Not a positive numeric TMDB movie ID."),
                MovieId("42", 8),
            ],
        )
        self.assertEqual(list(self.source.parent.iterdir()), [self.source])

    def test_empty_input_has_no_rows(self) -> None:
        for contents in ("", "tmdb_id\n"):
            with self.subTest(contents=contents):
                self.source.write_text(contents, encoding="utf-8")
                self.assertEqual(list(iter_movie_id_rows(self.source)), [])

    def test_wrong_header_fails_with_the_file_name(self) -> None:
        self.source.write_text("movie_id\n42\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "single 'tmdb_id' column.*titles.csv"):
            list(iter_movie_id_rows(self.source))

    def test_fetch_reader_yields_clean_ids_and_logs_skipped_rows_once(self) -> None:
        self.source.write_text("tmdb_id\n00042\n42\n", encoding="utf-8")

        for _ in range(2):
            self.assertEqual(
                list(iter_movie_ids(self.source, self.log)),
                [MovieId("42", 2, "00042")],
            )

        with self.log.open(newline="", encoding="utf-8") as file:
            self.assertEqual(
                list(csv.DictReader(file)),
                [
                    {
                        "source_file": "titles.csv",
                        "original_source_line": "3",
                        "removed_value": "42",
                        "reason": "Duplicate TMDB movie ID; skipped.",
                    }
                ],
            )

    def test_extra_column_fails_and_keeps_an_earlier_removal(self) -> None:
        self.source.write_text("tmdb_id\nbad\n42,43\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "line 3.*titles.csv"):
            list(iter_movie_ids(self.source, self.log))

        with self.log.open(newline="", encoding="utf-8") as file:
            logged_values = [row["removed_value"] for row in csv.DictReader(file)]
            self.assertEqual(logged_values, ["bad"])

    def test_missing_file_fails_and_leaves_no_log(self) -> None:
        with self.assertRaises(FileNotFoundError) as error:
            list(iter_movie_ids(self.source, self.log))

        self.assertEqual(error.exception.filename, str(self.source))
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
