"""Choose the same policy before the scenario is known, using the synthetic cohort price table."""
import argparse
import csv
import json
from math import isfinite
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "data" / "synthetic" / "policy_grid.synthetic.csv"


def matrices(rows):
    worlds = {}
    for r in rows:
        w=(r["world"],r["p3_source_policy"])
        a=(int(r["worker_subsidy"]),float(r["personal_match"]))
        if int(r["n"])!=72 or a in worlds.setdefault(w,{}):
            raise ValueError("Changed carrier count or duplicate arm")
        worlds[w][a]=r
    arms=sorted(next(iter(worlds.values())))
    if len(worlds)!=24 or len(arms)!=9 or any(sorted(g)!=arms for g in worlds.values()):
        raise ValueError("The full 24 by 9 published menu is required")
    def panel(field,scale=1,sign=1):
        return [[sign*(float(g[a][field])-float(g[0,0][field]))/scale for a in arms]
                for _,g in sorted(worlds.items())]
    return (arms, panel("mean_reference12_gap",sign=-1),panel("pv_direct",72),
            panel("pv_limited_public_pressure",72),panel("mean_predecision_shortfall"))


def select(budget, mixed=False, pressure_limit=None, household_limit=None, table=TABLE, extra_tables=()):
    if not isfinite(budget) or budget<0 or any(x is not None and not isfinite(x) for x in (pressure_limit,household_limit)):
        raise ValueError("Supply finite limits and a nonnegative direct budget")
    with Path(table).open(encoding="utf-8-sig",newline="") as fh:
        arms,gain,cost,pressure,loss=matrices(csv.DictReader(fh))
    for additional in extra_tables:
        with Path(additional).open(encoding="utf-8-sig",newline="") as fh:
            a,g,c,p,h=matrices(csv.DictReader(fh))
        if a!=arms:
            raise ValueError("Sensitivity has different policies")
        gain.extend(g);cost.extend(c);pressure.extend(p);loss.extend(h)
    constraints=[(cost,budget)]
    if pressure_limit is not None:
        constraints.append((pressure,pressure_limit))
    if household_limit is not None:
        constraints.append((loss,household_limit))
    if mixed:
        from scipy.optimize import linprog
        lhs,rhs=[],[]
        for table,limit in constraints:
            lhs.extend(r+[0.] for r in table)
            rhs.extend([limit]*len(table))
        lhs.extend([-x for x in r]+[1.] for r in gain)
        rhs.extend([0.]*len(gain))
        lp=linprog([0.]*len(arms)+[-1.],A_ub=lhs,b_ub=rhs,A_eq=[[1.]*len(arms)+[0.]],b_eq=[1.],
                   bounds=[(0.,1.)]*len(arms)+[(None,None)],method="highs")
        if not lp.success:
            raise ValueError(lp.message)
        shares=list(lp.x[:-1])
    else:
        eligible=[i for i in range(len(arms)) if all(max(r[i] for r in table)<=cap+1e-9 for table,cap in constraints)]
        if not eligible:
            raise ValueError("No common feasible policy")
        i=max(eligible,key=lambda i:(min(r[i] for r in gain),-max(r[i] for r in cost),-i))
        shares=[float(j==i) for j in range(len(arms))]
    def cornerrange(panel):
        vals=[sum(x*y for x,y in zip(r,shares,strict=True)) for r in panel]
        return [min(vals),max(vals)]
    if abs(sum(shares)-1.)>1e-7 or any(cornerrange(t)[1]>lim+1e-6 for t,lim in constraints):
        raise ArithmeticError("A scenario exceeds its limit")
    return {"mode":"synthetic", "worlds":len(gain), "budget_direct_pv_yuan_per_path":budget,
            "shares_always_fixed_before_world":[{"worker":a[0],"match":a[1],"share":x}
                                                 for a,x in zip(arms,shares,strict=True) if x>1e-8],
            "mean_gap_reduction_yuan_month_range":cornerrange(gain),"mean_direct_pv_range":cornerrange(cost),
            "mean_incremental_limited_public_pressure_pv_range":cornerrange(pressure),
            "mean_incremental_predecision_essential_shortfall_range":cornerrange(loss)}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget",type=float,required=True,help="direct subsidy PV per model path")
    parser.add_argument("--mixed",action="store_true",help="allow fixed ex ante eligibility proportions (requires SciPy)")
    parser.add_argument("--max-pressure",type=float,help="max increase of partial public ledger PV per path")
    parser.add_argument("--max-household-loss",type=float,help="max increase of mean cumulative predecision shortfall")
    parser.add_argument("--table",type=Path,default=TABLE,help="published or newly regenerated synthetic price table")
    parser.add_argument("--extra-table",type=Path,action="append",default=[],help="require the same policy to satisfy another complete behavioral price table")
    args=parser.parse_args()
    print(json.dumps(select(args.budget,args.mixed,args.max_pressure,args.max_household_loss,args.table,args.extra_table),ensure_ascii=False,indent=2))

