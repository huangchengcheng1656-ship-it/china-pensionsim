from dataclasses import replace
import unittest

from . import paths as P


class ValuationPathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = P.build()
        cls.rows = {(x["category"], x["arm"]): x for x in result["paths"]}
        cls.contrasts = result["contrasts"]
        cls.config, _, _ = P.B.policy_inputs()

    def test_unfunded_extension_and_undetermined_approval_remain_unvalued(self):
        for category in P.B.CATEGORIES:
            for arm in ("refund_unresolved", "refund_unfunded_extension"):
                r = self.rows[category, arm]
                self.assertEqual(r["worker_credited_at_last_adjudication_attempt"], 185)
                self.assertIsNone(r["route"])
                self.assertIsNone(r["first_payment_month"])
                self.assertIsNone(r["expected_pension_pv_yuan"])
            r = self.rows[category, "refund_unfunded_extension"]
            self.assertEqual(r["extension_cash_available_for_gross_payment_yuan"], 743.60)
            self.assertIs(r["extension_worker_posted"], False)

    def test_extension_posts_before_qualifying_and_requires_real_cash(self):
        for category in P.B.CATEGORIES:
            immediate = self.rows[category,"immediate"]
            self.assertEqual(immediate["credited_at_statutory_month_open"], 186)
            self.assertEqual(immediate["first_payment_month"], "2030-03")
            for arm, first in (("refund_extension_at_legal_month_end","2030-04"),
                               ("refund_extension_next_month","2030-05")):
                r = self.rows[category,arm]
                self.assertEqual(r["credited_at_statutory_month_open"], 185)
                self.assertEqual(r["extension_cash_available_for_gross_payment_yuan"], 893.60)
                self.assertEqual(r["worker_credited_at_last_adjudication_attempt"], 186)
                self.assertIs(r["extension_worker_posted"], True)
                self.assertEqual(r["first_payment_month"], first)
                self.assertEqual(r["net_household_contribution_nominal_yuan"],
                                 immediate["net_household_contribution_nominal_yuan"])
                self.assertEqual(r["direct_public_support_nominal_yuan"],
                                 immediate["direct_public_support_nominal_yuan"])

    def test_reject_same_month_posting_as_opening_credit(self):
        arm = replace(P.ARMS[-1], decision=P.B.LEGAL+1)
        with self.assertRaisesRegex(ValueError, "post before adjudication"):
            P.simulate_arm("male60",arm,self.config)

    def test_resident_approval_changes_amount_and_age(self):
        for category, first in zip(P.B.CATEGORIES, ("2030-03","2034-02","2038-06"), strict=True):
            r = self.rows[category,"refund_resident_if_approved"]
            self.assertEqual(r["route"],"resident")
            self.assertEqual(r["first_payment_month"],first)
            self.assertGreater(r["amount_to_resident_if_approved_yuan"],0)
            benchmark = self.rows[category,"immediate"]
            self.assertLess(r["expected_pension_pv_yuan"][P.BASE],
                            benchmark["expected_pension_pv_yuan"][P.BASE])

    def test_timing_and_amount_decomposition_and_discount_sensitivity(self):
        for x in self.contrasts:
            self.assertAlmostEqual(x["base_loss_timing_yuan"]+x["base_loss_amount_yuan"],
                                   x["base_loss_yuan"], delta=.011)
            self.assertLessEqual(x["stress_loss_min_yuan"],x["base_loss_yuan"])
            self.assertLessEqual(x["base_loss_yuan"],x["stress_loss_max_yuan"])
            if x["delay_months"]:
                self.assertGreater(x["base_loss_timing_yuan"],0.)
            else:
                self.assertEqual(x["base_loss_timing_yuan"],0.)
            if x["versus_immediate"] != "refund_resident_if_approved":
                self.assertLess(x["base_loss_amount_yuan"],0.)


if __name__ == "__main__":
    unittest.main()
