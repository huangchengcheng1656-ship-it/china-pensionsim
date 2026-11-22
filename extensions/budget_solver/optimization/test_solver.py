from itertools import product
from random import Random
from unittest import TestCase

from extensions.budget_solver.optimization.replay import r100_replay
from extensions.budget_solver.optimization.solver import Group, Option, solve, verify


def exhaustive(groups, caps, budget, floors):
    """Expand each independent household, preserving a separate no-support choice."""
    sets = [(group, (None, *group.options)) for group in groups for _ in group.household_ids]
    states = len(groups[0].options[0].value)
    rows = []
    for choices in product(*(options for _, options in sets)):
        selected = [(group, choice) for (group, _), choice in zip(sets, choices, strict=True) if choice]
        r = tuple(sum(choice.reserved[j] for _, choice in selected) for j in range(len(caps)))
        if sum(r) > budget or any(amount > cap for amount, cap in zip(r, caps, strict=True)):
            continue
        if any(sum(choice.count[s] for group, choice in selected if name in (group.id, group.cohort))
               < floor[s] for name, floor in floors.items() for s in range(states)):
            continue
        gains = tuple(sum(choice.value[s] for _, choice in selected) for s in range(states))
        counts = tuple(sum(choice.count[s] for _, choice in selected) for s in range(states))
        paid = sum(sum(choice.paid) for _, choice in selected)
        rows.append((gains, counts, (sum(r), paid, len(selected))))
    return rows


class ExactAllocationTests(TestCase):
    def test_frozen_r100_scenario_and_robust_results(self):
        report = r100_replay()
        self.assertEqual(len(report["model_checks_by_funding_rule"]), 2)
        gap = report["model_checks_by_funding_rule"]["reserve_verified_gap"]
        self.assertEqual(gap["maximin_gain"]["objective_score"], 164439)
        self.assertEqual(gap["minimax_regret"]["objective_score"], 74001)

    def test_matches_seeded_exhaustive_mixed_options(self):
        rng = Random(10342)
        for fixture in range(90):
            states = rng.randint(1, 3)
            months = rng.randint(1, 3)
            groups = []
            for index in range(rng.randint(1, 3)):
                options = []
                for action in range(rng.randint(1, 2)):
                    reserved = tuple(rng.randint(0, 6) for _ in range(months))
                    paid = tuple(rng.randint(0, v) for v in reserved)
                    values = tuple(rng.randint(-10, 15) for _ in range(states))
                    counts = tuple(rng.choice((0, 1)) for _ in range(states))
                    options.append(Option(f"o{action}", reserved, paid, counts, values))
                ids = tuple(f"{index}_{k}" for k in range(rng.randint(1, 2)))
                groups.append(Group(f"g{index}", ids, tuple(options), f"c{index % 2}"))
            caps = tuple(rng.randint(0, 15) for _ in range(months))
            budget = rng.randint(0, 2 + sum(caps))
            floors = {"c0": tuple(rng.choice((0, 1)) for _ in range(states))} if fixture % 3 else {}
            rows = exhaustive(groups, caps, budget, floors)
            scenario = rng.randrange(states)
            benchmark = tuple(max((row[0][state] for row in rows), default=0) for state in range(states))
            for objective in ("count", "gain", "maximin_gain", "minimax_regret"):
                def score(row):
                    value, count, _ = row
                    if objective == "count":
                        return count[scenario]
                    if objective == "gain":
                        return value[scenario]
                    if objective == "maximin_gain":
                        return min(value)
                    return -max(best - observed for best, observed in zip(benchmark, value, strict=True))
                model = solve(groups, month_caps=caps, budget=budget, min_timely=floors,
                              objective=objective, scenario=scenario)
                with self.subTest(fixture=fixture, objective=objective):
                    if not rows:
                        self.assertEqual(model["status"], "infeasible")
                        continue
                    expected = min((-score(row), *row[2]) for row in rows)
                    observed = model["objective_score"]
                    sign = 1 if objective == "minimax_regret" else -1
                    checked = verify(groups, model["allocation"], month_caps=caps, budget=budget, min_timely=floors)
                    self.assertEqual(model["value_fen_by_scenario"], checked["value_fen_by_scenario"])
                    self.assertEqual((sign * observed, sum(checked["reserved_by_month"]),
                                      sum(checked["paid_by_month"]),
                                      sum(sum(menu.values()) for menu in model["allocation"].values())), expected)

    def test_multiple_options_cannot_assign_same_household_twice(self):
        a = Option("A", (0, 5), (0, 3), (1, 1), (7, 8))
        b = Option("B", (5, 0), (3, 0), (1, 1), (8, 7))
        group = Group("both", ("only_1",), (a, b))
        with self.assertRaises(ValueError):
            verify([group], {"both": {"A": 1, "B": 1}}, month_caps=(10, 10), budget=20)
        actual = solve([group], month_caps=(10, 10), budget=20)
        self.assertEqual(actual["added_count_by_scenario"], (1, 1))

    def test_caps_apply_to_reserved_amount_even_when_paid_is_lower(self):
        option = Option("reserve", (10, 10), (4, 4), (1, 1), (20, 20))
        group = Group("g", ("h",), (option,))
        for caps, budget in (((8, 20), 40), ((15, 15), 19)):
            with self.subTest(caps=caps, budget=budget):
                self.assertFalse(solve([group], month_caps=caps, budget=budget)["allocation"])
        self.assertEqual(solve([group], month_caps=(10, 10), budget=20)["paid_by_month"], (4, 4))

    def test_cohort_floor_is_common_to_all_states_and_benchmarks(self):
        a = Group("a", ("p1",), (Option("fast", (5,), (5,), (1, 0), (7, 16)),), "women")
        b = Group("b", ("p2",), (Option("fast", (5,), (5,), (0, 1), (16, 7)),), "women")
        c = Group("c", ("p3",), (Option("fast", (2,), (2,), (1, 1), (70, 70)),), "men")
        good = solve((a, b, c), month_caps=(10,), budget=10, objective="minimax_regret",
                     min_timely={"women": (1, 1)})
        self.assertEqual(good["allocation"], {"a": {"fast": 1}, "b": {"fast": 1}})
        self.assertEqual(good["objective_score"], 0)
        short = solve((a, b, c), month_caps=(9,), budget=10, min_timely={"women": (1, 1)})
        self.assertEqual(short["status"], "infeasible")

    def test_duplicate_households_and_noninteger_cost_rejected(self):
        a = Group("a", ("p1",), (Option("route", (1,), (1,), (1,), (1,)),))
        b = Group("b", ("p1",), (Option("route", (1,), (1,), (1,), (1,)),))
        with self.assertRaises(ValueError):
            solve((a, b), month_caps=(10,), budget=10)
        with self.assertRaises(ValueError):
            solve((a,), month_caps=(9.5,), budget=10)

    def test_large_grouped_case_visits_small_fraction_of_individual_assignments(self):
        groups = tuple(Group(f"g_{label}", tuple(f"{label}_{k:03d}" for k in range(100)),
                             (Option("grant", (cost,), (cost,), (1, 1), values),))
                       for label, cost, values in (("A", 130, (200, 380)), ("B", 120, (210, 200)),
                                                   ("C", 110, (220, 220))))
        result = solve(groups, month_caps=(10000,), budget=11000)
        self.assertEqual(result["objective_score"], 19800)
        self.assertEqual(result["allocation"], {"g_C": {"grant": 90}})
        self.assertLess(result["nodes_visited"], 100_000)
