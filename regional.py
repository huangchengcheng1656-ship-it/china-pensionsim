"""Apply the layered public regional CSV to explicit synthetic-carrier scenarios."""
import csv
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path

import data_validation

from local_terms import LocalTerms
from regional_profile import FutureScenario, RegionalProfile

ROOT = Path(__file__).resolve().parent
REGIONAL_CSV = ROOT / "data" / "public" / "regional_parameters.csv"
LOCAL_REGISTRY = ROOT / "data" / "public" / "local_parameters.json"
SYNTHETIC_REGION = "synthetic_single_region"


def _one(rows, *, level, name=None, province=None):
    selected = [row for row in rows
                if row["area_level"] == level and row["year"] == "2026"
                and (name is None or row["area_name"] == name)
                and (province is None or row["province"] == province)]
    if len(selected) != 1:
        label = name or province
        raise ValueError(f"需要唯一且已登记的 2026 年地区参数：{label}；当前公开适配为浙江省")
    row = selected[0]
    if row["dataset_type"] != "public_official" or row["verification_status"] != "verified":
        raise ValueError("区域计算只接受已核验的 public_official 参数行")
    return row


def load_terms(region, *, through="2039-12", csv_path=None, registry_path=None):
    """Build Zhejiang worker / Hangzhou urban resident terms for synthetic carriers."""
    path = Path(csv_path or REGIONAL_CSV)
    # Every entry point applies the same contract as data_validation.py.
    errors = data_validation.validate_file(path, schema="regional_parameters.csv")
    if errors:
        raise ValueError("区域参数表未通过校验：" + "；".join(errors))
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    worker_row = _one(rows, level="province", name=region)
    resident_row = _one(rows, level="city", name="杭州市区", province=region)
    if region != "浙江省":
        raise ValueError("当前公开参数适配仅支持浙江省；请补充登记和适用域审阅后再扩展")

    registry = deepcopy(json.loads(Path(registry_path or LOCAL_REGISTRY).read_text(encoding="utf-8-sig")))
    periods = registry["employee"]["periods"]
    period = next(row for row in periods if row["applies_from"].startswith("2026-"))
    effective = worker_row["effective_from"]
    if not (period["applies_from"] <= effective <= period["applies_through"]) or not effective.endswith("-01"):
        raise ValueError("effective_from 须为 2026 年登记期间内某月 1 日")
    csv_terms = dict(
        floor_yuan_per_month=int(worker_row["contribution_floor_monthly"]),
        ceiling_yuan_per_month=int(worker_row["contribution_ceiling_monthly"]),
        new_retiree_wage_yuan_per_month=int(worker_row["retirement_base_monthly"]),
        document=worker_row["document"],
        sources=list(dict.fromkeys([*period["sources"], worker_row["source_url"]])),
    )
    if effective == period["applies_from"]:
        period.update(csv_terms)
    else:
        # Split the year: registered terms before the CSV's effective date, CSV terms from it.
        later = deepcopy(period) | csv_terms | {"applies_from": effective}
        period["applies_through"] = (date.fromisoformat(effective) - timedelta(days=1)).isoformat()
        periods.insert(periods.index(period) + 1, later)
    snapshots = registry["hangzhou_urban_resident"]["payment_amount_snapshots"]
    snapshot = max((row for row in snapshots if row["as_of"].startswith("2026-")),
                   key=lambda row: row["as_of"])
    snapshot["basic_yuan_per_month"] = int(resident_row["resident_basic_monthly"])
    snapshot["source"] = resident_row["source_url"]

    profile = RegionalProfile(registry)
    profile.selection = {
        "worker_area_level": worker_row["area_level"],
        "worker_area_name": worker_row["area_name"],
        "resident_area_level": resident_row["area_level"],
        "resident_area_name": resident_row["area_name"],
        "resident_observed_on": snapshot["as_of"],
        "through": through,
    }
    return LocalTerms(
        profile=profile,
        worker_region=SYNTHETIC_REGION,
        resident_region=SYNTHETIC_REGION,
        annual_tier=300,
        resident_payment_month=12,
        resident_benefit_override=float(snapshot["basic_yuan_per_month"]),
        resident_override_basis=(
            f"杭州市区{snapshot['as_of']}公开观察值；作为合成情景固定额，"
            "不据此推断首次生效日期"
        ),
        future_scenario=FutureScenario.frozen_2026(through=through),
    )


def describe(terms):
    """Return output metadata without presenting synthetic carriers as regional samples."""
    selected = terms.profile.selection
    worker = terms.profile.worker("2026-01")
    return {
        "mode": "regional_public_scenario",
        "label": "浙江省职工／杭州市区居民公开参数（合成载体情景）",
        "worker_area_level": selected["worker_area_level"],
        "worker_area_name": selected["worker_area_name"],
        "resident_area_level": selected["resident_area_level"],
        "resident_area_name": selected["resident_area_name"],
        "worker_contribution_floor_monthly": worker.floor,
        "worker_contribution_ceiling_monthly": worker.ceiling,
        "worker_retirement_base_monthly": worker.retirement_base,
        "resident_basic_monthly": int(terms.resident_benefit_override),
        "resident_observed_on": selected["resident_observed_on"],
        "carrier_mapping": (
            f"公开参数应用于合成载体；历史一致性标签保持 {SYNTHETIC_REGION}，"
            "不表示载体来自该地区"
        ),
        "future_assumption": (
            f"2027—{selected['through'][:4]} 年冻结 2026 年公开参数；非官方预测"
        ),
        "resident_assumption": terms.resident_override_basis,
    }


def default_description(cfg):
    return {
        "mode": "national_placeholder",
        "label": "全国占位参数",
        "worker_retirement_base_monthly": cfg["pension_base"],
        "resident_basic_monthly": cfg["resident_basic"],
        "note": "未提供 --region；沿用合成配置中的全国占位参数，不代表任何真实地区",
    }
