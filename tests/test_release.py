import csv
import inspect
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model
import optimize
from pension_core.ledger import simulate
from pension_core.history import ActiveHistory
from pension_core.rules import minimum_months, month


class ReleaseTests(unittest.TestCase):
    def test_scope_and_current_age_clock(self):
        self.assertTrue(inspect.signature(simulate).parameters["legal_vesting"].default)
        self.assertEqual([minimum_months(year) for year in (2029, 2030, 2039, 2041)], [180, 186, 240, 240])
        cfg, carriers = model.load_inputs()
        self.assertEqual(len(carriers), 18)
        row = next(model.paired(cfg, carriers[:1], model.WORLDS[0], model.DEFAULT_ARM, "worker", 0))
        self.assertAlmostEqual(row["p2_cash12"], row["enterprise_cash12"] + row["occupational_cash12"], places=7)
        self.assertAlmostEqual(row["pv_direct"], 0., places=7)

    def test_missing_months_and_balances(self):
        cfg, carriers = model.load_inputs()
        start = deepcopy(carriers[0]["starts"]["base"])
        person = model.Person(**start["person"])
        history = model.rights(start["history"])
        bad = model.replace(person, worker_paid=person.worker_paid - 1)
        with self.assertRaises(ValueError):
            ActiveHistory(history, bad, month(cfg["start_year"], 1), 0.)
        with self.assertRaises(ValueError):
            ActiveHistory(history, model.replace(person, worker_balance=float("nan")), month(cfg["start_year"], 1), 0.)

    def test_declared_regime_and_noncontribution_differ(self):
        kinds = ("standard", "nonstandard", "out", "nonstandard", "nonstandard")
        access = model.payment_access(kinds, "resident", 2)
        self.assertEqual([(item.affiliation, item.can_post) for item in access],
                         [("worker", True), ("resident", False), ("none", False),
                          ("resident", False), ("resident", True)])

    def test_uniform_price_boundary_uses_full_table(self):
        # Boundary = largest per-path direct cost of the 150-yuan arm across the 24 worlds
        # (826.468 in the 1.0.0 table; 791.779 before the month-order and tax fixes).
        before = optimize.select(826.46)
        after = optimize.select(826.47)
        self.assertEqual(before["shares_always_fixed_before_world"], [{"worker": 0, "match": 0., "share": 1.}])
        self.assertEqual(after["shares_always_fixed_before_world"], [{"worker": 150, "match": 0., "share": 1.}])
        self.assertGreater(after["mean_gap_reduction_yuan_month_range"][0], .75)
        with optimize.TABLE.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        with self.assertRaises(ValueError):
            optimize.matrices(rows[:-1])


if __name__ == "__main__":
    unittest.main()
