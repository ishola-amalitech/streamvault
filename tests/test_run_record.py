import hashlib
import unittest
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from streamvault.config import CONFIG
from streamvault.run_record import (
    read_record,
    snapshot_inputs,
    write_record,
    write_text_atomic,
)


class RunRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory()))

    def test_snapshot_tracks_file_contents_and_missing_inputs(self) -> None:
        config = replace(
            CONFIG,
            source_file=self.root / "titles.csv",
            cache_file=self.root / "movies.jsonl",
            removals_file=self.root / "removals.csv",
        )
        source = b"tmdb_id\n42\n"
        cache = b'{"id": 42}\n'
        config.source_file.write_bytes(source)
        config.cache_file.write_bytes(cache)

        before = snapshot_inputs(config)
        self.assertEqual(
            before,
            {
                "source": hashlib.sha256(source).hexdigest(),
                "cache": hashlib.sha256(cache).hexdigest(),
                "removals": None,
            },
        )

        config.cache_file.write_bytes(b'{"id": 43}\n')
        after = snapshot_inputs(config)
        self.assertNotEqual(before["cache"], after["cache"])
        self.assertEqual(before["source"], after["source"])

    def test_missing_report_reads_as_empty(self) -> None:
        self.assertEqual(read_record(self.root / "run.json"), {})

    def test_report_round_trip_preserves_nested_data(self) -> None:
        path = self.root / "reports" / "run.json"
        record = {"title": "Amélie", "inputs": {"cache": None}, "requested": 1}

        write_record(path, record)

        self.assertEqual(read_record(path), record)
        self.assertIn("Amélie", path.read_text(encoding="utf-8"))

    def test_non_object_report_is_rejected(self) -> None:
        path = self.root / "run.json"
        path.write_text("[]", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Expected a JSON object"):
            read_record(path)

    def test_line_writer_keeps_old_file_if_writing_stops(self) -> None:
        path = self.root / "report.txt"
        write_text_atomic(path, "previous report\n")

        def broken_lines() -> Iterator[str]:
            # Fail after the first line has reached the temporary file.
            yield "first line\n"
            raise ValueError("Could not write the next line")

        with self.assertRaisesRegex(ValueError, "Could not write"):
            write_text_atomic(path, broken_lines())

        self.assertEqual(path.read_text(encoding="utf-8"), "previous report\n")
        self.assertEqual(list(self.root.iterdir()), [path])
