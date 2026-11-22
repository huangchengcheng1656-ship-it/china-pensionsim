"""Join cash-feasible personal continuation to the native first-pillar accounts."""
from argparse import ArgumentParser
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from fractions import Fraction
import json
from math import fsum, isclose
from pathlib import Path

from pension_core.history import ActiveHistory, History
from pension_core.ledger import Person
from pension_core.portability import ResidentYear, WorkerMonth
from pension_core.rules import minimum_months, month, payout_divisor, worker_benefit
from extensions.continuation_valuation_base.valuation import assess as prior


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R95 = ROOT / "extensions/fixtures_routes/routes/route_sensitivity.synthetic.json"
R96 = ROOT / "extensions/fixtures_timing/timing/results.synthetic.json"
R97 = ROOT / "extensions/fixtures_installments/installments/results.synthetic.json"
R98 = ROOT / "extensions/continuation_valuation_base/valuation/results.synthetic.json"
ANCHORS = (R95, R96, R97, R98, prior.NATIVE)
AP_RISK, NORMAL = "april_resources_missing", "uninterrupted_resources_and_channel"
PAIRS = (
    ("extension_mar", "personal900"), ("extension_mar", "personal600"),
    ("resident", "personal600"), ("intact", "personal600"),
    ("personal600", "personal900"), ("no_grant_april_gap", "fixed_april_gap"),
    ("no_grant_april_gap", "direct_april_gap"), ("fixed_april_gap", "direct_april_gap"),
    ("fixed_april_gap", "late_may_april_gap"), ("fixed_normal", "direct_normal"),
)


def read(path):
    return json.loads(path.read_bytes())


def parse(label):
    y, m = map(int, label.split("-"))
    return month(y, m)


def cents(value):
    v = Decimal(str(value)) * 100
    if v != v.to_integral_value() or v < 0:
        raise ValueError("nonnegative whole cents required")
    return int(v)


def check_close(actual, expected, label):
    if not isclose(actual, expected, rel_tol=0, abs_tol=1e-7):
        raise ArithmeticError(f"{label}: {actual} != {expected}")


@dataclass(frozen=True)
class Payment:
    period: int
    base_yuan: float
    household_remittance_cents: int
    employer_cents: int = 0
    public_concurrent_cents: int = 0
    public_household_transfer_cents: int = 0

    @property
    def posted(self):
        return self.household_remittance_cents + self.employer_cents + self.public_concurrent_cents

    @property
    def public(self):
        return self.public_concurrent_cents + self.public_household_transfer_cents


def schedule_from_r95(case, amount):
    assumptions = case["continued_contributions"]
    if (cents(assumptions["assumed_monthly_fee_yuan"]) != 90000
            or cents(assumptions["scenario_opening_cash_yuan_carried_from_feb_snapshot"]) != 40774):
        raise ValueError("unexpected R95 personal terms")
    row = assumptions["alternatives"][amount]
    payments = [Payment(parse(p["month"]), 4500, cents(p["contribution"]))
                for p in row["monthly_cash_schedule"] if cents(p["contribution"])]
    first = row["conditional_decision_timing"].get("credits_at_opening", {}).get("entitlement_start")
    return payments, first


def schedule_from_r96(data):
    row = data["equal_commitment_comparison"]["no_grant"]["by_profile"][AP_RISK]
    payments = [Payment(parse(p["month"]), 4500, cents(p["current_premium_yuan"]))
                for p in row["monthly_ledger"] if cents(p["current_premium_yuan"])]
    return payments, row["conditional_due_start_if_decision_at_next_month_opening"]


def schedule_from_r97(data, program, profile):
    row = data["programs"][program][profile]
    march, april = data["pre_may_observed_premiums_yuan"][profile]
    if (cents(march), cents(april)) != (90000, 0):
        raise ValueError("R97 requires the sealed March payment and April nonpayment")
    payments = [Payment(parse("2030-03"), 4500, cents(march))]
    for r in row["ledger"]:
        p = Payment(parse(r["month"]), 4500, cents(r["household_premium_yuan"]),
                    public_concurrent_cents=cents(r["public_premium_yuan"]),
                    public_household_transfer_cents=cents(r["scheduled_transfer_yuan"]))
        if p.posted != cents(r["total_premium_posted_yuan"]):
            raise ArithmeticError("same-invoice splits do not add to the posted premium")
        if p.posted or p.public:
            payments.append(p)
    if sum(p.public for p in payments) != cents(row["actual_public_payment_in_simulation_yuan"]):
        raise ArithmeticError("fixed transfers and same-transaction cash failed reconciliation")
    return payments, row["simulated_entitlement_start_if_next_month_recognized"]


def restore_history(case):
    r = case["history"]
    return History(**(r | {
        "worker_opening": tuple(WorkerMonth(**w) for w in r["worker_opening"]),
        "resident_opening": tuple(ResidentYear(**(y | {"covered_months": frozenset(y["covered_months"])}))
                                  for y in r["resident_opening"]),
        "choice_by_month": {int(k): v for k, v in r["choice_by_month"].items()},
    }))


def clamp_base(cfg, wage):
    return min(cfg["p1_worker_max_base"], max(cfg["p1_worker_min_base"], wage))


def restore_accounts(cfg, source, native):
    person = Person(**source["person"])
    ordinary = source["ordinary_month"]
    start = month(cfg["start_year"], 1)
    rate = (1 + cfg["annual_returns"]["p1"]) ** (1 / 12) - 1
    hist = ActiveHistory(restore_history(source), person, start, rate)
    # R98 trace preserves actual posted months before the ordinary retirement age.
    postings, books, flows = native[-3:]
    expected = books[ordinary - 1 - start]
    idx = person.worker_index * (person.worker_paid + person.worker_deemed)
    for p in postings:
        t = p["month"]
        if t >= ordinary:
            break
        if p["resident_current_credit"] or flows[t - start]["resident_own"]:
            raise ValueError("this matched sample has no new resident contribution before ordinary age")
        if p["worker_posted"]:
            employee = p["employment"] == "standard"
            if not employee and p["employment"] != "nonstandard":
                raise ValueError("unsupported employment prior to the paired anchor")
            base = clamp_base(cfg, person.wage * (1.0 if employee else 0.72))
            hist.add_worker_credit(t, cfg["worker_account_rate"] * base, employee)
            idx += base / cfg["pension_base"]
    prior_credits = len(hist.worker) + person.worker_deemed
    prior_resident = sum(len(record[0]) for record in hist.resident.values())
    if (prior_credits, prior_resident) != (183, 3):
        raise ArithmeticError("the reconstructed native history missed the matched opening credits")
    reconstructed = fsum(float(w.account_component) * (1 + rate) ** (ordinary - 1 - t) for w, t in hist.worker)
    check_close(reconstructed, expected["worker_balance_end"], "pre-age worker balance")
    close = {"month": prior.date(ordinary - 1), "worker_credits": prior_credits,
             "resident_credits": prior_resident, "worker_account_yuan": expected["worker_balance_end"],
             "resident_account_yuan": expected["resident_balance_end"], "sum_worker_wage_indices": idx}
    return person, hist, close


def payment_dict(pay):
    remitted = pay.household_remittance_cents
    return {"month": prior.date(pay.period), "insured_base_yuan": pay.base_yuan if pay.posted else None,
            "total_premium_posted_yuan": pay.posted / 100,
            "household_premium_remitted_yuan": remitted / 100,
            "employer_premium_yuan": pay.employer_cents / 100,
            "public_premium_direct_yuan": pay.public_concurrent_cents / 100,
            "public_transfer_to_household_yuan": pay.public_household_transfer_cents / 100,
            "net_household_outlay_yuan": (remitted - pay.public_household_transfer_cents) / 100}


def bridge(cfg, source, native, payments, expected_first, identity):
    person, hist, opening = restore_accounts(cfg, source, native)
    ordinary = source["ordinary_month"]
    posted = [p for p in payments if p.posted]
    timeline = [payment_dict(p) for p in payments]
    if identity not in {"individual", "employee"}:
        raise ValueError("select the statutory worker insurance payment identity")
    if any(p.period < ordinary for p in payments) or len({p.period for p in payments}) != len(payments):
        raise ValueError("only one current-period payment per valid month")
    if list(payments) != sorted(payments, key=lambda p: p.period):
        raise ValueError("payments must be chronological")
    for p in posted:
        if identity == "individual":
            if p.period == ordinary or p.employer_cents or p.posted != cents(p.base_yuan * cfg["worker_flexible_rate"]):
                raise ValueError("personal continuation has no unit contribution or February posting")
        elif (p.household_remittance_cents != cents(p.base_yuan * cfg["worker_employee_rate"])
                or p.employer_cents != cents(p.base_yuan * cfg["worker_standard_employer_rate"])
                or p.public):
            raise ValueError("unit anchor requires the original personal/employer split")
    if not expected_first:
        if posted or payments:
            raise ValueError("the zero-resource case has no posted or paid event in the window")
        return opening, timeline, None
    final_post = posted[-1].period
    recognition = final_post + 1
    first = recognition + 1
    threshold = minimum_months(ordinary // 12)
    if prior.date(first) != expected_first or opening["worker_credits"] + len(posted) != threshold:
        raise ValueError("post-age credits must meet the threshold and preserve source recognition timing")
    hist.history = replace(hist.history, decision_month=recognition, threshold_reference="declared_scenario")
    monthly_rate = hist.rate
    worker, resident = opening["worker_account_yuan"], opening["resident_account_yuan"]
    index_sum = opening["sum_worker_wage_indices"]
    for t in range(ordinary, recognition + 1):
        worker += worker * monthly_rate
        resident += resident * monthly_rate
        event = next((p for p in posted if p.period == t), None)
        if event is not None:
            credit = event.base_yuan * cfg["worker_account_rate"]
            hist.add_worker_credit(t, credit, identity == "employee")
            worker += credit
            index_sum += event.base_yuan / cfg["pension_base"]
            timeline[payments.index(event)]["account_credited_yuan"] = credit
            timeline[payments.index(event)]["recognized_credit_added"] = 1
    transfer, payable = hist.adjudicate(recognition, worker, resident, ordinary, person.birth + 60 * 12, threshold)
    if not payable or transfer.direction != "resident_to_employee" or transfer.credited_months_after != threshold:
        raise ArithmeticError("worker right and account transfer did not follow the common R48 rules")
    final_account = worker - float(transfer.worker_account_cleared_elsewhere) + float(transfer.amount_moved)
    check_close(final_account, float(transfer.final_account), "reconciled transfer and account")
    avg = index_sum / threshold
    divisor = payout_divisor(recognition - person.birth, "linear")
    basic = worker_benefit(cfg["pension_base"], avg, threshold, 0, recognition - person.birth, "linear")
    account = final_account / divisor
    return opening, timeline, {
        "last_required_posting_month": prior.date(final_post), "recognition_month": prior.date(recognition),
        "first_model_payment": expected_first, "transfer_direction": transfer.direction,
        "recognized_worker_credits": transfer.credited_months_after,
        "resident_account_transferred_yuan": float(transfer.amount_moved),
        "worker_account_after_transfer_yuan": final_account, "mean_worker_wage_index": avg,
        "payout_divisor": divisor, "pooled_monthly_yuan": basic, "personal_account_monthly_yuan": account,
        "first_pillar_monthly_yuan": basic + account,
    }


def values(case, birth, start, rates, flows, level):
    if level is None:
        return []
    first = parse(case["first_model_payment"])
    probabilities = prior.survival(rates, prior.SEX[case["category"]], birth, start, birth + 1200)
    results = []
    for rate in prior.RATES:
        for age in prior.CUTOFF_AGES:
            weights = [p * (1 + rate) ** (-i / 12) for i, p in
                       enumerate(probabilities[:birth + 12 * age - start])]
            factor = fsum(weights[first - start:])
            premium = fsum(r["net_household_outlay_yuan"] * weights[parse(r["month"]) - start] for r in flows)
            public = fsum((r["public_premium_direct_yuan"] + r["public_transfer_to_household_yuan"])
                           * weights[parse(r["month"]) - start] for r in flows)
            gross = level * factor
            results.append({"discount_rate": rate, "cutoff_age": age, "annuity_factor": factor,
                            "first_pillar_gross_pv_yuan": gross, "household_first_pillar_outlay_pv_yuan": premium,
                            "first_pillar_net_of_household_outlay_pv_yuan": gross - premium,
                            "public_post_age_outlay_pv_yuan": public})
    return results


def output_case(cfg, source, native, name, identity, schedule, rates):
    p, arm = source["person"], name
    opening, timeline, award = bridge(cfg, source, native, *schedule, identity)
    case = {"category": p["category"], "arm": arm, "post_age_payment_identity": identity,
            "ordinary_month": prior.date(source["ordinary_month"]),
            "opening_ledger": opening, "award": award, "actual_first_bank_payment": None,
            "status": "conditional_award" if award else "unclaimed_through_2030_12",
            "first_model_payment": award["first_model_payment"] if award else None,
            "payments": timeline}
    case["values"] = values(case, p["birth"], month(cfg["start_year"], 1), rates, timeline,
                            award["first_pillar_monthly_yuan"] if award else None)
    return case


def old_case(entry):
    unit = entry["arm"].startswith("extension_")
    return {"category": entry["category"], "arm": entry["arm"],
            "post_age_payment_identity": "employee" if unit else entry["route"],
            "ordinary_month": entry["ordinary_month"], "actual_first_bank_payment": None,
            "status": "sealed_r98_reference", "first_model_payment": entry["first_model_payment"],
            "award": {"first_pillar_monthly_yuan": entry["monthly_first_pillar_yuan"]},
            "values": [{"discount_rate": v["discount_rate"], "cutoff_age": v["cutoff_age"],
                        "annuity_factor": v["annuity_factor"], "first_pillar_gross_pv_yuan": v["first_pillar_pv_yuan"],
                        "household_first_pillar_outlay_pv_yuan": (v["household_extension_payment_pv_yuan"]
                            + v["household_resident_post_age_payment_pv_yuan"]),
                        "first_pillar_net_of_household_outlay_pv_yuan": (v["first_pillar_pv_yuan"]
                            - v["household_extension_payment_pv_yuan"] - v["household_resident_post_age_payment_pv_yuan"])}
                       for v in entry["values"]]}


def compare(reference, alternative):
    x, y = reference["award"], alternative["award"]
    level0, level1 = (r["first_pillar_monthly_yuan"] for r in (x, y))
    rows = []
    for a, b in zip(reference["values"], alternative["values"], strict=True):
        mean = (a["annuity_factor"] + b["annuity_factor"]) / 2
        timing = (level0 + level1) / 2 * (b["annuity_factor"] - a["annuity_factor"])
        level = mean * (level1 - level0)
        gross = b["first_pillar_gross_pv_yuan"] - a["first_pillar_gross_pv_yuan"]
        check_close(timing + level, gross, "timing and nominal monthly level split")
        pooled = account = None
        if "pooled_monthly_yuan" in x and "pooled_monthly_yuan" in y:
            pooled = mean * (y["pooled_monthly_yuan"] - x["pooled_monthly_yuan"])
            account = mean * (y["personal_account_monthly_yuan"] - x["personal_account_monthly_yuan"])
            check_close(pooled + account, level, "pooled and personal account level split")
        net = b["first_pillar_net_of_household_outlay_pv_yuan"] - a["first_pillar_net_of_household_outlay_pv_yuan"]
        rows.append({"discount_rate": a["discount_rate"], "cutoff_age": a["cutoff_age"],
                     "difference_gross_pv_yuan": gross, "difference_net_pv_yuan": net,
                     "timing_component_pv_yuan": timing, "monthly_level_component_pv_yuan": level,
                     "pooled_benefit_level_component_pv_yuan": pooled,
                     "account_benefit_level_component_pv_yuan": account})
    return {"category": reference["category"], "from_arm": reference["arm"], "to_arm": alternative["arm"],
            "values": rows}


def assess():
    r95, r96, r97, r98, fixture = (read(p) for p in ANCHORS)
    if any(d["dataset_type"] != "synthetic" for d in (r95, r96, r97, r98, fixture)) or (
            r97["r96_output_sha256"] != prior.sha(R96) or r98["fixture_sha256"] != prior.sha(prior.NATIVE)):
        raise ValueError("use sealed synthetic cash and case fixtures")
    source_cases = {(c["category"], c["arm"]): c for c in r98["cases"]}
    resources = {c["category"]: c for c in r95["cases"]}
    rates = prior.read_mortality()
    cfg = fixture["config"]
    r99, contrasts = [], []
    for src in fixture["cases"]:
        if src["arm"] != "extension_mar":
            continue
        category = src["person"]["category"]
        native = prior.replay(fixture, src)
        current = {k: old_case(source_cases[category, k]) for k in ("intact", "resident")}
        for arm in ("extension_feb", "extension_mar"):
            ref = source_cases[category, arm]
            payments = [Payment(parse(p["month"]), 5550, cents(p["employee_yuan"]),
                                cents(p["combined_yuan"]) - cents(p["employee_yuan"]))
                        for p in ref["extension_payments"]]
            rec = output_case(cfg, src, native, arm, "employee", (payments, ref["first_model_payment"]), rates)
            check_close(rec["award"]["first_pillar_monthly_yuan"], ref["monthly_first_pillar_yuan"],
                        "native unit benefit anchor")
            for v, old in zip(rec["values"], ref["values"], strict=True):
                check_close(v["first_pillar_gross_pv_yuan"], old["first_pillar_pv_yuan"], "native unit PV anchor")
                check_close(v["household_first_pillar_outlay_pv_yuan"], old["household_extension_payment_pv_yuan"],
                            "native unit post-age household PV anchor")
            current[arm] = rec
        for name, amount in (("personal_zero", "0.00"), ("personal600", "600.00"), ("personal900", "900.00")):
            current[name] = output_case(cfg, src, native, name, "individual",
                                        schedule_from_r95(resources[category], amount), rates)
        current["no_grant_april_gap"] = output_case(cfg, src, native, "no_grant_april_gap", "individual",
                                                   schedule_from_r96(r96), rates)
        for name, method, profile in (
            ("fixed_april_gap", "fixed_installments", AP_RISK),
            ("direct_april_gap", "pay_verified_remainder_directly_to_fund", AP_RISK),
            ("late_may_april_gap", "may_installment_delayed_one_month", AP_RISK),
            ("fixed_normal", "fixed_installments", NORMAL),
            ("direct_normal", "pay_verified_remainder_directly_to_fund", NORMAL),
        ):
            current[name] = output_case(cfg, src, native, name, "individual",
                                        schedule_from_r97(r97, method, profile), rates)
        r99.extend(current.values())
        contrasts.extend(compare(current[left], current[right]) for left, right in PAIRS)
    if len(r99) != 39 or len(contrasts) != 30:
        raise ArithmeticError("one retirement-category path set is incomplete")
    return {"schema": "r99_first_pillar_personal_continuation", "dataset_type": "synthetic",
            "source_sha256": {path.relative_to(ROOT).as_posix(): prior.sha(path) for path in ANCHORS},
            "valuation_month": r98["valuation_month"],
            "scope": "Fixed nominal P1 awards, conditional on posting and modeled approval. No wage, work expense or bank assumptions.",
            "cases": r99, "comparisons": contrasts}


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    prior.write(parser.parse_args().out, assess())
