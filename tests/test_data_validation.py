import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_validation import validate_file, validate_paths


class DataValidationTests(unittest.TestCase):
    def setUp(self):
        self.samples = [ROOT / "data" / "synthetic" / f"{name}.csv" for name in (
            "cfps_transitions", "charls_benefits", "regional_parameters",
            "official_macro", "admin_validation",
        )]
        self.public_regional = ROOT / "data" / "public" / "regional_parameters.csv"

    def read_rows(self, path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return reader.fieldnames, list(reader)

    def write_rows(self, path, fields, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_supplied_samples_and_public_parameters_validate(self):
        self.assertEqual(validate_paths([*self.samples, self.public_regional]), [])
        for path in self.samples:
            _, rows = self.read_rows(path)
            self.assertTrue(rows)
            self.assertTrue(all(row["dataset_type"] == "synthetic" for row in rows), path.name)

    def test_missing_required_value_is_rejected(self):
        fields, rows = self.read_rows(self.samples[0])
        rows[0]["weighted_transitions"] = ""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / self.samples[0].name
            self.write_rows(path, fields, rows)
            errors = validate_file(path)
        self.assertTrue(any("weighted_transitions" in error and "required" in error for error in errors), errors)

    def test_nonfinite_and_negative_numbers_are_rejected(self):
        cases = ((self.samples[1], "weighted_mean_monthly", "nan"),
                 (self.samples[2], "contribution_floor_monthly", "-1"))
        for source, field, value in cases:
            with self.subTest(source=source.name):
                fields, rows = self.read_rows(source)
                rows[0][field] = value
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / source.name
                    self.write_rows(path, fields, rows)
                    errors = validate_file(path)
                self.assertTrue(any(field in error for error in errors), errors)

    def test_missing_bounds_and_sample_sizes_are_checked(self):
        cases = ((self.samples[1], "missing_lower", "0.4", "missing_upper", "0.2"),
                 (self.samples[0], "effective_n", "20", "unweighted_n", "10"))
        for source, first, first_value, second, second_value in cases:
            with self.subTest(source=source.name):
                fields, rows = self.read_rows(source)
                rows[0][first] = first_value
                rows[0][second] = second_value
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / source.name
                    self.write_rows(path, fields, rows)
                    errors = validate_file(path)
                self.assertTrue(errors, f"{source.name} invalid relation was accepted")

    def test_real_aggregate_requires_review_and_approved_rows_pass(self):
        fields, rows = self.read_rows(self.samples[0])
        rows[0]["dataset_type"] = "real_aggregate"
        rows[0]["review_status"] = "pending"
        rows[0]["review_reference"] = ""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / self.samples[0].name
            self.write_rows(path, fields, rows)
            errors = validate_file(path)
            self.assertTrue(any("review" in error for error in errors), errors)
            rows[0]["review_status"] = "approved"
            rows[0]["review_reference"] = "LOCAL-2026.01"
            self.write_rows(path, fields, rows)
            self.assertEqual(validate_file(path), [])

    def test_admin_dates_and_verified_zero_are_consistent(self):
        fields, rows = self.read_rows(self.samples[4])
        rows[0]["posting_month"] = "2019-12"
        rows[0]["contribution_period_month"] = "2020-01"
        rows[0]["verified_zero_receipt"] = "1"
        rows[0]["bank_receipt_yuan"] = "100"
        rows[0]["transfer_completion_date"] = "2026-02-30"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / self.samples[4].name
            self.write_rows(path, fields, rows)
            errors = validate_file(path)
        self.assertGreaterEqual(len(errors), 3, errors)

    def test_public_sources_and_regional_bounds_are_required(self):
        fields, rows = self.read_rows(self.public_regional)
        rows[0]["source_url"] = ""
        rows[0]["contribution_floor_monthly"] = "99999"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / self.public_regional.name
            self.write_rows(path, fields, rows)
            errors = validate_file(path)
        self.assertTrue(any("source_url" in error for error in errors), errors)
        self.assertTrue(any("floor" in error for error in errors), errors)

    def test_unknown_dataset_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unknown.csv"
            path.write_text("dataset_type\nsynthetic\n", encoding="utf-8")
            self.assertTrue(validate_file(path))

    def test_cli_default_reports_six_checked_files(self):
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "data_validation.py")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"files_checked": 6, "errors": []})


if __name__ == "__main__":
    unittest.main()
