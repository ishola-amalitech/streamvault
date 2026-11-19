"""Turn cached TMDB responses into tables that can be joined by ID.

Start with normalize_movie_records below. It builds the film and credit rows
and asks MovieReferences to handle collections, genres, and other shared details.
For example, a film with three genres gets one film row and three genre links.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from streamvault._normalize_references import MovieReferences
from streamvault._normalize_tables import (
    ReferenceRows,
    Row,
    clean_blank_columns,
    clean_text,
    object_list,
    object_values,
    positive_id,
    text_key,
)
from streamvault.diagnostics import run_data_checks


@dataclass(frozen=True)
class MovieTables:
    """Tables returned to the notebooks. Each field describes one kind of row."""

    movies: pd.DataFrame  # One film, including its collection ID when available.
    genres: pd.DataFrame  # One genre ID and its name.
    movie_genres: pd.DataFrame  # One film–genre pair.
    companies: pd.DataFrame  # One company and its details.
    movie_companies: pd.DataFrame  # One film–company pair.
    countries: pd.DataFrame  # One country code and its name when available.
    movie_origin_countries: pd.DataFrame  # One film–origin-country pair.
    movie_production_countries: pd.DataFrame  # One film–production-country pair.
    languages: pd.DataFrame  # One language code with its local and English names.
    movie_spoken_languages: pd.DataFrame  # One film–spoken-language pair.
    collections: pd.DataFrame  # One collection ID and its details.
    people: pd.DataFrame  # One person and details shared across their credits.
    cast_credits: pd.DataFrame  # One cast credit, including the role and billing order.
    crew_credits: pd.DataFrame  # One crew credit, including the department and job.


# The raw "id" becomes "movie_id". The other fields go to separate tables or
# describe the download itself. This keeps film facts like revenue on one row.
MOVIE_EXCLUDED_FIELDS = frozenset((
    "id", "belongs_to_collection", "cached_at_utc", "genres", "origin_country",
    "production_companies", "production_countries", "spoken_languages", "credits",
))

PERSON_ATTRIBUTES = (
    "adult", "gender", "known_for_department", "name", "original_name", "profile_path",
)

# Person details live in the people table. Keep the validated IDs set on the credit row.
CREDIT_EXCLUDED_FIELDS = frozenset(("id", "movie_id", "credit_id", *PERSON_ATTRIBUTES))
CREDIT_KEYS = ("movie_id", "credit_id", "person_id")
CAST_CREDIT_FIELDS = (*CREDIT_KEYS, "cast_id", "character", "order", "popularity")
CREW_CREDIT_FIELDS = (*CREDIT_KEYS, "department", "job", "popularity")


def _add_credits(
    record: Row,
    movie_id: int,
    people: ReferenceRows,
    credits_by_role: dict[str, list[Row]],
    seen_credit_ids: set[str],
) -> None:
    """Store each cast or crew entry and add the person to the shared lookup table."""
    raw_credits = record.get("credits")
    # An absent or null credits object has no rows. Check the shape when it is supplied.
    if raw_credits is None:
        return
    credits = object_values(
        raw_credits, f"Movie {movie_id}: expected 'credits' to be an object."
    )

    for role, rows in credits_by_role.items():
        for credit in object_list(credits, role, movie_id):
            person_id = positive_id(credit.get("id"), "Person ID")
            credit_id = text_key(credit.get("credit_id"), f"{role} credit ID")

            # One person can have many credits, even for the same film.
            # The credit ID itself must be unique across cast and crew.
            if credit_id in seen_credit_ids:
                raise ValueError(f"Duplicate credit ID {credit_id!r}.")
            seen_credit_ids.add(credit_id)
            people.add(person_id, {field: credit.get(field) for field in PERSON_ATTRIBUTES})

            # Keep film-specific details such as the job, character and popularity here.
            row: Row = {"movie_id": movie_id, "credit_id": credit_id, "person_id": person_id}
            row.update({
                field: clean_text(value)
                for field, value in credit.items()
                if field not in CREDIT_EXCLUDED_FIELDS
            })
            rows.append(row)


def _credit_frame(rows: list[Row], required_columns: tuple[str, ...]) -> pd.DataFrame:
    """Keep the credit columns available even when a cache has no credits."""
    if not rows:
        return pd.DataFrame(columns=required_columns)

    # Flatten extra nested values into columns. The keys and known fields come first.
    frame = pd.json_normalize(rows, sep="_")
    for column in required_columns:
        if column not in frame:
            frame[column] = pd.NA
    extra_columns = [column for column in frame if column not in required_columns]
    return clean_blank_columns(frame.reindex(columns=(*required_columns, *extra_columns)))


def _movie_frame(rows: list[Row]) -> pd.DataFrame:
    """Set the movie table's ID and date columns up for joins and filters."""
    if not rows:
        # Keep both join columns available when the cache has no films.
        return pd.DataFrame({
            "movie_id": pd.Series(dtype="int64"),
            "collection_id": pd.Series(dtype="Int64"),
        })

    movies = pd.DataFrame.from_records(rows)
    # A nullable integer keeps real collection IDs whole and allows an empty value.
    movies["collection_id"] = movies["collection_id"].astype("Int64")
    if "release_date" in movies:
        release_dates = movies["release_date"]
        parsed_dates = pd.to_datetime(release_dates, format="%Y-%m-%d", errors="coerce")
        # Blank dates were already marked as missing. Flag any supplied dates that failed.
        invalid_dates = release_dates.notna() & parsed_dates.isna()
        if invalid_dates.any():
            invalid_movie_ids = movies.loc[invalid_dates, "movie_id"].tolist()
            raise ValueError(f"Invalid release_date value for movie IDs: {invalid_movie_ids}")
        movies["release_date"] = parsed_dates
    return movies


def normalize_movie_records(records: Iterable[Row]) -> MovieTables:
    """Read the responses once, then build the 14 tables used for analysis."""
    movie_rows: list[Row] = []
    references = MovieReferences()
    people = ReferenceRows("person", "person_id", *PERSON_ATTRIBUTES)
    credits_by_role: dict[str, list[Row]] = {"cast": [], "crew": []}
    # Track these for the whole run, including IDs that repeat in different responses.
    seen_movie_ids: set[int] = set()
    seen_credit_ids: set[str] = set()

    for record in records:
        movie_id = positive_id(record.get("id"), "Movie ID")
        # Repeated films would double-count movie facts such as revenue.
        if movie_id in seen_movie_ids:
            raise ValueError(f"Duplicate movie ID {movie_id}.")
        seen_movie_ids.add(movie_id)

        movie_row: Row = {"movie_id": movie_id}
        movie_row.update({
            field: clean_text(value)
            for field, value in record.items()
            if field not in MOVIE_EXCLUDED_FIELDS
        })

        # A film has at most one collection. Store that link directly on the film row.
        collection_id = references.add_movie(record, movie_id)
        movie_row["collection_id"] = pd.NA if collection_id is None else collection_id
        movie_rows.append(movie_row)
        _add_credits(record, movie_id, people, credits_by_role, seen_credit_ids)

    # Build pandas tables once all shared details and relationship rows are collected.
    return MovieTables(
        movies=_movie_frame(movie_rows),
        genres=references.genres.to_frame(),
        movie_genres=references.movie_genres.to_frame(),
        companies=references.companies.to_frame(),
        movie_companies=references.movie_companies.to_frame(),
        countries=references.countries.to_frame(),
        movie_origin_countries=references.movie_origin_countries.to_frame(),
        movie_production_countries=references.movie_production_countries.to_frame(),
        languages=references.languages.to_frame(),
        movie_spoken_languages=references.movie_spoken_languages.to_frame(),
        collections=references.collections.to_frame(),
        people=people.to_frame(),
        cast_credits=_credit_frame(credits_by_role["cast"], CAST_CREDIT_FIELDS),
        crew_credits=_credit_frame(credits_by_role["crew"], CREW_CREDIT_FIELDS),
    )


def normalization_checks(
    stage: str, tables: MovieTables, expected_ids: set[str]
) -> pd.DataFrame:
    """Check the film rows and links the recommendation relies on."""
    movies = tables.movies
    movie_ids = movies["movie_id"]
    actual_ids = set(movie_ids.dropna().astype("string"))
    missing = sorted(expected_ids - actual_ids)
    unexpected = sorted(actual_ids - expected_ids)

    # A broken link to a film, genre, or person can bias the genre and talent analysis.
    broken_links: list[str] = []
    for name, links, key, reference in (
        ("genres", tables.movie_genres, "genre_id", tables.genres),
        ("cast", tables.cast_credits, "person_id", tables.people),
        ("crew", tables.crew_credits, "person_id", tables.people),
    ):
        bad = ~links["movie_id"].isin(movie_ids) | ~links[key].isin(reference[key])
        if bad.any():
            broken_links.append(f"{name}: {int(bad.sum())} broken links")

    # Test the collection join used to identify bundles. Missing collection IDs are allowed.
    joined = movies[["movie_id", "collection_id"]].merge(
        tables.collections[["collection_id"]],
        on="collection_id",
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    unmatched = joined["collection_id"].notna() & joined["_merge"].eq("left_only")
    return run_data_checks(stage, {
        "Movie IDs are present and unique": (
            bool(movie_ids.notna().all() and movie_ids.is_unique),
            f"{movie_ids.nunique()} distinct IDs in {len(movies)} rows",
        ),
        "Movie IDs match the resolved candidates": (
            not missing and not unexpected,
            f"{len(expected_ids)} expected, {len(actual_ids)} found. "
            f"Missing examples: {missing[:5]}. Unexpected examples: {unexpected[:5]}.",
        ),
        "Genre and credit links resolve": (
            not broken_links,
            ", ".join(broken_links) or "Every link points to an existing film and reference",
        ),
        "Collection join preserves films and resolves supplied IDs": (
            bool(len(joined) == len(movies) and joined["movie_id"].equals(movie_ids)
                 and not unmatched.any()),
            f"{len(joined)} rows from {len(movies)} films. "
            f"Unmatched example movie IDs: {joined.loc[unmatched, 'movie_id'].head().tolist()}",
        ),
    })
