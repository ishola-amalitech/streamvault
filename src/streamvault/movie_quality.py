"""Find film-level issues that need to be shown with the analysis."""

import pandas as pd


POSSIBLE_DUPLICATE = "Possible duplicate film"


def rating_inputs(films: pd.DataFrame) -> pd.DataFrame:
    """Return usable rating inputs and a reason for each missing or invalid value."""
    raw = films.reindex(columns=["vote_average", "vote_count"])
    # Convert through text so true or false cannot become a vote count or rating.
    rating = pd.to_numeric(raw["vote_average"].astype("string"), errors="coerce")
    votes = pd.to_numeric(raw["vote_count"].astype("string"), errors="coerce")
    valid_rating = rating.between(0, 10).fillna(False)
    valid_vote_range = votes.between(0, float("inf"), inclusive="left").fillna(False)
    valid_votes = votes.where(valid_vote_range).mod(1).eq(0).fillna(False)

    blank_reason = pd.Series("", index=raw.index, dtype="string")
    rating_issue = blank_reason.mask(~valid_rating, "Invalid rating")
    vote_count_issue = blank_reason.mask(~valid_votes, "Invalid vote count")
    return pd.DataFrame({
        "vote_average": rating.where(valid_rating),
        "vote_count": votes.where(valid_votes),
        "rating_issue": rating_issue.mask(raw["vote_average"].isna(), "Missing rating"),
        "vote_count_issue": vote_count_issue.mask(raw["vote_count"].isna(), "Missing vote count"),
    })


def film_quality_issues(movies: pd.DataFrame) -> pd.DataFrame:
    """List the films Adjoa should review, with one row for each issue."""
    films = movies.reindex(columns=[
        "movie_id", "title", "release_date", "status", "vote_average", "vote_count",
        "budget", "revenue",
    ]).copy()
    # Use the same release scope as the analysis when checking scoring inputs.
    dates = pd.to_datetime(films["release_date"])
    released = films["status"].astype("string").eq("Released").fillna(False)
    in_scope = dates.notna() & released
    inputs = rating_inputs(films.loc[in_scope])
    identities = films[["movie_id", "title"]].assign(release_year=dates.dt.year.astype("Int64"))
    issues: list[pd.DataFrame] = []

    for field, label in (("release_date", "release date"), ("status", "release status")):
        issues.append(identities.loc[films[field].isna()].assign(
            issue=f"Missing {label}", impact="Outside both release windows",
        ))

    for column in ("rating_issue", "vote_count_issue"):
        reasons = inputs.loc[inputs[column].ne(""), column]
        issues.append(identities.loc[reasons.index].assign(
            issue=reasons, impact="Film cannot be scored and can make its bundle ineligible",
        ))

    for field, label, impact in (
        ("budget", "production budget", "Excluded from calculations that need budget"),
        ("revenue", "box office gross", "Excluded from calculations that need gross"),
    ):
        amounts = films[field]
        values = pd.to_numeric(amounts.astype("string"), errors="coerce")
        invalid = amounts.notna() & ~values.between(0, float("inf"), inclusive="left").fillna(False)
        reason = pd.Series("", index=films.index, dtype="string")
        reason = reason.mask(amounts.isna(), f"Missing {label}")
        reason = reason.mask(invalid, f"Invalid {label}")
        reason = reason.mask(values.eq(0).fillna(False), f"Zero {label}")
        affected = reason.ne("")
        issues.append(identities.loc[affected].assign(issue=reason.loc[affected], impact=impact))

    # A title and year match is a review lead. Keep every ID, including remakes and reissues.
    matching_keys = pd.DataFrame({
        "title": films["title"].astype("string").str.strip().str.casefold().str.replace(
            r"\s+", " ", regex=True,
        ),
        "year": identities["release_year"],
    })
    matching_keys = matching_keys.loc[matching_keys["title"].fillna("").ne("")].dropna()
    possible = matching_keys.index[matching_keys.duplicated(keep=False)]
    issues.append(identities.loc[possible].assign(
        issue=POSSIBLE_DUPLICATE,
        impact="Shared title and release year. Review before relying on rankings.",
    ))

    return pd.concat(issues, ignore_index=True).sort_values(
        ["movie_id", "issue"], ignore_index=True,
    )
