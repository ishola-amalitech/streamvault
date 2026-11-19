import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from streamvault.removals import Removal, append_removals


class RemovalLogTests(unittest.TestCase):
    def test_append_adds_one_header_to_an_empty_file(self) -> None:
        log = Path(self.enterContext(TemporaryDirectory())) / "removals.csv"
        log.touch()
        missing = Removal("titles.csv", None, "123", "Missing title")
        invalid = Removal("titles.csv", 4, "bad", "Invalid ID")

        # Exercise both duplicate entries in one batch and repeats across runs.
        append_removals(log, [missing, missing])
        append_removals(log, [missing, invalid])

        with log.open(newline="", encoding="utf-8") as file:
            self.assertEqual(
                list(csv.reader(file)),
                [
                    ["source_file", "original_source_line", "removed_value", "reason"],
                    ["titles.csv", "", "123", "Missing title"],
                    ["titles.csv", "4", "bad", "Invalid ID"],
                ],
            )
