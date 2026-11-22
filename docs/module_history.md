# Module history / 模块沿革

China PensionSIM was built in numbered development rounds. The public release renamed the round directories to descriptive names. Fixtures that were not regenerated still mention the old names; `extensions/legacy_paths.py` maps them for the regression tests.

| Public path | Development directory | Role | 1.0.0 status |
| --- | --- | --- | --- |
| `pension_core/` | R48 release core | Monthly three-pillar engine | Corrected month order and wage tax |
| `extensions/mortality_wpp/` | continuation_r04 | WPP 2024 China mortality extract | Unchanged |
| `extensions/contribution_frontier/` | continuation_r51 | Payment-capacity frontier and policy parameters | Unchanged |
| `extensions/monthly_bridge/` | continuation_r52 | Bridge between frontier and engine | Unchanged |
| `extensions/survival_valuation/` | continuation_r53 | Survival-weighted valuation | Baseline regenerated; adjudication arms restated for end-of-month adjudication |
| `extensions/fixtures_portfolio/` | continuation_r100 | Example policy portfolio (solver input) | Unchanged |
| `extensions/budget_solver/` | continuation_r103 | Integer budget solver and replay | Unchanged |
| — | continuation_r95–r99 | Continuation-contribution valuation and its anchors | Not in 1.0.0 |
