import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from streamvault.config import CONFIG
from streamvault.removals import Removal, append_removals


@dataclass(frozen=True)
class MovieId:
    value: str
    source_line: int


def iter_movie_ids(
    file_path: str | Path, removals_path: str | Path | None = None
) -> Iterator[MovieId]:
    source_path = Path(file_path)
    removal_log_path = (
        Path(removals_path)
        if removals_path is not None
        else CONFIG.removals_file
    )
    seen_ids: set[str] = set()
    removals: list[Removal] = []

    try:
        with source_path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            header = next(reader, None)
            if header is None:
                return
            if [value.strip() for value in header] != ["tmdb_id"]:
                raise ValueError(
                    f"Expected a single 'tmdb_id' column in {source_path}."
                )

            for row in reader:
                source_line = reader.line_num
                # Handle blank rows and rows with unexpected number of columns
                if not row:
                    removals.append(
                        Removal(
                            source_path.name,
                            source_line,
                            "",
                            "Blank row; no TMDB movie ID.",
                        )
                    )
                    continue
                if len(row) != 1:
                    raise ValueError(
                        f"Expected one TMDB ID at line {source_line} in {source_path}."
                    )
                # Validate the TMDB movie ID
                movie_id = row[0].strip()
                if not movie_id:
                    removals.append(
                        Removal(
                            source_path.name,
                            source_line,
                            "",
                            "Blank row; no TMDB movie ID.",
                        )
                    )
                    continue
                # Validate that the TMDB movie ID is a positive numeric string
                if (
                    not movie_id.isascii()
                    or not movie_id.isdecimal()
                    or int(movie_id) <= 0
                ):
                    removals.append(
                        Removal(
                            source_path.name,
                            source_line,
                            movie_id,
                            "Not a positive numeric TMDB movie ID.",
                        )
                    )
                    continue
                # Check for duplicate TMDB movie IDs
                if movie_id in seen_ids:
                    removals.append(
                        Removal(
                            source_path.name,
                            source_line,
                            movie_id,
                            "Duplicate TMDB movie ID; skipped.",
                        )
                    )
                    continue

                seen_ids.add(movie_id)
                yield MovieId(movie_id, source_line)
    except FileNotFoundError:
        print(f"Error: The file at {source_path} was not found.")
    finally:
        append_removals(removal_log_path, removals)
