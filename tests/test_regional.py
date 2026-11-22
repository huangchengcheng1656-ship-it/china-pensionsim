import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_validation import validate_file
import model
from pension_core.rules import month
import regional


PUBLIC = ROOT / "data" / "public" / "regional_parameters.csv"
SYNTHETIC = ROOT / "data" / "synthetic" / "regional_parameters.csv"


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_rows(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class RegionalDataTests(unittest.TestCase):
    def test_public_worker_and_resident_areas_are_separate(self):
        fields, rows = read_rows(PUBLIC)
        self.assertIn("area_level", fields)
        self.assertIn("area_name", fields)
        self.assertEqual([(r["area_level"], r["area_name"]) for r in rows],
                         [("province", "浙江省"), ("city", "杭州市区")])
        worker, resident = rows
        self.assertEqual(worker["resident_basic_monthly"], "")
        self.assertEqual(worker["retirement_base_monthly"], "8537")
        self.assertEqual(resident["retirement_base_monthly"], "")
        self.assertEqual(resident["resident_basic_monthly"], "390")
        self.assertEqual(resident["effective_from"], "")
        self.assertNotIn(worker["source_url"], resident["source_url"])
        self.assertEqual(validate_file(PUBLIC), [])
        self.assertEqual(validate_file(SYNTHETIC), [])

    def test_regional_rows_require_only_their_own_level_parameters(self):
        fields, rows = read_rows(PUBLIC)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / PUBLIC.name
            mixed = [dict(row) for row in rows]
            mixed[1]["contribution_floor_monthly"] = "5122"
            write_rows(path, fields, mixed)
            errors = validate_file(path)
            self.assertTrue(any("city" in error and "worker" in error for error in errors), errors)

            missing = [dict(row) for row in rows]
            missing[0]["retirement_base_monthly"] = ""
            write_rows(path, fields, missing)
            errors = validate_file(path)
            self.assertTrue(any("retirement_base_monthly" in error and "required" in error for error in errors), errors)

            invalid = [dict(row) for row in rows]
            invalid[0]["area_level"] = "district"
            write_rows(path, fields, invalid)
            errors = validate_file(path)
            self.assertTrue(any("area_level" in error for error in errors), errors)


class RegionalTermsTests(unittest.TestCase):
    def test_public_csv_values_reach_local_terms_and_freeze_scenario(self):
        terms = regional.load_terms("浙江省", through="2039-12")
        worker = terms.employee(month(2026, 1))
        self.assertEqual((worker.floor, worker.ceiling, worker.retirement_base), (5122, 25611, 8537))
        future = terms.employee(month(2030, 1))
        self.assertEqual(future.source_mode, "scenario_freeze_2026")
        self.assertEqual(future.retirement_base, 8537)
        self.assertEqual(terms.resident_benefit(month(2030, 1)), 390)
        self.assertIn("2026-04-13", terms.resident_override_basis)
        self.assertEqual(terms.worker_region, "synthetic_single_region")
        self.assertEqual(terms.resident_region, "synthetic_single_region")
        with self.assertRaisesRegex(ValueError, "浙江省"):
            regional.load_terms("不存在省", through="2039-12")

    def test_paired_engine_uses_regional_retirement_base(self):
        cfg, carriers = model.load_inputs()
        terms = regional.load_terms("浙江省", through=f"{cfg['last_year']}-12")
        default = list(model.paired(cfg, carriers, model.WORLDS[0], model.DEFAULT_ARM, "worker", 0))
        applied = list(model.paired(cfg, carriers, model.WORLDS[0], model.DEFAULT_ARM,
                                    "worker", 0, local_terms=terms))
        self.assertEqual(cfg["pension_base"], 7500)
        comparisons = [(before, after) for before, after in zip(default, applied, strict=True)
                       if before["p1_cash12"] > 0]
        self.assertTrue(comparisons)
        self.assertTrue(any(after["p1_cash12"] != before["p1_cash12"]
                            for before, after in comparisons))


class RegionalCommandTests(unittest.TestCase):
    def run_cli(self, destination, region=None):
        command = [sys.executable, "-B", str(ROOT / "run.py"), "--out", str(destination)]
        if region is not None:
            command += ["--region", region]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        summary = json.loads((destination / "synthetic_summary.json").read_text(encoding="utf-8"))
        with (destination / "synthetic_paths.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 72)
        return summary

    def test_default_output_marks_national_placeholder(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = self.run_cli(Path(folder) / "default")
        self.assertEqual(summary["parameter_basis"]["mode"], "national_placeholder")
        self.assertEqual(summary["parameter_basis"]["label"], "全国占位参数")
        self.assertEqual(summary["parameter_basis"]["worker_retirement_base_monthly"], 7500)

    def test_zhejiang_output_marks_synthetic_regional_scenario(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = self.run_cli(Path(folder) / "zhejiang", "浙江省")
        basis = summary["parameter_basis"]
        self.assertEqual(basis["mode"], "regional_public_scenario")
        self.assertEqual(basis["worker_area_name"], "浙江省")
        self.assertEqual(basis["resident_area_name"], "杭州市区")
        self.assertEqual(basis["worker_retirement_base_monthly"], 8537)
        self.assertEqual(basis["resident_basic_monthly"], 390)
        self.assertIn("合成载体", basis["carrier_mapping"])
        self.assertIn("非官方预测", basis["future_assumption"])


if __name__ == "__main__":
    unittest.main()
