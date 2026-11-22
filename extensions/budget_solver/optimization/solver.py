"""Exact grouped multiple-choice allocation under common dated fiscal commitments."""
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class Option:
    id: str
    reserved: tuple[int, ...]
    paid: tuple[int, ...]
    count: tuple[int, ...]
    value: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    household_ids: tuple[str, ...]
    options: tuple[Option, ...]
    cohort: str | None = None


@dataclass(frozen=True, slots=True)
class Limits:
    month_caps: tuple[int, ...]
    budget: int
    floors: dict
    scenarios: int


def integers(values, length, *, signed=False):
    return len(values) == length and all(type(n) is int and (signed or n >= 0) for n in values)


def validate(groups, month_caps, budget, min_timely, scenario):
    if (not month_caps or not integers(month_caps, len(month_caps))
            or type(budget) is not int or budget < 0):
        raise ValueError("Nonempty nonnegative integer-cent budget caps are required.")
    months = len(month_caps)
    sizes = {len(option.value) for group in groups for option in group.options}
    if len(sizes) > 1:
        raise ValueError("Use one common scenario dimension for the full menu.")
    scenarios = next(iter(sizes), 1)
    if type(scenario) is not int or not 0 <= scenario < scenarios:
        raise ValueError("Select a valid zero-based scenario index.")
    ids = {group.id for group in groups}
    cohorts = {group.cohort for group in groups if group.cohort is not None}
    if (any(not isinstance(name, str) or not name for name in ids | cohorts)
            or len(ids) != len(groups) or ids & cohorts):
        raise ValueError("Group IDs must be unique and distinct from cohort labels.")
    households = [name for group in groups for name in group.household_ids]
    if (len(households) != len(set(households)) or
            any(not isinstance(name, str) or not name for name in households)):
        raise ValueError("Each household may occur just once in the common menu.")
    floors = {} if min_timely is None else dict(min_timely)
    if (not set(floors) <= (ids | cohorts)
            or any(not integers(wanted, scenarios) for wanted in floors.values())):
        raise ValueError("Timely floor keys and nonnegative targets must match groups and scenarios.")
    for group in groups:
        labels = [option.id for option in group.options]
        if (not group.household_ids or len(labels) != len(set(labels))
                or any(not isinstance(label, str) or not label for label in labels)):
            raise ValueError("A nonempty group and unique explicit option IDs are required.")
        for option in group.options:
            if (not integers(option.reserved, months) or not integers(option.paid, months)
                    or any(p > r for p, r in zip(option.paid, option.reserved, strict=True))
                    or not integers(option.count, scenarios) or any(x > 1 for x in option.count)
                    or not integers(option.value, scenarios, signed=True)):
                raise ValueError("Invalid months, scenario values, or paid amount above reserved amount.")
    return Limits(tuple(month_caps), budget, floors, scenarios)


def plus(a, b):
    return tuple(x + y for x, y in zip(a, b, strict=True))


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def times(vector, factor):
    return tuple(value * factor for value in vector)


def rooms_for(cost, room, max_households):
    return min((available // need for available, need in zip(room, cost, strict=True) if need),
               default=max_households)


def group_decisions(group, room, options):
    """Enumerate each feasible count vector once. Other members receive baseline."""
    selected = {}

    def choose(index, left, rest):
        if index == len(options):
            yield dict(selected), subtract(room, rest)
            return
        option, cost = options[index]
        maximum = min(left, rooms_for(cost, rest, left))
        for qty in range(maximum, -1, -1):
            if qty:
                selected[option.id] = qty
            else:
                selected.pop(option.id, None)
            yield from choose(index + 1, left - qty, subtract(rest, times(cost, qty)))
        selected.pop(option.id, None)

    yield from choose(0, len(group.household_ids), room)


def group_totals(group, decision, limits):
    months = len(limits.month_caps)
    reserved = paid = (0,) * months
    count = value = (0,) * limits.scenarios
    if not set(decision) <= {option.id for option in group.options}:
        raise ValueError("Allocation uses a nonexistent menu option.")
    if any(type(qty) is not int or qty <= 0 for qty in decision.values()):
        raise ValueError("An allocation must use strictly positive integer quantities.")
    if sum(decision.values()) > len(group.household_ids):
        raise ValueError("Household assignments exceed group size.")
    for option in group.options:
        if qty := decision.get(option.id, 0):
            reserved = plus(reserved, times(option.reserved, qty))
            paid = plus(paid, times(option.paid, qty))
            count = plus(count, times(option.count, qty))
            value = plus(value, times(option.value, qty))
    return reserved, paid, count, value


def totals(groups, allocation, limits):
    """Independently reconstruct the household assignments and cash totals."""
    if not set(allocation) <= {group.id for group in groups}:
        raise ValueError("Allocation uses an unknown group ID.")
    reserved = paid = (0,) * len(limits.month_caps)
    zero = (0,) * limits.scenarios
    count = value = zero
    assigned, per_group, per_cohort = {}, {}, {}
    for group in groups:
        decision = allocation.get(group.id, {})
        r, p, n, g = group_totals(group, decision, limits)
        reserved, paid, count, value = plus(reserved, r), plus(paid, p), plus(count, n), plus(value, g)
        per_group[group.id] = n
        if group.cohort is not None:
            per_cohort[group.cohort] = plus(per_cohort.get(group.cohort, zero), n)
        names = iter(sorted(group.household_ids))
        if decision:
            assigned[group.id] = {label: tuple(next(names) for _ in range(qty))
                                  for label, qty in sorted(decision.items())}
    if (sum(reserved) > limits.budget or
            any(actual > cap for actual, cap in zip(reserved, limits.month_caps, strict=True))):
        raise ValueError("Allocation violates fiscal commitments.")
    for name, floor in limits.floors.items():
        if any(n < wanted for n, wanted in zip((per_group | per_cohort)[name], floor, strict=True)):
            raise ValueError("Allocation violates a timely-completion floor.")
    return {"reserved_by_month": reserved, "paid_by_month": paid, "added_count_by_scenario": count,
            "value_fen_by_scenario": value, "added_count_by_group": per_group,
            "added_count_by_cohort": per_cohort, "assigned_household_ids": assigned}


def upper_bound(remaining, room, extract, offset, scenarios):
    """Exact, safe upper bound from group limits and one-budget relaxations."""
    upper = [0] * scenarios
    zero_cost = [[0] * scenarios for _ in room]
    ratio = [[Fraction(0)] * scenarios for _ in room]
    for group, options in remaining:
        size = len(group.household_ids)
        for i in range(scenarios):
            distinct, maximum = 0, 0
            free_best = [0] * len(room)
            for option, cost in options:
                magnitude = extract(option)[i]
                if magnitude <= 0:
                    continue
                limit = min(size, rooms_for(cost, room, size))
                if not limit:
                    continue
                distinct += magnitude * limit
                maximum = max(maximum, magnitude)
                for j, need in enumerate(cost):
                    if need == 0:
                        free_best[j] = max(free_best[j], magnitude)
                    else:
                        ratio[j][i] = max(ratio[j][i], Fraction(magnitude, need))
            upper[i] += min(distinct, maximum * size)
            for j, free in enumerate(free_best):
                zero_cost[j][i] += size * free
    for i in range(scenarios):
        for j, available in enumerate(room):
            upper[i] = min(upper[i], zero_cost[j][i] + int(available * ratio[j][i]))
    return plus(tuple(upper), offset)


def choice_key(primary, reserved, paid, allocation):
    signature = tuple((gid, tuple(sorted(menu.items()))) for gid, menu in sorted(allocation.items()) if menu)
    return (-primary, sum(reserved), sum(paid), sum(sum(menu.values()) for menu in allocation.values()), signature)


def search(groups, limits, kind, scenario, benchmarks=None):
    zero = (0,) * limits.scenarios
    months = len(limits.month_caps)
    caps = (*limits.month_caps, limits.budget)
    extract = (lambda option: option.count) if kind == "count" else (lambda option: option.value)

    def primary(value, count):
        if kind == "count":
            return count[scenario]
        if kind == "gain":
            return value[scenario]
        return min(value if benchmarks is None else subtract(value, benchmarks))

    # Start with strong options to acquire a good feasible incumbent. Bounds include every remaining option.
    ordered = []
    for group in sorted(groups, key=lambda g: g.id):
        options = ((option, (*option.reserved, sum(option.reserved))) for option in group.options
                   if any(n > 0 for n in (*option.count, *option.value)))
        ordered.append((group, tuple(sorted(options, key=lambda pair:
                       (-max(extract(pair[0])), sum(pair[0].reserved), pair[0].id)))))
    ordered.sort(key=lambda row: -max((max(extract(option)) for option, _ in row[1]), default=0))

    future_floor = [{} for _ in range(len(ordered) + 1)]
    for k in range(len(ordered) - 1, -1, -1):
        group, options = ordered[k]
        potential = tuple(max((option.count[i] for option, _ in options), default=0) * len(group.household_ids)
                          for i in range(limits.scenarios))
        future_floor[k] = future_floor[k + 1].copy()
        for key in (group.id, group.cohort):
            if key in limits.floors:
                future_floor[k][key] = plus(future_floor[k].get(key, zero), potential)

    best = None
    winning_choices, picked = {}, {}
    nodes = pruned = 0

    def visit(index, room, paid, count, value, reached):
        nonlocal nodes, pruned, best, winning_choices
        nodes += 1
        for key, floor in limits.floors.items():
            available = plus(reached.get(key, zero), future_floor[index].get(key, zero))
            if any(n < f for n, f in zip(available, floor, strict=True)):
                pruned += 1
                return
        if index == len(ordered):
            key = choice_key(primary(value, count), subtract(caps[:months], room[:months]), paid, picked)
            if best is None or key < best:
                best, winning_choices = key, picked.copy()
            return
        if best is not None:
            bound = upper_bound(ordered[index:], room, extract, count if kind == "count" else value,
                                limits.scenarios)
            if primary(bound, bound) < -best[0]:
                pruned += 1
                return
        group, options = ordered[index]
        for choice, cost in group_decisions(group, room, options):
            _, price, add, gain = group_totals(group, choice, limits)
            if choice:
                picked[group.id] = choice
            else:
                picked.pop(group.id, None)
            added = reached.copy()
            for key in (group.id, group.cohort):
                if key in limits.floors:
                    added[key] = plus(added.get(key, zero), add)
            visit(index + 1, subtract(room, cost), plus(paid, price), plus(count, add), plus(value, gain), added)
        picked.pop(group.id, None)

    visit(0, caps, (0,) * months, zero, zero, {})
    if best is None:
        return {"status": "infeasible", "nodes_visited": nodes, "nodes_pruned": pruned}
    witness = totals(groups, winning_choices, limits)
    score = primary(witness["value_fen_by_scenario"], witness["added_count_by_scenario"])
    if -score != best[0]:
        raise ArithmeticError("Best objective disagrees with the fiscal and household witness.")
    return {"status": "optimal", "objective": kind, "objective_score": score if benchmarks is None else -score,
            "allocation": {gid: dict(sorted(menu.items())) for gid, menu in sorted(winning_choices.items())},
            **witness, "nodes_visited": nodes, "nodes_pruned": pruned}


def solve(groups, *, month_caps, budget, min_timely=None, objective="maximin_gain", scenario=0):
    """Return an exact optimum, or prove no allocation satisfies all requirements."""
    if objective not in ("count", "gain", "maximin_gain", "minimax_regret"):
        raise ValueError("Unsupported objective.")
    groups = tuple(groups)
    limits = validate(groups, month_caps, budget, min_timely, scenario)
    if objective != "minimax_regret":
        return search(groups, limits, objective, scenario)
    benchmark = [search(groups, limits, "gain", i) for i in range(limits.scenarios)]
    result = {"status": "infeasible"}
    if all(row["status"] == "optimal" for row in benchmark):
        best_by_state = tuple(row["objective_score"] for row in benchmark)
        result = search(groups, limits, objective, scenario, best_by_state)
        result["per_scenario_optimum_fen"] = best_by_state
        result["regret_fen_by_scenario"] = subtract(best_by_state, result["value_fen_by_scenario"])
    for label in ("nodes_visited", "nodes_pruned"):
        result[label] = result.get(label, 0) + sum(row[label] for row in benchmark)
    return result


def verify(groups, allocation, *, month_caps, budget, min_timely=None):
    """Check a witness without invoking search. Optimality additionally requires search bounds."""
    groups = tuple(groups)
    return totals(groups, allocation, validate(groups, month_caps, budget, min_timely, 0))
