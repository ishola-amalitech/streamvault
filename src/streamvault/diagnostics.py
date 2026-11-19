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
    failed = report.loc[report["status"].eq("FAIL"), ["check", "details"]]
    if not failed.empty:
        # Keep the details visible when a script raises without printing the report.
        messages = failed["check"] + " (" + failed["details"] + ")"
        raise ValueError(
            f"Data checks failed at stage '{stage}': {', '.join(messages)}"
        )


def print_check_report(stage: str, report: pd.DataFrame) -> None:
    """Show the command-line report before stopping on any failed checks."""
    print(f"\n{stage}")
    print(report.to_string(index=False))
    raise_for_failed_checks(stage, report)
