# China PensionSIM 1.0：中国多层次养老金动态微观模拟模型

[English](README.md)

China PensionSIM 是用于中国多支柱养老金政策情景比较的按月动态微观模拟软件，按月追踪个人在三支柱体系中的缴费、权益与待遇：职工与城乡居民基本养老保险、企业年金与职业年金、个人养老金。模型写入了决定"谁能按月领取、何时领取、领多少"的法定规则，包括 2025—2039 年渐进式延迟法定退休年龄，以及 2030—2039 年最低缴费年限由 15 年逐步提高到 20 年；同时处理职工与居民制度之间的衔接转移、地区缴费基数上下限与计发基数、养老金相关个人所得税和家庭现金约束。

政策登记表（`data/public/policy_register.csv`）逐条列明规则的政策依据、实现模块，以及已实现、简化处理、研究假设或待建的状态。

1.0 是首个公开版本，以合成个体和公开政策参数运行，可用于规则核对、参数敏感性分析和条件性政策比较；总体估计和政策效应研究需另行接入获准数据并完成 `docs/validation_protocol.md` 所述的外部验证。月内事件次序和全部假设见 `docs/model_overview.md`。

## 能做什么

- 计算现行规则与改革规则下的逐月缴费历史、领取资格、首次领取月份和待遇。
- 比较情景：延迟退休、最低缴费年限 15→20 年、职业中断、职居转换、续缴资助与配套补贴。
- 用联合国《世界人口展望 2024》中国死亡率做生存加权的养老金现值估计。
- 在合成队列上为政策方案定价，并在固定预算下用整数求解器选择资助分配。
- 追踪家庭现金、工资个税累计预扣与年度汇算，以及个人养老金扣除的财政成本（简化税收情景，见 `docs/model_overview.md`）。
- 通过分层 CSV 接口接入地区参数（已收录浙江省职工与杭州市区居民公开参数）。

## 快速上手

需要 Python 3.11 及以上。核心模型、数据校验和测试只用标准库。

```bash
git clone https://github.com/huangchengcheng1656-ship-it/china-pensionsim.git
cd china-pensionsim
python -B run.py --out demo_output                  # 全国占位参数
python -B run.py --region 浙江省 --out demo_zhejiang  # 浙江 2026 年公开参数
python -B -m unittest discover -s tests -v
```

`run.py` 先校验输入表，再生成：

- `synthetic_paths.csv`：每条轨迹一行的汇总表（18 名合成个体共 72 条轨迹），不是逐月账本；逐月数据可用引擎的 `monthly_trace` 参数导出；
- `synthetic_summary.json`：各情景的 `trajectory_count`（72）、`risk_count`（期初在风险中的 48 条）、全部与风险组均值，及所用参数口径；
- `interruption.synthetic.json`：四组固定职业中断实验（回归样例，使用自带全国占位参数，不随 `--region` 改变）；
- `data_validation.json`：输入校验回执。

输出目录必须不存在，避免覆盖已有结果。

未提供 `--region` 时使用 7,500 元/月的全国占位计发基数。`--region 浙江省` 采用 2026 年浙江职工缴费基数下限 5,122 元、上限 25,611 元、计发基数 8,537 元/月，居民基础养老金采用杭州市区 2026-04-13 公开观察值 390 元/月。2027 年以后沿用 2026 年参数是显式情景设定，不是官方预测。

## 更多命令

```bash
python -B model.py --out demo_base
python -B model.py --nonstandard-system resident --closed-months 6 --out demo_resident_break
python -B model.py --grid --out demo_factorial         # 64 个政策组合、4,608 条轨迹
python -B model.py --budget-grid --out demo_pricing    # 政策价格表
python -B interruption.py
python -B optimize.py --budget 311.4254
python -B -m unittest extensions.survival_valuation.valuation.test_paths extensions.budget_solver.optimization.test_solver -v
```

混合投放求解（`optimize.py --mixed`）另需 NumPy 和 SciPy。详见 `python model.py --help`、`python optimize.py --help`。

## 目录

| 路径 | 内容 |
| --- | --- |
| `pension_core/` | 退休月份、领取门槛、计发公式、认定月数、职居衔接、年金、逐月三支柱现金流与税收 |
| `model.py`、`run.py`、`interruption.py` | 情景执行、一键示例、职业中断实验 |
| `regional.py`、`regional_profile.py`、`local_terms.py` | 分层地区参数接口 |
| `optimize.py` | 固定预算下的政策选择 |
| `data_validation.py` | 五类标准数据表的字段、取值、日期、来源与审阅校验 |
| `extensions/survival_valuation/` | 2030 年门槛附近的生存加权现金流估值 |
| `extensions/budget_solver/` | 整数预算求解与穷举验证 |
| `extensions/mortality_wpp/` | WPP 2024 中国死亡率摘录及来源清单 |
| `extensions/monthly_bridge/`、`extensions/contribution_frontier/`、`extensions/fixtures_portfolio/` | 估值与求解模块使用的支持模块和示例组合 |
| `data/public/` | 带出处的政策登记表和地区参数 |
| `data/requirements/` | 供获准研究者填写组级验证数据的空白模板 |
| `data/synthetic/` | 用于测试接口的合成样例 |
| `tests/` | 单元测试、手算边界测试和固定样例回归测试（相对容差 1e-12、绝对容差 1e-9） |
| `docs/` | 模型概述、验证规程、模块沿革 |

## 数据

本仓库不含任何调查微观数据。模型以合成个体和公开政策参数运行。获准使用 CHFS、CFPS、CHARLS 的研究者可按 `data/requirements/` 模板准备组级汇总表，见 [DATA_STATEMENT.md](DATA_STATEMENT.md) 与 `data/README.md`。

合成结果用于说明规则如何运作，不是对任何真实人群的估计。

## 引用

使用本模型请引用软件（见 [CITATION.cff](CITATION.cff)）：

> Wang, P., & Huang, C. (2026). *China PensionSIM: An open dynamic microsimulation model of China's multi-pillar pension system* (Version 1.0.0) [Computer software].

仓库：https://github.com/huangchengcheng1656-ship-it/china-pensionsim。首个存档版本发布后补充 DOI。

## 许可

- 代码：Apache License 2.0（[LICENSE](LICENSE)）。
- 政策参数、合成数据与文档：知识共享署名 4.0 国际许可（[LICENSE-DATA](LICENSE-DATA)）。

版权所有 © 2026 王平、黄程程。见 [NOTICE](NOTICE)。

## 作者

- 王平，台州职业技术学院
- 黄程程（通讯作者），潍坊海洋科技学院，huangcc_1986@126.com

开发中使用了 AI 编程助手，见 [AI_USE.md](AI_USE.md)。
