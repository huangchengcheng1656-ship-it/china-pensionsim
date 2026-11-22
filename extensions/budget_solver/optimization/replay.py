"""Recreate all eight R100 choices and the robust budgets with the grouped solver."""
from argparse import ArgumentParser
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from extensions.budget_solver.optimization.solver import Group, Option, solve, verify

ROOT = Path(__file__).resolve().parents[3]
R100 = ROOT / "extensions/fixtures_portfolio/portfolio"
FUNDING = ("reserve_verified_gap", "reserve_uniform_before_clearing")


def cents(yuan):
    value = Decimal(yuan) * 100
    if value != int(value):
        raise ValueError("The R100 fiscal menu requires exact cents.")
    return int(value)


def r100_input(funding, copies=1):
    """Read common R100 options; replicate the four explicitly synthetic cases by type."""
    if funding not in FUNDING or type(copies) is not int or copies <= 0:
        raise ValueError("Expected one registered R100 funding rule and positive integer copies.")
    design = json.loads((R100 / "cases.synthetic.json").read_bytes())
    source = json.loads((R100 / "results.synthetic.json").read_bytes())
    if any(fixture["dataset_type"] != "synthetic" for fixture in (design, source)):
        raise ValueError("The R100 adapter accepts only synthetic fixtures.")
    months = tuple(design["months"]["support_months"])
    scenarios = tuple(source["situations"])
    if tuple(row["id"] for row in design["situations"]) != scenarios:
        raise ValueError("R100 scenario order differs between the two fixtures.")
    common = tuple(({tuple(row["approved_households"]): row
                     for row in data["menus"][funding]["feasible"]}, data["households"])
                   for data in source["situations"].values())
    groups = []
    for row in design["households"]:
        case = row["id"]
        entries = [households[case] for _, households in common]
        reserved_and_paid = []
        for scenario_menu, _ in common:
            data = scenario_menu[(case,)]
            reserved_and_paid.append(tuple(tuple(cents(data[column][month]) for month in months)
                                           for column in ("nominal_public_reserved_by_month_yuan",
                                                          "nominal_public_spent_by_month_yuan")))
        if any(pair != reserved_and_paid[0] for pair in reserved_and_paid):
            raise ValueError("Cash commitments must be common to every scenario.")
        reserved, paid = reserved_and_paid[0]
        options = (Option("approve", reserved, paid, tuple(row["added_deadline_qualification"] for row in entries),
                          tuple(row["p1_pv_gain_fen"] for row in entries)),)
        synthetic_ids = (case,) if copies == 1 else tuple(f"{case}_{i + 1:04d}" for i in range(copies))
        cohort = "men" if row["category"] == "male60" else "women"
        groups.append(Group(case, synthetic_ids, options, cohort))
    caps = tuple(cents(design["funding"]["aggregate_month_caps_yuan"][month]) for month in months)
    budget = cents(design["funding"]["aggregate_budget_yuan"])
    return tuple(groups), caps, budget, scenarios


def core_witness(result):
    return {key: result[key] for key in ("allocation", "reserved_by_month", "paid_by_month",
                                        "added_count_by_scenario", "value_fen_by_scenario", "objective_score",
                                        "nodes_visited", "nodes_pruned")}


def r100_replay():
    source = json.loads((R100 / "results.synthetic.json").read_bytes())
    result = {"dataset_type": "synthetic", "units": "nominal fiscal cents and P1 value cents",
              "model_checks_by_funding_rule": {}}
    for rule in FUNDING:
        groups, caps, budget, scenarios = r100_input(rule)
        codes = {}
        for index, situation in enumerate(scenarios):
            codes[situation] = {}
            for outcome, key in (("count", "count_objective"), ("gain", "pension_objective")):
                expected = source["situations"][situation]["menus"][rule][key]["selected"]
                actual = solve(groups, month_caps=caps, budget=budget, objective=outcome, scenario=index)
                if (set(actual["allocation"]) != set(expected["approved_households"]) or
                        actual["objective_score"] != expected["added_deadline_qualifications" if outcome == "count"
                                                               else "gross_p1_pv_gain_fen"]):
                    raise ArithmeticError("The R100 scenario optimum did not reproduce.")
                fair = verify(groups, actual["allocation"], month_caps=caps, budget=budget)
                if (fair["reserved_by_month"] != tuple(map(cents, expected["nominal_public_reserved_by_month_yuan"].values()))
                        or fair["paid_by_month"] != tuple(map(cents, expected["nominal_public_spent_by_month_yuan"].values()))):
                    raise ArithmeticError("The R100 nominal commitment and payment did not reproduce.")
                codes[situation][outcome] = core_witness(actual)
        data = source["robust_without_probabilities"][rule]
        for objective, key in (("maximin_gain", "worst_gross_p1_pv_gain_fen"),
                               ("minimax_regret", "maximum_regret_fen")):
            actual = solve(groups, month_caps=caps, budget=budget, objective=objective)
            expected = data[objective]["selected"]
            if (set(actual["allocation"]) != set(expected["approved_households"])
                    or actual["objective_score"] != expected[key]):
                raise ArithmeticError("The R100 common-scenario optimum did not reproduce.")
            codes[objective] = core_witness(actual)
        result["model_checks_by_funding_rule"][rule] = codes
    result["source_sha256"] = {
        path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in (R100 / "cases.synthetic.json", R100 / "results.synthetic.json")}
    return result


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.out.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(r100_replay(), output, ensure_ascii=False, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
