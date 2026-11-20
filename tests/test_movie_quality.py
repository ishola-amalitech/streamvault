import unittest

import pandas as pd

from streamvault.movie_quality import film_quality_issues, financial_inputs, rating_inputs


class FinancialInputsTests(unittest.TestCase):
    def test_keeps_usable_amounts_independently_and_records_issues(self) -> None:
        films = pd.DataFrame({
            "budget": ["1000000", 0, None, -1, True, float("inf"), "unknown"],
            "revenue": [None, 500_000_000, 0, 2_942_649_778, False, "inf", -100],
        }, index=[12, 21, 34, 45, 56, 67, 78])
        original = films.copy()

        prepared = financial_inputs(films)

        pd.testing.assert_frame_equal(films, original)
        pd.testing.assert_series_equal(
            prepared["budget"].dropna(),
            pd.Series([1_000_000.0], index=[12], name="budget"),
        )
        pd.testing.assert_series_equal(
            prepared["revenue"].dropna(),
            pd.Series([500_000_000.0, 2_942_649_778.0], index=[21, 45], name="revenue"),
        )
        self.assertEqual(prepared["budget_issue"].tolist(), [
            "", "Zero production budget", "Missing production budget",
            "Invalid production budget", "Invalid production budget",
            "Invalid production budget", "Invalid production budget",
        ])
        self.assertEqual(prepared["revenue_issue"].tolist(), [
            "Missing box office gross", "", "Zero box office gross", "",
            "Invalid box office gross", "Invalid box office gross", "Invalid box office gross",
        ])

    def test_treats_absent_financial_columns_as_missing(self) -> None:
        prepared = financial_inputs(pd.DataFrame({"movie_id": [123]}, index=[7]))

        self.assertTrue(prepared.loc[7, ["budget", "revenue"]].isna().all())
        self.assertEqual(prepared.at[7, "budget_issue"], "Missing production budget")
        self.assertEqual(prepared.at[7, "revenue_issue"], "Missing box office gross")

class RatingAndDateTests(unittest.TestCase):
    def test_unrated_titles_and_fractional_votes_report_separate_issues(self) -> None:
        inputs = rating_inputs(pd.DataFrame({
            "vote_average": [0, 0, 8],
            "vote_count": [0, 500, 12.5],
        }))

        self.assertEqual(inputs["rating_issue"].tolist(), ["Missing rating", "", ""])
        self.assertEqual(inputs["vote_count_issue"].tolist(), ["", "", "Invalid vote count"])
        self.assertTrue(pd.isna(inputs.at[2, "vote_count"]))
        self.assertEqual(inputs.at[1, "vote_average"], 0)

    def test_film_quality_reports_malformed_release_dates(self) -> None:
        issues = film_quality_issues(pd.DataFrame({
            "movie_id": [155],
            "title": ["Example"],
            "release_date": ["2023-02-29"],
            "status": ["Released"],
        }))

        invalid_date = issues.loc[issues["issue"].eq("Invalid release date")]
        self.assertEqual(invalid_date["movie_id"].tolist(), [155])
        self.assertEqual(invalid_date["impact"].tolist(), ["Outside both release windows"])
