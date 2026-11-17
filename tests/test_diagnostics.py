import unittest
from contextlib import redirect_stdout
from io import StringIO

from streamvault.diagnostics import raise_for_failed_checks, run_data_checks


class DataCheckReportTests(unittest.TestCase):
    def test_returns_a_report_with_stage_status_and_details(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            report = run_data_checks(
                "loaded",
                {"IDs are unique": (True, "3 records checked")},
            )

        self.assertEqual(output.getvalue(), "")
        self.assertEqual(list(report.columns), ["check", "status", "details"])
        self.assertEqual(report.loc[0, "check"], "IDs are unique")
        self.assertEqual(report.loc[0, "status"], "PASS")
        self.assertEqual(report.loc[0, "details"], "3 records checked")

    def test_failed_checks_are_in_report_and_can_be_raised_after_display(self) -> None:
        report = run_data_checks("loaded", {"IDs are unique": (False, "duplicate ID")})

        self.assertEqual(report.loc[0, "status"], "FAIL")
        self.assertEqual(report.loc[0, "details"], "duplicate ID")
        with self.assertRaisesRegex(ValueError, "IDs are unique"):
            raise_for_failed_checks("loaded", report)


if __name__ == "__main__":
    unittest.main()
