"""Genre context and repeat-credit evidence behind the recommendation."""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from streamvault.diagnostics import raise_for_failed_checks, run_data_checks
from streamvault.normalize import MovieTables


GENRE_SUMMARY_MINIMUM = 10
GENRE_MODEL_MINIMUM = 15
TALENT_TITLE_MINIMUM = 3
TALENT_GROUP_MINIMUM = 2
_PERSON_ROLE = ["role", "person_id"]
_FILM_GROUP = ["standalone_group", "group_id"]


@dataclass
class TalentEvidence:
    """Keep the compact coverage, detailed tables, and check results together."""

    coverage: pd.DataFrame
    people: dict[str, pd.DataFrame]
    benchmarks: pd.DataFrame
    genres: dict[str, pd.DataFrame]
    genre_overlaps: dict[str, pd.DataFrame]
    checks: pd.DataFrame


def _fit_film_benchmark(
    films: pd.DataFrame, genre_flags: pd.DataFrame, outcome: str,
) -> tuple[pd.Series, pd.Series, dict[str, int | float | str]]:
    """Fit on other film groups and measure the difference for each held-aside film."""
    # Use the same complete films with and without tags so model errors are comparable.
    sample = films.dropna(subset=[outcome, "log_budget", "release_year"])
    controls = sample[["log_budget", "release_year", "standalone_group"]].astype(float)
    controls = controls.loc[:, controls.nunique().gt(1)]
    tags = genre_flags.loc[sample.index]
    in_genre = tags.sum()
    tag_ids = in_genre.index[in_genre.ge(GENRE_MODEL_MINIMUM) & in_genre.lt(len(sample))]
    # String labels keep all model features in the same format.
    with_tags = controls.join(tags[tag_ids].add_prefix("genre_"), validate="one_to_one")
    groups = pd.MultiIndex.from_frame(sample[["standalone_group", "group_id"]])
    group_codes, group_values = pd.factorize(groups, sort=True)
    result: dict[str, int | float | str] = {
        "benchmark_films": 0, "available_films": len(sample), "groups": len(group_values),
        "genre_terms": 0, "controls_error": np.nan, "genre_error": np.nan,
        "benchmark": "Too few films or groups",
    }
    empty_residuals = pd.Series(np.nan, index=films.index, dtype=float)
    empty_genre_effects = pd.Series(dtype=float)
    if len(group_values) < 2 or controls.shape[1] == 0:
        return empty_residuals, empty_genre_effects, result

    # Keep franchises together so the model cannot learn from another installment in the held-aside group.
    folds = list(GroupKFold(n_splits=min(5, len(group_values))).split(controls, groups=group_codes))
    smallest_training_set = min(len(train) for train, _ in folds)
    if smallest_training_set <= controls.shape[1] + 1:
        return empty_residuals, empty_genre_effects, result

    # A small Ridge penalty keeps overlapping terms from pulling estimates to extremes.
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    actual = sample[outcome].astype(float)
    control_residuals = actual - cross_val_predict(model, controls, actual, cv=folds)
    result.update(
        benchmark_films=len(sample), controls_error=control_residuals.abs().mean(), benchmark="Controls only",
    )
    if tag_ids.empty or smallest_training_set <= with_tags.shape[1] + 1:
        return control_residuals, empty_genre_effects, result

    residuals = actual - cross_val_predict(model, with_tags, actual, cv=folds)
    # Fit once on the full sample to describe the genre terms in their original units.
    model.fit(with_tags, actual)
    slopes = model[-1].coef_ / model[0].scale_
    genre_effects = pd.Series(slopes[-len(tag_ids):], index=tag_ids)
    result.update(genre_terms=len(tag_ids), genre_error=residuals.abs().mean(), benchmark="Controls and genres")
    return residuals, genre_effects, result


def _summarize_talent(credits: pd.DataFrame) -> pd.DataFrame:
    """Count each person's film groups and test the gap after removing the largest group."""
    # The same number can be a collection ID and a movie ID. Keep the type in the group key.
    groups = credits.groupby(_PERSON_ROLE + _FILM_GROUP).agg(
        group_films=("movie_id", "size"), group_label=("group_label", "first"),
    ).reset_index()
    summary = groups.groupby(_PERSON_ROLE).agg(
        films=("group_films", "sum"), groups=("group_id", "size"),
        standalone_films=("standalone_group", "sum"),
    )
    summary["collections"] = summary["groups"] - summary["standalone_films"]

    # Remove the largest group. In a tie pick a collection first, then the lowest numeric ID.
    largest = groups.sort_values(
        ["group_films", *_FILM_GROUP], ascending=[False, True, True],
    ).drop_duplicates(_PERSON_ROLE).set_index(_PERSON_ROLE).rename(columns={
        "group_films": "removed_films", "standalone_group": "removed_standalone",
        "group_id": "removed_group_id", "group_label": "removed_group",
    })
    summary = summary.join(largest, validate="one_to_one")
    marked = credits.join(
        largest[["removed_standalone", "removed_group_id"]], on=_PERSON_ROLE, validate="many_to_one",
    )
    omitted = marked["standalone_group"].eq(marked["removed_standalone"]) & marked["group_id"].eq(
        marked["removed_group_id"]
    )

    for outcome, prefix in (("adjusted_rating", "rating"), ("log_gross", "gross")):
        gap = f"{outcome}_gap"
        evidence = marked.loc[marked[gap].notna()]
        before = evidence.groupby(_PERSON_ROLE)[gap].agg(["count", "median"])
        after = marked.loc[~omitted].groupby(_PERSON_ROLE)[gap].agg(["count", "median"])
        evidence_groups = evidence.drop_duplicates(_PERSON_ROLE + _FILM_GROUP).groupby(_PERSON_ROLE).size()
        summary[f"{prefix}_films"] = before["count"].reindex(summary.index, fill_value=0)
        summary[f"{prefix}_films_left"] = after["count"].reindex(summary.index, fill_value=0)
        summary[f"{prefix}_before"] = before["median"]
        summary[f"{prefix}_after"] = after["median"]
        # A person's credits can cover multiple groups even when a measure only covers one.
        outcome_groups = evidence_groups.reindex(summary.index, fill_value=0)

        # Ignore numerical noise at zero when checking whether the gap survives.
        original = summary[f"{prefix}_before"]
        remaining = summary[f"{prefix}_after"]
        original_near_zero = np.isclose(original, 0, atol=1e-9)
        remaining_near_zero = np.isclose(remaining, 0, atol=1e-9)
        summary[f"{prefix}_signal"] = np.select(
            [
                summary["films"].lt(TALENT_TITLE_MINIMUM),
                summary["groups"].lt(TALENT_GROUP_MINIMUM),
                summary[f"{prefix}_films"].lt(TALENT_TITLE_MINIMUM),
                outcome_groups.lt(TALENT_GROUP_MINIMUM),
                summary[f"{prefix}_films_left"].lt(2),
                original_near_zero,
                remaining_near_zero,
                np.sign(remaining).ne(np.sign(original)),
                original.gt(0),
            ],
            [
                "Fewer than 3 credited films", "One franchise only",
                "Fewer than 3 benchmarked films", "Benchmarks cover one group",
                "Fragile: fewer than 2 films left", "No gap",
                "Fragile: gap disappears", "Fragile: gap reverses", "Above benchmark in both checks",
            ],
            default="Below benchmark in both checks",
        )
    return summary


def review_talent(
    tables: MovieTables,
    scored_windows: Mapping[str, pd.DataFrame],
    collection_names: pd.Series,
) -> TalentEvidence:
    """Compare film outcomes with similar films and check repeated credits in both windows."""
    genre_names = tables.genres.set_index("genre_id")["genre_name"]
    person_names = tables.people.set_index("person_id")["name"]
    genre_membership = pd.crosstab(tables.movie_genres["movie_id"], tables.movie_genres["genre_id"])

    # Cast roles use TMDB's billing order. Missing values and booleans cannot mark a lead.
    raw_order = tables.cast_credits["order"]
    cast_order = pd.to_numeric(raw_order, errors="coerce").where(
        ~raw_order.astype("string").isin(["True", "False"])
    )
    director_credits = tables.crew_credits.loc[
        tables.crew_credits["job"].eq("Director"), ["movie_id", "person_id"]
    ].assign(role="Director")
    lead_cast_credits = tables.cast_credits.loc[
        cast_order.isin([0, 1, 2]), ["movie_id", "person_id"]
    ].assign(role="Lead cast")
    talent_links = pd.concat([director_credits, lead_cast_credits], ignore_index=True).drop_duplicates(
        ["movie_id", "person_id", "role"]
    )

    # Verify stable IDs before using the links to count films or people.
    link_checks = {}
    for label, links, key, reference in (
        ("Genre", tables.movie_genres, "genre_id", genre_names),
        ("Talent", talent_links, "person_id", person_names),
    ):
        broken = links.loc[~links["movie_id"].isin(tables.movies["movie_id"]) | ~links[key].isin(reference.index)]
        link_checks[f"{label} links point to known films and reference IDs"] = (
            broken.empty and reference.index.is_unique,
            f"{len(broken)} unmatched links from {len(links)}. Example movie IDs: {broken['movie_id'].head(5).tolist()}",
        )

    link_stage = "Before joining film genre and talent evidence"
    link_report = run_data_checks(link_stage, link_checks)
    raise_for_failed_checks(link_stage, link_report)

    outcomes = {
        "adjusted_rating": "Audience rating",
        "log_gross": "Log gross",
    }
    genre_summaries = {}
    genre_overlaps = {}
    benchmark_rows = []
    benchmark_checks = {}
    talent_summaries = {}
    talent_coverage_rows = []

    for window, scored in scored_windows.items():
        # Keep one row per film. Use a separate genre flag column for each overlapping tag.
        films = scored.set_index("movie_id").sort_index()
        genre_flags = genre_membership.reindex(index=films.index, fill_value=0).astype(int)
        genre_flags = genre_flags.loc[:, genre_flags.any()]
        genre_counts = genre_flags.sum().rename("films")
        # Multiplying the flags counts shared films, including an empty window with no tags.
        flags_array = genre_flags.to_numpy(dtype=int)
        genre_overlaps[window] = pd.DataFrame(
            flags_array.T @ flags_array, index=genre_flags.columns, columns=genre_flags.columns,
        )
        summary = genre_counts.to_frame()
        summary["genre"] = summary.index.map(genre_names)
        # A standalone is its own group. The type keeps its ID distinct from a collection ID.
        films["standalone_group"] = films["collection_id"].isna()
        films["group_id"] = films["collection_id"].fillna(films.index.to_series())
        # The model reuses the checked dollar amounts from scoring.
        films["log_budget"] = np.log10(films["reported_budget"])
        films["log_gross"] = np.log10(films["reported_gross"])

        for outcome, label in outcomes.items():
            gap, effects, details = _fit_film_benchmark(films, genre_flags, outcome)
            films[f"{outcome}_gap"] = gap
            summary[f"{outcome}_genre_term"] = effects
            benchmark_rows.append({
                "window": window, "outcome": label, "window_films": len(films),
                "films_with_outcome": int(films[outcome].count()), **details,
            })

        # Joining the links here is only for counts and medians within each genre.
        genre_films = tables.movie_genres.merge(
            films[["adjusted_rating", "reported_gross"]], left_on="movie_id", right_index=True,
            how="inner", validate="many_to_one",
        )
        coverage = genre_films.groupby("genre_id").agg(
            scored_films=("adjusted_rating", "count"),
            median_rating=("adjusted_rating", "median"),
            gross_films=("reported_gross", "count"),
            median_gross=("reported_gross", "median"),
        )
        summary = summary.join(coverage, validate="one_to_one")
        summary["median_rating"] = summary["median_rating"].where(summary["scored_films"].ge(GENRE_SUMMARY_MINIMUM))
        summary["median_gross"] = summary["median_gross"].where(summary["gross_films"].ge(GENRE_SUMMARY_MINIMUM))
        genre_summaries[window] = summary
        benchmark_checks[f"{window}: The benchmark keeps the right film rows and inputs"] = (
            films.index.is_unique and set(films.index) == set(scored["movie_id"])
            and genre_flags.isin([0, 1]).all().all()
            and all(
                not (films[f"{outcome}_gap"].notna() & films[[outcome, "log_budget", "release_year"]].isna().any(axis=1)).any()
                and np.isfinite(films[f"{outcome}_gap"].dropna()).all()
                for outcome in outcomes
            ),
            f"{len(films)} film rows and {len(genre_counts)} observed genre tags",
        )

        # Use movie and collection names for display. All grouping and joins use IDs.
        # An empty collection lookup can return an integer column. Both sources are names here.
        group_labels = films["collection_id"].map(collection_names).astype("string").where(
            ~films["standalone_group"], films["title"].astype("string"),
        )
        group_labels = group_labels.fillna("ID " + films["group_id"].astype("string"))
        credits = talent_links.merge(
            films.assign(group_label=group_labels)[[
                *_FILM_GROUP, "group_label", "adjusted_rating_gap", "log_gross_gap",
            ]], left_on="movie_id", right_index=True, how="inner", validate="many_to_one",
        )
        summary = _summarize_talent(credits)
        summary["name"] = summary.index.get_level_values("person_id").map(person_names)
        talent_summaries[window] = summary
        credited_per_role = credits.groupby("role")["movie_id"].nunique()
        for role in ("Director", "Lead cast"):
            people = summary.loc[
                summary.index.get_level_values("role") == role
            ]
            enough_titles = people["films"].ge(TALENT_TITLE_MINIMUM)
            talent_coverage_rows.append({
                "window": window, "role": role,
                "films_with_credits": int(credited_per_role.get(role, 0)),
                "films_without_credits": len(films) - int(credited_per_role.get(role, 0)),
                "people": len(people), "people_with_three_films": int(enough_titles.sum()),
                "three_films_one_group": int((enough_titles & people["groups"].eq(1)).sum()),
                "eligible_across_groups": int((enough_titles & people["groups"].ge(TALENT_GROUP_MINIMUM)).sum()),
                "rating_above_both": int(people["rating_signal"].eq("Above benchmark in both checks").sum()),
            })
        expected_links = talent_links["movie_id"].isin(films.index).sum()
        benchmark_checks[f"{window}: Talent keeps one credit per film, person, and role"] = (
            len(credits) == expected_links
            and not credits.duplicated(["movie_id", *_PERSON_ROLE]).any()
            and summary["films"].sum() == expected_links
            and summary["removed_films"].le(summary["films"]).all(),
            f"{len(credits)} film-person-role links from {len(films)} films",
        )

    talent_coverage = pd.DataFrame(talent_coverage_rows)
    analysis_stage = "After preparing genre and talent summaries"
    analysis_report = run_data_checks(analysis_stage, benchmark_checks)
    raise_for_failed_checks(analysis_stage, analysis_report)

    return TalentEvidence(
        coverage=talent_coverage,
        people=talent_summaries,
        benchmarks=pd.DataFrame(benchmark_rows),
        genres=genre_summaries,
        genre_overlaps=genre_overlaps,
        checks=pd.concat([link_report, analysis_report], ignore_index=True),
    )
