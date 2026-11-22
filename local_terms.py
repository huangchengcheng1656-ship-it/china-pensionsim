"""Conventions that map jurisdictional evidence into the synthetic monthly simulator."""
from dataclasses import dataclass
from math import isfinite


def calendar(t):
    y, m = divmod(t, 12)
    return f"{y:04d}-{m+1:02d}"


@dataclass(frozen=True)
class LocalTerms:
    profile: object
    worker_region: str
    resident_region: str
    annual_tier: int
    resident_payment_month: int
    resident_benefit_override: float | None
    resident_override_basis: str | None
    future_scenario: object = None

    def __post_init__(self):
        if not isinstance(self.worker_region, str) or not self.worker_region.strip():
            raise ValueError("worker_region must be a nonempty synthetic or administrative label")
        if not isinstance(self.resident_region, str) or not self.resident_region.strip():
            raise ValueError("resident_region must be a nonempty synthetic or administrative label")
        if type(self.resident_payment_month) is not int or not 1 <= self.resident_payment_month <= 12:
            raise ValueError("specify a modeled annual resident payment month (1–12)")
        if self.resident_benefit_override is not None and (
            not isfinite(self.resident_benefit_override) or self.resident_benefit_override < 0
            or not self.resident_override_basis
        ):
            raise ValueError("a resident-benefit assumption requires an explicit basis")

    def employee(self, t):
        return self.profile.worker(calendar(t), scenario=self.future_scenario)

    def resident(self, t):
        return self.profile.resident_tier(calendar(t), self.annual_tier, scenario=self.future_scenario)

    def resident_benefit(self, t):
        if self.resident_benefit_override is not None:
            return self.resident_benefit_override
        return float(self.profile.resident_basic(calendar(t), scenario=self.future_scenario).amount)


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

