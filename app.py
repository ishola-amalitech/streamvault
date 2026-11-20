"""Run StreamVault from a candidate CSV uploaded in the local browser."""

import asyncio
from dataclasses import replace
from io import BytesIO
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from threading import Lock
from zipfile import ZIP_DEFLATED, ZipFile

import streamlit as st

from streamvault.config import CONFIG
from streamvault.fetch_movies import MissingTokenError
from streamvault.main import run


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


def render_page() -> None:
    st.title("StreamVault recommendations")
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
            mime="application/zip", on_click="ignore",
        )
        st.markdown(summary)


if __name__ == "__main__":
    render_page()
