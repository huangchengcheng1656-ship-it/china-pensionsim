"""Reconcile verified or explicitly simulated first-pillar histories in the monthly ledger."""
from dataclasses import dataclass
from fractions import Fraction
from math import isclose

from .portability import ResidentYear, WorkerMonth, reconcile


@dataclass(frozen=True)
class History:
    worker_opening: tuple
    resident_opening: tuple
    normal_worker_region: str
    hukou_region: str
    receiving_resident_region: str
    deemed_by_region: dict
    deemed_for_resident: int
    choice_by_month: dict
    decision_month: int
    threshold_reference: str | None = None


class ActiveHistory:
    def __init__(self, history, person, opening_month, rate):
        self.history = history
        self.opening_month = opening_month
        self.rate = rate
        self.worker = [(r, opening_month - 1) for r in history.worker_opening]
        self.resident = {r.year: (set(r.covered_months), r.own_principal, r.collective_principal)
                         for r in history.resident_opening}
        if (len({r.year for r in history.resident_opening}) != len(history.resident_opening)
                or len({r.month for r in history.worker_opening}) != person.worker_paid
                or sum(len(r.covered_months) for r in history.resident_opening) != person.resident_paid
                or sum(history.deemed_by_region.values()) != person.worker_deemed):
            raise ValueError("opening history and credited monthly duration disagree")
        if any(t >= opening_month for t in self.covered_months()):
            raise ValueError("opening history must precede the simulation")
        if not isclose(sum(float(r.account_component) for r in history.worker_opening),
                       person.worker_balance, rel_tol=1e-10, abs_tol=1e-7):
            raise ValueError("opening employee account components do not sum to the ledger balance")
        if sum(a+b for _,a,b in self.resident.values()) > person.resident_balance:
            raise ValueError("opening resident prior principal exceeds the account balance")

    def covered_months(self):
        for record, _ in self.worker:
            yield record.month
        for months, _, _ in self.resident.values():
            yield from months

    def add_worker_credit(self, t, amount, is_employee):
        identity = "employee" if is_employee else "individual"
        r = WorkerMonth(t, self.history.normal_worker_region, identity, str(amount))
        self.worker.append((r,t))

    def add_resident_credit(self, t, personal_principal):
        y = t // 12
        months, own, collective = self.resident.get(y,(set(),Fraction(),Fraction()))
        if t in months:
            raise ValueError("duplicate resident coverage after initialization")
        self.resident[y] = (months | {t}, own + Fraction(str(personal_principal)), collective)

    def adjudicate(self, t, worker_balance, resident_balance, legal, resident_age, threshold):
        grown = [
            WorkerMonth(r.month, r.region, r.identity,
                        str(float(r.account_component) * (1 + self.rate)**(t-posted)), r.temporary)
            for r,posted in self.worker
        ]
        if not isclose(sum(float(r.account_component) for r in grown),worker_balance,
                       rel_tol=1e-10, abs_tol=1e-7):
            raise ArithmeticError("monthly employee contribution ledger mismatch")
        years = [ResidentYear(y,frozenset(months),own,collective)
                 for y,(months,own,collective) in sorted(self.resident.items())]
        h=self.history
        return reconcile(worker_rows=grown,resident_years=years,
                         resident_account=str(resident_balance), deemed_by_region=h.deemed_by_region,
                         deemed_for_resident=h.deemed_for_resident, choice_by_month=h.choice_by_month,
                         normal_region=h.normal_worker_region,hukou_region=h.hukou_region,
                         resident_region=h.receiving_resident_region,decision_month=t,worker_legal_month=legal,
                         employee_threshold=threshold, resident_legal_month=resident_age, request_confirmed=True,
                         threshold_reference=h.threshold_reference)
