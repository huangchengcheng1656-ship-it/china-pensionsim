"""Published Zhejiang worker and Hangzhou urban resident pension parameters."""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re


REGISTRY = Path(__file__).resolve().parent / "data" / "public" / "local_parameters.json"
FUTURE_START = "2027-01"
REFERENCE_MONTH = "2026-12"


class CoverageError(ValueError):
    """The requested month has no matching published evidence or scenario."""


def _month(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("Month must be YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Amount must be numeric") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amount must be finite and nonnegative")
    return amount


@dataclass(frozen=True)
class FutureScenario:
    """Explicit nominal freeze of the verified 2026 reference schedules."""
    through: str

    def __post_init__(self):
        if _month(self.through) < FUTURE_START:
            raise ValueError("Scenario end month precedes 2027-01")

    @classmethod
    def frozen_2026(cls, *, through):
        return cls(through=through)


@dataclass(frozen=True)
class Evidence:
    month: str
    source_mode: str
    reference_month: str
    document: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class WorkerRules(Evidence):
    floor: int
    ceiling: int
    retirement_base: int
    ordinary_employee_person_rate: float
    employer_example_rate: float
    flexible_employment_rate: float
    individual_account_credit_rate: float

    def clamp_base(self, yuan):
        """Clip a declared personal contribution wage to the applicable limits."""
        return min(Decimal(self.ceiling), max(Decimal(self.floor), _money(yuan)))


@dataclass(frozen=True)
class ResidentTier(Evidence):
    own_yuan: int
    government_credit_yuan: int

    @property
    def total_account_credit_yuan(self):
        return self.own_yuan + self.government_credit_yuan


@dataclass(frozen=True)
class EvidenceAmount(Evidence):
    amount: int
    observed_on: str


@dataclass(frozen=True)
class ResidentPayment:
    month: str
    tier: ResidentTier
    own_yuan: int
    government_credit_yuan: int
    credited_contribution_years: int

    @property
    def total_account_credit_yuan(self):
        return self.own_yuan + self.government_credit_yuan


def _period_bounds(row):
    starts_on = date.fromisoformat(row["applies_from"])
    ends_on = date.fromisoformat(row["applies_through"]) if row["applies_through"] else None
    if starts_on.day != 1 or (ends_on and ends_on.day != monthrange(ends_on.year, ends_on.month)[1]):
        raise ValueError(f"Expected full calendar months for {row['document']}")
    start = starts_on.isoformat()[:7]
    through = ends_on.isoformat()[:7] if ends_on else REFERENCE_MONTH
    if start > through:
        raise ValueError(f"Reversed effective interval for {row['document']}")
    return start, through


def _checked_periods(rows):
    periods = sorted(((_period_bounds(row), row) for row in rows), key=lambda period: period[0])
    for (prior_bounds, _), (current_bounds, _) in zip(periods, periods[1:]):
        if prior_bounds[1] >= current_bounds[0]:
            raise ValueError("Overlapping regional rule periods")
    return periods


def _select_period(periods, reference, label):
    for (start, through), row in periods:
        if start <= reference <= through:
            return row
    raise CoverageError(f"{label} has no verified effective coverage for {reference}")


def _lookup_month(month, scenario):
    requested = _month(month)
    if scenario is not None and not isinstance(scenario, FutureScenario):
        raise TypeError("scenario must be a FutureScenario")
    if requested >= FUTURE_START and scenario is not None and requested <= scenario.through:
        return requested, REFERENCE_MONTH, "scenario_freeze_2026"
    return requested, requested, "published_effective_period"


class RegionalProfile:
    """Zhejiang employee rules and a separate Hangzhou urban resident profile."""

    def __init__(self, registry):
        employee = registry["employee"]
        resident = registry["hangzhou_urban_resident"]
        self._worker_periods = _checked_periods(employee["periods"])
        self._resident_periods = _checked_periods(resident["contribution_periods"])
        self._rate_fields = {
            key: float(employee[key]) for key in (
                "ordinary_employee_person_rate",
                "employer_example_rate",
                "flexible_employment_rate",
                "individual_account_credit_rate",
            )
        }
        if any(not 0 <= rate <= 1 for rate in self._rate_fields.values()):
            raise ValueError("Regional contribution rates must be between zero and one")
        self._snapshots = {}
        for snapshot in resident["payment_amount_snapshots"]:
            month = _month(snapshot["as_of"][:7])
            if month in self._snapshots:
                raise ValueError(f"Duplication of resident basic amount snapshots: {month}")
            self._snapshots[month] = snapshot
        self.resident_region = resident["region"]
        self.worker_region = employee["region"]
        self.resident_claim_age_years = resident["standard_claim_age_years"]
        self.resident_claim_minimum_years = resident["standard_claim_minimum_contribution_years"]
        self.resident_account_divisor = resident["account_divisor_months"]

    @classmethod
    def load(cls, path=None):
        with Path(path or REGISTRY).open(encoding="utf-8-sig") as file:
            return cls(json.load(file))

    def worker(self, month, *, scenario=None):
        requested, reference, mode = _lookup_month(month, scenario)
        row = _select_period(self._worker_periods, reference, "Zhejiang worker rules")
        floor = row["floor_yuan_per_month"]
        ceiling = row["ceiling_yuan_per_month"]
        retirement_base = row["new_retiree_wage_yuan_per_month"]
        if not 0 < floor <= retirement_base <= ceiling:
            raise ValueError("Invalid worker floor, ceiling or retirement base")
        return WorkerRules(
            requested, mode, reference, row["document"], tuple(row["sources"]),
            floor, ceiling, retirement_base, **self._rate_fields,
        )

    def resident_tier(self, month, annual_tier, *, scenario=None):
        requested, reference, mode = _lookup_month(month, scenario)
        current = _select_period(self._resident_periods, reference, "Hangzhou urban resident tiers")
        tiers = current["tier_to_account_credit_yuan_per_year"]
        if type(annual_tier) is not int or str(annual_tier) not in tiers:
            raise ValueError(f"Annual tier must be a published integer amount in {', '.join(tiers)} yuan")
        amount = tiers[str(annual_tier)]
        if type(amount) is not int or amount < 0:
            raise ValueError("Invalid resident tier credit")
        return ResidentTier(
            requested, mode, reference, current["document"], tuple(current["sources"]), annual_tier, amount,
        )

    def resident_basic(self, month, *, scenario=None):
        requested, reference, mode = _lookup_month(month, scenario)
        if mode == "scenario_freeze_2026":
            reference = max((key for key in self._snapshots if key.startswith("2026-")), default=reference)
        if reference not in self._snapshots:
            raise CoverageError(f"Hangzhou urban resident basic amount has no verified observation in {reference}")
        row = self._snapshots[reference]
        if mode == "published_effective_period":
            mode = "published_observation_month"
        return EvidenceAmount(
            requested, mode, reference, "Hangzhou resident basic pension public observation",
            (row["source"],), row["basic_yuan_per_month"], row["as_of"],
        )

    def resident_payment(self, month, annual_tier, *, prior=None, scenario=None):
        """Book one ordinary yearly payment or one same-year upward correction."""
        tier = self.resident_tier(month, annual_tier, scenario=scenario)
        if prior is None:
            return ResidentPayment(month, tier, tier.own_yuan, tier.government_credit_yuan, 1)
        if not isinstance(prior, ResidentPayment):
            raise TypeError("prior must be the latest ResidentPayment in this contribution year")
        if prior.month[:4] != month[:4] or prior.month > month:
            raise ValueError("Tier correction requires a prior payment in the same year")
        if prior.credited_contribution_years != 1 or annual_tier <= prior.tier.own_yuan:
            raise ValueError("Only one upward tier correction per paid calendar year is allowed")
        if prior.tier != self.resident_tier(prior.month, prior.tier.own_yuan, scenario=scenario):
            raise ValueError("Prior resident payment does not match the current profile or scenario")
        return ResidentPayment(
            month, tier, tier.own_yuan - prior.tier.own_yuan,
            tier.government_credit_yuan - prior.tier.government_credit_yuan, 0,
        )
