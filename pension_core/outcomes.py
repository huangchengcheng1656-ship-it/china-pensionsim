from math import fsum
from .access import Access
from .rules import month
from .ledger import Scenario
from .flows import near
REFERENCE = 24362

def policy_case(engine,cfg,profile,history,job,worker_subsidy,match,expand,protect,access=None,response=1.):
    form=access if access is not None else tuple(Access('none',False) if j=='out' else Access('worker') for j in job)
    log,trace,flows,transfer=[],[],[],[]
    terminal={}
    switch=Scenario('paired_upfront_and_match',subsidy=worker_subsidy,match=match,subsidy_delay_months=0,
                            annuity_expansion=expand,protect_annuity_vesting=protect,response=response)
    result=engine(profile,switch,cfg,job_path=job,access_path=form,access_log=log,mobility_trace=trace,
             transfer_events=transfer,monthly_trace=flows,verified_history=history,terminal=terminal)
    event,=transfer
    at=history.decision_month
    pre=[r for r in log if r['month']<at]
    posted=sum(r['worker_posted'] for r in pre)
    credited_r=sum(r['resident_current_credit'] for r in pre)
    if (event.worker_credit_before!=profile.worker_paid+profile.worker_deemed+posted
            or event.resident_credit_before!=profile.resident_paid+credited_r or event.overlapping_months):
        raise ArithmeticError('Pre-decision rights accounts do not reconcile')
    start=month(cfg['start_year'],1)
    if len(trace)!=len(job) or any(z['month']!=start+i for i,z in enumerate(trace)):
        raise ArithmeticError('Assigned work does not cover each simulated month')
    if [z['employment'] for z in trace]!=list(job):
        raise ArithmeticError('Actual work became unpaired')
    for d,z in zip(flows,trace,strict=True):
        # No delayed spouse reimbursement, and no separate payroll levy or policy fee is invented.
        support=d['worker_subsidy']
        expected=min(worker_subsidy,(d['worker_household_cash']+support)*2/3)
        if support and (z['employment']!='nonstandard' or d['worker_receipts']<=0):
            raise ArithmeticError('Worker grant paid outside actual individual payment')
        if support:
            near(support,expected,'actual per-month worker support')
        near(d['personal_public_reward'],match*z['p3_own'],'match needs actual own P3 cash')
    lo=REFERENCE-start
    window=trace[lo:lo+12]
    if [r['month'] for r in window]!=list(range(REFERENCE,REFERENCE+12)):
        raise ArithmeticError('Shared reference window incomplete')
    gap=lambda z:max(0.,cfg['benchmark_monthly']-z['p1']-z['p2']-z['p3'])
    pv=lambda field:fsum(z[field]*z['rate_discount'] for z in flows)
    w=pv('worker_subsidy')
    p=pv('personal_public_reward')
    d=pv('tax_deduction')
    wc=pv('worker_receipts')
    rc=pv('resident_own')
    rg=pv('resident_public')
    ben=pv('p1_benefit')
    tax=pv('retirement_tax')
    near(w+p,result['direct_subsidy'],'realized direct spending')
    near(d,result['tax_cost'],'P3 deduction cost')
    near(ben,result['p1_benefit_pv'],'PV first pillar bank cash')
    if result['unsettled_subsidy']:
        raise ArithmeticError('Upfront grants have no background reimbursement tail')
    # Gross P1 receipts already contain support on behalf of the member; include the
    # grant once in public outflows for a consolidated program/scheme comparison.
    pressure=w+p+d+ben-tax-wc-rc+rg
    return dict(worker_credit=event.worker_credit_before,resident_credit=event.resident_credit_before,
                worker_posting_months=posted,eligible_at_decision=int(result['eligible_at_legal']),
                route_actual=result['route'],first_payment_month=terminal['first_payment_month'],
                first_reference_p1=int(window[0]['p1']>0),any_reference12_p1=int(any(z['p1']>0 for z in window)),
                reference12_gap=fsum(map(gap,window))/12,reference_gap=gap(window[0]),
                p1_cash12=fsum(z['p1'] for z in window),p2_cash12=fsum(z['p2'] for z in window),
                p3_cash12=fsum(z['p3'] for z in window),p3_own=fsum(z['p3_own'] for z in trace),
                preretirement_shortfall=result['consumption_shortfall'],
                predecision_shortfall=fsum(z['household_preretirement_shortfall'] for z in flows if z['month']<at),
                prior12_liquidity=window[0]['ordinary_end'],
                pv_direct=w+p,pv_worker_subsidy=w,pv_personal_match=p,pv_personal_deduction=d,
                pv_worker_receipts=wc,pv_resident_member_receipts=rc,pv_resident_public_credit=rg,
                pv_p1_benefits=ben,pv_retirement_tax=tax,pv_limited_public_pressure=pressure)
