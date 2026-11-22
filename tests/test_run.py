import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ColdStartTests(unittest.TestCase):
    def test_one_command_validates_data_and_replays_synthetic_demo(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "output"
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / "run.py"), "--out", str(destination)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            summary = json.loads((destination / "synthetic_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["mode"], "synthetic")
            self.assertEqual(summary["scenario_results"][0]["risk_units"], 72)
            with (destination / "synthetic_paths.csv").open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 72)
            interruption = json.loads((destination / "interruption.synthetic.json").read_text(encoding="utf-8"))
            self.assertEqual(set(interruption), {"near_low", "near_high", "buffered_low", "buffered_high"})
            validation = json.loads((destination / "data_validation.json").read_text(encoding="utf-8"))
            self.assertEqual(validation["errors"], [])
            self.assertEqual(validation["files_checked"], 6)


if __name__ == "__main__":
    unittest.main()
