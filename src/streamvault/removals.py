import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


FIELDS = ("source_file", "original_source_line", "removed_value", "reason")


@dataclass(frozen=True)
class Removal:
    source_file: str
    source_line: int | None
    removed_value: str
    reason: str


def append_removals(path: Path, removals: Iterable[Removal]) -> None:
    pending = list(removals)
    if not pending:
        return

    # Read earlier entries so rerunning the same list adds each issue only once.
    existing: set[tuple[str, str, str, str]] = set()
    if path.exists():
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                existing.add(
                    (
                        row.get("source_file") or "",
                        row.get("original_source_line") or "",
                        row.get("removed_value") or "",
                        row.get("reason") or "",
                    )
                )

    new_rows: list[tuple[str, str, str, str]] = []
    for removal in pending:
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

    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if needs_header:
            writer.writerow(FIELDS)
        writer.writerows(new_rows)
