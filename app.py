"""Run StreamVault and compare saved reports in the local browser."""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from threading import Lock
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from openpyxl.utils.exceptions import InvalidFileException
import pandas as pd
import streamlit as st

from streamvault.config import CONFIG
from streamvault.fetch_movies import MissingTokenError
from streamvault.main import run
from streamvault.recommendation import ON_SHORTLIST
from streamvault.recommendation_inputs import ALL_YEARS, RECENT


WINDOWS = (ALL_YEARS, RECENT)


@dataclass(frozen=True)
class SavedRun:
    recorded_at: datetime
    conclusions: dict[str, str]
    rankings: pd.DataFrame


@st.cache_resource
def pipeline_lock() -> Lock:
    # Browser tabs share one movie cache, so let only one app run update it at a time.
    return Lock()


def prepare_download(name: str, contents: bytes) -> tuple[str, bytes]:
    with TemporaryDirectory(prefix="streamvault-") as directory:
        workspace = Path(directory)
        source = workspace / "input" / PureWindowsPath(name).name
        source.parent.mkdir()
        source.write_bytes(contents)
        # Keep the upload and its row log separate from the CLI's working files.
        config = replace(CONFIG, source_file=source, removals_file=workspace / "row-removals.csv")
        with pipeline_lock():
            analysis = asyncio.run(run(config, output_dir=workspace / "reports"))

        # Keep the finished ZIP in the browser session so downloading never runs the pipeline again.
        download = BytesIO()
        with ZipFile(download, "w", compression=ZIP_DEFLATED) as archive:
            archive.write(source, f"input/{source.name}")
            if config.removals_file.is_file():
                archive.write(config.removals_file, "row-removals.csv")
            # Include only the reports from this run in the download.
            for report in (
                analysis.directory / "recommendation.md", analysis.rankings_path,
                analysis.exclusions_path, analysis.directory / "run.json",
            ):
                archive.write(report, report.name)
        return analysis.summary, download.getvalue()


def clear_result() -> None:
    st.session_state.pop("result", None)


def read_saved_run(contents: bytes) -> SavedRun:
    """Read the decision and ranks from an app download without unpacking it to disk."""
    try:
        with ZipFile(BytesIO(contents)) as archive:
            # A 500-title report is well below these limits. Check before opening compressed data.
            run_file = archive.getinfo("run.json")
            rankings_file = archive.getinfo("rankings.xlsx")
            if max(run_file.file_size, rankings_file.file_size) > 8 * 1024**2:
                raise ValueError("Report files are too large.")
            record = json.loads(archive.read(run_file))
            workbook = archive.read(rankings_file)
        if record["rankings_sha256"] != sha256(workbook).hexdigest():
            raise ValueError("The workbook does not match the run record.")
        with ZipFile(BytesIO(workbook)) as spreadsheet:
            if sum(member.file_size for member in spreadsheet.infolist()) > 32 * 1024**2:
                raise ValueError("The workbook is too large.")

        recorded_at = datetime.fromisoformat(record["recorded_at_utc"])
        if recorded_at.tzinfo is None:
            raise ValueError("The run timestamp has no time zone.")
        baseline = {
            row["window"]: row["conclusion"] for row in record["comparison_results"] if row["scenario"] == "Baseline"
        }
        conclusions = {window: baseline[window] for window in WINDOWS}
        sheets = pd.read_excel(
            BytesIO(workbook), engine="openpyxl", sheet_name=["Bundles", "Standalones"],
            dtype={"Collection ID": str, "Movie ID": str}, keep_default_na=False,
        )
        rankings = []
        for sheet, kind, id_column, title_column in (
            ("Bundles", "Bundle", "Collection ID", "Bundle"),
            ("Standalones", "Standalone", "Movie ID", "Film"),
        ):
            for window in WINDOWS:
                columns = {
                    id_column: "ID", title_column: "Candidate", f"{window} rank": "Rank", f"{window} result": "Result",
                }
                rows = sheets[sheet][list(columns)].rename(columns=columns)
                rows["Rank"] = pd.to_numeric(rows["Rank"].replace("", pd.NA)).astype("Int64")
                if rows["ID"].eq("").any() or rows["ID"].duplicated().any():
                    raise ValueError("Candidate IDs are missing or repeated.")
                rankings.append(rows.assign(Window=window, Type=kind))
    except (BadZipFile, InvalidFileException, KeyError, OSError, RuntimeError, SyntaxError, TypeError, ValueError) as error:
        raise ValueError("Use an intact ZIP from StreamVault's Download reports button.") from error

    return SavedRun(recorded_at, conclusions, pd.concat(rankings).set_index(["Window", "Type", "ID"]))


def compare_shortlists(earlier: SavedRun, later: SavedRun) -> pd.DataFrame:
    """Show rank changes involving a shortlist spot, matched by ID within each window and type."""
    rows = earlier.rankings.join(later.rankings, how="outer", lsuffix=" earlier", rsuffix=" later", validate="one_to_one")
    picked_earlier = rows["Result earlier"].eq(ON_SHORTLIST).fillna(False)
    picked_later = rows["Result later"].eq(ON_SHORTLIST).fillna(False)
    # Keep the saved rank on either side, including when the candidate ranked below the shortlist.
    rows["Change"] = ""
    rows.loc[picked_earlier & ~picked_later, "Change"] = "Left shortlist"
    rows.loc[~picked_earlier & picked_later, "Change"] = "Entered shortlist"
    in_both = picked_earlier & picked_later
    rows.loc[in_both & rows["Rank later"].lt(rows["Rank earlier"]), "Change"] = "Moved up"
    rows.loc[in_both & rows["Rank later"].gt(rows["Rank earlier"]), "Change"] = "Moved down"
    rows["Candidate"] = rows["Candidate later"].combine_first(rows["Candidate earlier"])
    columns = ["Window", "Type", "Candidate", "Rank earlier", "Rank later", "Change"]
    return rows.loc[rows["Change"].ne("")].reset_index()[columns]


def render_recommendation() -> None:
    uploaded = st.file_uploader(
        "Candidate list", type="csv", help="Use a CSV with one column named tmdb_id.",
        on_change=clear_result,
    )
    run_clicked = st.button("Run recommendation", type="primary", disabled=uploaded is None)
    if uploaded is not None and run_clicked:
        clear_result()
        with st.spinner("Checking the candidate list and preparing reports…"):
            try:
                st.session_state.result = prepare_download(uploaded.name, uploaded.getvalue())
            except MissingTokenError:
                st.error("New movies need a TMDB read access token. Set it in .env and restart the app.")
            except (OSError, ValueError) as error:
                st.error(f"StreamVault could not finish this run. {error}")

    if "result" in st.session_state:
        summary, download = st.session_state.result
        st.download_button(
            "Download reports", download, file_name="streamvault-reports.zip",
            mime="application/zip", on_click="ignore", type="primary",
        )
        st.markdown(summary)


def render_comparison() -> None:
    st.caption("Upload the ZIP saved from each review to see what changed.")
    earlier_column, later_column = st.columns(2)
    with earlier_column:
        earlier_file = st.file_uploader("Earlier reports ZIP", type="zip")
    with later_column:
        later_file = st.file_uploader("Later reports ZIP", type="zip")
    if earlier_file is None or later_file is None:
        return
    try:
        earlier = read_saved_run(earlier_file.getvalue())
        later = read_saved_run(later_file.getvalue())
    except ValueError as error:
        st.error(str(error))
        return
    if earlier.recorded_at > later.recorded_at:
        st.error("Put the older run in Earlier reports ZIP.")
        return

    earlier_date = earlier.recorded_at.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    later_date = later.recorded_at.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    st.caption(f"Earlier run {earlier_date} · Later run {later_date}")
    st.subheader("Recommendation by release window")
    decisions = pd.DataFrame({
        "Window": WINDOWS, "Earlier": [earlier.conclusions[window] for window in WINDOWS],
        "Later": [later.conclusions[window] for window in WINDOWS],
    })
    st.table(decisions, hide_index=True)
    st.subheader("Shortlist changes")
    changes = compare_shortlists(earlier, later)
    if changes.empty:
        st.info("The shortlisted titles and their ranks stayed the same.")
    else:
        st.dataframe(changes, hide_index=True)


def render_output_guide() -> None:
    st.subheader("What’s in your download?")
    st.html("""
        <div class="sv-output-grid">
            <article class="sv-output-card">
                <h3>Recommendation</h3>
                <code>recommendation.md</code>
                <p>Start here for which deals to pursue first, the shortlists for both release windows,
                and what the evidence can support.</p>
            </article>
            <article class="sv-output-card">
                <h3>Rankings workbook</h3>
                <code>rankings.xlsx</code>
                <p>Use the Bundles and Standalones tabs to see how each option ranked across both windows.
                Filter a result column to Shortlisted to see the picks.</p>
            </article>
            <article class="sv-output-card">
                <h3>Exclusions report</h3>
                <code>recommendation_exclusions.md</code>
                <p>Check which entries were left out, why they were left out, and which films need review.</p>
            </article>
            <article class="sv-output-card">
                <h3>Run record</h3>
                <code>run.json</code>
                <p>Keep this with the workbook. It records the inputs, settings, checks, and timing,
                and the app uses it when you compare saved runs.</p>
            </article>
        </div>
    """)
    st.write("The ZIP also includes the CSV you uploaded and a row removal log when there are rows to log.")
    st.info("Save the whole ZIP for your next review. You can upload it directly in Compare saved runs.")


def render_page() -> None:
    st.set_page_config(page_title="StreamVault recommendations")
    # Scope the styles to the page header and guide so Streamlit keeps its native controls.
    st.html("""
        <style>
            .sv-header {
                background: linear-gradient(120deg, #163044, #146659);
                border-radius: 1.15rem;
                padding: clamp(1.25rem, 5vw, 2.35rem);
                margin-bottom: .75rem;
            }
            .sv-header h1 {
                color: #fff;
                font-size: clamp(1.8rem, 5vw, 2.9rem);
                line-height: 1.05;
                margin: 0 0 .65rem;
                padding: 0;
            }
            .sv-header p { color: #e6f7f3; margin: 0; }
            .sv-output-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
                gap: .85rem;
            }
            .sv-output-card {
                background: #fff;
                color: #162d38;
                border: 1px solid #d5e2de;
                border-top: 4px solid #087867;
                border-radius: .75rem;
                min-width: 0;
                padding: 1rem;
            }
            .sv-output-card:nth-child(2) { border-top-color: #396ba9; }
            .sv-output-card:nth-child(3) { border-top-color: #ab651d; }
            .sv-output-card:nth-child(4) { border-top-color: #73509b; }
            .sv-output-card h3 { color: inherit; font-size: 1.1rem; padding: 0; margin: 0 0 .35rem; }
            .sv-output-card code { color: #234b50; background: #e8f2ef; overflow-wrap: anywhere; }
            .sv-output-card p { color: inherit; margin: .6rem 0 0; }
        </style>
        <header class="sv-header">
            <h1>StreamVault recommendations</h1>
            <p>Run a candidate list, review the picks, or compare two saved reviews.</p>
        </header>
    """)
    recommendation, comparison, outputs = st.tabs(["Run recommendation", "Compare saved runs", "Output guide"])
    with recommendation:
        render_recommendation()
    with comparison:
        render_comparison()
    with outputs:
        render_output_guide()


if __name__ == "__main__":
    render_page()
