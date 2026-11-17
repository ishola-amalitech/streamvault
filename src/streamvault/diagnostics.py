from collections.abc import Mapping

import pandas as pd


DataCheck = tuple[bool, str]


def run_data_checks(stage: str, checks: Mapping[str, DataCheck]) -> pd.DataFrame:
    if not stage.strip():
        raise ValueError("A data-check stage name is required.")
    if not checks:
        raise ValueError(f"No data checks were provided for stage '{stage}'.")

    check_items = list(checks.items())
    report = pd.DataFrame(
        {
            "check": [name for name, _ in check_items],
            "status": [
                "PASS" if passed else "FAIL"
                for _, (passed, _) in check_items
            ],
            "details": [details for _, (_, details) in check_items],
        }
    )
    return report


def raise_for_failed_checks(stage: str, report: pd.DataFrame) -> None:
    failed_checks = report.loc[report["status"].eq("FAIL"), "check"].tolist()
    if failed_checks:
        raise ValueError(
            f"Data checks failed at stage '{stage}': {', '.join(failed_checks)}"
        )
