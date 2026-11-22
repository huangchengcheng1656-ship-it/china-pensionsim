"""Validate the release's public, reviewed-aggregate and synthetic CSV interfaces."""
import argparse
import csv
from datetime import date
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
COMMON = ("dataset_type", "review_status", "review_reference")
SCHEMAS = {
    "cfps_transitions.csv": COMMON + (
        "wave_pair", "age_band", "sex", "employment_from", "employment_to",
        "pension_from", "pension_to", "weighted_transitions", "unweighted_n",
        "effective_n", "missing_share",
    ),
    "charls_benefits.csv": COMMON + (
        "wave", "pension_scheme", "age_band", "sex", "weighted_mean_monthly",
        "weighted_median_monthly", "recipient_weight", "unweighted_n",
        "missing_lower", "missing_upper",
    ),
    "regional_parameters.csv": COMMON + (
        "province", "area_level", "area_name", "year", "average_wage_monthly", "contribution_floor_monthly",
        "contribution_ceiling_monthly", "retirement_base_monthly", "resident_basic_monthly",
        "source_url", "document", "effective_from", "verification_status",
    ),
    "official_macro.csv": COMMON + (
        "region", "year", "scheme", "participants", "contributors", "recipients",
        "fund_income_yuan", "fund_expenditure_yuan", "fiscal_subsidy_yuan",
        "statistical_scope", "source_url", "document",
    ),
    "admin_validation.csv": COMMON + (
        "person_key", "baseline_month", "worker_actual_months", "worker_deemed_months",
        "resident_credited_months", "contribution_period_month", "posting_month",
        "contribution_base_yuan", "transfer_completion_date", "retirement_category",
        "assessment_month", "first_payment_month", "bank_receipt_yuan", "verified_zero_receipt",
    ),
}
DEFAULT_FILES = tuple(ROOT / "data" / "synthetic" / name for name in SCHEMAS) + (
    ROOT / "data" / "public" / "regional_parameters.csv",
)
OPTIONAL = {"review_reference", "source_url", "document"}
REGIONAL_WORKER = {
    "average_wage_monthly", "contribution_floor_monthly", "contribution_ceiling_monthly",
    "retirement_base_monthly",
}
REGIONAL_CONDITIONAL = REGIONAL_WORKER | {"resident_basic_monthly", "effective_from"}
NONNEGATIVE = {
    "weighted_transitions", "effective_n", "weighted_mean_monthly", "weighted_median_monthly",
    "recipient_weight", "average_wage_monthly", "contribution_floor_monthly",
    "contribution_ceiling_monthly", "retirement_base_monthly", "resident_basic_monthly",
    "fund_income_yuan", "fund_expenditure_yuan", "fiscal_subsidy_yuan",
    "contribution_base_yuan", "bank_receipt_yuan",
}
INTEGERS = {
    "unweighted_n", "wave", "year", "participants", "contributors", "recipients",
    "worker_actual_months", "worker_deemed_months", "resident_credited_months",
}
MONTHS = {
    "baseline_month", "contribution_period_month", "posting_month", "assessment_month",
    "first_payment_month",
}
REVIEW_REFERENCE = re.compile(r"[A-Za-z0-9._-]{3,64}\Z")


def _number(row, field, line, errors, *, integer=False):
    raw = row.get(field, "")
    try:
        if integer and not re.fullmatch(r"[0-9]+", raw):
            raise ValueError
        value = int(raw) if integer else float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        errors.append(f"line {line}: {field} must be a finite nonnegative {'integer' if integer else 'number'}")
        return None
    return value


def _month(value):
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("month must be YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


def _full_date(value):
    date.fromisoformat(value)
    return value


def _common(row, line, errors):
    kind = row.get("dataset_type")
    status = row.get("review_status")
    reference = row.get("review_reference", "")
    if kind == "synthetic":
        if status != "not_required" or reference:
            errors.append(f"line {line}: synthetic rows must use review_status=not_required and no review reference")
    elif kind == "real_aggregate":
        if status != "approved" or not REVIEW_REFERENCE.fullmatch(reference):
            errors.append(f"line {line}: real_aggregate requires approved review and a valid review_reference")
    elif kind == "public_official":
        if status != "source_checked":
            errors.append(f"line {line}: public_official requires review_status=source_checked")
        sources = re.split(r"[\s;|]+", row.get("source_url", "").strip())
        if not row.get("source_url") or not row.get("document") or any(not item.startswith("https://") for item in sources):
            errors.append(f"line {line}: public_official requires document and HTTPS source_url")
    else:
        errors.append(f"line {line}: dataset_type must be synthetic, real_aggregate or public_official")


def _relations(name, row, line, errors):
    if name == "cfps_transitions.csv":
        match = re.fullmatch(r"([0-9]{4})-([0-9]{4})", row["wave_pair"])
        if not match or not int(match[1]) < int(match[2]):
            errors.append(f"line {line}: wave_pair must contain ascending YYYY-YYYY waves")
        for field in ("employment_from", "employment_to"):
            if row[field] not in {"standard", "nonstandard", "out", "unknown"}:
                errors.append(f"line {line}: invalid {field}")
        for field in ("pension_from", "pension_to"):
            if row[field] not in {"worker", "resident", "none", "unknown"}:
                errors.append(f"line {line}: invalid {field}")
        if row["sex"] not in {"female", "male", "all"}:
            errors.append(f"line {line}: sex must be female, male or all")
    elif name == "charls_benefits.csv":
        if row["pension_scheme"] not in {"worker", "resident"}:
            errors.append(f"line {line}: pension_scheme must be worker or resident")
        if row["sex"] not in {"female", "male", "all"}:
            errors.append(f"line {line}: sex must be female, male or all")
    elif name == "regional_parameters.csv":
        if row["verification_status"] not in {"synthetic_unverified", "verified"}:
            errors.append(f"line {line}: invalid verification_status")
        if row["dataset_type"] == "public_official" and row["verification_status"] != "verified":
            errors.append(f"line {line}: public_official regional parameters must be verified")
        level = row["area_level"]
        if level not in {"province", "city"}:
            errors.append(f"line {line}: area_level must be province or city")
            return
        if level == "province":
            for field in REGIONAL_WORKER | {"effective_from"}:
                if not row[field].strip():
                    errors.append(f"line {line}: {field} is required for province worker parameters")
            if row["resident_basic_monthly"].strip():
                errors.append(f"line {line}: province worker rows cannot mix city resident parameters")
        else:
            if not row["resident_basic_monthly"].strip():
                errors.append(f"line {line}: resident_basic_monthly is required for city resident parameters")
            if any(row[field].strip() for field in REGIONAL_WORKER):
                errors.append(f"line {line}: city resident rows cannot mix province worker parameters")
    elif name == "official_macro.csv" and row["scheme"] not in {"worker", "resident"}:
        errors.append(f"line {line}: scheme must be worker or resident")
    elif name == "admin_validation.csv" and row["verified_zero_receipt"] not in {"0", "1"}:
        errors.append(f"line {line}: verified_zero_receipt must be 0 or 1")


def _numeric_relations(name, values, row, line, errors):
    def value(field):
        return values.get(field)

    if name == "cfps_transitions.csv":
        if value("unweighted_n") is not None and value("unweighted_n") <= 0:
            errors.append(f"line {line}: unweighted_n must be greater than zero")
        if None not in (value("effective_n"), value("unweighted_n")) and value("effective_n") > value("unweighted_n"):
            errors.append(f"line {line}: effective_n cannot exceed unweighted_n")
        if value("missing_share") is not None and not 0 <= value("missing_share") <= 1:
            errors.append(f"line {line}: missing_share must be between zero and one")
    elif name == "charls_benefits.csv":
        lower, upper = value("missing_lower"), value("missing_upper")
        for field, number in (("missing_lower", lower), ("missing_upper", upper)):
            if number is not None and not 0 <= number <= 1:
                errors.append(f"line {line}: {field} must be between zero and one")
        if None not in (lower, upper) and lower > upper:
            errors.append(f"line {line}: missing_lower cannot exceed missing_upper")
    elif name == "regional_parameters.csv":
        floor, ceiling = value("contribution_floor_monthly"), value("contribution_ceiling_monthly")
        if None not in (floor, ceiling) and floor > ceiling:
            errors.append(f"line {line}: contribution floor cannot exceed ceiling")
        for field in ("average_wage_monthly", "retirement_base_monthly"):
            if value(field) == 0:
                errors.append(f"line {line}: {field} must be positive")
    elif name == "official_macro.csv":
        participants, contributors = value("participants"), value("contributors")
        if None not in (participants, contributors) and contributors > participants:
            errors.append(f"line {line}: contributors cannot exceed participants")
    elif name == "admin_validation.csv":
        try:
            if row["posting_month"] < row["contribution_period_month"]:
                errors.append(f"line {line}: posting_month precedes contribution_period_month")
            if row["first_payment_month"] < row["assessment_month"]:
                errors.append(f"line {line}: first_payment_month precedes assessment_month")
        except KeyError:
            pass
        if row.get("verified_zero_receipt") == "1" and value("bank_receipt_yuan") not in (None, 0):
            errors.append(f"line {line}: verified_zero_receipt=1 requires zero bank_receipt_yuan")


def validate_file(path, schema=None):
    """Return human-readable errors; an empty list means the CSV is accepted.

    ``schema`` names the standard table when the file has another name.
    """
    path = Path(path)
    name = schema or path.name
    prefix = f"{path}: "
    if name not in SCHEMAS:
        return [prefix + "unknown dataset filename"]
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)):
                return [prefix + "duplicate column names"]
            missing = [field for field in SCHEMAS[name] if field not in fields]
            if missing:
                return [prefix + "missing required columns: " + ", ".join(missing)]
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        return [prefix + f"unreadable CSV: {error}"]
    if not rows:
        return [prefix + "no data rows"]
    errors = []
    for line, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()):
            errors.append(f"line {line}: malformed CSV row")
            continue
        conditional = REGIONAL_CONDITIONAL if name == "regional_parameters.csv" else set()
        required = [field for field in SCHEMAS[name] if field not in OPTIONAL | conditional]
        for field in required:
            if not row.get(field, "").strip():
                errors.append(f"line {line}: {field} is required")
        _common(row, line, errors)
        if any(not row.get(field, "").strip() for field in required):
            continue
        _relations(name, row, line, errors)
        values = {}
        for field in NONNEGATIVE | INTEGERS | {"missing_share", "missing_lower", "missing_upper"}:
            if field in row and (row[field].strip() or field not in conditional):
                values[field] = _number(row, field, line, errors, integer=field in INTEGERS)
        for field in MONTHS:
            if field in row:
                try:
                    _month(row[field])
                except ValueError:
                    errors.append(f"line {line}: {field} must be a valid YYYY-MM")
        if name == "regional_parameters.csv":
            if row["effective_from"].strip():
                try:
                    _full_date(row["effective_from"])
                except ValueError:
                    errors.append(f"line {line}: effective_from must be a valid YYYY-MM-DD")
        elif name == "admin_validation.csv":
            try:
                _full_date(row["transfer_completion_date"])
            except ValueError:
                errors.append(f"line {line}: transfer_completion_date must be a valid YYYY-MM-DD")
        _numeric_relations(name, values, row, line, errors)
    return [prefix + error for error in errors]


def validate_paths(paths):
    errors = []
    for item in paths:
        path = Path(item)
        files = sorted(path.glob("*.csv")) if path.is_dir() else [path]
        if path.is_dir() and not files:
            errors.append(f"{path}: no CSV files")
        for file in files:
            errors.extend(validate_file(file))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=list(DEFAULT_FILES),
                        help="known CSV files or directories; defaults to supplied samples and public regional inputs")
    args = parser.parse_args(argv)
    paths = args.paths or list(DEFAULT_FILES)
    files = [file for path in paths
             for file in (sorted(path.glob("*.csv")) if path.is_dir() else [path])]
    errors = validate_paths(paths)
    print(json.dumps({"files_checked": len(files), "errors": errors}, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
