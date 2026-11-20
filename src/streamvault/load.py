import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from streamvault.removals import Removal, append_removals


MAX_TMDB_MOVIE_ID = 2_147_483_647
DUPLICATE_ID_REASON = "Duplicate TMDB movie ID; skipped."


@dataclass(frozen=True)
class MovieId:
    value: str
    source_line: int
    # Keep the original text for the audit when it differs from the ID we fetch.
    source_value: str | None = None


def is_tmdb_movie_id(movie_id: str) -> bool:
    """Check a movie ID after removing leading zeros."""
    # TMDB expects a positive, signed 32-bit integer.
    return (
        movie_id.isascii()
        and movie_id.isdecimal()
        and len(movie_id) <= 10
        and 0 < int(movie_id) <= MAX_TMDB_MOVIE_ID
    )


def iter_movie_id_rows(file_path: str | Path) -> Iterator[MovieId | Removal]:
    """Read source rows and their parsing outcomes without writing a log."""
    source_path = Path(file_path)
    seen_ids: set[str] = set()

    with source_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        header = next(reader, None)
        if header is None:
            return
        if [value.strip() for value in header] != ["tmdb_id"]:
            raise ValueError(f"Expected a single 'tmdb_id' column in {source_path}.")

        for row in reader:
            # Keep the CSV line number so someone can find the original entry.
            source_line = reader.line_num
            if len(row) > 1:
                raise ValueError(
                    f"Expected one TMDB ID at line {source_line} in {source_path}."
                )
            source_value = row[0].strip() if row else ""
            # ID 00123 refers to the same film as 123. All-zero IDs are invalid.
            movie_id = source_value.lstrip("0")
            if not source_value:
                reason = "Blank row; no TMDB movie ID."
            elif not is_tmdb_movie_id(movie_id):
                reason = "Not a positive numeric TMDB movie ID."
                if movie_id.isascii() and movie_id.isdecimal():
                    reason = "TMDB movie ID exceeds the maximum of 2,147,483,647."
            elif movie_id in seen_ids:
                reason = DUPLICATE_ID_REASON
            else:
                seen_ids.add(movie_id)
                original = source_value if source_value != movie_id else None
                yield MovieId(movie_id, source_line, original)
                continue

            yield Removal(source_path.name, source_line, source_value, reason)


def iter_movie_ids(
    file_path: str | Path, removals_path: str | Path,
) -> Iterator[MovieId]:
    """Read the complete list before logging skipped rows and yielding IDs."""
    rows = list(iter_movie_id_rows(file_path))
    append_removals(Path(removals_path), (row for row in rows if isinstance(row, Removal)))
    yield from (row for row in rows if isinstance(row, MovieId))
