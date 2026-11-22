from math import fsum, isclose
import unittest

from .assess import assess


def assert_json_close(case, actual, expected, path="$"):
    """Compare replayed JSON semantically, allowing only floating-point tail noise."""
    if isinstance(expected, dict):
        case.assertIsInstance(actual, dict, path)
        case.assertEqual(set(actual), set(expected), path)
        for key, value in expected.items():
            assert_json_close(case, actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        case.assertIsInstance(actual, list, path)
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


class PersonalContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = assess()
        cls.cases = {(r["category"], r["arm"]): r for r in result["cases"]}
        cls.contrasts = {(r["category"], r["from_arm"], r["to_arm"]): r["values"]
                         for r in result["comparisons"]}
        cls.categories = ("male60", "female55", "female50")

    def test_same_date_equal_credits_different_bases_and_costs(self):
        for category in self.categories:
            unit, individual = [self.cases[category, key] for key in ("extension_mar", "personal900")]
            self.assertEqual(unit["first_model_payment"], "2030-07")
            self.assertEqual(individual["first_model_payment"], "2030-07")
            self.assertEqual(unit["opening_ledger"], individual["opening_ledger"])
            for case, base, held, paid, received in (
                    (unit, 5550, 444, 1332, 3996), (individual, 4500, 360, 2700, 2700)):
                self.assertEqual(case["award"]["recognized_worker_credits"], 186)
                self.assertEqual([p["month"] for p in case["payments"]], ["2030-03", "2030-04", "2030-05"])
                self.assertEqual([p["insured_base_yuan"] for p in case["payments"]], [base] * 3)
                self.assertEqual([p["account_credited_yuan"] for p in case["payments"]], [held] * 3)
                self.assertEqual(fsum(p["net_household_outlay_yuan"] for p in case["payments"]), paid)
                self.assertEqual(fsum(p["total_premium_posted_yuan"] for p in case["payments"]), received)
            for v in self.contrasts[category, "extension_mar", "personal900"]:
                self.assertEqual(v["timing_component_pv_yuan"], 0)
                self.assertLess(v["pooled_benefit_level_component_pv_yuan"], 0)
                self.assertLess(v["account_benefit_level_component_pv_yuan"], 0)
                self.assertLess(v["difference_net_pv_yuan"], v["difference_gross_pv_yuan"])

    def test_postponed_liquidity_clock_and_zero_not_inferred_pension(self):
        for category in self.categories:
            self.assertEqual(self.cases[category, "personal600"]["first_model_payment"], "2030-08")
            self.assertEqual(self.cases[category, "no_grant_april_gap"]["first_model_payment"], "2030-09")
            no_capacity = self.cases[category, "personal_zero"]
            self.assertEqual(no_capacity["status"], "unclaimed_through_2030_12")
            self.assertIsNone(no_capacity["award"])
            self.assertIsNone(no_capacity["first_model_payment"])
            self.assertEqual(no_capacity["payments"], [])
            self.assertEqual(no_capacity["values"], [])

    def test_direct_and_fixed_match_same_cash_shortfall(self):
        for category in self.categories:
            fixed, direct = [self.cases[category, key] for key in ("fixed_april_gap", "direct_april_gap")]
            self.assertEqual(fixed["award"], direct["award"])
            self.assertEqual(fixed["values"], direct["values"])
            for row in direct["payments"]:
                self.assertAlmostEqual(row["household_premium_remitted_yuan"] + row["public_premium_direct_yuan"],
                                       row["total_premium_posted_yuan"])
            self.assertEqual(fsum(r["public_premium_direct_yuan"] for r in direct["payments"]), 492.26)
            self.assertEqual(fsum(r["public_transfer_to_household_yuan"] for r in fixed["payments"]), 492.26)
            self.assertEqual(fsum(r["net_household_outlay_yuan"] for r in fixed["payments"]), 2207.74)

    def test_public_support_timing_and_incidence_distinct_from_rights(self):
        for category in self.categories:
            late = self.cases[category, "late_may_april_gap"]
            direct = self.cases[category, "direct_normal"]
            fixed = self.cases[category, "fixed_normal"]
            self.assertEqual(late["first_model_payment"], "2030-09")
            self.assertEqual(direct["award"], fixed["award"])
            self.assertEqual(fsum(p["public_premium_direct_yuan"] for p in direct["payments"]), 0)
            for v in self.contrasts[category, "fixed_april_gap", "late_may_april_gap"]:
                self.assertLess(v["difference_gross_pv_yuan"], 0)
            for v in self.contrasts[category, "fixed_normal", "direct_normal"]:
                self.assertEqual(v["difference_gross_pv_yuan"], 0)
                self.assertLess(v["difference_net_pv_yuan"], 0)

    def test_exact_attribution_and_no_bank_inference(self):
        self.assertEqual(len(self.cases), 39)
        self.assertEqual(len(self.contrasts), 30)
        for c in self.cases.values():
            self.assertIsNone(c["actual_first_bank_payment"])
        for rows in self.contrasts.values():
            self.assertEqual(len(rows), 6)
            for v in rows:
                self.assertAlmostEqual(v["difference_gross_pv_yuan"],
                    v["timing_component_pv_yuan"] + v["monthly_level_component_pv_yuan"], places=6)
                if v["pooled_benefit_level_component_pv_yuan"] is not None:
                    self.assertAlmostEqual(v["monthly_level_component_pv_yuan"],
                        v["pooled_benefit_level_component_pv_yuan"] + v["account_benefit_level_component_pv_yuan"],
                        places=6)

    def test_cross_platform_float_tail_uses_numeric_comparison(self):
        from math import inf, nextafter

        frozen = {"nested": [{"amount": 12345.6789, "count": 3}]}
        rerun = {"nested": [{"amount": nextafter(12345.6789, inf), "count": 3}]}
        self.assertNotEqual(rerun, frozen)
        assert_json_close(self, rerun, frozen)
        for changed in (
                {"nested": [{"amount": 12345.6789, "count": 4}]},
                {"nested": [{"amount": 12345.6789}]},
                {"nested": [{"amount": 12345.6799, "count": 3}]}):
            with self.assertRaises(AssertionError):
                assert_json_close(self, changed, frozen)

    def test_replay_sealed_result_values_cross_platform(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from extensions.continuation_valuation_base.valuation.assess import write
        from extensions.legacy_paths import to_public

        saved = Path(__file__).with_name("results.synthetic.json")
        with TemporaryDirectory() as p:
            rerun = Path(p) / "fresh.synthetic.json"
            write(rerun, assess())
            assert_json_close(self, json.loads(rerun.read_text(encoding="utf-8")),
                              to_public(json.loads(saved.read_text(encoding="utf-8"))))
