import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


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

    # Read earlier entries so rerunning the same list adds each issue only once.
    existing: set[tuple[str, ...]] = set()
    if path.exists():
        with path.open(newline="", encoding="utf-8") as file:
            existing = {
                tuple(row.get(field) or "" for field in FIELDS)
                for row in csv.DictReader(file)
            }

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

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        # Append mode starts at the end. An empty file still needs its header.
        if file.tell() == 0:
            writer.writerow(FIELDS)
        writer.writerows(new_rows)
