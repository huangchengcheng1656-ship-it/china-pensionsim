# Model overview / 模型概述

This document states what China PensionSIM 1.0.0 computes, in what order, and under which assumptions. Rule sources are in `data/public/policy_register.csv`; the implementation status of each rule is recorded there.

## 1. State variables (per person)

| Group | Variables |
| --- | --- |
| Demography | birth month, statutory category (`male60`, `female55`, `female50`) |
| Labour | employment state (`standard`, `nonstandard`, `out`), monthly wage |
| Employee scheme | paid months, deemed months, average contribution index, individual account balance |
| Resident scheme | credited months, account balance |
| Second pillar | enterprise annuity (vested and pending), occupational annuity |
| Third pillar | individual pension account; year-to-date contributions |
| Household | monthly cash, liquid assets, debt service |
| Tax | year-to-date wage income, months of employment, special deductions, individual pension deductions, tax withheld (with and without the individual pension deduction), scheduled annual settlements |

## 2. Order of events within a month

1. Account balances earn the monthly return; a scheduled annual tax settlement (refund or top-up) is paid.
2. Annuity vesting events and job exits are processed.
3. Benefits are paid if the person retired in an earlier month (first payment = month after retirement).
4. For a person not yet retired: labour state, wage, contribution eligibility, wage-tax withholding, basic-pension and resident contributions, annuity contributions, individual pension contribution and its tax effect, household cash.
5. Eligibility and claim: at and after the statutory retirement month the model compares credited months, **including this month's contribution**, with the minimum period for the year (`minimum_months`). A qualifying worker retires in this month and is paid from the next month. With a verified history, adjudication happens at the end of the decision month, so credits posted in that month count; later credits are rejected.
6. In December the annual wage tax is computed and the difference from tax withheld is scheduled for June of the next year.

## 3. Eligibility and transfers

- Minimum period: 180 months to 2029; 186 in 2030, +6 a year, 240 from 2039, set by the year of the statutory retirement month.
- Shortfall at retirement: contributions continue for up to `Scenario.extension_months` months after the statutory month (default 24, a scenario assumption; national implementing rules for the post-2030 schedule are not yet published). If the minimum is still not met, the record moves to the resident scheme, where resident rules apply from age 60 with 180 credited months.
- Lump-sum buy-back is not modelled in 1.0.0.

## 4. Benefits

- Employee basic pension: pooled part = benefit base × (1 + average index) / 2 × credited years × 1%; account part = balance / payout months for the claim age (linear interpolation between whole ages by default).
- Resident pension: local basic pension + account balance / 139.
- Annuity and individual pension withdrawals over fixed periods (139 and 120 months by default); annuity withdrawals taxed with the monthly table, individual pension withdrawals at 3%.

## 5. Wage tax (simplified scenario)

- Cumulative withholding with a basic deduction of 5,000 yuan per month of employment in the year (SAT Announcement 2018 No. 61). A negative cumulative balance is not refunded within the year.
- Special deductions: for formal employees, the 8% basic-pension contribution and the employee annuity contribution up to 4% of the contribution base (MOF–SAT [2013] No. 103). Health insurance, housing fund and special additional deductions are not modelled.
- Annual settlement: annual tax with the 60,000-yuan standard deduction; the refund or top-up is paid in June of the next year. Small-amount exemptions from the annual settlement are not modelled.
- Wage income of nonstandard workers is taxed with the same wage schedule and receives no special deduction; the model does not assign business or service income categories.
- Fiscal cost of the individual pension deduction = tax collected without the deduction minus tax collected with it, month by month and at settlement, so the household gain and the fiscal cost reconcile.

## 6. Paths, valuation and fiscal accounting

- Labour states follow an annual transition matrix or a supplied path (for example a CFPS-calibrated path); scenarios share random draws.
- Present values use the scenario discount rate (2.5% a year by default) from January 2026. The survival-valuation module applies UN WPP 2024 mortality for China (medium variant, ages 40–99).
- `taxpayer_budget` = direct subsidies + fiscal cost of the individual pension deduction. `pv_limited_public_pressure` adds employee benefits and resident public credits and subtracts contributions and retirement tax; it is a partial public ledger, not a full fund projection.

## 7. Analysis modules and their fixed assumptions

- `extensions/survival_valuation/`: six declared adjudication arms around the 186-month threshold in 2030; adjudication at the end of the decision month.
- `extensions/budget_solver/`: integer allocation of a fixed budget across household groups; the example portfolio in `extensions/fixtures_portfolio/` was produced by the research version and is used as solver input only.
- Valuation of continued personal contributions (research version) is not part of 1.0.0; it will return once its fixtures are re-sealed under the month order above.
