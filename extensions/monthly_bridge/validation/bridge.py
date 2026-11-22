"""Check a CHFS-style opening cash comparison against the frozen monthly engine."""
from argparse import ArgumentParser
from dataclasses import dataclass
from hashlib import sha256
import json
from math import fsum, isclose
from pathlib import Path
import sys

from extensions.contribution_frontier.model.frontier import Plan, STATES, payment_capacity, possible_states

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
POLICY = ROOT / "extensions/contribution_frontier/policy/policy_parameters.json"

# Use the compact release engine and its explicit synthetic cohort.
from pension_core.access import Access
from pension_core.history import History
from pension_core.ledger import Person, Scenario, simulate
from pension_core.portability import WorkerMonth
from pension_core.rules import minimum_months, month, retirement_month

LEGAL = month(2030, 2)
START = month(2029, 1)
OPEN = 12
FOOD_UTILITY = 1500.0
SUPPORT = 150.0
REGION = "synthetic_region"
GUARD = "post-2029 cross-scheme threshold basis must be declared"
WINDOW = (month(2030, 3), month(2031, 2))
CATEGORIES = ("male60", "female55", "female50")


@dataclass(frozen=True)
class Fixture:
    name: str
    opening_months: int
    available_yuan: float
    delay: int = 0
    draw_limit: float = 2600.0


FIXTURES = (
    Fixture("time_short", 168, 10000.0),
    Fixture("immediate", 174, 8910.0),
    Fixture("refund_lag3", 174, 8910.0, delay=3),
    Fixture("draw_cap600", 174, 8910.0, draw_limit=600.0),
    Fixture("cash_short", 180, 0.0),
)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def birth_at_legal(category):
    matches = tuple(candidate for candidate in range(month(1960,1),month(1982,1))
                    if retirement_month(candidate,category) == LEGAL)
    birth, = matches
    return birth


def policy_inputs():
    rules = read_json(POLICY)
    ledger = rules["worker_zhejiang"]
    year, = [row for row in ledger["annual"] if row["year"] == 2023]
    price = float(year["flexible_own_due_at_min"])
    thresholds = rules["first_pillar_eligibility"]["worker_reference_year_thresholds"]
    if (thresholds["2029"],thresholds["2030"]) != (minimum_months(2029),minimum_months(2030)):
        raise ValueError("R51 rule register and R48 thresholds differ.")
    cfg = read_json(ROOT / "data/synthetic/cohort.synthetic.json")["config"]
    cfg.update(start_year=2029, last_year=2039, pension_base=year["new_award_monthly_reference"],
               p1_worker_min_base=year["contribution_base_min"], p1_worker_max_base=year["contribution_base_max"],
               worker_flexible_rate=float(ledger["flexible_own_rate"]),
               worker_account_rate=float(ledger["individual_account_credit_rate"]),
               p1_subsidy_base_chance=1., personal_chance=0., annuity_coverage_chance=0.)
    return cfg, price, (thresholds["2029"],thresholds["2030"])


def plain_month(index):
    if index is None:
        return None
    year, m = divmod(index,12)
    return f"{year:04d}-{m+1:02d}"


def verify_cash(annual, cash):
    for year, totals in annual.items():
        current = [r for r in cash if r["month"]//12 == year]
        for key, trace in (("worker_p1_subsidy","worker_subsidy"),
                           ("worker_gross_receipts","worker_receipts"),
                           ("p1_benefits","p1_benefit"),
                           ("resident_member_receipts","resident_own")):
            if not isclose(totals[key],fsum(r[trace] for r in current),abs_tol=1e-8):
                raise ArithmeticError("Monthly and annual balances disagree.")


def one(category, fixture, threshold, config, price, *, declared=True):
    original = minimum_months(2029)
    reformed = minimum_months(2030)
    if threshold not in (original,reformed):
        raise ValueError("Select the old threshold or the reformed threshold for the common legal month.")
    birth = birth_at_legal(category)
    stock = FOOD_UTILITY + 2 * fixture.available_yuan
    plan = Plan(threshold, OPEN, price, SUPPORT, 1., .5, 0)
    reported = (fixture.opening_months,) * 2
    available, = set(payment_capacity((stock,stock),(FOOD_UTILITY,FOOD_UTILITY),plan))
    static, = possible_states(reported,(stock,stock),(FOOD_UTILITY,FOOD_UTILITY),plan)
    static_pass = static in (STATES[0],STATES[3],STATES[4])

    # Nonstandard work yields just enough to pay household essentials and debt.
    # Pre-reservation makes R51 disposable cash the engine's opening savings.
    cfg = config | {"allowed_liquid_draw":fixture.draw_limit}
    wage = 5000.
    debt = .72*wage - cfg["expense_floor_share"]*.56*wage
    p = Person(birth,category,"nonstandard",wage,0.,available,fixture.opening_months,
               0,0,1.,300.*fixture.opening_months,0.,0.,0.,0.,0.,False,False,debt,271120)
    history = History(tuple(WorkerMonth(t,REGION,"employee","300") for t in range(START-fixture.opening_months,START)),
                      (),REGION,REGION,REGION,{},0,{},LEGAL,"declared_scenario" if declared else None)
    s = Scenario("r52_monthly_bridge",minimum_reform=threshold==reformed,
                 subsidy=SUPPORT,subsidy_delay_months=fixture.delay,response=0.)
    n = month(cfg["last_year"],12)-START+1
    access = tuple(Access("worker",t<OPEN) for t in range(n))
    annual, end, moves, entries, cash = {}, {}, [], [], []
    result = None
    try:
        result = simulate(p,s,cfg,job_path=("nonstandard",)*n,access_path=access,
                          verified_history=history,annual_ledger=annual,terminal=end,
                          transfer_events=moves,access_log=entries,monthly_trace=cash)
    except ValueError as error:
        if declared or str(error) != GUARD:
            raise
    posted = sum(row["worker_posted"] for row in entries if row["month"]<LEGAL)
    eligible = fixture.opening_months+posted >= threshold
    item = {"fixture":fixture.name,"category":category,"threshold_months":threshold,
            "opening_worker_months":fixture.opening_months,"available_yuan":available,
            "subsidy_lag_months":fixture.delay,"monthly_draw_limit_yuan":fixture.draw_limit,
            "static_cash_feasible":static_pass,"static_state":static,"posted_worker_months":posted,
            "credited_at_legal":fixture.opening_months+posted,"eligible_worker_at_legal":eligible,
            "legal_month":plain_month(LEGAL)}
    if result is None:
        if moves or end:
            raise ArithmeticError("An unresolved administrative route must have no posted transfer or payout.")
        return item | {"disposition":"unresolved_post_2029_threshold_basis","first_payment_month":None}
    if not declared or len(moves)!=1 or bool(result["eligible_at_legal"])!=eligible:
        raise ArithmeticError("Monthly path or adjudication mismatch.")
    transfer, = moves
    if transfer.worker_credit_before != item["credited_at_legal"]:
        raise ArithmeticError("Credited months at adjudication disagree.")
    verify_cash(annual,cash)
    first_p1 = next((r["month"] for r in cash if r["p1_benefit"]>0), None)
    if first_p1 != end["first_payment_month"]:
        raise ArithmeticError("Receipt must follow actual paid cash.")
    household_upfront = fsum(r["worker_household_cash"] for r in cash)
    subsidy = fsum(r["worker_subsidy"] for r in cash)
    net_household = household_upfront - (subsidy if fixture.delay else 0.0)
    receipts = fsum(r["worker_receipts"] for r in cash)
    if not isclose(net_household+subsidy,receipts,abs_tol=1e-8) or not isclose(receipts,posted*price,abs_tol=1e-8):
        raise ArithmeticError("Personal and public cash do not cover accrued pension contributions.")
    first_year_pension = fsum(r["p1_benefit"] for r in cash if WINDOW[0]<=r["month"]<=WINDOW[1])
    return item | {"disposition":transfer.direction,"route":result["route"],
                   "first_payment_month":plain_month(first_p1),
                   "payment_delay_after_worker_legal_months":None if first_p1 is None else first_p1-LEGAL,
                   "p1_cash_next_12_months_yuan":round(first_year_pension,2),
                   "initial_window_worker_upfront_yuan":round(household_upfront,2),
                   "all_months_net_worker_own_cash_yuan":round(net_household,2),
                   "public_subsidy_2029_yuan":round(annual[2029]["worker_p1_subsidy"],2),
                   "public_subsidy_2030_yuan":round(annual[2030]["worker_p1_subsidy"],2),
                   "simulated_worker_monthly_cash_yuan":round(end["p1_monthly_gross"],2)
                       if end["route"]=="worker" else None}

