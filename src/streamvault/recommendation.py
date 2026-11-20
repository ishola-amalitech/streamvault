"""Audience scoring and the bundle comparison shared by both release windows."""

import numpy as np
import pandas as pd

from streamvault.movie_quality import financial_inputs, rating_inputs


# Fixed rules keep comparable films on the same scale across windows and reruns.
MINIMUM_VOTES = 1_000
ANCHOR_RATING = 7.0
ANCHOR_VOTES = 1_000
BUNDLE_TARGET = 3
STANDALONE_TARGET = 5
COMPARISON_MINIMUM = 5
COMPARISON_MARGIN = 0.25
BOOTSTRAP_DRAWS = 2_000
BOOTSTRAP_SEED = 42
INSUFFICIENT_EVIDENCE = "Insufficient evidence to favor either group"
ON_SHORTLIST = "Shortlisted"
OUTCOME_FIELDS = ["vote_average", "vote_count", "popularity", "budget", "revenue"]


def score_films(
    films: pd.DataFrame,
    *,
    minimum_votes: int = MINIMUM_VOTES,
    anchor_rating: float = ANCHOR_RATING,
    anchor_votes: int = ANCHOR_VOTES,
) -> pd.DataFrame:
    """Keep one row per film and attach the score, usable dollars, and reason for any missing score."""
    # Preserve the film rows and make missing columns visible as missing values.
    scored = films.reindex(columns=films.columns.union(
        ["title", *OUTCOME_FIELDS], sort=False
    )).copy()
    inputs = rating_inputs(scored)
    rating = inputs["vote_average"]
    votes = inputs["vote_count"]
    enough_votes = votes.ge(minimum_votes).fillna(False)
    valid_votes = inputs["vote_count_issue"].eq("")
    eligible = inputs["rating_issue"].eq("") & valid_votes & enough_votes

    vote_problem = inputs["vote_count_issue"].mask(
        valid_votes & ~enough_votes, f"Fewer than {minimum_votes:,} votes",
    )
    scored["score_exclusion"] = inputs["rating_issue"].str.cat(vote_problem, sep=". ").str.strip(". ")

    # A weighted average keeps the adjusted score on the same 0 to 10 scale.
    scored["vote_average"] = rating
    scored["vote_count"] = votes
    eligible_votes = votes.where(eligible).astype(float)
    scored["adjusted_rating"] = (
        eligible_votes * rating.where(eligible) + anchor_votes * anchor_rating
    ) / (eligible_votes + anchor_votes)

    # Use the same dollar rules as the quality report, and keep each amount separately.
    amounts = financial_inputs(scored)
    budget = amounts["budget"]
    gross = amounts["revenue"]
    has_financials = budget.notna() & gross.notna()
    scored["reported_budget"] = budget
    scored["reported_gross"] = gross
    scored["gross_minus_budget"] = gross.where(has_financials) - budget.where(has_financials)
    scored["gross_difference_to_budget"] = scored["gross_minus_budget"] / budget.where(has_financials)
    # Use the same set of film rows when comparing gross and budget within a bundle.
    scored["gross_on_valid_pair"] = gross.where(has_financials)
    scored["budget_on_valid_pair"] = budget.where(has_financials)
    return scored


def _rank_candidates(candidates: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    # The last sort key is a numeric ID, so a tie never depends on input order.
    ranked = candidates.sort_values(order, ascending=[False] * (len(order) - 1) + [True])
    return ranked.assign(rank=range(1, len(ranked) + 1))


def summarize_bundles(scored: pd.DataFrame, collection_names: pd.Series) -> pd.DataFrame:
    """Summarize the films we observed in each collection for this window."""
    # Count every in-window installment, including any without a usable score.
    linked = scored.loc[scored["collection_id"].notna()]
    # Gross-only figures can use films that have no usable budget. Paired figures use both amounts.
    bundles = linked.groupby("collection_id").agg(
        films=("movie_id", "size"),
        scored_films=("adjusted_rating", "count"),
        median_adjusted_rating=("adjusted_rating", "median"),
        lowest_adjusted_rating=("adjusted_rating", "min"),
        median_votes=("vote_count", "median"),
        films_with_gross=("reported_gross", "count"),
        total_reported_gross=("reported_gross", "sum"),
        median_reported_gross=("reported_gross", "median"),
        films_with_budget_and_gross=("gross_minus_budget", "count"),
        median_budget=("budget_on_valid_pair", "median"),
        median_gross=("gross_on_valid_pair", "median"),
        median_gross_minus_budget=("gross_minus_budget", "median"),
        median_gross_difference_to_budget=("gross_difference_to_budget", "median"),
    ).reset_index()
    # A blank total means we have no reported gross for any film in the bundle.
    bundles["total_reported_gross"] = bundles["total_reported_gross"].where(bundles["films_with_gross"].gt(0))
    bundles["collection_name"] = bundles["collection_id"].map(collection_names)
    bundles["film_evidence"] = "Multiple films"
    bundles.loc[bundles["films"].eq(1), "film_evidence"] = "Based on one film"
    return bundles


def rank_window(
    scored: pd.DataFrame, bundles: pd.DataFrame, *, reach_first: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ranked eligible bundles and standalones, in that order."""
    # Require a score for every observed bundle film. A one-film bundle can qualify.
    eligible_bundles = bundles.loc[bundles["scored_films"].eq(bundles["films"])]
    eligible_standalones = scored.loc[scored["collection_id"].isna() & scored["adjusted_rating"].notna()]
    bundle_order = ["median_adjusted_rating", "lowest_adjusted_rating", "median_votes", "collection_id"]
    standalone_order = ["adjusted_rating", "vote_count", "movie_id"]
    # The reach test changes the sort order. Scores and eligibility stay the same.
    if reach_first:
        bundle_order = ["median_votes", "median_adjusted_rating", "lowest_adjusted_rating", "collection_id"]
        standalone_order = ["vote_count", "adjusted_rating", "movie_id"]
    return (
        _rank_candidates(eligible_bundles, bundle_order),
        _rank_candidates(eligible_standalones, standalone_order),
    )


def describe_rating_gap(bundle_scores: pd.Series, standalone_scores: pd.Series) -> dict[str, int | float]:
    # Use the same summary when each row is a bundle and when each row is a film.
    bundle_quartiles = bundle_scores.quantile([0.25, 0.50, 0.75])
    standalone_quartiles = standalone_scores.quantile([0.25, 0.50, 0.75])
    return {
        "bundle_units": len(bundle_scores),
        "standalone_units": len(standalone_scores),
        "bundle_median": bundle_quartiles.loc[0.50],
        "bundle_q1": bundle_quartiles.loc[0.25],
        "bundle_q3": bundle_quartiles.loc[0.75],
        "standalone_median": standalone_quartiles.loc[0.50],
        "standalone_q1": standalone_quartiles.loc[0.25],
        "standalone_q3": standalone_quartiles.loc[0.75],
        "rating_gap": bundle_quartiles.loc[0.50] - standalone_quartiles.loc[0.50],
    }


def compare_decision_units(
    bundles: pd.DataFrame, standalones: pd.DataFrame, *, possible_duplicates: bool,
) -> dict[str, int | float | str]:
    """Give each eligible option one score and compare the two group medians."""
    # Sorting by ID keeps the same seed tied to the same options if rows are reordered.
    bundle_scores = bundles.sort_values("collection_id")["median_adjusted_rating"]
    standalone_scores = standalones.sort_values("movie_id")["adjusted_rating"]
    result: dict[str, int | float | str] = {**describe_rating_gap(bundle_scores, standalone_scores)}
    result.update(
        bundle_films=int(bundles["films"].sum()),
        interval_low=np.nan,
        interval_high=np.nan,
        conclusion=INSUFFICIENT_EVIDENCE,
    )
    if min(len(bundle_scores), len(standalone_scores)) < COMPARISON_MINIMUM:
        return result

    # Each draw uses the original group size. Only the films or bundles drawn can repeat.
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    bundle_samples = rng.choice(bundle_scores.to_numpy(dtype=float), size=(BOOTSTRAP_DRAWS, len(bundle_scores)))
    standalone_samples = rng.choice(
        standalone_scores.to_numpy(dtype=float), size=(BOOTSTRAP_DRAWS, len(standalone_scores)),
    )
    gaps = np.median(bundle_samples, axis=1) - np.median(standalone_samples, axis=1)
    low, high = np.quantile(gaps, [0.025, 0.975])
    # Favor a group only when the entire range clears the practical margin.
    result.update(interval_low=float(low), interval_high=float(high))
    conclusion = INSUFFICIENT_EVIDENCE
    if low > COMPARISON_MARGIN:
        conclusion = "Favors bundles"
    elif high < -COMPARISON_MARGIN:
        conclusion = "Favors standalones"
    # A flagged release can affect eligibility or the balance of evidence in this window.
    if conclusion != INSUFFICIENT_EVIDENCE and possible_duplicates:
        conclusion = "Provisional — " + conclusion.lower()
    result["conclusion"] = conclusion
    return result


def omit_best_bundle_films(
    scored: pd.DataFrame, eligible_bundles: pd.DataFrame, collection_names: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the films removed and the bundle summaries for the films left."""
    # Start with the eligible bundles so this check cannot add new options.
    members = scored.loc[scored["collection_id"].isin(eligible_bundles["collection_id"])]
    # Use the lowest numeric movie ID if two films share the highest score.
    removed = members.sort_values(
        ["adjusted_rating", "movie_id"], ascending=[False, True],
    ).drop_duplicates("collection_id")
    remaining = members.loc[~members["movie_id"].isin(removed["movie_id"])]
    return removed, summarize_bundles(remaining, collection_names)
