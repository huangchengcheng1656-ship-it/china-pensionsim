"""Transaction-free calculations for documented first-pillar histories."""
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from itertools import groupby


def money(value):
    """Exact amount from a decimal string or integer yuan; reject binary floats."""
    if not isinstance(value, (str, int, Fraction)) or isinstance(value, bool):
        raise ValueError("specify exact monetary values as yuan integers or decimal strings")
    value = Fraction(value)
    if value < 0:
        raise ValueError("negative account component")
    return value


@dataclass(frozen=True)
class WorkerMonth:
    month: int  # year * 12 + month - 1
    region: str
    identity: str  # work-based insurance, or same system via individual payment
    account_component: Fraction
    temporary: bool = False

    def __post_init__(self):
        object.__setattr__(self, "account_component", money(self.account_component))
        if type(self.month) is not int or self.month < 0 or not self.region:
            raise ValueError("invalid insurance month or province")
        if self.identity not in ("employee", "individual"):
            raise ValueError("unsupported insured identity")


@dataclass(frozen=True)
class ResidentYear:
    year: int
    covered_months: frozenset[int]
    own_principal: Fraction
    collective_principal: Fraction

    def __post_init__(self):
        object.__setattr__(self, "own_principal", money(self.own_principal))
        object.__setattr__(self, "collective_principal", money(self.collective_principal))
        if type(self.year) is not int or self.year <= 0 or not self.covered_months:
            raise ValueError("declare the documented resident covered months")
        if any(type(m) is not int or m // 12 != self.year for m in self.covered_months):
            raise ValueError("resident months must lie within the declared year")


@dataclass(frozen=True)
class Transfer:
    direction: str
    decision_month: int
    benefit_region: str
    worker_credit_before: int
    resident_credit_before: int
    overlapping_months: int
    credited_months_after: int
    resident_own_refund: Fraction
    resident_collective_refund: Fraction
    amount_moved: Fraction
    final_account: Fraction
    worker_account_cleared_elsewhere: Fraction


def keep_employee_months(rows, choice_by_month):
    """Apply current same-scheme identity priority; report removed account separately."""
    kept, cleared = [], []
    for t, items in groupby(sorted(rows, key=lambda r: r.month), key=lambda r: r.month):
        items = list(items)
        if len({r.region for r in items}) != len(items):
            raise ValueError("multiple records in the same province require administrative reconciliation")
        preferred = [r for r in items if r.identity == "employee"] or items
        if len(preferred) == 1:
            row = preferred[0]
        else:
            selected = [r for r in preferred if r.region == choice_by_month.get(t)]
            if not selected:
                raise ValueError("insured person's retention choice is missing for duplicate same-identity months")
            row = selected[0]
        kept.append(row)
        cleared.extend(r for r in items if r != row)
    return kept, cleared


def benefit_location(worker_rows, normal_region, hukou_region, deemed_by_region):
    """Use documented ordinary relationship and credited province histories."""
    if not normal_region or not hukou_region:
        raise ValueError("document the household register and ordinary worker relationship province")
    if any(type(n) is not int or n < 0 for n in deemed_by_region.values()):
        raise ValueError("deemed months must be explicitly verified and nonnegative")
    if normal_region == hukou_region:
        return hukou_region
    normal = [r for r in worker_rows if not r.temporary]
    count = Counter(r.region for r in normal)
    count.update(deemed_by_region)
    if count[normal_region] >= 120:
        return normal_region
    previous = {r.region: r.month for r in normal if r.region != normal_region}
    uncertain = {r for r in count if r != normal_region and count[r] >= 120 and r not in previous}
    if uncertain:
        raise ValueError("ten-year province with no verified ordinary relationship order")
    for region in sorted(previous, key=previous.__getitem__, reverse=True):
        if count[region] >= 120:
            return region
    return hukou_region


def reconcile(*, worker_rows, resident_years, resident_account, deemed_by_region,
              deemed_for_resident, choice_by_month, normal_region, hukou_region,
              resident_region, decision_month, worker_legal_month, employee_threshold,
              resident_legal_month, resident_threshold=180, request_confirmed=False,
              already_in_pay=False, threshold_reference=None):
    """Compute one approved event, using verified histories as of the decision month.

    Include only account values still due to be collected or merged at this event.
    Each worker credit and balance contribution is supplied after upstream statements
    have reconciled principal and interest to the decision date.
    """
    if not request_confirmed or already_in_pay or decision_month < worker_legal_month:
        raise ValueError("this prospective interface requires a verified post-age application without existing payments")
    if any(type(n) is not int or n <= 0 for n in (employee_threshold, resident_threshold)):
        raise ValueError("positive monthly eligibility thresholds required")
    if decision_month >= 2030 * 12 and threshold_reference not in (
            "documented_local_interpretation", "declared_scenario"):
        raise ValueError("post-2029 cross-scheme threshold basis must be declared")
    resident_years = tuple(resident_years)
    if len({y.year for y in resident_years}) != len(resident_years):
        raise ValueError("provide one resident account principal entry per year")
    resident_balance = money(resident_account)
    kept, cleared = keep_employee_months(worker_rows, choice_by_month)
    worker_dates = {r.month for r in kept}
    # Adjudication happens at the end of the decision month, after that month's posting.
    if any(t > decision_month for t in worker_dates):
        raise ValueError("future credits cannot enter eligibility")
    if any(type(n) is not int or n < 0 for n in deemed_by_region.values()):
        raise ValueError("document the province-level deemed credit")
    deemed_total = sum(deemed_by_region.values())
    if type(deemed_for_resident) is not int or not 0 <= deemed_for_resident <= deemed_total:
        raise ValueError("document the separate deemed credit for resident conversion")
    worker_credit, resident_credit, overlaps = len(kept) + deemed_total, 0, 0
    own = collective = Fraction()
    resident_principal = Fraction()
    for year in resident_years:
        if any(t > decision_month for t in year.covered_months):
            raise ValueError("future resident credits cannot enter eligibility")
        covered = year.covered_months
        resident_credit += len(covered)
        n = len(covered & worker_dates)
        overlaps += n
        resident_principal += year.own_principal + year.collective_principal
        own += year.own_principal * n / 12
        collective += year.collective_principal * n / 12
    if resident_principal > resident_balance:
        raise ValueError("documented resident principal exceeds the supplied account balance")
    net_resident = resident_balance - own - collective
    worker_balance = sum((row.account_component for row in kept), Fraction())
    cleared_balance = sum((row.account_component for row in cleared), Fraction())
    to_worker = worker_credit >= employee_threshold
    resident_after = len(kept) + deemed_for_resident + resident_credit - overlaps
    if to_worker:
        location = benefit_location(kept, normal_region, hukou_region, deemed_by_region)
        direction, amount, credits = "resident_to_employee", net_resident, worker_credit
    else:
        if not resident_region:
            raise ValueError("document the destination resident insurance region")
        location = resident_region
        direction, amount, credits = "employee_to_resident", worker_balance, resident_after
    first_pay_candidate = to_worker or (decision_month >= resident_legal_month and credits >= resident_threshold)
    event = Transfer(direction, decision_month, location, worker_credit, resident_credit,
                     overlaps, credits, own, collective, amount, net_resident + worker_balance, cleared_balance)
    return event, first_pay_candidate
