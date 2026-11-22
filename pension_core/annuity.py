"""Vesting and custody events for enterprise and occupational annuities."""
from dataclasses import dataclass
from fractions import Fraction
if __package__:
    from .portability import money
else:
    from portability import money

FULL_VESTING = {
    "statutory_retirement", "complete_disability", "death", "plan_termination",
    "employer_termination_without_worker_fault", "worker_resigns_employer_breach",
    "employer_declines_renewal", "documented_plan_event",
}


@dataclass(frozen=True)
class Entitlement:
    enterprise_personal: Fraction = Fraction()
    enterprise_employer: Fraction = Fraction()
    occupational_real: Fraction = Fraction()
    occupational_book: Fraction = Fraction()
    occupational_supplemental: Fraction = Fraction()

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, money(getattr(self,name)))

    def total(self):
        return sum(vars(self).values(), Fraction())


def exit_job(opening, *, service_months, vesting_schedule, exit_reason,
             receiving_plan, funded_book=0, same_fiscal_body=False,
             employer_contract_verified=False):
    """Calculate custody and employer reversion, keeping origin components distinct."""
    if type(service_months) is not int or service_months < 0:
        raise ValueError("validated completed service months required")
    if receiving_plan not in ("enterprise", "occupational", "none"):
        raise ValueError("document the receiving plan or that it is absent")
    if exit_reason not in FULL_VESTING | {"ordinary_exit"}:
        raise ValueError("unknown reason; use alternative verifiable vesting scenarios")
    if opening.enterprise_employer and exit_reason not in FULL_VESTING:
        if not employer_contract_verified:
            raise ValueError("ordinary exit requires the employer's verified vesting plan")
        steps = [(m, money(v)) for m,v in vesting_schedule]
        if (not steps or steps[0][0] != 0 or steps[-1][1] != 1
                or any(type(m) is not int or not 0 <= m <= 96 or not 0 <= v <= 1 for m,v in steps)
                or any(a[0] >= b[0] or a[1] > b[1] for a,b in zip(steps,steps[1:]))):
            raise ValueError("vesting must be monotone and reach 100% within eight years")
        owned_share = max(v for m,v in steps if m <= service_months)
    else:
        owned_share = Fraction(1)
    reversion = opening.enterprise_employer * (1-owned_share)
    real = opening.occupational_real
    book = opening.occupational_book
    funded = money(funded_book)
    if funded > book:
        raise ValueError("funded amount exceeds original verified book credit")
    if book and receiving_plan != "none":
        allowed_book = receiving_plan == "occupational" and same_fiscal_body
        if not allowed_book and funded != book:
            raise ValueError("cash-funded conversion must be independently evidenced before this transfer")
    if funded:
        real += funded
        book -= funded
    preserved = Entitlement(opening.enterprise_personal, opening.enterprise_employer * owned_share,
                            real, book, opening.occupational_supplemental)
    if opening.total() != preserved.total() + reversion:
        raise ArithmeticError("portable balances do not reconcile")
    return {"preserved": preserved, "returns_to_enterprise_plan": reversion, "separate_cash_funding": funded,
            "receiving_plan": receiving_plan, "custody": "retained_without_new_contributions"
            if receiving_plan == "none" else "transfer_to_verified_receiving_plan"}
