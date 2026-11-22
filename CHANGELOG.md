# Changelog

## 1.0.0 — 2026-11-22

First public release.

- Monthly three-pillar engine: employee and resident basic pensions, enterprise and occupational annuities, individual pension accounts, taxes and household cash balances.
- Statutory rules for the 2025–2039 retirement-age reform and the 2030–2039 rise of the minimum contribution period from 180 to 240 months, with employee–resident transfers.
- Layered regional parameter interface with Zhejiang (2025–2026) employee parameters and Hangzhou resident basic pension.
- Survival-weighted valuation (WPP 2024 China mortality), continuation-contribution valuation and an integer budget solver.
- Policy register with legal sources; data validation for five standard group-level tables.
- Policy register implementation column updated to public module paths (`src/rules.py` → `pension_core/rules.py`, `src/sim.py` → `pension_core/ledger.py`); modules not in this release are marked.
- Development directories renamed to descriptive names (`docs/module_history.md`); synthetic fixtures kept byte-identical to the sealed research release, and all outputs verified identical before and after the change.
