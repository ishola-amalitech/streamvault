import unittest

import pandas as pd

from streamvault.recommendation import (
    INSUFFICIENT_EVIDENCE,
    compare_decision_units,
    omit_best_bundle_films,
    rank_window,
    score_films,
    summarize_bundles,
)
from streamvault.recommendation_reports import prepare_standalone_report, standalone_candidate_report


class RecommendationTests(unittest.TestCase):
    def test_ranking_requires_every_observed_bundle_film_and_breaks_ties_by_id(self) -> None:
        films = pd.DataFrame({
            "movie_id": [4, 3, 2, 1, 5, 6, 7],
            "collection_id": pd.array([10, 10, 20, 20, 30, None, None], dtype="Int64"),
            "vote_average": [9.0] * 7,
            "vote_count": [1_000, 1_000, 1_000, 999, 1_000, 1_000, 1_000],
        }).iloc[::-1]
        names = pd.Series({10: "A", 20: "B", 30: "C"})
        scored = score_films(films)
        bundles, standalones = rank_window(scored, summarize_bundles(scored, names))

        # Bundle 20 has one unscored film. Bundle 30 can still qualify with its only film.
        self.assertEqual(bundles["collection_id"].tolist(), [10, 30])
        self.assertEqual(bundles["median_adjusted_rating"].tolist(), [8.0, 8.0])
        self.assertEqual(standalones["movie_id"].tolist(), [6, 7])
        self.assertEqual(bundles["film_evidence"].tolist(), ["Multiple films", "Based on one film"])

        # Both films in Bundle 10 have the same score, so the lower movie ID goes first.
        removed, reduced = omit_best_bundle_films(scored, bundles, names)
        self.assertEqual(set(removed["movie_id"]), {3, 5})
        self.assertEqual(reduced["collection_id"].tolist(), [10])
        self.assertEqual(reduced["films"].tolist(), [1])

    def test_comparison_withholds_small_samples_and_flags_duplicates(self) -> None:
        bundles = pd.DataFrame({
            "collection_id": range(1, 6), "median_adjusted_rating": [7.0] * 5, "films": [2] * 5,
        })
        standalones = pd.DataFrame({"movie_id": range(6, 11), "adjusted_rating": [8.0] * 5})

        small = compare_decision_units(bundles, standalones.head(4), possible_duplicates=False)
        self.assertEqual(small["conclusion"], INSUFFICIENT_EVIDENCE)
        result = compare_decision_units(bundles, standalones, possible_duplicates=True)
        self.assertEqual(result["conclusion"], "Provisional — favors standalones")
        self.assertEqual(result["interval_low"], -1.0)
        self.assertEqual(result["interval_high"], -1.0)

    def test_standalone_csv_data_keeps_original_and_usable_gross_separate(self) -> None:
        films = pd.DataFrame({
            "movie_id": [1, 2, 3, 4],
            "collection_id": pd.array([None, None, None, None], dtype="Int64"),
            "vote_average": [9.0] * 4,
            "vote_count": [1_000] * 4,
            "budget": [10, 10, 0, 5],
            "revenue": ["0", "unavailable", "100", "30"],
        })
        base = prepare_standalone_report(films, pd.Series(dtype="string"))
        scored = score_films(films.iloc[:3])
        _, ranking = rank_window(scored, summarize_bundles(scored, pd.Series(dtype="string")))
        outcomes = pd.Series({1: "Shortlisted", 2: "Shortlisted", 3: "Shortlisted", 4: "Before cutoff"})
        report = standalone_candidate_report(base, scored, ranking, outcomes)

        self.assertEqual(report["raw_gross"].tolist(), ["0", "unavailable", "100", "30"])
        self.assertTrue(report.loc[[1, 2], "reported_gross"].isna().all())
        self.assertEqual(report.loc[[3, 4], "reported_gross"].tolist(), [100.0, 30.0])
        self.assertTrue(report["gross_minus_budget"].isna().all())
        self.assertEqual(report.loc[[1, 2, 3], "adjusted_rating"].tolist(), [8.0, 8.0, 8.0])
        self.assertTrue(pd.isna(report.at[4, "rank"]))
