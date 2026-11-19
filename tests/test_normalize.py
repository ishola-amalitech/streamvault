import unittest

import pandas as pd

from streamvault.normalize import normalize_movie_records


def movie_record(
    movie_id: int, popularity: float, release_date: str
) -> dict[str, object]:
    return {
        "id": movie_id,
        "title": f"Movie {movie_id}",
        "homepage": " ",
        "release_date": release_date,
        "belongs_to_collection": {
            "id": 10,
            "name": "Example Collection",
            "poster_path": "/collection.jpg",
            "backdrop_path": "/backdrop.jpg",
        },
        "genres": [{"id": 28, "name": "Action"}],
        "origin_country": ["US"],
        "production_companies": [
            {
                "id": 1,
                "name": "Example Studios",
                "logo_path": "/logo.png",
                "origin_country": "US",
            }
        ],
        "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
        "spoken_languages": [
            {
                "iso_639_1": "en",
                "name": "English",
                "english_name": "English",
            }
        ],
        "credits": {
            "cast": [
                {
                    "id": 5,
                    "credit_id": f"cast-{movie_id}",
                    "cast_id": movie_id,
                    "name": "Actor One",
                    "original_name": "Actor One",
                    "gender": 2,
                    "adult": False,
                    "known_for_department": "Acting",
                    "profile_path": "/actor.png",
                    "character": "Lead",
                    "order": 0,
                    "popularity": popularity,
                }
            ],
            "crew": [
                {
                    "id": 6,
                    "credit_id": f"crew-{movie_id}",
                    "name": "Director One",
                    "original_name": "Director One",
                    "gender": 2,
                    "adult": False,
                    "known_for_department": "Directing",
                    "profile_path": "/director.png",
                    "department": "Directing",
                    "job": "Director",
                    "popularity": popularity,
                }
            ],
        },
    }


class NormalizeMovieRecordsTests(unittest.TestCase):
    def test_deduplicates_entities_and_preserves_every_relationship(self) -> None:
        first = movie_record(155, 1.2, "2020-01-02")
        first["cached_at_utc"] = "2026-11-17T11:00:00+00:00"
        second = movie_record(165, 2.4, "2021-03-04")
        third = {
            "id": 242,
            "title": "No Collection",
            "release_date": "",
            "belongs_to_collection": None,
            "genres": [],
            "origin_country": [],
            "production_companies": [],
            "production_countries": [],
            "spoken_languages": [],
            "credits": {"cast": [], "crew": []},
        }

        tables = normalize_movie_records([first, second, third])

        self.assertEqual(len(tables.movies), 3)
        self.assertNotIn("cached_at_utc", tables.movies.columns)
        self.assertEqual(tables.movies["movie_id"].tolist(), [155, 165, 242])
        self.assertEqual(tables.movies["collection_id"].tolist()[:2], [10, 10])
        self.assertTrue(pd.isna(tables.movies.loc[2, "collection_id"]))
        self.assertEqual(str(tables.movies["collection_id"].dtype), "Int64")
        self.assertTrue(pd.isna(tables.movies.loc[0, "homepage"]))
        self.assertEqual(
            tables.movies.loc[0, "release_date"], pd.Timestamp("2020-01-02")
        )
        self.assertTrue(pd.isna(tables.movies.loc[2, "release_date"]))

        self.assertEqual(tables.genres.to_dict("records"), [
            {"genre_id": 28, "genre_name": "Action"}
        ])
        self.assertEqual(
            tables.movie_genres.to_dict("records"),
            [{"movie_id": 155, "genre_id": 28}, {"movie_id": 165, "genre_id": 28}],
        )
        self.assertEqual(len(tables.companies), 1)
        self.assertEqual(len(tables.movie_companies), 2)
        self.assertEqual(tables.countries.to_dict("records"), [
            {"country_code": "US", "country_name": "United States"}
        ])
        self.assertEqual(len(tables.movie_origin_countries), 2)
        self.assertEqual(len(tables.movie_production_countries), 2)
        self.assertEqual(len(tables.languages), 1)
        self.assertEqual(len(tables.movie_spoken_languages), 2)
        self.assertEqual(len(tables.collections), 1)
        self.assertEqual(len(tables.people), 2)
        self.assertNotIn("popularity", tables.people.columns)
        self.assertEqual(len(tables.cast_credits), 2)
        self.assertEqual(len(tables.crew_credits), 2)
        self.assertEqual(tables.cast_credits["popularity"].tolist(), [1.2, 2.4])
        self.assertTrue(tables.cast_credits["credit_id"].is_unique)
        self.assertTrue(tables.crew_credits["credit_id"].is_unique)

        for frame, entity_id, dimension in (
            (tables.movie_genres, "genre_id", tables.genres),
            (tables.movie_companies, "company_id", tables.companies),
            (tables.movie_origin_countries, "country_code", tables.countries),
            (tables.movie_production_countries, "country_code", tables.countries),
            (tables.movie_spoken_languages, "language_code", tables.languages),
            (tables.cast_credits, "person_id", tables.people),
            (tables.crew_credits, "person_id", tables.people),
        ):
            self.assertTrue(frame[entity_id].isin(dimension[entity_id]).all())
            self.assertTrue(frame["movie_id"].isin(tables.movies["movie_id"]).all())
        self.assertTrue(
            tables.companies.loc[
                tables.companies["origin_country_code"].notna(),
                "origin_country_code",
            ]
            .isin(tables.countries["country_code"])
            .all()
        )
        self.assertTrue(
            tables.movies["collection_id"]
            .dropna()
            .isin(tables.collections["collection_id"])
            .all()
        )
        self.assertFalse(
            tables.movie_genres.duplicated(["movie_id", "genre_id"]).any()
        )
        self.assertFalse(
            tables.movie_companies.duplicated(["movie_id", "company_id"]).any()
        )

    def test_conflicting_reference_attributes_are_reported(self) -> None:
        first = movie_record(155, 1.2, "2020-01-02")
        second = movie_record(165, 2.4, "2021-03-04")
        second["genres"] = [{"id": 28, "name": "Different name"}]

        with self.assertRaisesRegex(ValueError, "Conflicting genre"):
            normalize_movie_records([first, second])

    def test_duplicate_relationship_is_rejected(self) -> None:
        record = movie_record(155, 1.2, "2020-01-02")
        record["genres"] = [
            {"id": 28, "name": "Action"},
            {"id": 28, "name": "Action"},
        ]

        with self.assertRaisesRegex(ValueError, "Duplicate movie–genre"):
            normalize_movie_records([record])

    def test_duplicate_credit_id_is_rejected(self) -> None:
        first = movie_record(155, 1.2, "2020-01-02")
        second = movie_record(165, 2.4, "2021-03-04")
        second["credits"] = {
            "cast": [
                {
                    "id": 5,
                    "credit_id": "cast-155",
                    "name": "Actor One",
                    "original_name": "Actor One",
                    "gender": 2,
                    "adult": False,
                    "known_for_department": "Acting",
                    "profile_path": "/actor.png",
                    "popularity": 2.4,
                }
            ],
            "crew": [],
        }

        with self.assertRaisesRegex(ValueError, "Duplicate credit ID"):
            normalize_movie_records([first, second])

    def test_credit_row_uses_the_trimmed_id(self) -> None:
        record = {
            "id": 155,
            "credits": {"cast": [{"id": 5, "credit_id": " cast-155 "}]},
        }

        tables = normalize_movie_records([record])

        self.assertEqual(tables.cast_credits["credit_id"].tolist(), ["cast-155"])

    def test_credits_can_be_missing_but_must_be_an_object_when_supplied(self) -> None:
        tables = normalize_movie_records([{"id": 155}, {"id": 165, "credits": None}])

        self.assertTrue(tables.cast_credits.empty)
        self.assertTrue(tables.crew_credits.empty)
        self.assertTrue(tables.people.empty)
        with self.assertRaisesRegex(ValueError, "Movie 155: expected 'credits' to be an object"):
            normalize_movie_records([{"id": 155, "credits": []}])

    def test_duplicate_movie_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate movie ID 155"):
            duplicate = movie_record(155, 1.2, "2020-01-02")
            normalize_movie_records([duplicate, duplicate])

    def test_invalid_release_date_is_reported_with_movie_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "movie IDs: \\[155\\]"):
            normalize_movie_records([movie_record(155, 1.2, "not-a-date")])

    def test_invalid_nested_list_shape_is_reported(self) -> None:
        record = movie_record(155, 1.2, "2020-01-02")
        record["genres"] = {"id": 28}
        with self.assertRaisesRegex(ValueError, "expected 'genres' to be a list"):
            normalize_movie_records([record])


if __name__ == "__main__":
    unittest.main()
