from dataclasses import dataclass, field
from math import isclose
from random import Random
from .access import validate_path
from .annuity import Entitlement, exit_job
from .history import ActiveHistory
from .rules import minimum_months, month, payout_divisor, progressive_tax, retirement_month, worker_benefit
from .flows import source_limit, source_row, annuity_row


@dataclass(frozen=True)
class Scenario:
    name: str
    age_reform: bool = True
    minimum_reform: bool = True
    subsidy: float = 0.0
    annuity_expansion: float = 0.0
    protect_annuity_vesting: bool = False
    personal_deduction: bool = True
    flat: float = 0.0
    match: float = 0.0
    default: bool = False
    response: float = 1.0
    history_shift: int = 0
    divisor: str = "linear"
    extension_months: int = 24
    return_shift: float = 0.0
    subsidy_delay_months: int = 0


@dataclass(frozen=True)
class Person:
    birth: int
    category: str
    job: str
    wage: float
    cash: float
    liquid: float
    worker_paid: int
    worker_deemed: int
    resident_paid: int
    worker_index: float
    worker_balance: float
    resident_balance: float
    corporate_owned: float
    corporate_pending: float
    occupational: float
    personal: float
    self_employed: bool
    government_job: bool
    debtservice: float
    seed: int


@dataclass
class Account:
    opening: float
    balance: float = field(init=False)
    contributions: float = 0.0
    earnings: float = 0.0
    net_transfer: float = 0.0
    payouts: float = 0.0
    forfeitures: float = 0.0

    def __post_init__(self):
        self.balance = self.opening

    def grow(self, rate):
        earned = self.balance * rate
        self.earnings += earned
        self.balance += earned

    def add(self, amount):
        self.contributions += amount
        self.balance += amount

    def transfer(self, other):
        self.move_amount(other, self.balance)

    def move_amount(self, other, amount):
        if not 0 <= amount <= self.balance:
            raise ValueError("partial transfer exceeds balance")
        self.net_transfer -= amount
        self.balance -= amount
        other.net_transfer += amount
        other.balance += amount

    def draw(self, amount):
        actual = min(amount, self.balance)
        self.balance -= actual
        self.payouts += actual
        return actual

    def forfeit(self):
        self.forfeitures += self.balance
        self.balance = 0.0

    def check(self):
        expected = (self.opening + self.contributions + self.earnings
                    + self.net_transfer - self.payouts - self.forfeitures)
        if self.balance < -1e-7 or not isclose(self.balance, expected, rel_tol=1e-10, abs_tol=1e-7):
            raise ArithmeticError("account reconciliation failed")


class ResidentSchedule:
    """Cash paid once; elapsed coverage in a paid year enters the staged ledger."""
    def __init__(self, terms):
        self.terms = terms
        self.year = None
        self.cleared = False
        self.pending_months = []

    def terms_for_month(self, t, eligible):
        y, m = divmod(t,12)
        if self.year != y:
            self.year, self.cleared, self.pending_months = y, False, []
        if eligible:
            self.pending_months.append(t)
        if not eligible or self.cleared or m+1 != self.terms.resident_payment_month:
            return None
        return self.terms.resident(t)

    def settle(self, eligible, paid_now):
        if paid_now:
            if self.cleared:
                raise ValueError("a resident year cannot be paid twice")
            self.cleared = True
        if eligible and self.cleared:
            months, self.pending_months = self.pending_months, []
            return months
        return []


def tax_annual(base, deductible):
    return progressive_tax(base - 60000 - deductible, annual=True)


def route_job(rng, config, previous):
    transitions = config["annual_transitions"][previous]
    return rng.choices(list(transitions), list(transitions.values()))[0]

LEDGER_FIELDS = ('worker_p1_subsidy', 'p3_public_reward', 'personal_deduction', 'worker_gross_receipts', 'resident_member_receipts', 'resident_member_receipts_pv', 'resident_public_credit', 'p1_benefits', 'retirement_tax', 'employer_annuity')

def simulate(p, s, cfg, *, job_path=None, annual_ledger=None, claim_snapshot=None, verified_history=None, transfer_events=None,
             annuity_exits=None, annuity_events=None, reference_assets=None, local_terms=None, monthly_trace=None, terminal=None, access_path=None, access_log=None, mobility_trace=None, source_mode="legacy_once",
             source_reserve=0., source_trace=None, annuity_trace=None, legal_vesting=True):
    start = month(cfg["start_year"], 1)
    common_reference = retirement_month(p.birth, p.category) + 1
    legal = retirement_month(p.birth, p.category, s.age_reform)
    resident_age = p.birth + 60 * 12
    last = month(cfg["last_year"], 12)
    if job_path is not None:
        if len(job_path) != last - start + 1 or job_path[0] != p.job:
            raise ValueError("job path must cover the full cashflow window and start at the observed state")
        if set(job_path) - {"standard", "nonstandard", "out"}:
            raise ValueError("unknown employment state")
    if access_path is not None:
        validate_path(access_path, last-start+1)
    if access_log is not None and access_log:
        raise ValueError("pass an empty access trace")
    if annual_ledger is not None and annual_ledger:
        raise ValueError("pass an empty annual ledger for each simulation")
    if verified_history is not None and s.history_shift:
        raise ValueError("history stress requires an alternative documented history")
    if verified_history is not None and not max(start, legal) <= verified_history.decision_month < last:
        raise ValueError("the modeled adjudication month must follow legal age and permit a payment in the window")
    if annuity_exits is not None and any(type(t) is not int or not start <= t <= last for t in annuity_exits):
        raise ValueError("dated enterprise annuity exits must be inside the simulation window")
    if terminal is not None and terminal:
        raise ValueError("pass an empty terminal mapping")
    if reference_assets is not None and reference_assets:
        raise ValueError("pass an empty reference-assets mapping")
    if claim_snapshot is not None and claim_snapshot:
        raise ValueError("pass an empty claim snapshot for each simulation")
    if s.subsidy_delay_months < 0:
        raise ValueError("subsidy lag must be nonnegative")
    if local_terms is not None and verified_history is not None:
        if (verified_history.normal_worker_region != local_terms.worker_region
                or verified_history.receiving_resident_region != local_terms.resident_region):
            raise ValueError("opening/current contribution and resident domains must match local rules")
    resident_schedule = ResidentSchedule(local_terms) if local_terms is not None else None
    reimbursements = {}
    rng = Random(p.seed)
    job = p.job
    # This staged draw shifts a positive history for sensitivity; no inferred national stock.
    worker_paid = max(0, p.worker_paid + s.history_shift)
    deemed = p.worker_deemed
    indexed_sum = p.worker_index * (worker_paid + deemed)
    resident_paid = p.resident_paid
    if not p.worker_paid and s.history_shift:
        raise ValueError("specify a separate account balance scenario when opening worker months are zero")
    opening_worker = p.worker_balance if not s.history_shift else p.worker_balance * worker_paid / p.worker_paid
    worker = Account(opening_worker)
    resident = Account(p.resident_balance)
    owned = Account(p.corporate_owned)
    pending = Account(p.corporate_pending)
    occupational = Account(p.occupational)
    personal = Account(p.personal)
    liquid = Account(p.liquid)
    accounts = (worker, resident, owned, pending, occupational, personal, liquid)
    portfolio = (owned, occupational, personal)
    returns = {k: (1 + r + (s.return_shift if k != "liquid" else 0)) ** (1 / 12) - 1
               for k, r in cfg["annual_returns"].items()}
    detailed = ActiveHistory(verified_history, p, start, returns["p1"]) if verified_history is not None else None
    transfer = None
    personal_ytd = deductible_ytd = taxable_ytd = last_wage = 0.0
    regular_months = 0
    regime = "worker"  # synthetic affiliation can persist with no payment
    route = "unclaimed"
    retired_at = None
    claimed = [0.0] * 4
    draws = [0.0] * 3
    budget = direct_subsidy = tax_cost = receipts = employer_cost = gross_benefits = p1_benefit_pv = retirement_tax_pv = consumption_shortfall = 0.0
    switches = worker_nonpay = no_first_pillar_payment = contribution_observation_months = 0
    at_reference = None
    first_annual = []
    eligible_at_legal = None
    fallback = False
    offer = False
    account_payout = 0.0
    for t in range(start, last + 1):
        y, m = divmod(t, 12)
        pv = (1 + cfg["pv_annual_rate"]) ** ((start - t) / 12)
        if m == 0:
            if annual_ledger is not None:
                ledger = dict.fromkeys(LEDGER_FIELDS, 0.0)
                annual_ledger[y] = ledger
            personal_ytd = deductible_ytd = taxable_ytd = 0.0
        # Consume the same random draws in every scenario, regardless of policy or claim.
        prev_job = job
        if m == 0:
            candidate = route_job(rng, cfg, job)
            if t > start:
                job = candidate
        if job_path is not None:
            job = job_path[t - start]
        u_pay, u_cover, u_personal, u_optout = (rng.random() for _ in range(4))
        if t == start or prev_job != job:
            existing_offer = t == start and p.corporate_owned > 0
            offer = existing_offer or u_cover < min(1.0, cfg["annuity_coverage_chance"] + s.annuity_expansion)
        p3_open_before_growth = personal.balance
        ordinary_open_before_growth = liquid.balance
        a_open = (owned.balance, pending.balance, occupational.balance)
        a_forfeit = pending.forfeitures
        a_cond_xfer = pending.net_transfer
        a_econ = a_efirm = a_ocon = a_ofirm = 0.0
        a_gross = (0.,0.)
        a_eligible = False
        new_offer_assign = False
        for acct, name in zip(accounts, ("p1", "p1", "p2", "p2", "p2", "p3", "liquid")):
            acct.grow(returns[name])

        p3_before_withdraw = personal.balance
        p3_gross = 0.0
        source_work = None
        cash_resident = cash_government = cash_worker = cash_own_worker = cash_subsidy = 0.0
        cash_personal_reward = cash_tax_deduction = cash_retirement_tax = cash_p1_benefit = 0.0
        refund_cash = 0.0
        current_resident_credit = False
        household_net_cash = household_cash_gap = 0.0
        reimbursed = reimbursements.pop(t, 0.0)
        if reimbursed:
            direct_subsidy += pv * reimbursed
            if annual_ledger is not None:
                ledger["worker_p1_subsidy"] += reimbursed

        mobility_open_liquid = liquid.balance
        mobility_p3 = mobility_p2_own = mobility_p2_firm = 0.0
        mobility_retirement = (0.0, 0.0, 0.0)
        if legal_vesting and t >= legal:
            pending.transfer(owned)
        confirmed_exit = annuity_exits.get(t) if annuity_exits else None
        if confirmed_exit is not None:
            if retired_at is not None:
                raise ValueError("this job-exit interface requires a worker who has not started pension claim")
            opening_annuity = Entitlement(enterprise_employer=str(pending.balance))
            settlement = exit_job(opening_annuity, **confirmed_exit)
            vested = float(settlement["preserved"].enterprise_employer)
            pending.move_amount(owned, vested)
            pending.forfeit()
            regular_months = 0
            offer = job == "standard" and settlement["receiving_plan"] == "enterprise"
            if annuity_events is not None:
                annuity_events.append(dict(month=t, vested=vested,
                                           reversion=float(settlement["returns_to_enterprise_plan"]),
                                           receiving_plan=settlement["receiving_plan"]))
        if retired_at is None:
            threshold = minimum_months(y, s.minimum_reform)
            if t == legal:
                eligible_at_legal = worker_paid + deemed >= threshold
            if detailed is not None and transfer is None and t == verified_history.decision_month:
                transfer, payable = detailed.adjudicate(t, worker.balance, resident.balance, legal, resident_age, threshold)
                cleared = float(transfer.worker_account_cleared_elsewhere)
                worker.draw(cleared)
                refund_cash = float(transfer.resident_own_refund + transfer.resident_collective_refund)
                liquid.add(resident.draw(refund_cash))
                if transfer.direction == "resident_to_employee":
                    resident.transfer(worker)
                    route = "worker"
                    account_payout = worker.balance / payout_divisor(t - p.birth, s.divisor)
                    if local_terms is not None and transfer.benefit_region != local_terms.worker_region:
                        raise ValueError("validate a retirement base for the determined benefit region")
                    pension_base = (float(local_terms.employee(t).retirement_base)
                                    if local_terms is not None else cfg["pension_base"])
                    claimed[0] = worker_benefit(pension_base, indexed_sum / (worker_paid + deemed),
                                                transfer.credited_months_after, worker.balance, t - p.birth, s.divisor)
                    retired_at = t
                    receiving = worker
                else:
                    worker.transfer(resident)
                    fallback = True
                    resident_paid = transfer.credited_months_after
                    receiving = resident
                    if payable:
                        route = "resident"
                        account_payout = resident.balance / 139
                        claimed[0] = (local_terms.resident_benefit(t) if local_terms is not None else cfg["resident_basic"]) + account_payout
                        retired_at = t
                if not isclose(receiving.balance, float(transfer.final_account), rel_tol=1e-10, abs_tol=1e-7):
                    raise ArithmeticError("combined account balance disagrees with administrative reconciliation")
                if transfer_events is not None:
                    transfer_events.append(transfer)
            elif detailed is not None and fallback and t >= resident_age and resident_paid >= 180:
                route = "resident"
                account_payout = resident.balance / 139
                claimed[0] = (local_terms.resident_benefit(t) if local_terms is not None else cfg["resident_basic"]) + account_payout
                retired_at = t
            elif detailed is None and t >= legal and not fallback and worker_paid + deemed >= threshold:
                resident.transfer(worker)
                route = "worker"
                account_payout = worker.balance / payout_divisor(t - p.birth, s.divisor)
                pension_base = (float(local_terms.employee(t).retirement_base)
                                if local_terms is not None else cfg["pension_base"])
                claimed[0] = worker_benefit(pension_base, indexed_sum / (worker_paid + deemed),
                                            worker_paid + deemed, worker.balance, t - p.birth, s.divisor)
                retired_at = t
            elif detailed is None and t >= legal + s.extension_months:
                fallback = True
                # No top-up grandfathering. The demo uses actual employee months in this route.
                if t >= resident_age and worker_paid + resident_paid >= 180:
                    worker.transfer(resident)
                    route = "resident"
                    account_payout = resident.balance / 139
                    claimed[0] = (local_terms.resident_benefit(t) if local_terms is not None else cfg["resident_basic"]) + account_payout
                    retired_at = t

        if reimbursed and retired_at is not None:
            liquid.add(reimbursed)

        if retired_at == t:
            pending.transfer(owned)  # retirement triggers full corporate vesting
            if claim_snapshot is not None:
                claim_snapshot.update(retirement_month=t, first_payment_month=t+1,
                                      p1_monthly_gross=claimed[0], enterprise_vested=owned.balance,
                                      occupational=occupational.balance, personal=personal.balance,
                                      liquid=liquid.balance, corporate_mode="finite",
                                      occupational_mode="finite", personal_mode="finite")
            draws = [owned.balance / cfg["annuity_draw_months"],
                     occupational.balance / cfg["annuity_draw_months"],
                     personal.balance / cfg["personal_draw_months"]]

        if retired_at is not None and t > retired_at:
            elapsed = t - retired_at - 1
            limits = (cfg["annuity_draw_months"], cfg["annuity_draw_months"], cfg["personal_draw_months"])
            drawn = [a.draw(amt) if elapsed < span - 1 else a.draw(a.balance)
                     if elapsed == span - 1 else 0.0
                     for a, amt, span in zip(portfolio, draws, limits)]
            a_gross = (drawn[0], drawn[1])
            combined = drawn[0] + drawn[1]
            annuity_net = combined - progressive_tax(combined, annual=False)
            claimed[1] = annuity_net * drawn[0] / combined if combined else 0.0
            claimed[2] = annuity_net * drawn[1] / combined if combined else 0.0
            claimed[3] = drawn[2] * 0.97
            p3_gross = drawn[2]
            mobility_retirement = tuple(claimed[1:])
            (worker if route == "worker" else resident).draw(account_payout)
            gross_benefits += pv * (claimed[0] + sum(drawn))
            p1_benefit_pv += pv * claimed[0]
            retirement_tax = sum(drawn) - sum(claimed[1:])
            retirement_tax_pv += pv * retirement_tax
            cash_retirement_tax, cash_p1_benefit = retirement_tax, claimed[0]
            if annual_ledger is not None:
                ledger["p1_benefits"] += claimed[0]
                ledger["retirement_tax"] += retirement_tax
            if elapsed < 12:
                first_annual.append(sum(claimed))

        if retired_at is None:
            # Employer/contract category drives employment. Affiliation and payment are separate.
            current_regime = "resident" if fallback or (job != "standard" and p.self_employed) else (
                regime if job == "out" else "worker")
            access = access_path[t-start] if access_path is not None else None
            access_open = access is None or access.can_post
            if access is not None:
                current_regime = "resident" if fallback else access.affiliation
            switches += int(current_regime != regime)
            regime = current_regime
            gross = p.wage * {"standard": 1.0, "nonstandard": .72, "out": 0}[job]
            formal = job == "standard" and regime == "worker"
            calendar_rules = local_terms.employee(t) if local_terms is not None and regime == "worker" and job != "out" else None
            if calendar_rules is None:
                worker_base = min(cfg["p1_worker_max_base"], max(cfg["p1_worker_min_base"], gross))
                wage_reference = cfg["pension_base"]
            else:
                worker_base = float(calendar_rules.clamp_base(gross))
                wage_reference = float(calendar_rules.retirement_base)
            if calendar_rules is None:
                insured_rate = cfg["worker_employee_rate" if formal else "worker_flexible_rate"]
                employer_rate = cfg["worker_standard_employer_rate"]
                account_rate = cfg["worker_account_rate"]
            else:
                insured_rate = (calendar_rules.ordinary_employee_person_rate if formal
                                else calendar_rules.flexible_employment_rate)
                employer_rate = calendar_rules.employer_example_rate
                account_rate = calendar_rules.individual_account_credit_rate
            requested = insured_rate * worker_base
            intended = access_open and regime == "worker" and (formal or (job != "out" and
                u_pay < min(1, cfg["p1_subsidy_base_chance"] + s.response * s.subsidy / 1000)))
            resident_active = access_open and regime == "resident" and (job != "out" or fallback)
            worker_subsidy = min(s.subsidy, requested * 2 / 3) if intended and not formal else 0.0
            upfront_support = 0.0 if s.subsidy_delay_months else worker_subsidy

            current_cash = gross + p.cash - p.debtservice + reimbursed
            essential = cfg["expense_floor_share"] * (p.wage * .56 + p.cash)
            # Use an annual cumulative tax schedule. Prior months' deductions are carried.
            tax_at_start = tax_annual(taxable_ytd, deductible_ytd)
            taxable_ytd += gross
            conservative_tax = tax_annual(taxable_ytd, deductible_ytd) - tax_at_start
            funds = current_cash - essential - conservative_tax
            liquid_draw = min(cfg["allowed_liquid_draw"], liquid.balance)

            paid = intended and (formal or funds + liquid_draw >= requested - upfront_support)
            own1 = 0.0
            if paid:
                own1 = requested - upfront_support
                worker_credit = account_rate * worker_base
                worker.add(worker_credit)
                if detailed is not None:
                    detailed.add_worker_credit(t, worker_credit, formal)
                worker_paid += 1
                indexed_sum += worker_base / wage_reference
                employer = employer_rate * worker_base if formal else 0.0
                cash_worker, cash_own_worker, cash_subsidy = requested + employer, own1, upfront_support
                receipts += cash_worker * pv
                direct_subsidy += pv * upfront_support
                if worker_subsidy and s.subsidy_delay_months:
                    reimbursements[t + s.subsidy_delay_months] = worker_subsidy
                if annual_ledger is not None:
                    ledger["worker_p1_subsidy"] += upfront_support
                    ledger["worker_gross_receipts"] += requested + employer
            resident_active = resident_active and not paid
            resident_paid_now = False
            if resident_schedule is None:
                if resident_active and funds + liquid_draw >= cfg["resident_own_monthly"]:
                    cash_resident, cash_government = cfg["resident_own_monthly"], cfg["resident_fiscal_monthly"]
                    resident_credits = [t]
                    resident_paid_now = True
                else:
                    resident_credits = []
            else:
                annual_terms = resident_schedule.terms_for_month(t, resident_active)
                resident_paid_now = annual_terms is not None and funds + liquid_draw >= float(annual_terms.own_yuan)
                if resident_paid_now:
                    cash_resident = float(annual_terms.own_yuan)
                    cash_government = float(annual_terms.government_credit_yuan)
                resident_credits = resident_schedule.settle(resident_active, resident_paid_now)
            current_resident_credit = t in resident_credits
            own1 += cash_resident
            resident.add(cash_resident + cash_government)
            resident_paid += len(resident_credits)
            if detailed is not None and transfer is None and resident_credits:
                for credited_t in resident_credits:
                    detailed.add_resident_credit(credited_t, cash_resident if credited_t == t else 0)
            if annual_ledger is not None and resident_paid_now:
                ledger["resident_member_receipts"] += cash_resident
                ledger["resident_member_receipts_pv"] += pv * cash_resident
                ledger["resident_public_credit"] += cash_government
            if access_log is not None:
                access_log.append(dict(month=t, employment=job, affiliation=regime, access_open=access_open,
                                       worker_intended=intended, worker_posted=paid,
                                       resident_cash_posted=resident_paid_now,
                                       resident_current_credit=current_resident_credit,
                                       worker_total=worker_paid, resident_total=resident_paid))
            worker_nonpay += int(not paid)
            no_first_pillar_payment += int(not paid and not resident_paid_now)
            contribution_observation_months += 1
            funds -= own1

            # Static offer within continuous employment. The first eight years are the
            # declared maximum vesting demo. A lost offer does not erase owned balances.
            if confirmed_exit is None and prev_job != job and prev_job == "standard":
                if s.protect_annuity_vesting:
                    pending.transfer(owned)
                else:
                    pending.forfeit()
                regular_months = 0
            if formal and p.government_job:
                own2, firm2 = .04 * worker_base, .08 * worker_base
                occupational.add(own2 + firm2)
            elif formal and offer:
                own2 = cfg["employee_annuity_rate"] * worker_base
                firm2 = cfg["employer_annuity_rate"] * worker_base
                owned.add(own2)
                if regular_months >= 96 or (legal_vesting and t >= legal):
                    owned.add(firm2)
                else:
                    pending.add(firm2)
            else:
                own2 = firm2 = 0.0
            if formal:
                regular_months += 1
                if regular_months == 96:
                    pending.transfer(owned)
            a_eligible = formal and not p.government_job and offer
            new_offer_assign = bool(a_eligible and (t==start or prev_job!=job) and
                 not existing_offer and cfg["annuity_coverage_chance"]<=u_cover<
                 min(1.,cfg["annuity_coverage_chance"]+s.annuity_expansion))
            a_econ,a_efirm=(own2,firm2) if not p.government_job else (0.,0.)
            a_ocon,a_ofirm=(own2,firm2) if p.government_job else (0.,0.)
            mobility_p2_own, mobility_p2_firm = own2, firm2
            funds -= own2
            employer_cost += pv * firm2

            choice = min(1.0, cfg["personal_chance"] + s.response * (s.match * .27 + s.flat / 1000))
            participate = u_personal < choice or (s.default and u_optout > .48)
            authorized = min(cfg["personal_candidate"], cfg["annual_personal_cap"] - personal_ytd)
            own3 = min(authorized, source_limit(funds, liquid_draw, liquid.balance, source_mode, source_reserve)) if participate else 0.0
            if own3:
                reward = min(s.flat, own3) + s.match * own3
                personal.add(own3 + reward)
            else:
                reward = 0.0
            mobility_p3 = own3
            deductible = own3 if s.personal_deduction else 0.0
            tax_after = tax_annual(taxable_ytd, deductible_ytd + deductible)
            tax_saved = max(0.0, tax_annual(taxable_ytd, deductible_ytd) - tax_after)
            source_work = (funds, liquid_draw, conservative_tax, conservative_tax-tax_saved, essential,
                           p.debtservice, own1, own2, bool(paid), liquid.balance, tax_saved)
            personal_ytd += own3
            deductible_ytd += deductible
            direct_subsidy += pv * reward
            tax_cost += pv * tax_saved
            cash_personal_reward, cash_tax_deduction = reward, tax_saved
            household_net_cash = funds + tax_saved - own3
            if annual_ledger is not None:
                ledger["p3_public_reward"] += reward
                ledger["personal_deduction"] += tax_saved
                ledger["employer_annuity"] += firm2
            funds += tax_saved - own3
            if funds < 0:
                deficit = -funds - liquid.draw(min(-funds, liquid_draw))
                household_cash_gap = max(0.0, deficit)
                consumption_shortfall += household_cash_gap
            else:
                liquid.add(funds)
            last_wage = gross if gross > 0 else last_wage

        if annuity_trace is not None:
            annuity_trace.append(annuity_row(t,pv,job,p.government_job,a_open,
                (owned.balance,pending.balance,occupational.balance),returns["p2"],
                a_econ,a_efirm,a_ocon,a_ofirm,a_cond_xfer-pending.net_transfer,pending.forfeitures-a_forfeit,
                a_eligible,new_offer_assign,a_gross,mobility_retirement[:2]))
        if source_trace is not None:
            source_trace.append(source_row(t,job,ordinary_open_before_growth,p3_open_before_growth,
                liquid.balance,personal.balance,p3_before_withdraw,p3_gross,mobility_p3,
                cash_personal_reward,mobility_retirement[2],source_work,returns["liquid"],returns["p3"],
                household_cash_gap,refund_cash,reimbursed if retired_at is not None else 0.0))
        if mobility_trace is not None:
            mobility_trace.append(dict(month=t, employment=job, route=route,
                 active=retired_at is None, p1=cash_p1_benefit,
                 enterprise_net=mobility_retirement[0], occupational_net=mobility_retirement[1],
                 p2=sum(mobility_retirement[:2]), p3=mobility_retirement[2],
                 p3_own=mobility_p3, p3_subsidy=cash_personal_reward, tax_deduction=cash_tax_deduction,
                 p2_own=mobility_p2_own, p2_employer=mobility_p2_firm,
                 enterprise_vested_end=owned.balance, enterprise_pending_end=pending.balance,
                 personal_account_end=personal.balance, ordinary_open=mobility_open_liquid,
                 ordinary_end=liquid.balance, worker_balance_end=worker.balance, resident_balance_end=resident.balance))
        if monthly_trace is not None:
            monthly_trace.append(dict(month=t, rate_discount=pv, resident_own=cash_resident,
                                      resident_public=cash_government, worker_receipts=cash_worker,
                                      worker_household_cash=cash_own_worker, worker_subsidy=cash_subsidy + reimbursed,
                                      personal_public_reward=cash_personal_reward, tax_deduction=cash_tax_deduction,
                                      p1_benefit=cash_p1_benefit, retirement_tax=cash_retirement_tax,
                                      household_preretirement_surplus=household_net_cash,
                                      household_preretirement_shortfall=household_cash_gap,
                                      overlap_refund=refund_cash, open_subsidy=sum(reimbursements.values()),
                                      resident_cover_booked_in_this_event=current_resident_credit,
                                      resident_credited_total=resident_paid))
        if t == common_reference:
            if reference_assets is not None:
                reference_assets.update(month=t, ordinary_liquid=liquid.balance,
                                        corporate_vested=owned.balance, corporate_conditional=pending.balance,
                                        occupational=occupational.balance, personal_pension=personal.balance,
                                        worker_book_balance=worker.balance,resident_book_balance=resident.balance)
            paid_now = retired_at is not None and t > retired_at
            cashflow = claimed if paid_now else [0.0] * 4
            at_reference = (sum(cashflow), cashflow[0], cashflow[1] + cashflow[2], cashflow[3], liquid.balance,
                            not paid_now)

    if terminal is not None:
        terminal.update(as_of_month=last, route=route, worker_credited=worker_paid + deemed,
                        resident_credited=resident_paid, first_payment_month=None if retired_at is None else retired_at + 1,
                        p1_monthly_gross=claimed[0] if retired_at is not None else None,
                        worker_account=worker.balance, resident_account=resident.balance,
                        enterprise_vested=owned.balance, enterprise_contingent=pending.balance,
                        occupational_account=occupational.balance, personal_account=personal.balance,
                        unsettled_subsidy_by_due_month=dict(sorted(reimbursements.items())))
    budget = direct_subsidy + tax_cost
    awaiting_reimbursement = sum(reimbursements.values())
    for a in accounts:
        a.check()
    if not isclose(sum(a.net_transfer for a in accounts), 0, abs_tol=1e-7):
        raise ArithmeticError("transfers do not balance")
    if at_reference is None:
        raise ValueError("synthetic cohort falls outside configured reporting horizon")
    income, p1, p2, p3, liquid_ref, no_payment = at_reference
    first_year = sum(first_annual) / 12 if len(first_annual) == 12 else None
    return dict(reference_income=income, p1=p1, p2=p2, p3=p3, liquid=liquid_ref,
                retirement_gap=max(0, cfg["benchmark_monthly"] - income), route=route,
                no_payment=no_payment, final_unclaimed=retired_at is None,
                payment_lag_months=None if retired_at is None else retired_at + 1 - common_reference,
                eligible_at_legal=eligible_at_legal, switches=switches, worker_nonpay=worker_nonpay,
                no_first_pillar_payment=no_first_pillar_payment, active_months=contribution_observation_months,
                taxpayer_budget=budget, direct_subsidy=direct_subsidy, tax_cost=tax_cost,
                p1_benefit_pv=p1_benefit_pv, retirement_tax_pv=retirement_tax_pv,
                unsettled_subsidy=awaiting_reimbursement,
                employer_cost=employer_cost, contributions=receipts, gross_pension_pv=gross_benefits,
                first_year=first_year, replacement=(first_year / last_wage
                                                      if last_wage and first_year is not None else None),
                consumption_shortfall=consumption_shortfall)
