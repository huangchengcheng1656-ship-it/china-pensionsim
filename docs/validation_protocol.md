# Validation protocol / 验证规程

China PensionSIM reports three kinds of evidence.

1. **Rule checks.** The policy register (`data/public/policy_register.csv`) records rule sources and implementation status. Unit tests cover selected implemented rule boundaries and accounting identities.
2. **Frozen regression.** Sealed synthetic results are replayed at relative tolerance 1e-12 (`tests/test_frozen_regression.py`).
3. **Empirical validation with survey aggregates.** Run by approved users in their own secure environment; only reviewed group-level tables enter the repository through `data/requirements/` templates.

## Empirical validation design used by the authors

- **CFPS employment and scheme transitions.** States are employment (standard, nonstandard, out) × reported scheme. Transition matrices are estimated on the 2018→2020 waves, annualised as a row-stochastic matrix P whose square best matches the observed two-wave matrix, frozen with source hashes, and only then compared with the 2020→2022 waves (observed minus predicted, cell by cell). Cells with fewer than 30 respondents in the origin row, or 1–9 respondents in a destination cell, are suppressed.
- **CHARLS benefit receipt.** Weighted monthly benefits of confirmed recipients by scheme and age band from CHARLS Wave 6 (2021–2023 fieldwork batches), compared with model benefit levels as a plausibility check, not as calibration.
- **Administrative macro references.** National fund expenditure divided by recipients from the MOHRSS statistical bulletins, used only as an external order-of-magnitude reference.

Results of this validation will be added to `docs/validation_results.md` after the authors complete the disclosure review of the survey aggregates.
