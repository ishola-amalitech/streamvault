import tempfile
import unittest
from pathlib import Path

from streamvault.config import CONFIG, load_config


class AppConfigTests(unittest.TestCase):
    def test_paths_resolve_relative_to_config_file(self) -> None:
        project_root = Path(__file__).resolve().parents[1]

        self.assertEqual(CONFIG.project_root, project_root)
        self.assertEqual(CONFIG.source_file, project_root / "id_list.csv")
        self.assertEqual(
            CONFIG.cache_file, project_root / "data" / "raw" / "movies.jsonl"
        )
        self.assertEqual(
            CONFIG.removals_file, project_root / "id_list_removals.csv"
        )

    def test_missing_config_section_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.toml"
            config_path.write_text(
                "[paths]\nsource_file = 'ids.csv'\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "Config section 'api'"):
                load_config(config_path)

    def test_nonpositive_request_rate_fails_explicitly(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config_contents = (project_root / "config.toml").read_text(
            encoding="utf-8"
        )
        invalid_config = config_contents.replace(
            "requests_per_second = 4.0", "requests_per_second = 0.0"
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.toml"
            config_path.write_text(invalid_config, encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError, "requests_per_second.*greater than 0.0"
            ):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
