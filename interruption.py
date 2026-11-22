"""Recompute the four points in the paper's career-interruption figure without historical project folders."""
from collections import defaultdict
import json
from math import fsum
from statistics import mean

from model import HERE,Person,rights
from pension_core.access import Access
from pension_core.ledger import Scenario,simulate
from pension_core.rules import month


def run():
    fixtures=json.loads((HERE/"data"/"synthetic"/"interruption.synthetic.json").read_text(encoding="utf-8"))
    assert fixtures["mode"]=="synthetic"
    cfg=fixtures["config"]
    start=month(cfg["start_year"],1)
    data=defaultdict(list)
    for c in fixtures["carriers"]:
        for setting,initial in c["starts"].items():
            p,h=Person(**initial["person"]),rights(initial["history"])
            gaps=[]
            for s in c["scenarios"]:
                trace=[]
                simulate(p,Scenario("paired_interruption",match=s["match"]),cfg,job_path=s["jobs"],
                         access_path=[Access(**a) for a in s["access"]],verified_history=h,
                         annuity_exits={int(k):v for k,v in s["exits"].items()},mobility_trace=trace)
                i=c["decision"]+1-start
                interval=trace[i:i+12]
                if len(interval)!=12:raise ValueError("Incomplete 12-month pension window")
                gaps.append(fsum(max(0.,cfg["benchmark_monthly"]-r["p1"]-r["p2"]-r["p3"]) for r in interval)/12)
            before,interrupted,repaired=gaps
            data[setting].append((interrupted-before,interrupted-repaired,repaired-before))
    return {k:dict(zip(("break_gap","offset_gap","residual_gap"),map(mean,zip(*records,strict=True)))) for k,records in data.items()}
if __name__=="__main__":
    print(json.dumps(run(),ensure_ascii=False,indent=2))

