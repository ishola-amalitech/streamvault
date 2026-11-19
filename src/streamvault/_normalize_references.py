"""Extract film collections, genres, companies, countries, and languages."""

from streamvault._normalize_tables import (
    MovieLinks,
    ReferenceRows,
    Row,
    clean_text,
    is_missing,
    object_list,
    object_values,
    positive_id,
    text_key,
    text_list,
)


class MovieReferences:
    """Collect shared details and the links to each film during one run."""

    def __init__(self) -> None:
        # Each lookup row is keyed by its own ID or code. The links connect those
        # IDs to films without repeating the lookup details for every film.
        self.collections = ReferenceRows(
            "collection", "collection_id", "collection_name",
            "collection_poster_path", "collection_backdrop_path",
        )
        self.genres = ReferenceRows("genre", "genre_id", "genre_name")
        self.movie_genres = MovieLinks("movie–genre", "genre_id")
        self.companies = ReferenceRows(
            "company", "company_id", "company_name", "company_logo_path",
            "origin_country_code",
        )
        self.movie_companies = MovieLinks("movie–company", "company_id")
        self.countries = ReferenceRows("country", "country_code", "country_name")
        self.movie_origin_countries = MovieLinks("movie–origin-country", "country_code")
        self.movie_production_countries = MovieLinks("movie–production-country", "country_code")
        self.languages = ReferenceRows(
            "language", "language_code", "language_name", "language_english_name"
        )
        self.movie_spoken_languages = MovieLinks("movie–spoken-language", "language_code")

    def add_movie(self, record: Row, movie_id: int) -> int | None:
        """Add one film's shared details and return its collection ID, if it has one."""
        collection_id = self._add_collection(record.get("belongs_to_collection"), movie_id)
        self._add_genres(record, movie_id)
        self._add_origin_countries(record, movie_id)
        self._add_companies(record, movie_id)
        self._add_production_countries(record, movie_id)
        self._add_languages(record, movie_id)
        return collection_id

    def _add_collection(self, value: object, movie_id: int) -> int | None:
        # A standalone can have no collection. The caller leaves its collection ID empty.
        if value is None:
            return None
        collection = object_values(
            value, f"Movie {movie_id}: expected 'belongs_to_collection' to be an object or null."
        )
        details = {
            "collection_name": collection.get("name"),
            "collection_poster_path": collection.get("poster_path"),
            "collection_backdrop_path": collection.get("backdrop_path"),
        }
        raw_id = collection.get("id")
        if raw_id is None:
            # Some responses use an empty object. Collection details need an ID to join on.
            if any(not is_missing(clean_text(detail)) for detail in details.values()):
                raise ValueError(f"Movie {movie_id}: collection metadata requires an ID.")
            return None

        collection_id = positive_id(raw_id, "Collection ID")
        self.collections.add(collection_id, details)
        return collection_id

    def _add_genres(self, record: Row, movie_id: int) -> None:
        # A film can have several genres. Save the name once and link each genre by ID.
        for genre in object_list(record, "genres", movie_id):
            genre_id = positive_id(genre.get("id"), "Genre ID")
            self.genres.add(genre_id, {"genre_name": genre.get("name")})
            self.movie_genres.add(movie_id, genre_id)

    def _add_origin_countries(self, record: Row, movie_id: int) -> None:
        # This list contains codes. Production countries may fill in the names later.
        for raw_code in text_list(record, "origin_country", movie_id):
            code = text_key(raw_code, "Origin country code")
            self.countries.add(code, {})
            self.movie_origin_countries.add(movie_id, code)

    def _add_companies(self, record: Row, movie_id: int) -> None:
        for company in object_list(record, "production_companies", movie_id):
            company_id = positive_id(company.get("id"), "Company ID")
            raw_country = company.get("origin_country")
            country_code = None
            if not is_missing(clean_text(raw_country)):
                # The company's home country is a detail about the company itself.
                country_code = text_key(raw_country, "Company origin country code")
                self.countries.add(country_code, {})
            self.companies.add(
                company_id,
                {
                    "company_name": company.get("name"),
                    "company_logo_path": company.get("logo_path"),
                    "origin_country_code": country_code,
                },
            )
            self.movie_companies.add(movie_id, company_id)

    def _add_production_countries(self, record: Row, movie_id: int) -> None:
        # Origin and production have separate film links, even when their codes match.
        for country in object_list(record, "production_countries", movie_id):
            code = text_key(country.get("iso_3166_1"), "Production country code")
            self.countries.add(code, {"country_name": country.get("name")})
            self.movie_production_countries.add(movie_id, code)

    def _add_languages(self, record: Row, movie_id: int) -> None:
        # Keep the local and English language names so both are available for display.
        for language in object_list(record, "spoken_languages", movie_id):
            code = text_key(language.get("iso_639_1"), "Spoken language code")
            self.languages.add(
                code,
                {
                    "language_name": language.get("name"),
                    "language_english_name": language.get("english_name"),
                },
            )
            self.movie_spoken_languages.add(movie_id, code)
