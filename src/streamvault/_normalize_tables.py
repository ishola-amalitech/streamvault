"""Read nested TMDB values and build tables with consistent IDs."""

import math
from typing import cast

import pandas as pd


# Values from TMDB can be text, numbers, lists, or nested objects.
type Row = dict[str, object]
type ReferenceID = int | str


def positive_id(value: object, field: str) -> int:
    """Read a numeric TMDB key so a string like "0028" joins to the integer 28."""
    # Python counts True and False as integers, but neither is a TMDB ID.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field} must be a positive numeric ID.")

    text = str(value)
    if not text.isascii() or not text.isdecimal() or not text.lstrip("0"):
        raise ValueError(f"{field} must be a positive numeric ID.")
    return int(text)


def text_key(value: object, field: str) -> str:
    """Read a country code, language code, or credit ID and trim its outer spaces."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a non-empty string.")
    key = value.strip()
    if not key:
        raise ValueError(f"{field} must be a non-empty string.")
    return key


def clean_text(value: object) -> object:
    """Turn empty or whitespace-only text into a missing value."""
    if isinstance(value, str) and not value.strip():
        return pd.NA
    return value


def is_missing(value: object) -> bool:
    """Recognize the missing values we accept from JSON and pandas."""
    if value is None or value is pd.NA:
        return True
    return isinstance(value, float) and math.isnan(value)


def object_values(value: object, error_message: str) -> Row:
    """Check that a nested value is a dictionary with text keys."""
    if not isinstance(value, dict):
        raise ValueError(error_message)
    # JSON already has text keys. This check also covers records passed directly from Python.
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise ValueError(error_message)
    return cast(Row, mapping)


def _list_values(record: Row, field: str, movie_id: int) -> list[object]:
    value = record.get(field)
    # An optional list can be absent or null. A supplied value must be a list.
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Movie {movie_id}: expected '{field}' to be a list.")
    return cast(list[object], value)


def object_list(record: Row, field: str, movie_id: int) -> list[Row]:
    """Read a list of nested objects and name the exact item if one is invalid."""
    return [
        object_values(
            item, f"Movie {movie_id}: expected '{field}[{index}]' to be an object."
        )
        for index, item in enumerate(_list_values(record, field, movie_id))
    ]


def text_list(record: Row, field: str, movie_id: int) -> list[str]:
    """Read simple lists such as a film's country codes."""
    strings: list[str] = []
    for index, item in enumerate(_list_values(record, field, movie_id)):
        if not isinstance(item, str):
            raise ValueError(f"Movie {movie_id}: expected '{field}[{index}]' to be text.")
        strings.append(item)
    return strings


def clean_blank_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the same blank-text rule to each column of a finished table."""
    for column in frame.columns:
        frame[column] = frame[column].map(clean_text)
    return frame


class ReferenceRows:
    """Store shared details once per ID, such as a genre name or a person."""

    def __init__(self, name: str, key_column: str, *detail_columns: str) -> None:
        self._name = name
        self._key_column = key_column
        self._columns = (key_column, *detail_columns)
        self._rows: dict[ReferenceID, Row] = {}

    def add(self, key: ReferenceID, details: Row) -> None:
        # Create the row even if we only know the key, as with a country code.
        row = self._rows.setdefault(key, {self._key_column: key})
        for field, raw_value in details.items():
            value = clean_text(raw_value)
            if is_missing(value):
                continue

            # Later films can fill gaps. Two supplied values for the same fact should agree.
            existing = row.get(field, pd.NA)
            if is_missing(existing):
                row[field] = value
            elif existing != value:
                raise ValueError(
                    f"Conflicting {self._name} {self._key_column}={key!r} "
                    f"attribute '{field}': {existing!r} != {value!r}."
                )

    def to_frame(self) -> pd.DataFrame:
        # Explicit columns keep the same join keys available when there are no rows.
        frame = pd.DataFrame.from_records(list(self._rows.values()), columns=self._columns)
        return clean_blank_columns(frame)


class MovieLinks:
    """Store one row for each film's connection to another table."""

    def __init__(self, name: str, key_column: str) -> None:
        self._name = name
        self._key_column = key_column
        self._rows: dict[tuple[int, ReferenceID], Row] = {}

    def add(self, movie_id: int, reference_id: ReferenceID) -> None:
        # The pair identifies the row. A repeated pair would multiply rows after a join.
        key = (movie_id, reference_id)
        if key in self._rows:
            raise ValueError(f"Duplicate {self._name} relationship {key!r}.")
        self._rows[key] = {"movie_id": movie_id, self._key_column: reference_id}

    def to_frame(self) -> pd.DataFrame:
        # Dict order keeps the output in the same order as the source.
        frame = pd.DataFrame.from_records(
            list(self._rows.values()), columns=("movie_id", self._key_column)
        )
        return clean_blank_columns(frame)
