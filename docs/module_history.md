# Module history / 模块沿革

China PensionSIM was built in numbered development rounds. The public release renamed the round directories to descriptive names. Synthetic fixtures were kept byte-identical to the sealed research release, so they still mention the old names; `extensions/legacy_paths.py` maps them for the regression tests.

| Public path | Development directory | Role |
| --- | --- | --- |
| `pension_core/` | R48 release core | Monthly three-pillar engine |
| `extensions/mortality_wpp/` | continuation_r04 | WPP 2024 China mortality extract and valuation helpers |
| `extensions/contribution_frontier/` | continuation_r51 | Payment-capacity frontier and policy parameters |
| `extensions/monthly_bridge/` | continuation_r52 | Monthly bridge between frontier and engine |
| `extensions/survival_valuation/` | continuation_r53 | Survival-weighted cash-flow valuation |
| `extensions/fixtures_routes/` | continuation_r95 | Synthetic route and path anchors |
| `extensions/fixtures_timing/` | continuation_r96 | Synthetic payment-timing anchors |
| `extensions/fixtures_installments/` | continuation_r97 | Synthetic instalment anchors |
| `extensions/continuation_valuation_base/` | continuation_r98 | Base valuation for continued contributions |
| `extensions/continuation_valuation/` | continuation_r99 | Continuation-contribution valuation |
| `extensions/fixtures_portfolio/` | continuation_r100 | Synthetic policy portfolio cases |
| `extensions/budget_solver/` | continuation_r103 | Integer budget solver and replay |

Verification of the renaming: all unit and frozen regression tests pass; demo runs (national and Zhejiang), the 64-arm policy grid, the policy price table, the optimiser and the interruption experiments produce byte-identical outputs before and after the change.
