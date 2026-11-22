"""Bound minimum-period attainment with survey stocks and a standardized payment scenario."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import fsum, inf, isfinite
from typing import Iterable

STATES = ("opening_duration_met", "window_too_short", "insufficient_after_support",
          "affordable_only_with_support", "affordable_at_full_price")
EVENTS = {
    "opening_duration_met": frozenset([STATES[0]]),
    "window_too_short": frozenset([STATES[1]]),
    "needs_payment_and_window_is_long_enough": frozenset(STATES[2:]),
    "can_reach_full_price": frozenset([STATES[0], STATES[4]]),
    "can_reach_with_support": frozenset([STATES[0], *STATES[3:]]),
    "lift_from_support_only": frozenset([STATES[3]]),
    "can_complete_new_payments_with_support": frozenset(STATES[3:]),
    "insufficient_after_support": frozenset([STATES[2]]),
}


@dataclass(frozen=True)
class Plan:
    threshold_months: int
    future_months: int
    payment_yuan: float
    support_yuan_per_month: float
    protected_expense_months: float
    available_household_share: float
    reporting_error_months: int

    def __post_init__(self):
        for value in (self.threshold_months,self.future_months,self.reporting_error_months):
            if type(value) is not int or value < 0:
                raise ValueError("Months must be nonnegative integers.")
        numbers=(self.payment_yuan,self.support_yuan_per_month,self.protected_expense_months,self.available_household_share)
        if not all(isfinite(x) for x in numbers):
            raise ValueError("Financial inputs must be finite.")
        if not (self.threshold_months>0 and self.future_months<=120 and self.payment_yuan>0
                and 0<=self.support_yuan_per_month<self.payment_yuan and self.protected_expense_months>=0
                and 0<=self.available_household_share<=1):
            raise ValueError("Invalid standardized scenario.")


def monthly_equivalent(years):
    """Convert the survey decimal answer as a scenario assumption, using half-up rounding."""
    if not isfinite(years) or years<0:
        raise ValueError("Invalid reported duration.")
    return int((Decimal(str(years))*12).to_integral_value(rounding=ROUND_HALF_UP))


def assumed_months(reported, chronological_upper, error):
    if reported is None:
        return 0,chronological_upper
    near=monthly_equivalent(reported)
    if near>chronological_upper:
        raise ValueError("Report exceeds the broad chronological limit.")
    return max(0,near-error),min(near+error,chronological_upper)


def financial_interval(bounds):
    lo,hi=bounds
    hi=inf if hi is None else hi
    if not isfinite(lo) or not (0<=lo<=hi):
        raise ValueError("Monetary uncertainty interval is invalid.")
    return lo,hi


def payment_capacity(liquid, expenses, plan):
    assets_lo,assets_hi=financial_interval(liquid)
    expenses_lo,expenses_hi=financial_interval(expenses)
    if plan.available_household_share==0:
        return 0.,0.
    protect=plan.protected_expense_months
    lower=max(0.,assets_lo-protect*expenses_hi) if protect else assets_lo
    upper=max(0.,assets_hi-protect*expenses_lo)
    return lower*plan.available_household_share,upper*plan.available_household_share


def possible_states(months, liquid, expenses, plan):
    first,last=months
    if not (type(first) is int and type(last) is int and 0<=first<=last):
        raise ValueError("Opening months must be a valid whole-month interval.")
    can_use_lo,can_use_hi=payment_capacity(liquid,expenses,plan)
    states={}
    if last>=plan.threshold_months:
        states[STATES[0]]=[0.]
    if first<plan.threshold_months-plan.future_months:
        states[STATES[1]]=[0.]
    gap_min=max(1,plan.threshold_months-last)
    gap_max=min(plan.future_months,plan.threshold_months-first)
    payment=Decimal(str(plan.payment_yuan))
    support=Decimal(str(plan.support_yuan_per_month))
    for need in range(gap_min,gap_max+1):
        full=float(need*payment)
        net=float(need*(payment-support))
        paid=float(need*support)
        if can_use_lo<net:
            states.setdefault(STATES[2],[]).append(0.)
        if net<full and can_use_lo<full and can_use_hi>=net:
            states.setdefault(STATES[3],[]).append(paid)
        if can_use_hi>=full:
            states.setdefault(STATES[4],[]).append(paid)
    if not states:
        raise ArithmeticError("At least one opening and affordability state must remain possible.")
    return states


def report_weighted(cases: Iterable, minimum_support=20):
    """Summarize per-unit feasible states and preserve the same latent values across policies."""
    cases=list(cases)
    if not cases or any(not isfinite(w) or w<=0 or not states for w,states in cases):
        raise ValueError("Use positive weights and a complete feasible support.")
    weights=[w for w,_ in cases]
    total=fsum(weights)
    n=len(cases)
    kish=round(total**2/fsum(w*w for w in weights),2)
    if n<minimum_support:
        return {"status":"suppressed_small_denominator"}
    intervals={}
    for key,event in EVENTS.items():
        parts=[(w,set(s)<=event,bool(set(s)&event)) for w,s in cases]
        counts=[sum(p[k] for p in parts) for k in (1,2)]
        protected=any(0<min(count,n-count)<minimum_support for count in counts)
        intervals[key]={"status":"withheld_small_support"} if protected else {
            "status":"range","share":[fsum(p[0] for p in parts if p[k])/total for k in (1,2)]}
    prices=[(w,[cost for choices in outcome.values() for cost in choices]) for w,outcome in cases]
    direct=[fsum(w*edge(values) for w,values in prices)/total for edge in (min,max)]
    above=sum(max(c)>0 for _,c in prices)
    definite=sum(min(c)>0 for _,c in prices)
    prices_visible=not any(0<min(n-count,count)<minimum_support for count in (above,definite))
    return {"status":"available","denominator":{"n":n,"kish_n_eff":kish},"events":intervals,
            "direct_supported_completion_cost_yuan_per_target":[*direct] if prices_visible else None}


def grouped_point_masses(cases):
    """Use disclosed group pattern masses. The resulting bounds also incorporate grouping coarseness."""
    cases=list(cases)
    if not cases or any(not isfinite(w) or w<0 or not s for w,s in cases):
        raise ValueError("Incompatible public pattern weight or support.")
    if abs(fsum(w for w,_ in cases)-1)>1e-8:
        raise ValueError("Pattern weights must exhaust the group.")
    return {key:[fsum(w for w,states in cases if predicate(states,event))
                 for predicate in (lambda s,e:set(s)<=e,lambda s,e:bool(set(s)&e))]
            for key,event in EVENTS.items()}

