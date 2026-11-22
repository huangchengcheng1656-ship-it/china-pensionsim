"""Run the synthetic monthly three-pillar model using Python's standard library."""
import argparse
import csv
from dataclasses import replace
from functools import partial
from itertools import product
import json
from math import fsum, isfinite
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from pension_core.access import Access
from pension_core.history import History
from pension_core.ledger import Person, simulate
from pension_core.outcomes import REFERENCE, policy_case
from pension_core.portability import ResidentYear, WorkerMonth
from pension_core.rules import month
import regional

HERE = Path(__file__).resolve().parent
FACTOR_WORLDS = ("base_annual_tight","base_slow_liquid","history24_annual_tight","history24_slow_liquid")
WORLDS = tuple("_".join(x) for x in product(("base","history24"),("annual","slow"),("tight","liquid")))
SOURCES = {"legacy_once":0., "reserve_1500":1500., "cash_only":0.}
DEFAULT_ARM = (0., 0., "legacy_once", "native", "native")
BASE_GRID = tuple(product((150.,),(0.,.30),("legacy_once","reserve_1500"),("native","expand_25pp"),("native","protect")))


def load_inputs():
    data = json.loads((HERE/"data"/"synthetic"/"cohort.synthetic.json").read_text(encoding="utf-8"))
    if data["mode"]!="synthetic":
        raise ValueError("This release uses only its synthetic cohort.")
    return data["config"], data["carriers"]


def rights(raw):
    fields = dict(raw)
    fields["worker_opening"] = tuple(WorkerMonth(**r) for r in raw["worker_opening"])
    fields["resident_opening"] = tuple(ResidentYear(**(r|{"covered_months":frozenset(r["covered_months"])}))
                                       for r in raw["resident_opening"])
    fields["choice_by_month"] = {int(k):v for k,v in raw["choice_by_month"].items()}
    return History(**fields)


def payment_access(jobs, system, closed_months):
    access = []
    remaining = closed_months
    for job in jobs:
        if job=="out":
            access.append(Access("none",False))
        elif job=="standard":
            access.append(Access("worker"))
        else:
            access.append(Access(system, remaining==0))
            remaining = max(0,remaining-1)
    return tuple(access)


def paired(cfg, carriers, world, arm, system, closed_months, response=1., local_terms=None):
    history_key, path_key, liquidity = world.split("_")
    worker, match, funding, offer, vest = arm
    for c in carriers:
        initial = c["starts"][history_key]
        p = replace(Person(**initial["person"]), liquid=4800. if liquidity=="liquid" else 0.)
        h = rights(initial["history"])
        for draw, paths in c["paths"].items():
            jobs = paths[path_key]
            annuity, cash = [], []
            engine = partial(simulate,source_mode=funding,source_reserve=SOURCES[funding],
                             source_trace=cash,annuity_trace=annuity,local_terms=local_terms)
            result = policy_case(engine,cfg,p,h,jobs,worker,match,.25 if offer=="expand_25pp" else 0.,
                                 vest=="protect",access=payment_access(jobs,system,closed_months),response=response)
            start = month(cfg["start_year"],1)
            window = annuity[REFERENCE-start:REFERENCE-start+12]
            for scheme in ("enterprise","occupational"):
                result[scheme+"_cash12"] = fsum(r[scheme+"_cash"] for r in window)
                for payer in ("employee","employer"):
                    field = scheme+"_"+payer+"_contribution"
                    result["pv_"+field] = fsum(r[field+"_yuan"]*r["pv_factor"] for r in annuity)
            end = annuity[REFERENCE-start-1]
            for account in ("enterprise_vested","enterprise_contingent","occupational"):
                result[account+"_pre_reference"] = end[account+"_close"]
            result["enterprise_forfeitures_yuan"] = fsum(r["enterprise_forfeitures_yuan"] for r in annuity)
            result["ordinary_pre_reference"] = cash[REFERENCE-start-1]["ordinary_end"]
            yield {"world":world,"person_key":c["id"],"path_seed":int(draw),"worker_subsidy":worker,
                   "personal_match":match,"p3_source_policy":funding,"enterprise_offer_policy":offer,
                   "enterprise_vesting_policy":vest,"nonstandard_system":system,"closed_months":closed_months,
                   "opening_at_risk":c["opening_at_risk"]} | result


def positive(value):
    x=float(value)
    if not isfinite(x) or x<0:
        raise argparse.ArgumentTypeError("expected a finite nonnegative number")
    return x


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True,type=Path,help="new synthetic output directory")
    parser.add_argument("--region",help="apply a registered public regional scenario, currently 浙江省")
    parser.add_argument("--world",choices=WORLDS,default=WORLDS[0])
    grid_flags = parser.add_mutually_exclusive_group()
    grid_flags.add_argument("--budget-grid",action="store_true",help="recompute all 216 cells of the policy price table")
    grid_flags.add_argument("--grid",action="store_true",help="replay 64 fixed R48 arms and all 4,608 trajectories")
    parser.add_argument("--worker-subsidy",type=positive,default=0.,help="yuan per eligible paid month")
    parser.add_argument("--match",type=positive,default=0.,help="P3 public match fraction, e.g. 0.30")
    parser.add_argument("--funding",choices=SOURCES,default="legacy_once")
    parser.add_argument("--offer",choices=("native","expand_25pp"),default="native")
    parser.add_argument("--vesting",choices=("native","protect"),default="native")
    parser.add_argument("--nonstandard-system",choices=("worker","resident"),default="worker")
    parser.add_argument("--closed-months",type=int,default=0,help="close the first N nonstandard payment opportunities")
    parser.add_argument("--response",type=positive,default=1.,help="multiplier on explicit policy participation response (0 to 2)")
    args=parser.parse_args()
    if args.closed_months<0 or args.match>1 or args.response>2:
        parser.error("closed-months must be nonnegative and match at most 1 and response at most 2.")
    chosen=(args.worker_subsidy,args.match,args.funding,args.offer,args.vesting)
    if (args.grid or args.budget_grid) and (chosen!=DEFAULT_ARM or args.closed_months or args.nonstandard_system!="worker" or args.world!=WORLDS[0]):
        parser.error("--grid uses the fixed published worlds, rules, and payment opportunities")
    destination=args.out.resolve()
    if destination.exists():
        parser.error("Choose a new output directory")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix=".pension-run-",dir=destination.parent) as staging:
        args.out=Path(staging)/"results"
        execute(args,chosen)
        args.out.rename(destination)
    print(f"Saved synthetic results in {destination}")


def execute(args,chosen):
    args.out.mkdir()
    cfg,carriers=load_inputs()
    local_terms = (regional.load_terms(args.region, through=f"{cfg['last_year']}-12")
                   if args.region else None)
    parameter_basis = regional.describe(local_terms) if local_terms else regional.default_description(cfg)
    worlds,arms=(FACTOR_WORLDS,BASE_GRID) if args.grid else ((args.world,),(chosen,))
    if args.budget_grid:
        worlds=WORLDS
        arms=tuple(product((0.,150.,300.),(0.,.15,.30),SOURCES,("native",),("native",)))
    summaries=[]
    prices=[]
    with (args.out/"synthetic_paths.csv").open("w",encoding="utf-8",newline="") as f:
        writer=None
        for world,arm in product(worlds,arms):
            rows=list(paired(cfg,carriers,world,arm,args.nonstandard_system,args.closed_months,args.response,
                             local_terms=local_terms))
            if writer is None:
                writer=csv.DictWriter(f,fieldnames=rows[0],lineterminator="\n")
                writer.writeheader()
            writer.writerows(rows)
            if args.budget_grid:
                w,m,funding,_,_=arm
                risk=[r for r in rows if r["opening_at_risk"]]
                price={"world":world,"p3_source_policy":funding,"worker_subsidy":int(w),"personal_match":m,
                       "n":len(rows),"risk_n":len(risk)}
                for name in ("pv_direct","pv_worker_subsidy","pv_personal_match","pv_personal_deduction",
                             "pv_p1_benefits","pv_retirement_tax","pv_worker_receipts","pv_resident_member_receipts",
                             "pv_resident_public_credit","pv_limited_public_pressure"):
                    price[name]=fsum(r[name] for r in rows)
                price.update(mean_reference12_gap=mean(r["reference12_gap"] for r in rows),
                             risk_mean_reference12_gap=mean(r["reference12_gap"] for r in risk),
                             eligible_share=mean(r["eligible_at_decision"] for r in rows),
                             mean_predecision_shortfall=mean(r["predecision_shortfall"] for r in rows),
                             mean_worker_posting_months=mean(r["worker_posting_months"] for r in rows))
                prices.append(price)
            fields=("reference12_gap","eligible_at_decision","any_reference12_p1","predecision_shortfall",
                    "pv_direct","pv_limited_public_pressure","pv_enterprise_employee_contribution",
                    "pv_enterprise_employer_contribution","p1_cash12","p2_cash12","p3_cash12")
            summaries.append({"world":world,"arm":arm,"risk_units":len(rows),"means_per_path":{k:mean(r[k] for r in rows) for k in fields}})
    if prices:
        with (args.out/"policy_grid.synthetic.csv").open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=prices[0],lineterminator="\n")
            writer.writeheader()
            writer.writerows(prices)
    report={"mode":"synthetic","reference_window":"2030-03 to 2031-02","closed_months":args.closed_months,
            "nonstandard_system":args.nonstandard_system,"response":args.response,
            "parameter_basis":parameter_basis,"scenario_results":summaries}
    (args.out/"synthetic_summary.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(f"{len(summaries)} scenarios, {sum(s['risk_units'] for s in summaries)} synthetic trajectories")


if __name__=="__main__":
    main()

