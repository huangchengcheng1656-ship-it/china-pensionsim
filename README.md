# China PensionSIM 1.0

**An open, rule-based dynamic microsimulation model of China's multi-pillar pension system.**

[中文说明](README.zh.md)

China PensionSIM follows individuals month by month through China's three pension pillars: the employee and resident basic pension schemes, enterprise and occupational annuities, and the individual pension account. It encodes the statutory rules that decide who can draw a monthly pension, when, and how much, including the 2025–2039 retirement-age reform and the rise of the minimum contribution period from 15 to 20 years between 2030 and 2039. It also covers transfers between the employee and resident schemes, regional contribution floors, ceilings and benefit bases, personal income tax on pension flows, and household cash constraints.

Every rule is registered with its legal source in `data/public/policy_register.csv`, so users can trace each modelling choice back to the document that sets it.

Version 1.0 is the first public release.

## What you can do with it

- Compute monthly contribution histories, eligibility, first-claim dates and benefits under current and reformed rules.
- Compare scenarios: delayed retirement, the 15-to-20-year minimum contribution rule, interrupted careers, moves between the employee and resident schemes, contribution subsidies and matching rules.
- Value pension streams with survival weights (UN World Population Prospects 2024 mortality for China).
- Price policy options and choose subsidy allocations under a fixed budget with an integer budget solver.
- Plug in regional parameters through a layered CSV interface (Zhejiang province and Hangzhou city parameters are included).

## Quick start

Requires Python 3.11 or later. The core model, data checks and tests use only the standard library.

```bash
git clone <repository-url> china-pensionsim
cd china-pensionsim
python -B run.py --out demo_output                  # national placeholder parameters
python -B run.py --region 浙江省 --out demo_zhejiang  # Zhejiang 2026 public parameters
python -B -m unittest discover -s tests -v
```

`run.py` validates the input tables and writes:

- `synthetic_paths.csv`: 72 monthly paths for 18 synthetic individuals;
- `synthetic_summary.json`: scenario means and the parameter basis used;
- `interruption.synthetic.json`: four fixed career-interruption experiments;
- `data_validation.json`: the input validation receipt.

The output directory must not already exist, so earlier results are never overwritten.

## More commands

```bash
python -B model.py --out demo_base
python -B model.py --nonstandard-system resident --closed-months 6 --out demo_resident_break
python -B model.py --grid --out demo_factorial         # 64 policy arms, 4,608 trajectories
python -B model.py --budget-grid --out demo_pricing    # policy price table
python -B interruption.py
python -B optimize.py --budget 311.4254
python -B -m unittest extensions.survival_valuation.valuation.test_paths extensions.continuation_valuation.valuation.test_assess extensions.budget_solver.optimization.test_solver -v
```

Mixed-allocation solving (`optimize.py --mixed`) additionally needs NumPy and SciPy. See `python model.py --help` and `python optimize.py --help`.

## Repository layout

| Path | Contents |
| --- | --- |
| `pension_core/` | Retirement month, eligibility thresholds, benefit formulas, credited months, employee–resident transfers, annuities, monthly three-pillar cash flows and taxes |
| `model.py`, `run.py`, `interruption.py` | Scenario runner, one-command demo, career-interruption experiments |
| `regional.py`, `regional_profile.py`, `local_terms.py` | Layered regional parameter interface |
| `optimize.py` | Fixed-budget policy choice on the synthetic price table |
| `data_validation.py` | Field, range, date, source and review checks for the five standard data tables |
| `extensions/survival_valuation/` | Survival-weighted valuation of pension cash flows |
| `extensions/continuation_valuation/` | Cash feasibility and value of continued personal contributions |
| `extensions/budget_solver/` | Integer budget solver with exhaustive verification |
| `extensions/mortality_wpp/` | WPP 2024 China mortality extract with source manifest |
| `extensions/fixtures_*`, `extensions/*_base/`, `extensions/monthly_bridge/`, `extensions/contribution_frontier/` | Synthetic anchors and supporting modules used by the valuation and solver modules |
| `data/public/` | Public policy register and regional parameters with sources |
| `data/requirements/` | Empty templates for approved researchers to supply group-level validation data |
| `data/synthetic/` | Synthetic examples for testing the interfaces |
| `tests/` | Unit tests and frozen regression tests (relative tolerance 1e-12) |
| `docs/` | Model overview, validation protocol, module history |

## Data

No survey microdata are included. The model runs on synthetic individuals and public policy parameters. Researchers with approved access to CHFS, CFPS or CHARLS can prepare group-level tables using the templates in `data/requirements/`; see [DATA_STATEMENT.md](DATA_STATEMENT.md) and `data/README.md`.

Synthetic results illustrate how the rules work. They are not estimates for any real population.

## How to cite

If you use China PensionSIM, please cite the software (see [CITATION.cff](CITATION.cff)):

> Wang, P., & Huang, C. (2026). *China PensionSIM: An open dynamic microsimulation model of China's multi-pillar pension system* (Version 1.0.0) [Computer software].

A DOI will be added after the first archived release.

## License

- Code: Apache License 2.0 ([LICENSE](LICENSE)).
- Policy parameters, synthetic data and documentation: Creative Commons Attribution 4.0 International ([LICENSE-DATA](LICENSE-DATA)).

Copyright 2026 Ping Wang and Chengcheng Huang. See [NOTICE](NOTICE).

## Authors

- Ping Wang, Taizhou Vocational and Technical College, China
- Chengcheng Huang (corresponding), Weifang Ocean University of Science and Technology, China — huangcc_1986@126.com

AI coding assistants were used in development; see [AI_USE.md](AI_USE.md).
