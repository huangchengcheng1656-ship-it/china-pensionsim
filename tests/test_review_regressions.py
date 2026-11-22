"""Independent hand-calculated regressions for the release-review boundaries."""
import json
from pathlib import Path
import unittest

from pension_core.access import Access
from pension_core.history import History
from pension_core.ledger import Person, Scenario, simulate
from pension_core.portability import ResidentYear, WorkerMonth
from pension_core.rules import month


ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'data/synthetic/cohort.synthetic.json').read_text(encoding='utf-8'))['config']
CFG = dict(CFG, last_year=2027, personal_chance=0., expense_floor_share=0.,
           annuity_coverage_chance=0., pv_annual_rate=0.,
           annual_returns=dict(p1=0., p2=0., p3=0., liquid=0.))
START = month(2026, 1)
JOBS = ['standard'] * 24


def person(**changes):
    fields = dict(birth=month(1967, 1), category='male60', job='standard', wage=10000.,
                  cash=0., liquid=100000., worker_paid=200, worker_deemed=0, resident_paid=0,
                  worker_index=1., worker_balance=10000., resident_balance=0., corporate_owned=0.,
                  corporate_pending=0., occupational=0., personal=0., self_employed=False,
                  government_job=False, debtservice=0., seed=7)
    fields.update(changes)
    return Person(**fields)


class ReviewRegressionTests(unittest.TestCase):
    def test_adjudication_refund_keeps_source_trace_consistent(self):
        p = person(resident_paid=12, resident_balance=1200.)
        history = History(
            worker_opening=tuple(WorkerMonth(t, 'X', 'employee', '50')
                                 for t in range(START - 200, START)),
            resident_opening=(ResidentYear(2025, frozenset(range(month(2025, 1), START)),
                                           '1200', '0'),),
            normal_worker_region='X', hukou_region='X', receiving_resident_region='X',
            deemed_by_region={}, deemed_for_resident=0, choice_by_month={},
            decision_month=month(2027, 8))
        trace, events, terminal, untraced_terminal = [], [], {}, {}
        simulate(p, Scenario('overlap_refund'), CFG, job_path=JOBS, verified_history=history,
                 terminal=untraced_terminal)
        simulate(p, Scenario('overlap_refund'), CFG, job_path=JOBS, verified_history=history,
                 source_trace=trace, transfer_events=events, terminal=terminal)
        self.assertEqual(terminal, untraced_terminal)
        self.assertEqual(terminal['first_payment_month'], month(2027, 9))
        self.assertEqual(events[0].direction, 'resident_to_employee')
        self.assertEqual(float(events[0].resident_own_refund), 1200.)
        row = next(r for r in trace if r['month'] == month(2027, 8))
        # 100,000 opening + 20*(10,000-800) wages net of P1 - 2,520 tax
        # in 2026 - 1,008 withheld in Jan-Aug 2027 + 1,200 overlap refund.
        self.assertAlmostEqual(row['ordinary_end'], 281672., places=7)
        self.assertEqual(row['ordinary_overlap_refund'], 1200.)
        self.assertEqual(row['p3_own'], 0.)

    def test_paid_annuity_remains_deductible_when_p1_posting_is_closed(self):
        trace = []
        access = [Access('worker', False)] + [Access('worker', True)] * 23
        simulate(person(government_job=True), Scenario('P1_January_closed'), CFG,
                 job_path=JOBS, access_path=access, source_trace=trace)
        year = trace[:12]
        self.assertEqual(year[0]['p1_member_paid'], 0.)
        self.assertEqual(year[0]['p2_member_paid'], 400.)
        self.assertAlmostEqual(sum(r['p1_member_paid'] for r in year), 8800., places=7)
        self.assertAlmostEqual(sum(r['p2_member_paid'] for r in year), 4800., places=7)
        # January: (10,000 - 5,000 - 400) * 3% = 138.
        self.assertAlmostEqual(year[0]['income_tax_after_p3'], 138., places=7)
        # Annual: (120,000 - 60,000 - 11*800 - 12*400) * 10% - 2,520 = 2,120.
        self.assertAlmostEqual(sum(r['income_tax_after_p3'] for r in year), 2120., places=7)


if __name__ == '__main__':
    unittest.main()
