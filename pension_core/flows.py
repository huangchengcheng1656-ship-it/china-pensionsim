from math import fsum, isclose
BALANCE = ('enterprise_vested', 'enterprise_contingent', 'occupational')

def near(got,want,label):
    if not isclose(got,want,rel_tol=1e-11,abs_tol=1e-7):
        raise ArithmeticError(f'{label}: {got} != {want}')


def limit_p3(surplus, regular_limit, ordinary, mode, reserve):
    if mode=='legacy_once':
        return max(0.,surplus+regular_limit)
    available=0. if mode=='cash_only' else min(regular_limit,max(0.,ordinary-reserve))
    return max(0.,surplus+available)


def funding(funds,limit,deposit,relief):
    """Date-fixed within-month counterfactual holding previous tax/draw state."""
    if min(limit,deposit,relief)<0. or deposit>max(0.,funds+limit)+1e-8:
        raise ValueError('P3 transfer cannot use cash or ordinary assets exceeding its shared limit')
    owed_before=max(0.,-funds)
    gap_reserved=min(limit,owed_before)
    actual_draw=min(limit,max(0.,deposit-funds-relief))
    current=min(deposit,max(0.,funds))
    gross_asset=deposit-current
    asset=min(gross_asset,max(0.,actual_draw-gap_reserved))
    contribution_relief=max(0.,deposit-current-asset)
    remaining=relief-contribution_relief
    if remaining < -1e-7:
        raise ArithmeticError('Tax-funded P3 source exceeds actual incremental relief')
    ordinary_save_pre=max(0.,funds)
    ordinary_save_after=max(0.,funds+relief-deposit)
    any_uncovered=max(0.,deposit-funds-relief-actual_draw)
    delta_ordinary=(ordinary_save_after-actual_draw)-(ordinary_save_pre-gap_reserved)
    return dict(p3_own=deposit,p3_own_from_current_cash=current,p3_own_from_ordinary_assets=asset,
           p3_own_from_tax_saving=contribution_relief,p3_gross_ordinary_source=gross_asset,
           tax_relief_remaining_or_ordinary_replenishment=max(0.,remaining),
           ordinary_draw_total=actual_draw,ordinary_draw_without_p3_same_month=gap_reserved,
           reduced_ordinary_saving_same_month=ordinary_save_pre-ordinary_save_after,
           ordinary_end_vs_no_p3_same_month=delta_ordinary,uncovered_model=any_uncovered)


def trace_row(t,job,ordinary0,p30,ordinary1,p31,p3_before_withdraw,p3_gross,deposit,match,p3_cash,
              work,ord_rate,p3_rate,gap,refund,retired_reimbursement,tax_settlement=0.):
    p3_earn=p30*p3_rate
    ordinary_earn=ordinary0*ord_rate
    near(p3_before_withdraw,p30+p3_earn,'observed P3 before any draw or new contribution')
    near(p31,p30+p3_earn+deposit+match-p3_gross,'protected P3 directly observed conservation')
    if work is None:
        before_tax=after_tax=needed=debt=p1=p2=posted=relief=0.
        before_p3=ordinary0+ordinary_earn+refund+retired_reimbursement+tax_settlement
        funds=0.
        effects=funding(0.,0.,0.,0.)
        near(ordinary1,before_p3,'redistribution after retirement without new household events')
    else:
        funds,limit,before_tax,after_tax,needed,debt,p1,p2,posted,before_p3,relief=work
        effects=funding(funds,limit,deposit,relief)
        # Adjudication follows work and the P3 deposit. Its overlap refund is a
        # later cash inflow, not a source available for the earlier P3 deposit.
        base=before_p3+max(0.,funds+relief-deposit)-effects['ordinary_draw_total']+refund
        near(base,ordinary1,'ordinary assets and single actual draw')
        near(gap,effects['uncovered_model'],'household cash gap in same-month partition')
    near(before_tax-after_tax,relief,'tax liability and realized relief')
    near(deposit,fsum(effects[k] for k in ('p3_own_from_current_cash','p3_own_from_ordinary_assets',
            'p3_own_from_tax_saving')),'observed P3 self-funding sources no excess')
    near(effects['ordinary_end_vs_no_p3_same_month']+deposit+match,relief+match,
         'own transfer makes no outside assets at fixed current state')
    near(p3_gross-p3_cash,p3_gross*.03,'retirement withholding separate from deposit deduction')
    return dict(month=t,employment=job,active=int(work is not None),ordinary_open=ordinary0,ordinary_end=ordinary1,
        ordinary_before_p3=before_p3,protected_p3_open=p30,protected_p3_end=p31,
        protected_p3_before_withdrawal=p3_before_withdraw,ordinary_growth=ordinary_earn,p3_growth=p3_earn,
        ordinary_overlap_refund=refund,ordinary_deferred_reimbursement=retired_reimbursement,
        ordinary_tax_settlement=tax_settlement,
        combined_ordinary_p3_end=ordinary1+p31,necessary_due=needed,debtservice=debt,
        income_tax_before_p3=before_tax,income_tax_after_p3=after_tax,tax_deduction=relief,
        p1_member_paid=p1,p2_member_paid=p2,worker_posted=int(posted),p3_cash=p3_cash,p3_gross_withdrawal=p3_gross,
        p3_tax_withholding=p3_gross-p3_cash,funds_before_p3=funds,p3_subsidy=match,
        household_preretirement_shortfall=gap,p3_own_in_out_employment=deposit if job=='out' else 0.,
        p3_deposit_in_out_month=int(job=='out' and deposit>0.),**effects)


def annuity_row(month,pv,job,government,opening,closing,ret,ee,er,oe,ore,vesting,forfeit,offered,new,gross,net):
    gains=tuple(x*ret for x in opening)
    v0,c0,o0=opening
    v1,c1,o1=closing
    vg,cg,og=gains
    amount_to_contingent=c1-c0-cg+vesting+forfeit
    near(ee+er-amount_to_contingent,v1-v0-vg-vesting+gross[0],'acquired enterprise contract balance')
    near(o0+og+oe+ore-gross[1],o1,'separate occupational contract balance')
    near(v0+c0+vg+cg+ee+er-gross[0]-forfeit,v1+c1,'employer conditional, released, and reverted')
    if min(vesting,forfeit,ee,er,oe,ore)<-1e-7 or (offered and (government or job!='standard')):
        raise ArithmeticError('Enterprise eligibility, own/employer amounts or custody invalid')
    if (ee or er) and (oe or ore):
        raise ArithmeticError('Two distinct employee plans counted for same modeled employment')
    base=dict(month=month,pv_factor=pv,employment=job,government_job=int(government),
         enterprise_employee_contribution_yuan=ee,enterprise_employer_contribution_yuan=er,
         occupational_employee_contribution_yuan=oe,occupational_employer_contribution_yuan=ore,
         enterprise_external_vested_yuan=vesting,enterprise_forfeitures_yuan=forfeit,
         enterprise_offer=int(offered),enterprise_new_offer_assignment=int(new),enterprise_contribution=int(ee+er>0),
         enterprise_cash=net[0],occupational_cash=net[1],enterprise_gross_cash=gross[0],
         occupational_gross_cash=gross[1],p2_tax=sum(gross)-sum(net))
    for name,b,e,z in zip(BALANCE,opening,gains,closing,strict=True):
        base.update({name+'_open':b,name+'_earn':e,name+'_close':z})
    return base


source_limit = limit_p3
source_row = trace_row
