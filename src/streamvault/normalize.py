import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

import pandas as pd


@dataclass(frozen=True)
class MovieTables:
    # One row per film; stores film-level attributes.
    movies: pd.DataFrame
    # One row per genre; shared reference data for films.
    genres: pd.DataFrame
    # One row per film–genre relationship.
    movie_genres: pd.DataFrame
    # One row per production company; shared company details.
    companies: pd.DataFrame
    # One row per film–company relationship.
    movie_companies: pd.DataFrame
    # One row per country code; shared country details.
    countries: pd.DataFrame
    # One row per film–origin-country relationship.
    movie_origin_countries: pd.DataFrame
    # One row per film–production-country relationship.
    movie_production_countries: pd.DataFrame
    # One row per language code; shared language details.
    languages: pd.DataFrame
    # One row per film–spoken-language relationship.
    movie_spoken_languages: pd.DataFrame
    # One row per collection; shared collection details.
    collections: pd.DataFrame
    # One row per person; shared person details.
    people: pd.DataFrame
    # One row per cast member credit in one film.
    cast_credits: pd.DataFrame
    # One row per crew member credit in one film.
    crew_credits: pd.DataFrame


PERSON_ATTRIBUTES = (
    "adult",
    "gender",
    "known_for_department",
    "name",
    "original_name",
    "profile_path",
)

MOVIE_FIELDS = ("movie_id", "collection_id")
GENRE_FIELDS = ("genre_id", "genre_name")
MOVIE_GENRE_FIELDS = ("movie_id", "genre_id")
COMPANY_FIELDS = (
    "company_id",
    "company_name",
    "company_logo_path",
    "origin_country_code",
)
MOVIE_COMPANY_FIELDS = ("movie_id", "company_id")
COUNTRY_FIELDS = ("country_code", "country_name")
MOVIE_COUNTRY_FIELDS = ("movie_id", "country_code")
LANGUAGE_FIELDS = ("language_code", "language_name", "language_english_name")
MOVIE_LANGUAGE_FIELDS = ("movie_id", "language_code")
COLLECTION_FIELDS = (
    "collection_id",
    "collection_name",
    "collection_poster_path",
    "collection_backdrop_path",
)
PEOPLE_FIELDS = ("person_id", *PERSON_ATTRIBUTES)
CAST_CREDIT_FIELDS = (
    "movie_id",
    "credit_id",
    "person_id",
    "cast_id",
    "character",
    "order",
    "popularity",
)
CREW_CREDIT_FIELDS = (
    "movie_id",
    "credit_id",
    "person_id",
    "department",
    "job",
    "popularity",
)


def _positive_id(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field} must be a positive numeric ID.")

    text = str(value)
    if not text.isascii() or not text.isdecimal() or int(text) <= 0:
        raise ValueError(f"{field} must be a positive numeric ID.")
    return int(text)


def _text_key(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _clean_text(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return pd.NA
    return value


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    return isinstance(value, float) and math.isnan(value)


def _mapping_values(
    record: dict[str, object], field: str, movie_id: int
) -> list[dict[str, object]]:
    value = record.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Movie {movie_id}: expected '{field}' to be a list.")

    mappings: list[dict[str, object]] = []
    for index, item in enumerate(cast(list[object], value)):
        if not isinstance(item, dict):
            raise ValueError(
                f"Movie {movie_id}: expected '{field}[{index}]' to be an object."
            )
        mapping = cast(dict[object, object], item)
        if not all(isinstance(key, str) for key in mapping):
            raise ValueError(
                f"Movie {movie_id}: expected '{field}[{index}]' to be an object."
            )
        mappings.append(cast(dict[str, object], mapping))
    return mappings


def _string_values(
    record: dict[str, object], field: str, movie_id: int
) -> list[str]:
    value = record.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Movie {movie_id}: expected '{field}' to be a list.")

    strings: list[str] = []
    for index, item in enumerate(cast(list[object], value)):
        if not isinstance(item, str):
            raise ValueError(
                f"Movie {movie_id}: expected '{field}[{index}]' to be text."
            )
        strings.append(item)
    return strings


def _frame(
    rows: list[dict[str, object]], columns: tuple[str, ...]
) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(rows, columns=columns)
    for column in frame.columns:
        frame[column] = frame[column].map(_clean_text)
    return frame


def _dynamic_frame(
    rows: list[dict[str, object]], required_columns: tuple[str, ...]
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=required_columns)

    # Flatten nested credit fields once, using these as their final column names.
    frame = pd.json_normalize(rows, sep="_")
    for column in required_columns:
        if column not in frame:
            frame[column] = pd.NA
    extra_columns = [column for column in frame if column not in required_columns]
    frame = frame.reindex(columns=(*required_columns, *extra_columns))
    for column in frame.columns:
        frame[column] = frame[column].map(_clean_text)
    return frame


def _register_entity(
    entities: dict[object, dict[str, object]],
    key: object,
    key_column: str,
    entity_name: str,
    attributes: dict[str, object],
) -> None:
    entity = entities.setdefault(key, {key_column: key})
    for field, raw_value in attributes.items():
        value = _clean_text(raw_value)
        if _is_missing(value):
            continue

        existing = entity.get(field, pd.NA)
        if _is_missing(existing):
            entity[field] = value
        elif existing != value:
            raise ValueError(
                f"Conflicting {entity_name} {key_column}={key!r} "
                f"attribute '{field}': {existing!r} != {value!r}."
            )


def _append_relationship(
    rows: list[dict[str, object]],
    seen: set[tuple[object, ...]],
    key: tuple[object, ...],
    relationship_name: str,
    row: dict[str, object],
) -> None:
    if key in seen:
        raise ValueError(f"Duplicate {relationship_name} relationship {key!r}.")
    seen.add(key)
    rows.append(row)


def _credit_row(
    person: dict[str, object],
    movie_id: int,
    role: str,
    people: dict[object, dict[str, object]],
    seen_credit_ids: set[str],
) -> dict[str, object]:
    person_id = _positive_id(person.get("id"), "Person ID")
    credit_id = _text_key(person.get("credit_id"), f"{role} credit ID")
    if credit_id in seen_credit_ids:
        raise ValueError(f"Duplicate credit ID {credit_id!r}.")
    seen_credit_ids.add(credit_id)

    _register_entity(
        people,
        person_id,
        "person_id",
        "person",
        {field: person.get(field) for field in PERSON_ATTRIBUTES},
    )
    row: dict[str, object] = {
        "movie_id": movie_id,
        "credit_id": credit_id,
        "person_id": person_id,
    }
    for field, value in person.items():
        if field not in {"id", "movie_id", *PERSON_ATTRIBUTES}:
            row[field] = _clean_text(value)
    return row


def normalize_movie_records(
    records: Iterable[dict[str, object]],
) -> MovieTables:
    movie_rows: list[dict[str, object]] = []
    genre_entities: dict[object, dict[str, object]] = {}
    movie_genre_rows: list[dict[str, object]] = []
    company_entities: dict[object, dict[str, object]] = {}
    movie_company_rows: list[dict[str, object]] = []
    country_entities: dict[object, dict[str, object]] = {}
    movie_origin_country_rows: list[dict[str, object]] = []
    movie_production_country_rows: list[dict[str, object]] = []
    language_entities: dict[object, dict[str, object]] = {}
    movie_language_rows: list[dict[str, object]] = []
    collection_entities: dict[object, dict[str, object]] = {}
    people_entities: dict[object, dict[str, object]] = {}
    cast_credit_rows: list[dict[str, object]] = []
    crew_credit_rows: list[dict[str, object]] = []
    movie_genre_keys: set[tuple[object, ...]] = set()
    movie_company_keys: set[tuple[object, ...]] = set()
    movie_origin_country_keys: set[tuple[object, ...]] = set()
    movie_production_country_keys: set[tuple[object, ...]] = set()
    movie_language_keys: set[tuple[object, ...]] = set()
    seen_movie_ids: set[int] = set()
    seen_credit_ids: set[str] = set()

    nested_fields = {
        "belongs_to_collection",
        "cached_at_utc",
        "genres",
        "origin_country",
        "production_companies",
        "production_countries",
        "spoken_languages",
        "credits",
    }

    for record in records:
        movie_id = _positive_id(record.get("id"), "Movie ID")
        if movie_id in seen_movie_ids:
            raise ValueError(f"Duplicate movie ID {movie_id}.")
        seen_movie_ids.add(movie_id)

        movie_row: dict[str, object] = {"movie_id": movie_id}
        for field, value in record.items():
            if field not in nested_fields and field != "id":
                movie_row[field] = _clean_text(value)

        collection = record.get("belongs_to_collection")
        if collection is None:
            collection = {}
        if not isinstance(collection, dict):
            raise ValueError(
                f"Movie {movie_id}: expected 'belongs_to_collection' to be "
                "an object or null."
            )
        collection_mapping = cast(dict[object, object], collection)
        if not all(isinstance(key, str) for key in collection_mapping):
            raise ValueError(
                f"Movie {movie_id}: expected 'belongs_to_collection' to be "
                "an object or null."
            )
        collection_values = cast(dict[str, object], collection_mapping)
        collection_id_value = collection_values.get("id")
        if collection_id_value is None:
            if any(
                not _is_missing(_clean_text(collection_values.get(field)))
                for field in ("name", "poster_path", "backdrop_path")
            ):
                raise ValueError(
                    f"Movie {movie_id}: collection metadata requires an ID."
                )
            movie_row["collection_id"] = pd.NA
        else:
            collection_id = _positive_id(collection_id_value, "Collection ID")
            movie_row["collection_id"] = collection_id
            _register_entity(
                collection_entities,
                collection_id,
                "collection_id",
                "collection",
                {
                    "collection_name": collection_values.get("name"),
                    "collection_poster_path": collection_values.get("poster_path"),
                    "collection_backdrop_path": collection_values.get(
                        "backdrop_path"
                    ),
                },
            )
        movie_rows.append(movie_row)

        for genre in _mapping_values(record, "genres", movie_id):
            genre_id = _positive_id(genre.get("id"), "Genre ID")
            _register_entity(
                genre_entities,
                genre_id,
                "genre_id",
                "genre",
                {"genre_name": genre.get("name")},
            )
            _append_relationship(
                movie_genre_rows,
                movie_genre_keys,
                (movie_id, genre_id),
                "movie–genre",
                {"movie_id": movie_id, "genre_id": genre_id},
            )

        for raw_country_code in _string_values(record, "origin_country", movie_id):
            country_code = _text_key(raw_country_code, "Origin country code")
            _register_entity(
                country_entities,
                country_code,
                "country_code",
                "country",
                {"country_name": None},
            )
            _append_relationship(
                movie_origin_country_rows,
                movie_origin_country_keys,
                (movie_id, country_code),
                "movie–origin-country",
                {"movie_id": movie_id, "country_code": country_code},
            )

        for company in _mapping_values(record, "production_companies", movie_id):
            company_id = _positive_id(company.get("id"), "Company ID")
            origin_country = company.get("origin_country")
            origin_country_code = (
                None
                if _is_missing(_clean_text(origin_country))
                else _text_key(origin_country, "Company origin country code")
            )
            if origin_country_code is not None:
                _register_entity(
                    country_entities,
                    origin_country_code,
                    "country_code",
                    "country",
                    {"country_name": None},
                )
            _register_entity(
                company_entities,
                company_id,
                "company_id",
                "company",
                {
                    "company_name": company.get("name"),
                    "company_logo_path": company.get("logo_path"),
                    "origin_country_code": origin_country_code,
                },
            )
            _append_relationship(
                movie_company_rows,
                movie_company_keys,
                (movie_id, company_id),
                "movie–company",
                {"movie_id": movie_id, "company_id": company_id},
            )

        for country in _mapping_values(record, "production_countries", movie_id):
            country_code = _text_key(
                country.get("iso_3166_1"), "Production country code"
            )
            _register_entity(
                country_entities,
                country_code,
                "country_code",
                "country",
                {"country_name": country.get("name")},
            )
            _append_relationship(
                movie_production_country_rows,
                movie_production_country_keys,
                (movie_id, country_code),
                "movie–production-country",
                {"movie_id": movie_id, "country_code": country_code},
            )

        for language in _mapping_values(record, "spoken_languages", movie_id):
            language_code = _text_key(
                language.get("iso_639_1"), "Spoken language code"
            )
            _register_entity(
                language_entities,
                language_code,
                "language_code",
                "language",
                {
                    "language_name": language.get("name"),
                    "language_english_name": language.get("english_name"),
                },
            )
            _append_relationship(
                movie_language_rows,
                movie_language_keys,
                (movie_id, language_code),
                "movie–spoken-language",
                {"movie_id": movie_id, "language_code": language_code},
            )

        credits = record.get("credits")
        if credits is None:
            credits = {}
        if not isinstance(credits, dict):
            raise ValueError(f"Movie {movie_id}: expected 'credits' to be an object.")
        credit_mapping = cast(dict[object, object], credits)
        if not all(isinstance(key, str) for key in credit_mapping):
            raise ValueError(f"Movie {movie_id}: expected 'credits' to be an object.")
        credit_values = cast(dict[str, object], credit_mapping)
        for person in _mapping_values(credit_values, "cast", movie_id):
            cast_credit_rows.append(
                _credit_row(person, movie_id, "cast", people_entities, seen_credit_ids)
            )
        for person in _mapping_values(credit_values, "crew", movie_id):
            crew_credit_rows.append(
                _credit_row(person, movie_id, "crew", people_entities, seen_credit_ids)
            )

    movies = pd.DataFrame.from_records(movie_rows)
    if "movie_id" not in movies:
        movies["movie_id"] = pd.Series(dtype="int64")
    if "collection_id" not in movies:
        movies["collection_id"] = pd.Series(dtype="Int64")
    else:
        movies["collection_id"] = movies["collection_id"].astype("Int64")
    if "release_date" in movies:
        release_dates = movies["release_date"]
        parsed_dates = pd.to_datetime(
            release_dates, format="%Y-%m-%d", errors="coerce"
        )
        invalid_dates = release_dates.notna() & parsed_dates.isna()
        if invalid_dates.any():
            invalid_movie_ids = movies.loc[invalid_dates, "movie_id"].tolist()
            raise ValueError(
                f"Invalid release_date value for movie IDs: {invalid_movie_ids}"
            )
        movies["release_date"] = parsed_dates

    return MovieTables(
        movies=movies,
        genres=_frame(list(genre_entities.values()), GENRE_FIELDS),
        movie_genres=_frame(movie_genre_rows, MOVIE_GENRE_FIELDS),
        companies=_frame(list(company_entities.values()), COMPANY_FIELDS),
        movie_companies=_frame(movie_company_rows, MOVIE_COMPANY_FIELDS),
        countries=_frame(list(country_entities.values()), COUNTRY_FIELDS),
        movie_origin_countries=_frame(
            movie_origin_country_rows, MOVIE_COUNTRY_FIELDS
        ),
        movie_production_countries=_frame(
            movie_production_country_rows, MOVIE_COUNTRY_FIELDS
        ),
        languages=_frame(list(language_entities.values()), LANGUAGE_FIELDS),
        movie_spoken_languages=_frame(movie_language_rows, MOVIE_LANGUAGE_FIELDS),
        collections=_frame(list(collection_entities.values()), COLLECTION_FIELDS),
        people=_frame(list(people_entities.values()), PEOPLE_FIELDS),
        cast_credits=_dynamic_frame(cast_credit_rows, CAST_CREDIT_FIELDS),
        crew_credits=_dynamic_frame(crew_credit_rows, CREW_CREDIT_FIELDS),
    )
