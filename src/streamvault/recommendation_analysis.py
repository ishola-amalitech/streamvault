"""Run the audience recommendation and scoring tests for both release windows."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from streamvault.diagnostics import raise_for_failed_checks, run_data_checks
from streamvault.movie_quality import POSSIBLE_DUPLICATE
from streamvault.recommendation import (
    ANCHOR_RATING,
    ANCHOR_VOTES,
    BUNDLE_TARGET,
    COMPARISON_MINIMUM,
    INSUFFICIENT_EVIDENCE,
    MINIMUM_VOTES,
    ON_SHORTLIST,
    STANDALONE_TARGET,
    compare_decision_units,
    describe_rating_gap,
    omit_best_bundle_films,
    rank_window,
    score_films,
    summarize_bundles,
)
from streamvault.recommendation_inputs import ALL_YEARS, RECENT, RecommendationInputs


# Save the baseline settings with the alternatives so the tests can be repeated.
SCENARIOS = {
    "Baseline": {},
    "Reach first": {"reach_first": True},
    "At least 500 votes": {"minimum_votes": 500},
    "At least 5,000 votes": {"minimum_votes": 5_000},
    "6.5 rating anchor": {"anchor_rating": 6.5},
}
BASELINE_SETTINGS = {
    "minimum_votes": MINIMUM_VOTES, "anchor_rating": ANCHOR_RATING, "anchor_votes": ANCHOR_VOTES,
}


@dataclass
class Recommendation:
    """Film and bundle rankings, comparisons, and exclusion reasons by window."""

    scored_windows: dict[str, pd.DataFrame]
    bundle_summaries: dict[str, pd.DataFrame]
    ranked_bundles: dict[str, pd.DataFrame]
    ranked_standalones: dict[str, pd.DataFrame]
    bundle_shortlists: dict[str, pd.DataFrame]
    standalone_shortlists: dict[str, pd.DataFrame]
    shortlisted_bundle_films: dict[str, pd.DataFrame]
    windows_with_duplicates: dict[str, bool]
    window_evidence: pd.DataFrame
    decision_comparison: pd.DataFrame
    film_comparison: pd.DataFrame
    omission_comparison: pd.DataFrame
    omission_details: dict[str, pd.DataFrame]
    film_outcomes: pd.DataFrame
    checks: pd.DataFrame


@dataclass
class ScoringTests:
    """How the decision and picks respond to different rules."""

    leaders: pd.DataFrame
    comparisons: pd.DataFrame
    shortlist_changes: pd.DataFrame
    gross_comparison: pd.DataFrame


def recommend(
    inputs: RecommendationInputs, record_stage_time: Callable[[str], None],
) -> Recommendation:
    """Apply the same scoring and comparison rules to each window."""
    windows = inputs.windows
    collection_names = inputs.collection_names
    quality = inputs.quality_issues
    possible_duplicate_ids = quality.loc[quality["issue"].eq(POSSIBLE_DUPLICATE), "movie_id"]

    # Score both windows with the same rules and keep an explanation for every missing score.
    scored_windows = {
        window: score_films(films)
        for window, films in windows.items()
    }

    score_stage = "After scoring films"
    score_checks = {}
    for window, scored in scored_windows.items():
        # Check that every score has the evidence it needs and every unscored film has a reason.
        has_score = scored["adjusted_rating"].notna()
        votes = scored["vote_count"].where(has_score)
        valid_score = (
            scored["vote_average"].between(0, 10).fillna(False)
            & votes.between(MINIMUM_VOTES, float("inf"), inclusive="left").fillna(False)
            & votes.mod(1).eq(0).fillna(False)
            & scored["adjusted_rating"].between(0, 10).fillna(False)
        )
        reasons = scored["score_exclusion"]
        wrong_reason = reasons.isna() | has_score.ne(reasons.eq("").fillna(False))
        bad_ids = scored.loc[(has_score & ~valid_score) | wrong_reason, "movie_id"]
        score_checks[f"{window}: Scores have valid inputs and exclusions have reasons"] = (
            bad_ids.empty,
            f"{int(has_score.sum())} scored, {int((~has_score).sum())} unscored. "
            f"{len(bad_ids)} issues. Example movie IDs: {bad_ids.head(5).tolist()}",
        )
    score_report = run_data_checks(score_stage, score_checks)
    raise_for_failed_checks(score_stage, score_report)

    bundle_summaries = {}
    ranked_bundles = {}
    ranked_standalones = {}
    bundle_shortlists = {}
    standalone_shortlists = {}
    shortlisted_bundle_films = {}

    for window, scored in scored_windows.items():
        bundles = summarize_bundles(scored, collection_names)
        bundle_summaries[window] = bundles
        ranked_bundles[window], ranked_standalones[window] = rank_window(scored, bundles)
        bundle_shortlists[window] = ranked_bundles[window].head(BUNDLE_TARGET)
        standalone_shortlists[window] = ranked_standalones[window].head(STANDALONE_TARGET)

        # Attach a single bundle rank to each member by ID. A name can belong to multiple collections.
        shortlist_ranks = bundle_shortlists[window].set_index("collection_id")["rank"]
        member_rank = scored["collection_id"].map(shortlist_ranks)
        members = scored.loc[member_rank.notna()].assign(bundle_rank=member_rank.dropna().astype(int))
        shortlisted_bundle_films[window] = members.sort_values(["bundle_rank", "release_date", "movie_id"])

    shortlist_stage = "After ranking candidates and attaching films to shortlisted bundles"
    shortlist_checks = {}
    for window, members in shortlisted_bundle_films.items():
        shortlist = bundle_shortlists[window]
        expected_member_ids = scored_windows[window].loc[
            scored_windows[window]["collection_id"].isin(shortlist["collection_id"]), "movie_id"
        ]
        shortlist_checks[f"{window}: Each shortlisted bundle keeps all its scored films"] = (
            members["movie_id"].is_unique
            and set(members["movie_id"]) == set(expected_member_ids)
            and len(members) == int(shortlist["films"].sum())
            and bool(shortlist["films"].ge(1).all() and members["adjusted_rating"].notna().all()),
            f"{len(members)} member rows, {len(expected_member_ids)} expected, for {len(shortlist)} bundles",
        )
    shortlist_report = run_data_checks(shortlist_stage, shortlist_checks)
    raise_for_failed_checks(shortlist_stage, shortlist_report)

    # Give Adjoa the evidence counts before she relies on a shortlist or comparison.
    coverage_rows = []
    windows_with_duplicates = {}
    for window, films in windows.items():
        bundles = len(ranked_bundles[window])
        standalones = len(ranked_standalones[window])
        duplicate_count = int(films["movie_id"].isin(possible_duplicate_ids).sum())
        windows_with_duplicates[window] = bool(duplicate_count)
        if min(bundles, standalones) < COMPARISON_MINIMUM:
            comparison_status = "Too few options for a firm comparison"
        elif duplicate_count:
            comparison_status = "Provisional pending duplicate review"
        else:
            comparison_status = "Enough options to compare"
        coverage_rows.append({
            "Window": window,
            "Eligible bundles": bundles,
            "Eligible standalones": standalones,
            "Bundle spots unfilled": max(0, BUNDLE_TARGET - bundles),
            "Standalone spots unfilled": max(0, STANDALONE_TARGET - standalones),
            "Films flagged for duplicate review": duplicate_count,
            "Comparison evidence": comparison_status,
        })
    window_evidence = pd.DataFrame(coverage_rows).set_index("Window")

    # Use every eligible option for the main decision, even if it missed the shortlist.
    decision_rows = []
    film_rows = []
    comparison_checks = {}
    for window, scored in scored_windows.items():
        bundles = ranked_bundles[window]
        standalones = ranked_standalones[window]
        has_score = scored["adjusted_rating"].notna()
        linked = scored["collection_id"].notna()

        # A collection with any unscored installment stays out of the main comparison.
        ineligible_ids = scored.loc[linked & ~has_score, "collection_id"]
        eligible_members = scored.loc[linked & ~scored["collection_id"].isin(ineligible_ids)]
        eligible_standalone_ids = scored.loc[~linked & has_score, "movie_id"]
        comparison_checks[f"{window}: The comparison has one row per eligible option"] = (
            bundles["collection_id"].is_unique
            and standalones["movie_id"].is_unique
            and set(bundles["collection_id"]) == set(eligible_members["collection_id"])
            and int(bundles["films"].sum()) == len(eligible_members)
            and set(standalones["movie_id"]) == set(eligible_standalone_ids),
            f"{len(bundles)} bundles covering {len(eligible_members)} films, {len(standalones)} standalones",
        )
        decision_rows.append({"window": window, **compare_decision_units(
            bundles, standalones, possible_duplicates=windows_with_duplicates[window],
        )})
        film_rows.append({
            "window": window,
            **describe_rating_gap(
                scored.loc[linked & has_score, "adjusted_rating"],
                scored.loc[~linked & has_score, "adjusted_rating"],
            ),
        })

    decision_comparison = pd.DataFrame(decision_rows).set_index("window")
    film_comparison = pd.DataFrame(film_rows).set_index("window")
    record_stage_time("Score, rank, and compare eligible options")

    # Remove the best film from each eligible bundle and compare the options that remain.
    omission_rows = []
    omission_details = {}
    for window, scored in scored_windows.items():
        original = ranked_bundles[window].set_index("collection_id")
        removed, reduced = omit_best_bundle_films(scored, ranked_bundles[window], collection_names)
        # Keep a row even when removing the only observed film makes the bundle disappear.
        detail = original[["collection_name", "films", "median_adjusted_rating"]].join(
            removed.set_index("collection_id")[["movie_id", "title", "adjusted_rating"]].rename(columns={
                "movie_id": "removed_movie_id", "title": "removed_title", "adjusted_rating": "removed_score",
            }),
            validate="one_to_one",
        ).join(
            reduced.set_index("collection_id")[["films", "median_adjusted_rating"]].rename(columns={
                "films": "films_left", "median_adjusted_rating": "new_median",
            }),
            validate="one_to_one",
        )
        detail["films_left"] = detail["films_left"].fillna(0).astype(int)
        detail["median_change"] = detail["new_median"] - detail["median_adjusted_rating"]
        omission_details[window] = detail
        comparison_checks[f"{window}: The sensitivity removed one film from each eligible bundle"] = (
            detail["removed_movie_id"].notna().all()
            and detail["removed_movie_id"].is_unique
            and detail["films_left"].eq(detail["films"] - 1).all(),
            f"{len(removed)} films removed from {len(original)} bundles",
        )
        omission_rows.append({
            "window": window,
            **compare_decision_units(
                reduced, ranked_standalones[window], possible_duplicates=windows_with_duplicates[window],
            ),
            "bundles_lost": int(detail["films_left"].eq(0).sum()),
            "bundles_left_with_one": int(detail["films_left"].eq(1).sum()),
        })

    omission_comparison = pd.DataFrame(omission_rows).set_index("window")
    omission_comparison["gap_change"] = omission_comparison["rating_gap"] - decision_comparison["rating_gap"]

    comparison_stage = "After preparing the bundle and standalone comparisons"
    comparison_report = run_data_checks(comparison_stage, comparison_checks)
    raise_for_failed_checks(comparison_stage, comparison_report)
    record_stage_time("Test removing the strongest films")

    film_outcomes = inputs.candidates.reindex(columns=["movie_id", "title"]).copy()
    for window, scored in scored_windows.items():
        bundles = bundle_summaries[window].set_index("collection_id")
        bundle_rank = scored["collection_id"].map(ranked_bundles[window].set_index("collection_id")["rank"])
        standalone_rank = scored["movie_id"].map(ranked_standalones[window].set_index("movie_id")["rank"])
        # Give a film's own scoring problem first. Otherwise explain its bundle or rank.
        reason = scored["score_exclusion"].copy()
        linked = scored["collection_id"].notna()
        good_score = reason.eq("")
        reason.loc[good_score & linked & bundle_rank.isna()] = "Another in-window bundle film could not be scored"
        reason.loc[bundle_rank.gt(BUNDLE_TARGET)] = (
            "Bundle ranked #" + bundle_rank.dropna().astype(int).astype("string")
            + f" (top {BUNDLE_TARGET} selected)"
        )
        one_film_below_cut = bundle_rank.gt(BUNDLE_TARGET) & scored["collection_id"].map(bundles["films"]).eq(1)
        reason.loc[one_film_below_cut] = reason.loc[one_film_below_cut] + ". Based on one film"
        reason.loc[standalone_rank.gt(STANDALONE_TARGET)] = (
            "Standalone ranked #" + standalone_rank.dropna().astype(int).astype("string")
            + f" (top {STANDALONE_TARGET} selected)"
        )
        reason.loc[bundle_rank.le(BUNDLE_TARGET) | standalone_rank.le(STANDALONE_TARGET)] = ON_SHORTLIST

        window_outcome = inputs.release_outcomes[window].copy()
        window_outcome.loc[scored.index] = reason
        film_outcomes[window] = window_outcome

    exclusion_stage = "Before writing the film exclusions report"
    exclusion_checks = {}
    for window in windows:
        outcome = film_outcomes[window]
        accounted_ids = set(film_outcomes.loc[outcome.eq(ON_SHORTLIST), "movie_id"])
        shortlisted_ids = set(shortlisted_bundle_films[window]["movie_id"]) | set(
            standalone_shortlists[window]["movie_id"]
        )
        exclusion_checks[f"{window}: Every film has an outcome that agrees with the shortlist"] = (
            bool(outcome.notna().all() and outcome.ne("").all() and accounted_ids == shortlisted_ids),
            f"{len(accounted_ids)} shortlisted films and {len(outcome) - len(accounted_ids)} films left out",
        )
    exclusion_report = run_data_checks(exclusion_stage, exclusion_checks)
    raise_for_failed_checks(exclusion_stage, exclusion_report)
    record_stage_time("Account for every film's shortlist outcome")

    return Recommendation(
        scored_windows, bundle_summaries, ranked_bundles, ranked_standalones,
        bundle_shortlists, standalone_shortlists, shortlisted_bundle_films,
        windows_with_duplicates, window_evidence, decision_comparison, film_comparison,
        omission_comparison, omission_details, film_outcomes,
        pd.concat([score_report, shortlist_report, comparison_report, exclusion_report], ignore_index=True),
    )


def _shortlist_movement(
    before: pd.DataFrame, after: pd.DataFrame, id_key: str, name_key: str, target: int,
) -> pd.DataFrame:
    # Keep changes involving a shortlist spot and use full ranks to explain entries and exits.
    old = before.set_index(id_key)[["rank", name_key]].rename(columns={"rank": "before"})
    new = after.set_index(id_key)[["rank", name_key]].rename(columns={"rank": "after", name_key: "new_name"})
    movement = old.join(new, how="outer", validate="one_to_one")
    movement[name_key] = movement[name_key].combine_first(movement.pop("new_name"))
    in_before = movement["before"].le(target)
    in_after = movement["after"].le(target)
    relevant = (in_before | in_after) & movement["before"].ne(movement["after"])
    movement["change"] = np.select(
        [~in_before & in_after, in_before & ~in_after], ["Entered", "Left"], default="Moved",
    )
    return movement.loc[relevant].rename(columns={name_key: "name"}).rename_axis("candidate_id").reset_index()


def test_scoring_choices(inputs: RecommendationInputs, results: Recommendation) -> ScoringTests:
    """Check alternative vote rules and show which ranks or decisions changed."""
    windows = inputs.windows
    collection_names = inputs.collection_names
    scored_windows = results.scored_windows
    bundle_summaries = results.bundle_summaries
    ranked_bundles = results.ranked_bundles
    ranked_standalones = results.ranked_standalones
    decision_comparison = results.decision_comparison
    windows_with_duplicates = results.windows_with_duplicates
    omission_comparison = results.omission_comparison

    rating_scenarios = {}
    sensitivity_rows = []
    recommendation_rows = []

    for scenario, changes in SCENARIOS.items():
        settings = BASELINE_SETTINGS | {key: value for key, value in changes.items() if key in BASELINE_SETTINGS}
        reach_first = changes.get("reach_first", False)
        for window, films in windows.items():
            if settings == BASELINE_SETTINGS:
                franchise, standalone = ranked_bundles[window], ranked_standalones[window]
                if reach_first:
                    franchise, standalone = rank_window(
                        scored_windows[window], bundle_summaries[window], reach_first=True,
                    )
                # Changing only the order cannot change the scores or the options we compare.
                comparison = decision_comparison.loc[window].to_dict()
            else:
                scored = score_films(films, **settings)
                bundles = summarize_bundles(scored, collection_names)
                franchise, standalone = rank_window(scored, bundles)
                comparison = compare_decision_units(
                    franchise, standalone, possible_duplicates=windows_with_duplicates[window],
                )
            rating_scenarios[scenario, window] = {"Bundle": franchise, "Standalone": standalone}
            recommendation_rows.append({"scenario": scenario, "window": window, **comparison})

            # Compare leaders by ID. Names are only used in the results table.
            for kind, ranking, baseline, id_key, name_key, target in (
                ("Bundle", franchise, ranked_bundles[window], "collection_id", "collection_name", BUNDLE_TARGET),
                ("Standalone", standalone, ranked_standalones[window], "movie_id", "title", STANDALONE_TARGET),
            ):
                leader = ranking[id_key].iloc[0] if len(ranking) else None
                baseline_id = baseline[id_key].iloc[0] if len(baseline) else None
                status = "Insufficient evidence"
                if leader is not None and baseline_id is not None:
                    status = "Stable" if leader == baseline_id else "Changed"
                sensitivity_rows.append({
                    "scenario": scenario, "window": window, "type": kind, "eligible": len(ranking),
                    "shortlisted": min(len(ranking), target),
                    "leader": ranking[name_key].iloc[0] if len(ranking) else "No eligible option",
                    "leader_status": status,
                })

    # Reuse the comparison that removed the best film from each eligible bundle.
    for window, result in omission_comparison.iterrows():
        recommendation_rows.append({"scenario": "Remove best bundle film", "window": window, **result.to_dict()})

    sensitivity_leaders = pd.DataFrame(sensitivity_rows)
    recommendation_sensitivity = pd.DataFrame(recommendation_rows)
    base_result = recommendation_sensitivity["window"].map(decision_comparison["conclusion"])
    test_result = recommendation_sensitivity["conclusion"]
    recommendation_sensitivity["status"] = np.select(
        [test_result.eq(INSUFFICIENT_EVIDENCE), test_result.eq(base_result)],
        ["Insufficient evidence", "Stable"], default="Changed",
    )

    movement_frames = []
    for kind, id_key, name_key, target in (
        ("Bundle", "collection_id", "collection_name", BUNDLE_TARGET),
        ("Standalone", "movie_id", "title", STANDALONE_TARGET),
    ):
        for (scenario, window), scenario_rankings in rating_scenarios.items():
            if scenario == "Baseline":
                continue
            movement = _shortlist_movement(
                rating_scenarios["Baseline", window][kind], scenario_rankings[kind], id_key, name_key, target,
            )
            movement_frames.append(movement.assign(scenario=scenario, window=window, type=kind))

        # Compare the baseline shortlists across the two release windows as well.
        movement = _shortlist_movement(
            rating_scenarios["Baseline", ALL_YEARS][kind],
            rating_scenarios["Baseline", RECENT][kind], id_key, name_key, target,
        )
        movement_frames.append(movement.assign(scenario="2000 cutoff", window="All years to 2000 onward", type=kind))

    shortlist_changes = pd.concat(movement_frames, ignore_index=True)
    shortlist_changes[["before", "after"]] = shortlist_changes[["before", "after"]].astype("Int64")

    # Keep historical gross separate from the rating tests. Compare the typical film.
    gross_rows = []
    for window, films in scored_windows.items():
        # Compare film by film so a large bundle does not get extra dollars through summing.
        by_type = films.groupby("title_type")["reported_gross"]
        by_type = by_type.agg(["count", "median"]).reindex(["Collection-linked", "Standalone"])
        counts = by_type["count"].fillna(0).astype(int)
        gross_rows.append({
            "window": window,
            "collection_films": int(counts["Collection-linked"]),
            "standalone_films": int(counts["Standalone"]),
            "collection_median": by_type.loc["Collection-linked", "median"],
            "standalone_median": by_type.loc["Standalone", "median"],
        })
    gross_comparison = pd.DataFrame(gross_rows)
    return ScoringTests(sensitivity_leaders, recommendation_sensitivity, shortlist_changes, gross_comparison)
