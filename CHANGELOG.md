# Changelog

## 1.0.0 — 2026-11-22

First public release.

### Model
- Monthly three-pillar engine: employee and resident basic pensions, enterprise and occupational annuities, individual pension accounts, wage tax and household cash.
- Statutory rules for the 2025–2039 retirement-age reform and the 2030–2039 rise of the minimum contribution period from 180 to 240 months, with employee–resident transfers.
- Layered regional parameter interface with Zhejiang (2025–2026) employee parameters and Hangzhou resident basic pension.
- Survival-weighted valuation (WPP 2024 China mortality) and an integer budget solver.

### Corrections made after the pre-release review
- Fiscal cost of the individual pension deduction now counts the tax reduction in every later month and at the annual settlement; household gain and fiscal cost reconcile (`tests/test_boundaries.py`).
- Order within a month: wages and contributions post before eligibility and claim. A worker who reaches the minimum with the retirement month's contribution retires that month and is paid from the next month. Verified-history adjudication happens at the end of the decision month.
- Wage tax: cumulative withholding with 5,000 yuan per month of employment; formal employees' basic-pension and annuity (up to 4%) contributions are deducted; no refund within the year; annual settlement paid the following June.
- Regional CSV `effective_from` now splits the year instead of being ignored; every entry point applies the same input validation; CFPS rows require `unweighted_n > 0`.
- Summary output separates `trajectory_count` (72) from `risk_count` (48); the interruption output is labelled as a fixed fixture not affected by `--region`.
- Regenerated: the three policy price tables (`data/synthetic/policy_grid*.csv`) and the survival-valuation baseline. The 150-yuan arm's largest per-path direct cost moved from 791.78 to 826.47 because the retirement-month contribution now posts.
- Continuation-contribution valuation (research version) removed from this release until its fixtures are re-sealed under the corrected month order.
- Policy register implementation column points to public module paths; development directories renamed (`docs/module_history.md`).
