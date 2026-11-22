"""Price the R52 liquidity case under explicit and separate adjudication paths."""

from argparse import ArgumentParser
from dataclasses import dataclass
from hashlib import sha256
from math import fsum, isclose
from pathlib import Path
import json

from extensions.mortality_wpp.valuation import valuation as V
from extensions.monthly_bridge.validation import bridge as B
from pension_core.rules import minimum_months

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FROZEN = ROOT / "extensions/monthly_bridge/validation/monthly_bridge.synthetic.json"
MORTALITY = ROOT / "extensions/mortality_wpp/valuation/mortality_public"
CUTS = (95, 100)
RATES = (.01, .025, .04)
BASE = "age100_rate_0.025"
OPENING = 174
CASH = 8910.0
PRIVATE_TOP_UP = 150.0


@dataclass(frozen=True)
class Arm:
    name: str
    delay: int
    reference: str | None
    decision: int = B.LEGAL
    extra_month: int | None = None
    private_cash: float = 0.


ARMS = (
    Arm("immediate", 0, "declared_scenario"),
    Arm("refund_resident_if_approved", 3, "declared_scenario"),
    Arm("refund_unresolved", 3, None),
    # Adjudication happens at the end of the decision month, after that month's posting.
    Arm("refund_unfunded_extension", 3, None, B.LEGAL + 1, B.LEGAL),
    Arm("refund_extension_at_legal_month_end", 3, "declared_scenario",
        B.LEGAL, B.LEGAL, PRIVATE_TOP_UP),
    Arm("refund_extension_next_month", 3, "declared_scenario",
        B.LEGAL + 1, B.LEGAL + 1, PRIVATE_TOP_UP),
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def close(left, right):
    return isclose(left, right, abs_tol=1e-7, rel_tol=0)


def simulate_arm(category, arm, config):
    birth = B.birth_at_legal(category)
    final_age = birth + 1200
    cfg = config | {"last_year": (final_age - 1) // 12, "allowed_liquid_draw": 2600.}
    if minimum_months(arm.decision // 12) != minimum_months(B.LEGAL // 12):
        raise ValueError("Adjudication outside the unchanged threshold year needs a separate rule.")
    if arm.extra_month is not None and not B.LEGAL <= arm.extra_month <= arm.decision:
        raise ValueError("New ordinary payments must post no later than the adjudication month.")
    n = B.month(cfg["last_year"], 12) - B.START + 1
    wage = 5000.
    debt = .72 * wage - cfg["expense_floor_share"] * .56 * wage
    # Extra private funds are explicit. There is no interest on the liquid account.
    if cfg["annual_returns"]["liquid"] != 0:
        raise ValueError("The matched pre-funding comparison requires zero liquid interest.")
    person = B.Person(birth, category, "nonstandard", wage, 0., CASH + arm.private_cash,
                      OPENING, 0, 0, 1., 300. * OPENING, 0., 0., 0., 0., 0.,
                      False, False, debt, 271120)
    history = B.History(
        tuple(B.WorkerMonth(t, B.REGION, "employee", "300")
              for t in range(B.START - OPENING, B.START)),
        (), B.REGION, B.REGION, B.REGION, {}, 0, {}, arm.decision, arm.reference,
    )
    scenario = B.Scenario("r53_pension_adjudication", minimum_reform=True,
                          subsidy=B.SUPPORT, subsidy_delay_months=arm.delay, response=0.)
    access = tuple(B.Access("worker", i < B.OPEN or B.START + i == arm.extra_month)
                   for i in range(n))
    cash, mobility, entries, moves, claim = [], [], [], [], {}
    annual, terminal = {}, {}
    outcome = None
    try:
        outcome = B.simulate(person, scenario, cfg, job_path=("nonstandard",)*n,
                             access_path=access, verified_history=history, access_log=entries,
                             monthly_trace=cash, mobility_trace=mobility, transfer_events=moves,
                             claim_snapshot=claim, terminal=terminal, annual_ledger=annual)
    except ValueError as error:
        if arm.reference is not None or str(error) != B.GUARD:
            raise
        if moves or claim or terminal or len(cash) != arm.decision - B.START:
            raise ArithmeticError("The undeclared route was priced or not guarded.") from error
    if len(cash) != len(mobility) or any(
            c["month"] != B.START + i or c["month"] != m["month"]
            for i,(c,m) in enumerate(zip(cash,mobility,strict=True))):
        raise ArithmeticError("The modeled months must be contiguous and shared across traces.")
    entry_by_month = {e["month"]:e for e in entries}
    at_legal_open = OPENING + sum(e["worker_posted"] for e in entries if e["month"] < B.LEGAL)
    at_legal = OPENING + sum(e["worker_posted"] for e in entries if e["month"] <= B.LEGAL)
    final_count = OPENING + sum(e["worker_posted"] for e in entries)
    start_cash = person.liquid
    extension_cash = None
    extension_paid = None
    if arm.extra_month is not None:
        i = arm.extra_month - B.START
        extension_paid = entry_by_month[arm.extra_month]["worker_posted"]
        extension_cash = mobility[i]["ordinary_open"] + cash[i]["worker_subsidy"]
    if any(c[k] != 0. for c in cash for k in ("resident_own", "personal_public_reward", "retirement_tax")):
        raise ArithmeticError("The reference case has no second- or third-pillar payment or resident contribution.")
    first = next((c["month"] for c in cash if c["p1_benefit"] > 0.), None)
    cutoff = final_age
    if outcome is not None:
        B.verify_cash(annual, cash)
        move, = moves
        if (first != claim["first_payment_month"] or first != terminal["first_payment_month"]
                or final_count != move.worker_credit_before
                or outcome["eligible_at_legal"] != (at_legal >= 186)):
            raise ArithmeticError("Eligibility, receipt, and credited months do not reconcile.")
        if any(c["p1_benefit"] != claim["p1_monthly_gross"] for c in cash if c["month"] >= first):
            raise ArithmeticError("This fixed-pension run must preserve the awarded stream.")
        contribution_total = fsum(c["worker_receipts"] for c in cash)
        own_cash = fsum(c["worker_household_cash"] for c in cash)
        public = fsum(c["worker_subsidy"] for c in cash)
        net_own = own_cash - public if arm.delay else own_cash
        if (not close(net_own + public, contribution_total)
                or not close(contribution_total, 892.4 * (final_count - OPENING))
                or not close(start_cash - net_own, mobility[-1]["ordinary_end"])):
            raise ArithmeticError("Gross contribution, reimbursement and liquid accounts disagree.")
    else:
        if first is not None:
            raise ArithmeticError("Unresolved cases cannot have simulated pension receipts.")
        public = net_own = None
    item = {
        "category": category, "arm": arm.name, "birth_month": B.plain_month(birth),
        "statutory_month": B.plain_month(B.LEGAL), "threshold_months": 186,
        "starting_worker_months": OPENING,
        "starting_disposable_yuan_before_private_top_up": CASH,
        "added_private_funds_yuan": arm.private_cash,
        "credited_at_statutory_month_open": at_legal_open,
        "extended_ordinary_payment_month": B.plain_month(arm.extra_month),
        "extension_cash_available_for_gross_payment_yuan":
            None if extension_cash is None else round(extension_cash, 2),
        "extension_worker_posted": extension_paid,
        "worker_credited_at_last_adjudication_attempt": final_count,
        "adjudication_attempt_month": B.plain_month(arm.decision),
        "adjudication_status": "simulated_approval" if outcome is not None else "undetermined",
        "route": None if outcome is None else outcome["route"],
        "first_payment_month": B.plain_month(first),
        "first_month_gross_pension_yuan": None if first is None else round(claim["p1_monthly_gross"], 2),
        "delay_relative_to_immediate_first_payment_month": None if first is None else first - B.LEGAL - 1,
        "direct_public_support_nominal_yuan": None if public is None else round(public, 2),
        "net_household_contribution_nominal_yuan": None if net_own is None else round(net_own, 2),
        "amount_to_resident_if_approved_yuan":
            None if not moves or moves[0].direction != "employee_to_resident"
            else round(float(moves[0].amount_moved), 2),
        "before_age100_month": B.plain_month(cutoff),
    }
    return item, cash, mobility, birth


def value_path(row, cash, birth, mortality):
    if row["route"] is None:
        return None
    category = row["category"]
    survival = mortality.month_survival(V.SEX_BY_CATEGORY[category], birth, B.START, birth + 1200, None)
    if len(cash) < len(survival) - 1:
        raise ArithmeticError("The stream must reach the mortality cutoff.")
    return {
        f"age{age}_rate_{rate}": fsum(
            c["p1_benefit"] * survival[i] * V.discount(i, rate)
            for i,c in enumerate(cash[:birth + age*12 - B.START])
        )
        for age in CUTS for rate in RATES
    }


def timing_decomposition(category, birth, benchmark, alternative, mortality):
    """Value the months without receipt at the benchmark amount, then value the amount difference."""
    end = birth + 1200
    survival = mortality.month_survival(V.SEX_BY_CATEGORY[category], birth, B.START, end, None)
    timing, amount = [], []
    for i,(old,new) in enumerate(zip(benchmark[:end-B.START], alternative[:end-B.START], strict=True)):
        if old["month"] != new["month"] or (old["p1_benefit"] == 0. and new["p1_benefit"] > 0.):
            raise ArithmeticError("The timing and amount decomposition needs ordered first receipt.")
        change = (old["p1_benefit"] - new["p1_benefit"]) * survival[i] * V.discount(i, .025)
        (timing if new["p1_benefit"] == 0. else amount).append(change)
    return fsum(timing), fsum(amount)


def compare_pre_adjudication(all_paths):
    """Posting and cash transactions for every lagged path agree before the legal month."""
    n = B.LEGAL - B.START
    old = all_paths["refund_resident_if_approved"]
    for arm in ARMS:
        if not arm.delay or arm.name == "refund_resident_if_approved":
            continue
        row, cash, mobility, _ = all_paths[arm.name]
        if cash[:n] != old[1][:n]:
            raise ArithmeticError("Lagged arms altered reference monthly transactions.")
        for current, previous in zip(mobility[:n],old[2][:n],strict=True):
            for field in ("ordinary_open", "ordinary_end"):
                if not close(current[field] - previous[field], row["added_private_funds_yuan"]):
                    raise ArithmeticError("Pre-funded cash difference is not carried identically.")
            for field in ("worker_balance_end", "resident_balance_end"):
                if not close(current[field], previous[field]):
                    raise ArithmeticError("Pension balance changed before extension.")


def verify_reference(all_paths, reference):
    for name, fixture in (("immediate", "immediate"),
                          ("refund_resident_if_approved", "refund_lag3")):
        row, cash, _, _ = all_paths[name]
        prior = reference[row["category"],fixture]
        common_cash = fsum(c["p1_benefit"] for c in cash if B.WINDOW[0] <= c["month"] <= B.WINDOW[1])
        public = {y:fsum(c["worker_subsidy"] for c in cash if c["month"]//12 == y) for y in (2029,2030)}
        if (row["credited_at_statutory_month_open"] != prior["credited_at_legal"]
                or row["first_payment_month"] != prior["first_payment_month"]
                or row["route"] != prior["route"] or abs(round(common_cash,2)-prior["p1_cash_next_12_months_yuan"])>1e-8
                or any(abs(round(public[y],2)-prior[f"public_subsidy_{y}_yuan"])>1e-8 for y in public)
                or row["net_household_contribution_nominal_yuan"] != prior["all_months_net_worker_own_cash_yuan"]):
            raise ArithmeticError("Extension projection no longer matches the frozen R52 row.")


def build():
    config, price, _ = B.policy_inputs()
    if not close(price,892.4):
        raise ValueError("This liquidity edge uses the registered 2023 benchmark.")
    prior = {
        (r["category"],r["fixture"]):r for r in B.read_json(FROZEN)["rows"] if r["threshold_months"] == 186
    }
    hazard = V.validate_public_source(MORTALITY)
    mortality = V.Mortality.from_csv(hazard)
    rows = []
    contrasts = []
    for category in B.CATEGORIES:
        paths = {arm.name:simulate_arm(category, arm, config) for arm in ARMS}
        compare_pre_adjudication(paths)
        verify_reference(paths, prior)
        values = {name:value_path(p[0],p[1],p[3],mortality) for name,p in paths.items()}
        for name,path in paths.items():
            row = path[0]
            v = values[name]
            rows.append(row | {"expected_pension_pv_yuan":
                               None if v is None else {key:round(value, 2) for key,value in v.items()}})
            if v is None or name == "immediate":
                continue
            losses = {key:values["immediate"][key] - value for key,value in v.items()}
            timing, amount = timing_decomposition(category, path[3], paths["immediate"][1], path[1], mortality)
            if not close(timing + amount, losses[BASE]):
                raise ArithmeticError("The timing and amount effects must reconcile to total PV difference.")
            contrasts.append({
                "category": category, "versus_immediate": name,
                "delay_months":row["delay_relative_to_immediate_first_payment_month"],
                "base_loss_yuan":round(losses[BASE],2),
                "base_loss_timing_yuan":round(timing,2),
                "base_loss_amount_yuan":round(amount,2),
                "stress_loss_min_yuan":round(min(losses.values()),2),
                "stress_loss_max_yuan":round(max(losses.values()),2),
            })
    inputs = (Path(__file__), FROZEN, Path(B.__file__), B.POLICY, Path(V.__file__),
              hazard, MORTALITY / "source_manifest.json", ROOT / "data/synthetic/cohort.synthetic.json",
              *sorted((ROOT / "pension_core").glob("*.py")))
    return {
        "schema": "r53_marginal_payment_path_pension_values_v1",
        "data_mode": "synthetic case, registered historical contribution costs, public WPP 2024",
        "valuation_anchor_month": B.plain_month(B.START), "valuation_rate":.025, "valuation_cutoff_age":100,
        "stress_rates":RATES, "stress_cutoff_ages":CUTS,
        "reference_cash_and_payment_checks":6,
        "common_pre_legal_lagged_path_checks":12,
        "notes": {
            "extension": "New ordinary payment only with explicitly assumed approval and private prefunding. No automatic retroactive credit.",
            "unfunded": "Extra payment opportunity without liquid top-up, no assumed fallback or valuation.",
            "resident": "Transfer and resident admission are simulated only under explicit alternate approval; base resident pension 220 yuan/month is synthetic.",
            "valuation": "First pillar paid cash only. China medium WPP age/year/sex mortality, nominal unchanged awards. Excludes contributions, government cost and property.",
        },
        "paths": rows, "contrasts": contrasts,
        "sha256":{p.relative_to(ROOT).as_posix():digest(p) for p in inputs},
    }


if __name__ == "__main__":
    cli = ArgumentParser(description=__doc__)
    cli.add_argument("--out", type=Path, required=True)
    args = cli.parse_args()
    destination = args.out.resolve()
    if not destination.is_relative_to(HERE) or destination.exists():
        cli.error("Choose a new output file inside the R53 valuation directory.")
    report = build()
    with destination.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write("\n")
    print(f"{len(report['paths'])} matched paths and {len(report['contrasts'])} pension valuation contrasts verified.")
