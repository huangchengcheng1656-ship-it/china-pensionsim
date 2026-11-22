# Data statement / 数据声明

## What is included

| Folder | Type | Licence |
| --- | --- | --- |
| `data/public/` | Public policy register and regional parameters, each row with its official source | CC BY 4.0 (sources remain public documents) |
| `data/synthetic/`, `extensions/**/*.synthetic.json` | Synthetic individuals and synthetic fixtures generated for testing | CC BY 4.0 |
| `data/requirements/` | Empty templates (headers only) | CC BY 4.0 |
| `extensions/mortality_wpp/valuation/mortality_public/` | Extract of UN World Population Prospects 2024 (China) | CC BY 3.0 IGO; see `source_manifest.json` and NOTICE |

## What is not included

No individual-level records from any survey or administrative source are distributed. In particular, the repository contains no data from the China Household Finance Survey (CHFS), the China Family Panel Studies (CFPS) or the China Health and Retirement Longitudinal Study (CHARLS).

Researchers who want to calibrate or validate the model with these surveys must obtain access from the data providers:

- CHFS: Survey and Research Center for China Household Finance, Southwestern University of Finance and Economics (https://chfs.swufe.edu.cn)
- CFPS: Institute of Social Science Survey, Peking University (https://www.isss.pku.edu.cn/cfps/)
- CHARLS: National School of Development, Peking University (https://charls.pku.edu.cn)

Group-level tables prepared under those providers' rules can be supplied through the templates in `data/requirements/` and checked with `python -B data_validation.py`. Rows marked `real_aggregate` must carry `review_status=approved` and a review reference; the validator rejects unreviewed real data but does not replace a disclosure review.

## 中文说明

本仓库只包含公开政策参数、合成数据、空白模板和联合国人口展望死亡率摘录，不分发任何调查或行政个体记录，不含 CHFS、CFPS、CHARLS 数据。需要用这些调查校准或验证模型的研究者，请向数据提供方申请使用权限，并按 `data/requirements/` 模板准备经披露审查的组级汇总表。
