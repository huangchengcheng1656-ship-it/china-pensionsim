"""Replay sealed synthetic outputs.

The survival-valuation baseline was regenerated for release 1.0.0 after the
month-order correction (contributions post before adjudication); the budget
solver replays the research-release portfolio fixture unchanged.
"""
import json
from math import isclose
from pathlib import Path
import unittest

from extensions.survival_valuation.valuation.paths import build as build_r53
from extensions.budget_solver.optimization.replay import r100_replay
from extensions.legacy_paths import to_public

ROOT = Path(__file__).resolve().parents[1]


def assert_json_close(case, actual, expected, path="$"):
    if isinstance(expected, dict):
        case.assertIsInstance(actual, dict, path)
        case.assertEqual(set(actual), set(expected), path)
        for key, value in expected.items():
            assert_json_close(case, actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        case.assertIsInstance(actual, (list, tuple), path)
        case.assertEqual(len(actual), len(expected), path)
        for index, value in enumerate(expected):
            assert_json_close(case, actual[index], value, f"{path}[{index}]")
    elif isinstance(expected, float):
        case.assertIsInstance(actual, (int, float), path)
        case.assertNotIsInstance(actual, bool, path)
        case.assertTrue(isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9),
                        f"{path}: {actual!r} != {expected!r}")
    else:
        case.assertEqual(actual, expected, path)


class FrozenR103RegressionTests(unittest.TestCase):
    def test_r53_survival_weighted_values_match_frozen_content(self):
        frozen = json.loads((ROOT / "extensions/survival_valuation/valuation/cashflow_values.json").read_text(encoding="utf-8"))
        actual = build_r53()
        # Source hashes are intentionally excluded: module and engine paths changed during adaptation.
        for key in frozen:
            assert_json_close(self, actual[key], frozen[key], f"$.{key}")

    def test_r103_integer_solver_replay_matches_frozen_result(self):
        frozen = json.loads((ROOT / "extensions/budget_solver/optimization/verified_r100.synthetic.json").read_text(encoding="utf-8"))
        assert_json_close(self, r100_replay(), to_public(frozen))


if __name__ == "__main__":
    unittest.main()
