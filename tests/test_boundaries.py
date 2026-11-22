"""Hand-checked boundary cases for eligibility timing, wage tax and input contracts.

Expected values are computed by hand from the rules, not copied from model output.
"""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

import data_validation
import regional
from pension_core.ledger import Person, Scenario, simulate
from pension_core.rules import minimum_months, month, retirement_month

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "data" / "synthetic" / "cohort.synthetic.json").read_text(encoding="utf-8"))["config"]
START, LAST = month(CFG["start_year"], 1), month(CFG["last_year"], 12)
JOBS = ["standard"] * (LAST - START + 1)


def person(**changes):
    fields = dict(birth=month(1975, 1), category="male60", job="standard", wage=10000., cash=0.,
                  liquid=50000., worker_paid=60, worker_deemed=0, resident_paid=0, worker_index=1.0,
                  worker_balance=0., resident_balance=0., corporate_owned=0., corporate_pending=0.,
                  occupational=0., personal=0., self_employed=False, government_job=False,
                  debtservice=0., seed=7)
    fields.update(changes)
    return Person(**fields)


def months_before(legal):
    return legal - START


class EligibilityTimingTests(unittest.TestCase):
    def claim(self, birth, opening):
        terminal = {}
        result = simulate(person(birth=birth, worker_paid=opening, liquid=0.), Scenario("boundary"), CFG,
                          job_path=JOBS, terminal=terminal)
        return result, terminal

    def test_180th_contribution_in_the_retirement_month_counts(self):
        birth = month(1967, 1)
        legal = retirement_month(birth, "male60")
        self.assertEqual(legal, month(2027, 8))          # 60 years + 7 months
        opening = 179 - months_before(legal)            # 179 at the start of August 2027
        result, terminal = self.claim(birth, opening)
        self.assertEqual(result["route"], "worker")
        self.assertTrue(result["eligible_at_legal"])
        self.assertEqual(terminal["worker_credited"], 180)
        self.assertEqual(terminal["first_payment_month"], month(2027, 9))

    def test_186th_contribution_in_a_2030_retirement_month_counts(self):
        birth = month(1969, 3)
        legal = retirement_month(birth, "male60")
        self.assertEqual(legal, month(2030, 4))
        self.assertEqual(minimum_months(2030), 186)
        result, terminal = self.claim(birth, 185 - months_before(legal))
        self.assertTrue(result["eligible_at_legal"])
        self.assertEqual(terminal["worker_credited"], 186)
        self.assertEqual(terminal["first_payment_month"], month(2030, 5))

    def test_one_month_short_claims_after_one_extension_month(self):
        birth = month(1969, 3)
        legal = retirement_month(birth, "male60")
        result, terminal = self.claim(birth, 184 - months_before(legal))
        self.assertFalse(result["eligible_at_legal"])
        self.assertEqual(terminal["worker_credited"], 186)
        self.assertEqual(terminal["first_payment_month"], legal + 2)


class WageTaxTests(unittest.TestCase):
    """10,000 yuan a month, 8% basic pension, 1,000 yuan of individual pension a month."""

    cfg = dict(CFG, personal_chance=1.0, personal_candidate=1000, annuity_coverage_chance=0.0,
               annual_returns={"p1": 0., "p2": 0., "p3": 0., "liquid": 0.}, pv_annual_rate=0.)

    def run_case(self, jobs=JOBS, deduction=True):
        ledger, trace, sources = {}, [], []
        simulate(person(), Scenario("tax", personal_deduction=deduction), self.cfg, job_path=jobs,
                 annual_ledger=ledger, mobility_trace=trace, source_trace=sources)
        return ledger, trace, sources

    def test_annual_withholding_and_january_amount(self):
        _, _, sources = self.run_case()
        year = [r for r in sources if r["month"] // 12 == 2026]
        # January: (10,000 - 5,000 - 800 - 1,000) x 3% = 96.
        self.assertAlmostEqual(year[0]["income_tax_after_p3"], 96.0, places=6)
        # Year: 120,000 - 60,000 - 9,600 - 12,000 = 38,400 -> 1,080 + 240 = 1,320.
        self.assertAlmostEqual(sum(r["income_tax_after_p3"] for r in year), 1320.0, places=6)

    def test_fiscal_cost_equals_household_gain(self):
        ledger, trace, _ = self.run_case()
        _, trace_off, _ = self.run_case(deduction=False)
        end = {z["month"]: z["ordinary_end"] for z in trace}
        end_off = {z["month"]: z["ordinary_end"] for z in trace_off}
        dec = month(2026, 12)
        # Without the deduction: 50,400 taxable -> 2,520; with it 1,320; cost 1,200.
        self.assertAlmostEqual(ledger[2026]["personal_deduction"], 1200.0, places=6)
        self.assertAlmostEqual(end[dec] - end_off[dec], 1200.0, places=6)

    def test_no_refund_before_annual_settlement(self):
        jobs = list(JOBS)
        jobs[month(2026, 11) - START] = "out"
        _, _, sources = self.run_case(jobs=jobs)
        self.assertTrue(all(r["income_tax_after_p3"] >= 0 for r in sources))


class InputContractTests(unittest.TestCase):
    def rows(self):
        text = (ROOT / "data" / "public" / "regional_parameters.csv").read_text(encoding="utf-8")
        return list(csv.DictReader(io.StringIO(text)))

    def write(self, rows, name="custom.csv"):
        path = Path(tempfile.mkdtemp()) / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_effective_date_splits_the_year(self):
        rows = self.rows()
        rows[0].update(effective_from="2026-07-01", contribution_floor_monthly="6000")
        terms = regional.load_terms("浙江省", csv_path=self.write(rows))
        self.assertEqual(terms.profile.worker("2026-06").floor, 5122)
        self.assertEqual(terms.profile.worker("2026-07").floor, 6000)

    def test_every_entry_point_rejects_unreviewed_rows(self):
        rows = self.rows()
        rows[0].update(review_status="pending", source_url="")
        with self.assertRaises(ValueError):
            regional.load_terms("浙江省", csv_path=self.write(rows))

    def test_zero_sample_cfps_row_is_rejected(self):
        text = (ROOT / "data" / "synthetic" / "cfps_transitions.csv").read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))[:1]
        rows[0]["unweighted_n"] = "0"
        errors = data_validation.validate_file(self.write(rows, "cfps_transitions.csv"))
        self.assertTrue(any("greater than zero" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
