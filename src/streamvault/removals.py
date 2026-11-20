import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from streamvault.run_record import atomic_output_path


FIELDS = ("source_file", "original_source_line", "removed_value", "reason")


@dataclass(frozen=True)
class Removal:
    """A skipped entry and enough detail to find it in the source list."""
    source_file: str
    source_line: int | None
    removed_value: str
    reason: str


def append_removals(path: Path, removals: Iterable[Removal]) -> None:
    """Add new issues to the removal CSV, keeping the earlier entries."""
    pending = list(removals)
    if not pending:
        return

    # Check the old file before adding anything so a bad log stays available for repair.
    existing_rows: list[tuple[str, ...]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as file:
            reader = csv.reader(file, strict=True)
            try:
                header = next(reader, None)
                if header is not None and tuple(header) != FIELDS:
                    raise ValueError(
                        f"Invalid header in removal log {path}. Expected {', '.join(FIELDS)}."
                    )
                for row in reader:
                    if len(row) != len(FIELDS):
                        raise ValueError(
                            f"Invalid row in removal log {path} at line {reader.line_num}."
                        )
                    existing_rows.append(tuple(row))
            except csv.Error as error:
                raise ValueError(
                    f"Malformed CSV in removal log {path} at line {reader.line_num}."
                ) from error
    existing = set(existing_rows)

    new_rows: list[tuple[str, str, str, str]] = []
    for removal in pending:
        # Use a blank CSV cell when the source line is unknown.
        source_line = (
            "" if removal.source_line is None else str(removal.source_line)
        )
        key = (
            removal.source_file,
            source_line,
            removal.removed_value,
            removal.reason,
        )
        if key not in existing:
            existing.add(key)
            new_rows.append(key)

    if not new_rows:
        return

    # Replace the full log in one step so an interrupted write leaves the old log intact.
    with atomic_output_path(path) as temporary_path:
        with temporary_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(FIELDS)
            writer.writerows(existing_rows)
            writer.writerows(new_rows)
