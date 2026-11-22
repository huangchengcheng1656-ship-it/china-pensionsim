"""Replay the synthetic R95 routes and value their modeled pension cash streams."""

from argparse import ArgumentParser
import csv
from hashlib import sha256
from itertools import product
import json
from math import exp, fsum, isclose, isfinite
from pathlib import Path

from pension_core.access import Access
from pension_core.history import History
from pension_core.ledger import Person, Scenario, simulate
from pension_core.portability import ResidentYear, WorkerMonth
from pension_core.rules import month


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NATIVE = HERE / "native_fixture.synthetic.json"
R95 = ROOT / "extensions/fixtures_routes/path_audit"
MORTALITY = ROOT / "extensions/mortality_wpp/valuation/mortality_public"
ANCHORS = (R95 / "r50_core.synthetic.json", R95 / "native_extension.synthetic.json")
CATEGORIES = ("male60", "female55", "female50")
ARMS = ("intact", "resident", "extension_feb", "extension_mar")
RATES, CUTOFF_AGES = (.01, .025, .04), (95, 100)
SEX = {"male60": "male", "female55": "female", "female50": "female"}
CONTRASTS = (
    ("intact", "resident"), ("resident", "extension_feb"), ("resident", "extension_mar"),
    ("intact", "extension_feb"), ("intact", "extension_mar"), ("extension_feb", "extension_mar"),
)


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def date(index):
    year, mm = divmod(index, 12)
    return f"{year:04}-{mm + 1:02}"


def path_signature(result, transfer, terminal, postings, cash, flows):
    """Fingerprint monthly pensions, costs and selected balances through the projection."""
    checks = []
    by_month = {p["month"]: p for p in postings}
    for pensions, bills in zip(cash, flows, strict=True):
        if pensions["month"] != bills["month"]:
            raise ArithmeticError("The monthly ledgers are out of phase.")
        posted = by_month.get(pensions["month"], {})
        checks.append([pensions["month"], pensions["employment"], pensions["route"],
                       bool(posted.get("worker_posted")), posted.get("worker_total"),
                       *(round(pensions[k], 7) for k in
                         ("p1", "p2", "p3", "worker_balance_end", "resident_balance_end",
                          "ordinary_end", "enterprise_vested_end", "personal_account_end")),
                       *(round(bills[k], 7) for k in ("worker_household_cash", "worker_receipts",
                                                     "resident_own", "resident_public"))])
    doc = [result["route"], transfer.direction, transfer.worker_credit_before,
           terminal["first_payment_month"], checks]
    return sha256(json.dumps(doc, separators=(",", ":"), allow_nan=False).encode("ascii")).hexdigest()


def replay(bundle, case):
    cfg = bundle["config"] | {"last_year": (case["person"]["birth"] + 1200 - 1) // 12}
    person = Person(**case["person"])
    raw = case["history"]
    history = History(**(raw | {
        "worker_opening": tuple(WorkerMonth(**row) for row in raw["worker_opening"]),
        "resident_opening": tuple(ResidentYear(**(row | {"covered_months": frozenset(row["covered_months"])}))
                                  for row in raw["resident_opening"]),
        "choice_by_month": {int(k): v for k, v in raw["choice_by_month"].items()},
    }))
    cash, flows, postings, transfers = [], [], [], []
    terminal = {}
    result = simulate(person, Scenario("paired_boundary"), cfg, job_path=case["jobs"],
                      access_path=[Access(**row) for row in case["access"]], verified_history=history,
                      annuity_exits={int(k): v for k, v in case["exits"].items()}, mobility_trace=cash,
                      access_log=postings, monthly_trace=flows, terminal=terminal,
                      transfer_events=transfers, legal_vesting=True)
    transfer, = transfers
    if path_signature(result, transfer, terminal, postings, cash, flows) != case["native_path_sha256"]:
        raise ArithmeticError(f"Portable and original R50/R95 paths differ for {person.category}/{case['arm']}.")
    return result, transfer, terminal, postings, cash, flows


def read_mortality():
    table = MORTALITY / "wpp2024_china_mortality_40_99.csv"
    info = json.loads((MORTALITY / "source_manifest.json").read_bytes())
    if sha(table) != info["output_sha256"]:
        raise ValueError("The WPP extract checksum differs.")
    rates = {}
    with table.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = int(row["year"]), int(row["age"]), row["sex"]
            rate = float(row["mx_per_person_year"])
            if key in rates or not isfinite(rate) or rate < 0 or not 40 <= key[1] < 100:
                raise ValueError("Invalid or duplicate WPP death-to-exposure rate.")
            rates[key] = rate
    if len(rates) != info["expected_rows"]:
        raise ValueError("Incomplete WPP mortality extract.")
    return rates


def survival(rates, sex, birth, start, stop):
    """Beginning-of-month survival conditional on being alive at the valuation month."""
    if not birth < start < stop <= birth + 1200:
        raise ValueError("Valuation must stop before age 100 or an earlier cutoff.")
    risk = 0.0
    values = []
    for t in range(start, stop):
        values.append(exp(-risk))
        risk += rates[t // 12, (t - birth) // 12, sex] / 12
    return values


def value(cash, payment_rows, resident_rows, probabilities, cutoff, first, start, rate, age):
    weights = [p * (1.0 + rate) ** (-i / 12) for i, p in enumerate(probabilities[:cutoff - start])]
    amounts = tuple(fsum(row[pillar] * weight for row, weight in zip(cash[:len(weights)], weights, strict=True))
                    for pillar in ("p1", "p2", "p3"))
    employee = fsum(row["employee_yuan"] * weights[t - start] for t, row in payment_rows.items())
    resident = fsum(row["household_yuan"] * weights[t - start] for t, row in resident_rows.items())
    return {"discount_rate": rate, "cutoff_age": age, "annuity_factor": fsum(weights[first - start:]),
            "first_pillar_pv_yuan": amounts[0], "second_pillar_pv_yuan": amounts[1],
            "third_pillar_pv_yuan": amounts[2], "household_extension_payment_pv_yuan": employee,
            "household_resident_post_age_payment_pv_yuan": resident}


def case_result(bundle, case, rates, core, extension):
    result, transfer, terminal, postings, cash, flows = replay(bundle, case)
    start = month(bundle["config"]["start_year"], 1)
    category, birth = case["person"]["category"], case["person"]["birth"]
    ordinary, arm = case["ordinary_month"], case["arm"]
    first, level = terminal["first_payment_month"], terminal["p1_monthly_gross"]
    is_extension = arm.startswith("extension_")
    expected = extension[category, arm] if is_extension else core[category]
    date_key = "first_model_payment" if is_extension else f"{arm}_first_model_payment"
    level_key = "monthly_benefit_assumed_formula_yuan" if is_extension else date_key + "_yuan"
    if date(first) != expected[date_key] or f"{level:.2f}" != expected[level_key]:
        raise ArithmeticError("The projection altered the sealed R95 first pension.")
    expected_route = "resident" if arm == "resident" else "worker"
    if (date(ordinary) != expected["ordinary_month"] or result["route"] != expected_route or
            transfer.worker_credit_before != {"intact": 187, "resident": 183}.get(arm, 186)):
        raise ArithmeticError("The original threshold or transfer differs.")
    payment_rows = {
        t: {"month": date(t), "employee_yuan": flows[t - start]["worker_household_cash"],
            "combined_yuan": flows[t - start]["worker_receipts"]}
        for t in range(ordinary, first - 1) if postings[t - start]["worker_posted"]
    }
    if is_extension:
        if ([r["month"] for r in payment_rows.values()] != expected["posted_months"] or
                f"{fsum(r['employee_yuan'] for r in payment_rows.values()):.2f}" != expected["worker_cash_yuan"] or
                f"{fsum(r['combined_yuan'] for r in payment_rows.values()):.2f}" != expected["fund_receipts_yuan"]):
            raise ArithmeticError("Extension costs or postings differ from R95.")
    elif payment_rows:
        raise ArithmeticError("A reference arm has an unexpected post-eligibility employee contribution.")
    resident_rows = {
        row["month"]: {"month": date(row["month"]), "household_yuan": row["resident_own"],
                       "public_yuan": row["resident_public"]}
        for row in flows[ordinary - start:] if row["resident_own"] or row["resident_public"]
    }
    if resident_rows and arm != "resident":
        raise ArithmeticError("Unexpected resident premiums outside the transfer option.")
    if (len(cash) < birth + 1200 - start or
            any(row["month"] != start + i or row["p1"] != (level if row["month"] >= first else 0.0)
                for i, row in enumerate(cash)) or any(row["p3_subsidy"] for row in cash)):
        raise ArithmeticError("Incomplete fixed-level benefit stream or unexpected personal matching.")
    probabilities = survival(rates, SEX[category], birth, start, birth + 1200)
    return {
        "category": category, "arm": arm, "birth": date(birth), "ordinary_month": date(ordinary),
        "route": result["route"], "transfer_direction": transfer.direction,
        "credits_at_route_decision": transfer.worker_credit_before,
        "model_retirement_month": date(first - 1), "first_model_payment": date(first),
        "monthly_first_pillar_yuan": level, "extension_payments": list(payment_rows.values()),
        "resident_post_age_payments": list(resident_rows.values()),
        "finite_payouts": [{"month": date(row["month"]), "second_yuan": row["p2"], "third_yuan": row["p3"]}
                           for row in cash if row["month"] < birth + 1200 and (row["p2"] or row["p3"])],
        "values": [value(cash, payment_rows, resident_rows, probabilities, birth + age * 12, first, start, rate, age)
                   for rate, age in product(RATES, CUTOFF_AGES)],
    }


def compare(reference, arm):
    rows = []
    level0, level1 = reference["monthly_first_pillar_yuan"], arm["monthly_first_pillar_yuan"]
    for base, alternative in zip(reference["values"], arm["values"], strict=True):
        a0, a1 = base["annuity_factor"], alternative["annuity_factor"]
        timing = ((level0 + level1) / 2) * (a1 - a0)
        amount = ((a0 + a1) / 2) * (level1 - level0)
        gain = alternative["first_pillar_pv_yuan"] - base["first_pillar_pv_yuan"]
        if not isclose(gain, timing + amount, rel_tol=0, abs_tol=1e-7):
            raise ArithmeticError("The timing and monthly benefit decomposition did not close.")
        employee0, employee1 = (v["household_extension_payment_pv_yuan"] for v in (base, alternative))
        resident0, resident1 = (v["household_resident_post_age_payment_pv_yuan"] for v in (base, alternative))
        parity = (alternative["first_pillar_pv_yuan"] - employee1) / a0 if (
            reference["arm"] == "resident" and arm["arm"].startswith("extension_")) else None
        rows.append({
            "discount_rate": base["discount_rate"], "cutoff_age": base["cutoff_age"],
            "first_pillar_gain_pv_yuan": gain, "timing_component_pv_yuan": timing,
            "benefit_level_component_pv_yuan": amount,
            "second_pillar_gain_pv_yuan": alternative["second_pillar_pv_yuan"] - base["second_pillar_pv_yuan"],
            "third_pillar_gain_pv_yuan": alternative["third_pillar_pv_yuan"] - base["third_pillar_pv_yuan"],
            "incremental_household_extension_payment_pv_yuan": employee1 - employee0,
            "first_pillar_gain_net_of_both_modeled_household_post_age_payments_pv_yuan":
                gain - (employee1 - employee0) - (resident1 - resident0),
            "monthly_increase_for_pension_pv_parity_yuan": level0 * (a0 / a1 - 1),
            "resident_monthly_parity_after_extension_employee_payment_yuan": parity,
            "resident_monthly_parity_after_both_modeled_household_payments_yuan":
                parity + resident0 / a0 if parity is not None else None,
        })
    return {"category": reference["category"], "from_arm": reference["arm"], "to_arm": arm["arm"], "values": rows}


def assess():
    bundle = json.loads(NATIVE.read_bytes())
    if bundle["dataset_type"] != "synthetic":
        raise ValueError("Only the synthetic R95 projection is supported.")
    if {p.name: sha(p) for p in ANCHORS} != bundle["r95_sha256"]:
        raise ValueError("The R95 anchors differ from the extracted synthetic fixture.")
    core_source, extension_source = (json.loads(p.read_bytes()) for p in ANCHORS)
    if any(x["dataset_type"] != "synthetic" for x in (core_source, extension_source)):
        raise ValueError("R95 anchors must be synthetic.")
    core = {x["category"]: x for x in core_source["cases"]}
    names = {"credit_available_in_statutory_month": "extension_feb",
             "credit_unavailable_in_statutory_month": "extension_mar"}
    extension = {(x["category"], names[x["case"]]): x for x in extension_source["cases"]}
    rates = read_mortality()
    cases = [case_result(bundle, case, rates, core, extension) for case in bundle["cases"]]
    by_key = {(c["category"], c["arm"]): c for c in cases}
    if len(cases) != 12 or by_key.keys() != set(product(CATEGORIES, ARMS)):
        raise ValueError("Expected three matched synthetic careers with four options each.")
    comparisons = [compare(by_key[category, ref], by_key[category, arm])
                   for category in CATEGORIES for ref, arm in CONTRASTS]
    return {
        "dataset_type": "synthetic", "valuation_month": date(month(bundle["config"]["start_year"], 1)),
        "convention": "Beginning-of-month survival and nominal discount. Cutoff excludes the age birthday month.",
        "scope": "Fixed nominal first-pillar pension with conditional survival. Pillars two and three follow the native joint-claim calendar. Separately priced costs are modeled individual first-pillar payments from the ordinary age; actual bank receipts are unobserved.",
        "fixture_sha256": sha(NATIVE), "anchor_sha256": bundle["r95_sha256"], "cases": cases, "comparisons": comparisons,
    }


def write(path, result):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    write(parser.parse_args().out, assess())
