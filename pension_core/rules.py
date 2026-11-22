"""Central rules used by the demonstration, with explicit local assumptions."""
from bisect import bisect_right
from math import isfinite

ORIGINAL_AGES = {"male60": 60, "female55": 55, "female50": 50}
PAYOUT_DIVISORS = (195, 190, 185, 180, 175, 170, 164, 158, 152, 145, 139,
                   132, 125, 117, 109, 101, 93, 84, 75, 65, 56)
# 财税〔2018〕164号月度表（年金）与综合所得年度表共享税率，税基及档距不同。
MONTHLY_TAX_BOUNDS = (3000, 12000, 25000, 35000, 55000, 80000)
RATES = (0.03, 0.10, 0.20, 0.25, 0.30, 0.35, 0.45)

def month(year: int, calendar_month: int) -> int:
    if not 1 <= calendar_month <= 12:
        raise ValueError("expected month 1–12")
    return year * 12 + calendar_month - 1

def retirement_month(birth: int, category: str, reform: bool = True) -> int:
    original = birth + 12 * ORIGINAL_AGES[category]
    offset = original - month(2025, 1)
    if not reform or offset < 0:
        return original
    pace, limit = (2, 60) if category == "female50" else (4, 36)
    return original + min(limit, 1 + offset // pace)

def minimum_months(year: int, reform: bool = True) -> int:
    return 180 + 6 * min(10, max(0, year - 2029)) if reform else 180

def payout_divisor(age_months: int, interpolation: str = "linear") -> float:
    age = min(70 * 12, max(50 * 12, age_months))
    whole, part = divmod(age, 12)
    floor_value = PAYOUT_DIVISORS[whole - 50]
    if part == 0 or interpolation == "floor":
        return floor_value
    ceil_value = PAYOUT_DIVISORS[whole + 1 - 50]
    if interpolation == "ceil":
        return ceil_value
    if interpolation != "linear":
        raise ValueError(interpolation)
    return floor_value + (ceil_value - floor_value) * part / 12

def progressive_tax(taxable: float, annual: bool) -> float:
    if not isfinite(taxable):
        raise ValueError("tax base must be finite")
    if taxable <= 0:
        return 0.0
    bounds = [bound * (12 if annual else 1) for bound in MONTHLY_TAX_BOUNDS]
    count = bisect_right(bounds, taxable)
    starts = [0, *bounds]
    established = sum((bounds[i] - starts[i]) * RATES[i] for i in range(count))
    return established + (taxable - starts[count]) * RATES[count]

def worker_benefit(base: float, average_index: float, credited: int,
                   account: float, age_months: int, interpolation: str) -> float:
    pooled = base * (1 + average_index) / 2 * (credited / 12) * 0.01
    return pooled + account / payout_divisor(age_months, interpolation)
